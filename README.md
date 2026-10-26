# KPI Intelligence Platform

Universal Metadata Extraction, KPI Ontology Mapping, Human Approval, and KPI Rationalisation Platform.

## Canonical Data Model Documentation & Implementation

The complete canonical data model, PostgreSQL schema (61 tables), data dictionary, ER diagrams, architecture specifications, table inventory, implementation notes, and validation scripts are implemented in:

👉 **[Canonical Data Model Documentation](docs/kpi-intelligence-canonical-model/README.md)**

### Quick Links
- **Power BI Connector Documentation**: [`docs/connectors/powerbi_connector.md`](docs/connectors/powerbi_connector.md)
- **Power BI Ingestion CLI**: [`scripts/ingest_powerbi.py`](scripts/ingest_powerbi.py)
- **DDL Schema (61 tables)**: [`docs/kpi-intelligence-canonical-model/canonical_schema.sql`](docs/kpi-intelligence-canonical-model/canonical_schema.sql)
- **Data Dictionary**: [`docs/kpi-intelligence-canonical-model/data_dictionary.md`](docs/kpi-intelligence-canonical-model/data_dictionary.md)
- **Architecture**: [`docs/kpi-intelligence-canonical-model/architecture.md`](docs/kpi-intelligence-canonical-model/architecture.md)
- **ER Diagrams**: [`docs/kpi-intelligence-canonical-model/er_diagram.md`](docs/kpi-intelligence-canonical-model/er_diagram.md)
- **Table Inventory CSV**: [`docs/kpi-intelligence-canonical-model/table_inventory.csv`](docs/kpi-intelligence-canonical-model/table_inventory.csv)
- **Implementation Notes**: [`docs/kpi-intelligence-canonical-model/implementation_notes.md`](docs/kpi-intelligence-canonical-model/implementation_notes.md)
- **Validation Script**: [`scripts/validate_canonical_model.py`](scripts/validate_canonical_model.py)

## Running Ingestion & Tests

```bash
# Ingest the reference Power BI project
python3 scripts/ingest_powerbi.py --source reference --dry-run

# Run all connector unit and integration tests (31 tests)
python3 -m unittest discover -s tests -p "test_*.py" -v

# Run canonical model static validator and integrity suites
python3 scripts/validate_canonical_model.py
python3 scripts/test_schema_integrity.py
python3 scripts/test_kpi_bank_parser.py
```

