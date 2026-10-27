"""
KPI Intelligence — TMDL Parser.

Complete lexer and parser for Tabular Model Definition Language (TMDL).
Parses Power BI / SSAS tabular semantic models into structured Python dataclasses.
Supports tables, columns (physical and calculated), measures (single-line and multiline DAX),
calculation groups & items, partitions (M and calculated), relationships, hierarchies,
shared expressions, database compatibility, and model-level settings.
"""

import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple
from backend.ingestion.paths import safe_open


def unquote_identifier(ident: str) -> str:
    """Removes single quotes and unescapes double single-quotes from TMDL identifiers."""
    s = ident.strip()
    if len(s) >= 2 and s.startswith("'") and s.endswith("'"):
        return s[1:-1].replace("''", "'")
    return s


def parse_qualified_column_ref(ref_str: str) -> Tuple[str, str]:
    """
    Parses a qualified column reference like:
      verkoop.klantkey -> ('verkoop', 'klantkey')
      'Datum tabel'.Date -> ('Datum tabel', 'Date')
      produkt.[prod naam] -> ('produkt', 'prod naam')
    """
    s = ref_str.strip()
    # Try regex matching quoted or unquoted table and column
    m = re.match(r"^(?:'([^']+)'|([a-zA-Z0-9_#$ -]+))\.(?:'([^']+)'|\[([^\]]+)\]|([a-zA-Z0-9_#$ -]+))$", s)
    if m:
        tbl = m.group(1) or m.group(2)
        col = m.group(3) or m.group(4) or m.group(5)
        return unquote_identifier(tbl), unquote_identifier(col)
    parts = s.split(".", 1)
    if len(parts) == 2:
        return unquote_identifier(parts[0]), unquote_identifier(parts[1])
    return "", unquote_identifier(s)


@dataclass
class TmdlColumn:
    name: str
    data_type: Optional[str] = None
    is_calculated: bool = False
    expression: Optional[str] = None
    format_string: Optional[str] = None
    source_column: Optional[str] = None
    summarize_by: Optional[str] = None
    sort_by_column: Optional[str] = None
    is_key: bool = False
    is_hidden: bool = False
    is_name_inferred: bool = False
    data_category: Optional[str] = None
    lineage_tag: Optional[str] = None
    annotations: Dict[str, Any] = field(default_factory=dict)
    extended_properties: Dict[str, Any] = field(default_factory=dict)
    properties: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TmdlMeasure:
    name: str
    expression: str
    format_string: Optional[str] = None
    lineage_tag: Optional[str] = None
    display_folder: Optional[str] = None
    is_hidden: bool = False
    description: Optional[str] = None
    annotations: Dict[str, Any] = field(default_factory=dict)
    properties: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TmdlCalculationItem:
    name: str
    expression: str
    format_string_definition: Optional[str] = None
    ordinal: Optional[int] = None
    properties: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TmdlCalculationGroup:
    precedence: Optional[int] = None
    items: List[TmdlCalculationItem] = field(default_factory=list)


@dataclass
class TmdlPartition:
    name: str
    partition_type: str = "m"  # 'm', 'calculated', 'entity', 'none'
    mode: str = "import"        # 'import', 'directQuery', 'dual'
    source_expression: str = ""
    properties: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TmdlHierarchyLevel:
    name: str
    column_name: str
    ordinal: int
    lineage_tag: Optional[str] = None


@dataclass
class TmdlHierarchy:
    name: str
    lineage_tag: Optional[str] = None
    levels: List[TmdlHierarchyLevel] = field(default_factory=list)


@dataclass
class TmdlTable:
    name: str
    lineage_tag: Optional[str] = None
    data_category: Optional[str] = None
    is_hidden: bool = False
    description: Optional[str] = None
    columns: List[TmdlColumn] = field(default_factory=list)
    measures: List[TmdlMeasure] = field(default_factory=list)
    calculation_group: Optional[TmdlCalculationGroup] = None
    partitions: List[TmdlPartition] = field(default_factory=list)
    hierarchies: List[TmdlHierarchy] = field(default_factory=list)
    annotations: Dict[str, Any] = field(default_factory=dict)
    properties: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TmdlRelationship:
    relationship_id: str
    from_table: str
    from_column: str
    to_table: str
    to_column: str
    cardinality: str = "oneToMany"
    cross_filtering_behavior: str = "oneDirection"
    is_active: bool = True
    properties: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TmdlExpression:
    name: str
    expression_text: str
    lineage_tag: Optional[str] = None
    annotations: Dict[str, Any] = field(default_factory=dict)
    properties: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TmdlRole:
    name: str
    model_permission: Optional[str] = None
    table_permissions: Dict[str, str] = field(default_factory=dict)
    annotations: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TmdlModel:
    name: str = "Model"
    compatibility_level: Optional[str] = None
    culture: Optional[str] = None
    default_powerbi_data_source_version: Optional[str] = None
    discourage_implicit_measures: bool = False
    tables: Dict[str, TmdlTable] = field(default_factory=dict)
    relationships: List[TmdlRelationship] = field(default_factory=list)
    expressions: Dict[str, TmdlExpression] = field(default_factory=dict)
    roles: Dict[str, TmdlRole] = field(default_factory=dict)
    annotations: Dict[str, Any] = field(default_factory=dict)
    properties: Dict[str, Any] = field(default_factory=dict)


class TmdlLineReader:
    """Helper to read lines and track indentation levels in TMDL files."""

    def __init__(self, content: str):
        # Normalize newlines
        self.raw_lines = content.splitlines()
        self.lines: List[Tuple[int, str]] = []
        self._preprocess()
        self.idx = 0

    def _preprocess(self):
        for line in self.raw_lines:
            # Strip trailing whitespaces
            rstripped = line.rstrip()
            if not rstripped:
                # keep blank lines for multiline parsing if needed, but in token stream we can record
                self.lines.append((-1, ""))
                continue
            # Calculate indentation (count tabs, or 4 spaces = 1 tab)
            indent = 0
            i = 0
            while i < len(rstripped):
                if rstripped[i] == '\t':
                    indent += 1
                    i += 1
                elif rstripped[i:i+4] == '    ':
                    indent += 1
                    i += 4
                else:
                    break
            text = rstripped[i:]
            self.lines.append((indent, text))

    def has_next(self) -> bool:
        return self.idx < len(self.lines)

    def peek(self) -> Optional[Tuple[int, str]]:
        if self.idx < len(self.lines):
            return self.lines[self.idx]
        return None

    def consume(self) -> Tuple[int, str]:
        item = self.lines[self.idx]
        self.idx += 1
        return item


class TmdlParser:
    """Parser for complete TMDL definition directories and individual files."""

    @staticmethod
    def _read_multiline_block(reader: TmdlLineReader, base_indent: int, already_in_backtick: bool = False) -> str:
        """
        Reads multiline code until indentation returns to <= base_indent
        or a closing triple backtick is encountered.
        """
        lines = []
        in_backtick = already_in_backtick
        
        while reader.has_next():
            indent, text = reader.peek()
            
            # If line is blank
            if indent == -1:
                reader.consume()
                lines.append("")
                continue
                
            if "```" in text:
                if not in_backtick:
                    in_backtick = True
                    reader.consume()
                    continue
                else:
                    # Closing backtick
                    reader.consume()
                    break
                    
            if not in_backtick and indent <= base_indent:
                # Exited the indented block
                break
                
            reader.consume()
            lines.append(text)
            
        return "\n".join(lines).strip()

    @classmethod
    def parse_table_file(cls, content: str) -> TmdlTable:
        """Parses a single table TMDL file (e.g. tables/verkoop.tmdl)."""
        reader = TmdlLineReader(content)
        table = TmdlTable(name="Unnamed")
        
        # Read header: table <TableName>
        while reader.has_next():
            indent, text = reader.consume()
            if not text or text.startswith("//"):
                continue
            if text.startswith("table "):
                table.name = unquote_identifier(text[6:].strip())
                break
                
        # Parse table contents
        while reader.has_next():
            indent, text = reader.peek()
            if indent == -1 or not text or text.startswith("//"):
                reader.consume()
                continue
                
            if indent == 1:
                reader.consume()
                # Table properties
                if text.startswith("lineageTag:"):
                    table.lineage_tag = text[11:].strip()
                elif text.startswith("dataCategory:"):
                    table.data_category = text[13:].strip()
                elif text == "isHidden":
                    table.is_hidden = True
                elif text.startswith("description:"):
                    table.description = text[12:].strip()
                elif text.startswith("annotation "):
                    m = re.match(r"^annotation\s+([a-zA-Z0-9_#$ -]+)\s*=\s*(.*)$", text)
                    if m:
                        table.annotations[m.group(1).strip()] = m.group(2).strip()
                elif text.startswith("column "):
                    col = cls._parse_column(text[7:].strip(), reader, base_indent=1)
                    table.columns.append(col)
                elif text.startswith("measure "):
                    meas = cls._parse_measure(text[8:].strip(), reader, base_indent=1)
                    table.measures.append(meas)
                elif text.startswith("calculationGroup"):
                    calc_group = cls._parse_calculation_group(reader, base_indent=1)
                    table.calculation_group = calc_group
                elif text.startswith("partition "):
                    part = cls._parse_partition(text[10:].strip(), reader, base_indent=1)
                    table.partitions.append(part)
                elif text.startswith("hierarchy "):
                    hier = cls._parse_hierarchy(text[10:].strip(), reader, base_indent=1)
                    table.hierarchies.append(hier)
                else:
                    # Generic table property
                    parts = text.split(":", 1)
                    if len(parts) == 2:
                        table.properties[parts[0].strip()] = parts[1].strip()
            else:
                reader.consume()
                
        return table

    @classmethod
    def _parse_column(cls, header: str, reader: TmdlLineReader, base_indent: int) -> TmdlColumn:
        """Parses a column declaration and its nested properties."""
        # Header can be:
        # column key
        # column 'Prijs product' = RELATED(produkt[prijs])
        # column 1
        is_calculated = False
        expression = None
        
        if " = " in header:
            parts = header.split(" = ", 1)
            col_name = unquote_identifier(parts[0].strip())
            is_calculated = True
            expression = parts[1].strip()
        else:
            col_name = unquote_identifier(header.strip())
            
        col = TmdlColumn(name=col_name, is_calculated=is_calculated, expression=expression)
        
        while reader.has_next():
            indent, text = reader.peek()
            if indent == -1 or not text or text.startswith("//"):
                reader.consume()
                continue
            if indent <= base_indent:
                break
                
            reader.consume()
            if indent == base_indent + 1:
                if text.startswith("dataType:"):
                    col.data_type = text[9:].strip()
                elif text.startswith("formatString:"):
                    col.format_string = text[13:].strip()
                elif text.startswith("lineageTag:"):
                    col.lineage_tag = text[11:].strip()
                elif text.startswith("summarizeBy:"):
                    col.summarize_by = text[12:].strip()
                elif text.startswith("sourceColumn:"):
                    sc = text[13:].strip()
                    if sc.startswith("[") and sc.endswith("]"):
                        sc = sc[1:-1]
                    col.source_column = sc
                elif text.startswith("sortByColumn:"):
                    col.sort_by_column = unquote_identifier(text[13:].strip())
                elif text == "isKey":
                    col.is_key = True
                elif text == "isHidden":
                    col.is_hidden = True
                elif text == "isNameInferred":
                    col.is_name_inferred = True
                elif text.startswith("dataCategory:"):
                    col.data_category = text[13:].strip()
                elif text.startswith("annotation "):
                    m = re.match(r"^annotation\s+([a-zA-Z0-9_#$ -]+)\s*=\s*(.*)$", text)
                    if m:
                        col.annotations[m.group(1).strip()] = m.group(2).strip()
                elif text.startswith("extendedProperty "):
                    # Might be multiline JSON
                    m = re.match(r"^extendedProperty\s+([a-zA-Z0-9_#$ -]+)\s*=\s*(.*)$", text)
                    if m:
                        prop_name = m.group(1).strip()
                        initial_val = m.group(2).strip()
                        if not initial_val:
                            block = cls._read_multiline_block(reader, base_indent=indent)
                            col.extended_properties[prop_name] = block
                        else:
                            col.extended_properties[prop_name] = initial_val
                else:
                    parts = text.split(":", 1)
                    if len(parts) == 2:
                        col.properties[parts[0].strip()] = parts[1].strip()
                        
        return col

    @classmethod
    def _parse_measure(cls, header: str, reader: TmdlLineReader, base_indent: int) -> TmdlMeasure:
        """Parses a measure declaration and its nested properties."""
        # measure Omzet = SUMX(verkoop, ...)
        # measure 'avg verkopen' = AVERAGE(...)
        # measure Waarde = \n <multiline>
        if " = " in header:
            parts = header.split(" = ", 1)
            meas_name = unquote_identifier(parts[0].strip())
            expr = parts[1].strip()
        elif header.endswith(" ="):
            meas_name = unquote_identifier(header[:-2].strip())
            expr = ""
        else:
            meas_name = unquote_identifier(header.strip())
            expr = ""
            
        # Check if expression continues on subsequent lines
        if not expr:
            expr_lines = []
            while reader.has_next():
                indent, text = reader.peek()
                if indent == -1:
                    reader.consume()
                    expr_lines.append("")
                    continue
                if indent <= base_indent:
                    break
                # Measure properties are typically at base_indent + 1: formatString:, lineageTag:, etc.
                if text.startswith(("formatString:", "lineageTag:", "displayFolder:", "isHidden", "description:", "annotation ")):
                    break
                reader.consume()
                expr_lines.append(text)
            expr = "\n".join(expr_lines).strip()
            
        meas = TmdlMeasure(name=meas_name, expression=expr)
        
        while reader.has_next():
            indent, text = reader.peek()
            if indent == -1 or not text or text.startswith("//"):
                reader.consume()
                continue
            if indent <= base_indent:
                break
                
            reader.consume()
            if indent == base_indent + 1:
                if text.startswith("formatString:"):
                    meas.format_string = text[13:].strip()
                elif text.startswith("lineageTag:"):
                    meas.lineage_tag = text[11:].strip()
                elif text.startswith("displayFolder:"):
                    meas.display_folder = text[14:].strip()
                elif text == "isHidden":
                    meas.is_hidden = True
                elif text.startswith("description:"):
                    meas.description = text[12:].strip()
                elif text.startswith("annotation "):
                    m = re.match(r"^annotation\s+([a-zA-Z0-9_#$ -]+)\s*=\s*(.*)$", text)
                    if m:
                        meas.annotations[m.group(1).strip()] = m.group(2).strip()
                else:
                    parts = text.split(":", 1)
                    if len(parts) == 2:
                        meas.properties[parts[0].strip()] = parts[1].strip()
                        
        return meas

    @classmethod
    def _parse_calculation_group(cls, reader: TmdlLineReader, base_indent: int) -> TmdlCalculationGroup:
        """Parses a calculationGroup declaration and its calculationItems."""
        calc_group = TmdlCalculationGroup()
        
        while reader.has_next():
            indent, text = reader.peek()
            if indent == -1 or not text or text.startswith("//"):
                reader.consume()
                continue
            if indent <= base_indent:
                break
                
            reader.consume()
            if text.startswith("precedence:"):
                try:
                    calc_group.precedence = int(text[11:].strip())
                except ValueError:
                    pass
            elif text.startswith("calculationItem "):
                item = cls._parse_calculation_item(text[16:].strip(), reader, base_indent=indent)
                calc_group.items.append(item)
                
        return calc_group

    @classmethod
    def _parse_calculation_item(cls, header: str, reader: TmdlLineReader, base_indent: int) -> TmdlCalculationItem:
        """Parses a calculationItem definition."""
        if " = " in header:
            parts = header.split(" = ", 1)
            item_name = unquote_identifier(parts[0].strip())
            expr = parts[1].strip()
        elif header.endswith(" ="):
            item_name = unquote_identifier(header[:-2].strip())
            expr = ""
        else:
            item_name = unquote_identifier(header.strip())
            expr = ""
            
        if not expr:
            expr_lines = []
            while reader.has_next():
                indent, text = reader.peek()
                if indent == -1:
                    reader.consume()
                    expr_lines.append("")
                    continue
                if indent <= base_indent:
                    break
                if text.startswith(("formatStringDefinition =", "ordinal:")):
                    break
                reader.consume()
                expr_lines.append(text)
            expr = "\n".join(expr_lines).strip()
            
        item = TmdlCalculationItem(name=item_name, expression=expr)
        
        while reader.has_next():
            indent, text = reader.peek()
            if indent == -1 or not text or text.startswith("//"):
                reader.consume()
                continue
            if indent <= base_indent:
                break
                
            reader.consume()
            if text.startswith("formatStringDefinition ="):
                fmt_expr = text[24:].strip()
                if not fmt_expr:
                    fmt_expr = cls._read_multiline_block(reader, base_indent=indent)
                item.format_string_definition = fmt_expr
            elif text.startswith("ordinal:"):
                try:
                    item.ordinal = int(text[8:].strip())
                except ValueError:
                    pass
                    
        return item

    @classmethod
    def _parse_partition(cls, header: str, reader: TmdlLineReader, base_indent: int) -> TmdlPartition:
        """Parses a partition declaration (M code or calculated DAX)."""
        # partition verkoop-4ea753a0 = m
        # partition _Field_param_product = calculated
        parts = header.split(" = ", 1)
        part_name = unquote_identifier(parts[0].strip())
        part_type = parts[1].strip() if len(parts) > 1 else "m"
        
        part = TmdlPartition(name=part_name, partition_type=part_type)
        
        while reader.has_next():
            indent, text = reader.peek()
            if indent == -1 or not text or text.startswith("//"):
                reader.consume()
                continue
            if indent <= base_indent:
                break
                
            reader.consume()
            if text.startswith("mode:"):
                part.mode = text[5:].strip()
            elif text.startswith("source ="):
                expr = text[8:].strip()
                if not expr or expr == "```":
                    expr = cls._read_multiline_block(reader, base_indent=indent)
                part.source_expression = expr
            else:
                p_parts = text.split(":", 1)
                if len(p_parts) == 2:
                    part.properties[p_parts[0].strip()] = p_parts[1].strip()
                    
        return part

    @classmethod
    def _parse_hierarchy(cls, header: str, reader: TmdlLineReader, base_indent: int) -> TmdlHierarchy:
        """Parses a hierarchy and its ordered levels."""
        hier_name = unquote_identifier(header.strip())
        hier = TmdlHierarchy(name=hier_name)
        
        current_level: Optional[TmdlHierarchyLevel] = None
        level_order = 1
        
        while reader.has_next():
            indent, text = reader.peek()
            if indent == -1 or not text or text.startswith("//"):
                reader.consume()
                continue
            if indent <= base_indent:
                break
                
            reader.consume()
            if text.startswith("lineageTag:"):
                hier.lineage_tag = text[11:].strip()
            elif text.startswith("level "):
                level_name = unquote_identifier(text[6:].strip())
                current_level = TmdlHierarchyLevel(name=level_name, column_name="", ordinal=level_order)
                level_order += 1
                hier.levels.append(current_level)
            elif current_level and text.startswith("column:"):
                current_level.column_name = unquote_identifier(text[7:].strip())
            elif current_level and text.startswith("lineageTag:"):
                current_level.lineage_tag = text[11:].strip()
                
        return hier

    @classmethod
    def parse_relationships_file(cls, content: str) -> List[TmdlRelationship]:
        """Parses relationships.tmdl."""
        reader = TmdlLineReader(content)
        relationships: List[TmdlRelationship] = []
        
        current_rel: Optional[TmdlRelationship] = None
        
        while reader.has_next():
            indent, text = reader.consume()
            if not text or text.startswith("//") or indent == -1:
                continue
                
            if indent == 0 and text.startswith("relationship "):
                rel_id = text[13:].strip()
                current_rel = TmdlRelationship(
                    relationship_id=rel_id,
                    from_table="",
                    from_column="",
                    to_table="",
                    to_column=""
                )
                relationships.append(current_rel)
            elif current_rel and indent >= 1:
                if text.startswith("fromColumn:"):
                    tbl, col = parse_qualified_column_ref(text[11:].strip())
                    current_rel.from_table = tbl
                    current_rel.from_column = col
                elif text.startswith("toColumn:"):
                    tbl, col = parse_qualified_column_ref(text[9:].strip())
                    current_rel.to_table = tbl
                    current_rel.to_column = col
                elif text.startswith("cardinality:"):
                    current_rel.cardinality = text[12:].strip()
                elif text.startswith("crossFilteringBehavior:"):
                    current_rel.cross_filtering_behavior = text[23:].strip()
                elif text.startswith("isActive:"):
                    val = text[9:].strip().lower()
                    current_rel.is_active = (val == "true")
                else:
                    parts = text.split(":", 1)
                    if len(parts) == 2:
                        current_rel.properties[parts[0].strip()] = parts[1].strip()
                        
        return relationships

    @classmethod
    def parse_expressions_file(cls, content: str) -> Dict[str, TmdlExpression]:
        """Parses expressions.tmdl (shared M expressions/parameters)."""
        reader = TmdlLineReader(content)
        expressions: Dict[str, TmdlExpression] = []
        res = {}
        
        while reader.has_next():
            indent, text = reader.consume()
            if not text or text.startswith("//") or indent == -1:
                continue
                
            if indent == 0 and text.startswith("expression "):
                # expression Query1 = ``` ... ```
                # or expression Query1 = ...
                m = re.match(r"^expression\s+([a-zA-Z0-9_#$ -]+)\s*=\s*(.*)$", text)
                if m:
                    expr_name = unquote_identifier(m.group(1).strip())
                    rest = m.group(2).strip()
                    if rest == "```" or rest.startswith("```"):
                        expr_code = cls._read_multiline_block(reader, base_indent=0, already_in_backtick=True)
                    elif not rest:
                        expr_code = cls._read_multiline_block(reader, base_indent=0, already_in_backtick=False)
                    else:
                        expr_code = rest
                        
                    expr_obj = TmdlExpression(name=expr_name, expression_text=expr_code)
                    
                    # Read properties under expression
                    while reader.has_next():
                        sub_indent, sub_text = reader.peek()
                        if sub_indent == -1 or not sub_text or sub_text.startswith("//"):
                            reader.consume()
                            continue
                        if sub_indent == 0:
                            break
                        reader.consume()
                        if sub_text.startswith("lineageTag:"):
                            expr_obj.lineage_tag = sub_text[11:].strip()
                        elif sub_text.startswith("annotation "):
                            am = re.match(r"^annotation\s+([a-zA-Z0-9_#$ -]+)\s*=\s*(.*)$", sub_text)
                            if am:
                                expr_obj.annotations[am.group(1).strip()] = am.group(2).strip()
                                
                    res[expr_name] = expr_obj
                    
        return res

    @classmethod
    def parse_model_file(cls, content: str) -> TmdlModel:
        """Parses model.tmdl."""
        reader = TmdlLineReader(content)
        model = TmdlModel()
        
        while reader.has_next():
            indent, text = reader.consume()
            if not text or text.startswith("//") or indent == -1:
                continue
                
            if indent == 0 and text.startswith("model "):
                model.name = text[6:].strip()
            elif indent >= 1:
                if text.startswith("culture:"):
                    model.culture = text[8:].strip()
                elif text.startswith("defaultPowerBIDataSourceVersion:"):
                    model.default_powerbi_data_source_version = text[32:].strip()
                elif text == "discourageImplicitMeasures":
                    model.discourage_implicit_measures = True
                elif text.startswith("annotation "):
                    m = re.match(r"^annotation\s+([a-zA-Z0-9_#$ -]+)\s*=\s*(.*)$", text)
                    if m:
                        model.annotations[m.group(1).strip()] = m.group(2).strip()
                else:
                    parts = text.split(":", 1)
                    if len(parts) == 2:
                        model.properties[parts[0].strip()] = parts[1].strip()
                        
        return model

    @classmethod
    def parse_database_file(cls, content: str) -> Dict[str, Any]:
        """Parses database.tmdl."""
        reader = TmdlLineReader(content)
        props = {}
        while reader.has_next():
            indent, text = reader.consume()
            if not text or text.startswith("//") or indent == -1:
                continue
            if text.startswith("compatibilityLevel:"):
                props["compatibility_level"] = text[19:].strip()
            else:
                parts = text.split(":", 1)
                if len(parts) == 2:
                    props[parts[0].strip()] = parts[1].strip()
        return props

    @classmethod
    def parse_semantic_model_directory(cls, dir_path: str) -> TmdlModel:
        """
        Parses an entire *.SemanticModel/definition directory containing:
          model.tmdl, database.tmdl, relationships.tmdl, expressions.tmdl, tables/*.tmdl
        """
        def_dir = dir_path
        if os.path.exists(os.path.join(dir_path, "definition")):
            def_dir = os.path.join(dir_path, "definition")
            
        model = TmdlModel()
        
        # 1. Parse database.tmdl
        db_path = os.path.join(def_dir, "database.tmdl")
        if os.path.exists(db_path):
            with safe_open(db_path, "r", encoding="utf-8", errors="replace") as f:
                db_props = cls.parse_database_file(f.read())
                model.compatibility_level = db_props.get("compatibility_level")
                model.properties.update(db_props)
                
        # 2. Parse model.tmdl
        model_path = os.path.join(def_dir, "model.tmdl")
        if os.path.exists(model_path):
            with safe_open(model_path, "r", encoding="utf-8", errors="replace") as f:
                parsed_model = cls.parse_model_file(f.read())
                model.name = parsed_model.name
                model.culture = parsed_model.culture
                model.default_powerbi_data_source_version = parsed_model.default_powerbi_data_source_version
                model.discourage_implicit_measures = parsed_model.discourage_implicit_measures
                model.annotations.update(parsed_model.annotations)
                model.properties.update(parsed_model.properties)
                
        # 3. Parse relationships.tmdl
        rel_path = os.path.join(def_dir, "relationships.tmdl")
        if os.path.exists(rel_path):
            with safe_open(rel_path, "r", encoding="utf-8", errors="replace") as f:
                model.relationships = cls.parse_relationships_file(f.read())
                
        # 4. Parse expressions.tmdl
        expr_path = os.path.join(def_dir, "expressions.tmdl")
        if os.path.exists(expr_path):
            with safe_open(expr_path, "r", encoding="utf-8", errors="replace") as f:
                model.expressions = cls.parse_expressions_file(f.read())
                
        # 5. Parse tables/*.tmdl
        tables_dir = os.path.join(def_dir, "tables")
        if os.path.exists(tables_dir):
            for fname in sorted(os.listdir(tables_dir)):
                if fname.endswith(".tmdl"):
                    t_path = os.path.join(tables_dir, fname)
                    with safe_open(t_path, "r", encoding="utf-8", errors="replace") as f:
                        tbl = cls.parse_table_file(f.read())
                        model.tables[tbl.name] = tbl
                        
        return model
