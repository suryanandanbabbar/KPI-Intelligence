"""
KPI Intelligence — TMDL Parser Unit Tests.
"""

import unittest
from backend.connectors.powerbi.tmdl_parser import (
    TmdlParser,
    unquote_identifier,
    parse_qualified_column_ref,
    TmdlModel,
    TmdlTable,
    TmdlColumn,
    TmdlMeasure,
)


class TestTmdlParser(unittest.TestCase):

    def test_unquote_identifier(self):
        self.assertEqual(unquote_identifier("simple"), "simple")
        self.assertEqual(unquote_identifier("'Quoted Name'"), "Quoted Name")
        self.assertEqual(unquote_identifier("'O''Reilly'"), "O'Reilly")
        self.assertEqual(unquote_identifier(""), "")

    def test_parse_qualified_column_ref(self):
        t1, c1 = parse_qualified_column_ref("verkoop.klantkey")
        self.assertEqual(t1, "verkoop")
        self.assertEqual(c1, "klantkey")

        t2, c2 = parse_qualified_column_ref("'Datum tabel'.Date")
        self.assertEqual(t2, "Datum tabel")
        self.assertEqual(c2, "Date")

        t3, c3 = parse_qualified_column_ref("produkt.[prod naam]")
        self.assertEqual(t3, "produkt")
        self.assertEqual(c3, "prod naam")

    def test_parse_table_basic(self):
        content = """
table Customers
\tlineageTag: 12345-abcde
\tdataCategory: Customers

\tcolumn CustomerId
\t\tdataType: int64
\t\tisKey
\t\tformatString: 0
\t\tsourceColumn: CustID

\tcolumn CustomerName
\t\tdataType: string
\t\tsummarizeBy: none

\tmeasure 'Total Customers' = COUNTROWS(Customers)
\t\tformatString: #,##0
\t\tlineageTag: 999-xyz

\tpartition Customers-part = m
\t\tmode: import
\t\tsource =
\t\t\t\tlet
\t\t\t\t    Source = Sql.Database(...)
\t\t\t\tin
\t\t\t\t    Source
        """
        tbl = TmdlParser.parse_table_file(content)
        self.assertEqual(tbl.name, "Customers")
        self.assertEqual(tbl.lineage_tag, "12345-abcde")
        self.assertEqual(tbl.data_category, "Customers")
        self.assertEqual(len(tbl.columns), 2)
        self.assertEqual(tbl.columns[0].name, "CustomerId")
        self.assertTrue(tbl.columns[0].is_key)
        self.assertEqual(tbl.columns[0].data_type, "int64")
        self.assertEqual(tbl.columns[0].source_column, "CustID")
        self.assertEqual(len(tbl.measures), 1)
        self.assertEqual(tbl.measures[0].name, "Total Customers")
        self.assertEqual(tbl.measures[0].expression, "COUNTROWS(Customers)")
        self.assertEqual(tbl.measures[0].format_string, "#,##0")
        self.assertEqual(len(tbl.partitions), 1)
        self.assertEqual(tbl.partitions[0].name, "Customers-part")
        self.assertIn("Sql.Database", tbl.partitions[0].source_expression)

    def test_parse_calculated_column(self):
        content = """
table Sales
\tcolumn 'Net Revenue' = Sales[Gross] - Sales[Discount]
\t\tdataType: double
\t\tformatString: $#,##0.00
        """
        tbl = TmdlParser.parse_table_file(content)
        self.assertEqual(len(tbl.columns), 1)
        col = tbl.columns[0]
        self.assertEqual(col.name, "Net Revenue")
        self.assertTrue(col.is_calculated)
        self.assertEqual(col.expression, "Sales[Gross] - Sales[Discount]")
        self.assertEqual(col.data_type, "double")

    def test_parse_calculation_group(self):
        content = """
table 'Time Intelligence'
\tcalculationGroup
\t\tprecedence: 10

\t\tcalculationItem YTD = CALCULATE(SELECTEDMEASURE(), DATESYTD('Date'[Date]))
\t\t\tformatStringDefinition = "0.0%"

\t\tcalculationItem MTD =
\t\t\t\tCALCULATE(SELECTEDMEASURE(), DATESMTD('Date'[Date]))
        """
        tbl = TmdlParser.parse_table_file(content)
        self.assertIsNotNone(tbl.calculation_group)
        self.assertEqual(tbl.calculation_group.precedence, 10)
        self.assertEqual(len(tbl.calculation_group.items), 2)
        item1 = tbl.calculation_group.items[0]
        self.assertEqual(item1.name, "YTD")
        self.assertEqual(item1.format_string_definition, '"0.0%"')
        item2 = tbl.calculation_group.items[1]
        self.assertEqual(item2.name, "MTD")
        self.assertIn("DATESMTD", item2.expression)

    def test_parse_relationships(self):
        content = """
relationship rel-1
\tfromColumn: Sales.CustomerId
\ttoColumn: Customers.Id
\tcardinality: oneToMany
\tcrossFilteringBehavior: bothDirections
\tisActive: true

relationship rel-2
\tfromColumn: 'Sales Order'.DateKey
\ttoColumn: 'Date Dim'.DateKey
\tisActive: false
        """
        rels = TmdlParser.parse_relationships_file(content)
        self.assertEqual(len(rels), 2)
        self.assertEqual(rels[0].relationship_id, "rel-1")
        self.assertEqual(rels[0].from_table, "Sales")
        self.assertEqual(rels[0].from_column, "CustomerId")
        self.assertEqual(rels[0].to_table, "Customers")
        self.assertEqual(rels[0].to_column, "Id")
        self.assertEqual(rels[0].cross_filtering_behavior, "bothDirections")
        self.assertTrue(rels[0].is_active)

        self.assertEqual(rels[1].relationship_id, "rel-2")
        self.assertEqual(rels[1].from_table, "Sales Order")
        self.assertEqual(rels[1].to_table, "Date Dim")
        self.assertFalse(rels[1].is_active)

    def test_parse_expressions_with_backticks(self):
        content = """
expression DateHelper = ```
\tlet
\t    Source = #date(2026, 1, 1)
\tin
\t    Source
```
\tlineageTag: tag-123
        """
        exprs = TmdlParser.parse_expressions_file(content)
        self.assertIn("DateHelper", exprs)
        self.assertIn("#date(2026, 1, 1)", exprs["DateHelper"].expression_text)
        self.assertEqual(exprs["DateHelper"].lineage_tag, "tag-123")


if __name__ == "__main__":
    unittest.main()
