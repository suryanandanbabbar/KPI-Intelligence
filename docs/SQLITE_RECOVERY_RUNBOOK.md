# KPI Intelligence — Local SQLite Storage Non-Destructive Recovery Runbook

## Overview

This runbook provides safe, non-destructive diagnostic and recovery procedures for the KPI Intelligence local SQLite database (`kpi_intelligence.sqlite3`).

If you encounter:
```
sqlite3.DatabaseError: database disk image is malformed
```
or an HTTP 503 response with error code `STORAGE_CORRUPTED`, **do not delete, overwrite, or re-initialize the database**. SQLite file corruption often leaves the vast majority of database pages intact. Following this runbook allows you to recover valid records to a **new database file** without data loss.

---

## 1. Operational Precaution: Cloud-Sync Folders & OneDrive

### Why Synchronization Tools Threaten SQLite Databases
When a SQLite database operates in Write-Ahead Logging (WAL) mode, SQLite relies on three coordinated files:
1. `kpi_intelligence.sqlite3` (Main B-tree database)
2. `kpi_intelligence.sqlite3-wal` (Write-ahead log journal containing uncommitted/uncheckpointed transactions)
3. `kpi_intelligence.sqlite3-shm` (Shared memory index used by concurrent readers and writers)

If the project directory resides in a cloud-synchronized folder (such as Microsoft OneDrive, Dropbox, Box, or Google Drive), the sync engine continuously attempts to upload these files as they are modified. This creates severe concurrency hazards:
- **Lock Contention**: The sync engine opens read handles on `-wal` or `-shm` files while SQLite attempts a checkpoint or write, causing file access violations.
- **Asynchronous Sync Divergence**: If the sync client uploads the main database file at time $T_1$ and the WAL file at time $T_2$, or replaces a local file with a conflicting remote version, the shared memory index points to invalid page offsets, triggering `database disk image is malformed`.

### Safe Local Path Configuration
To avoid sync interference, configure `KPI_SQLITE_PATH` in your `.env` to point to a local non-synchronized directory outside OneDrive.

#### Windows Example:
```dotenv
KPI_SQLITE_PATH=C:\kpi_data\kpi_intelligence.sqlite3
```
or using your local app data directory:
```dotenv
KPI_SQLITE_PATH=C:\Users\<username>\AppData\Local\KPIIntelligence\kpi_intelligence.sqlite3
```

#### macOS / Linux Example:
```dotenv
KPI_SQLITE_PATH=/var/tmp/kpi_intelligence.sqlite3
```

---

## 2. Non-Destructive Step-by-Step Recovery Procedure

### Step 1: Stop the Application
Stop all running backend processes, Uvicorn servers, and inspection tools to ensure no active connections hold write locks.
```bash
# Verify no Python or Uvicorn process is accessing the database
# Windows (PowerShell):
Get-Process python*

# macOS / Linux:
ps aux | grep uvicorn
```

---

### Step 2: Create a Complete Snapshot (Including Sidecars)
Before inspecting or running any repair commands, copy the primary database file **and both sidecar files** to a dedicated backup directory.

#### Windows (PowerShell):
```powershell
$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$BackupDir = "local_data\backups_$Timestamp"
New-Item -ItemType Directory -Force -Path $BackupDir

Copy-Item "local_data\kpi_intelligence.sqlite3*" -Destination $BackupDir
Get-ChildItem $BackupDir
```

#### macOS / Linux:
```bash
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="local_data/backups_${TIMESTAMP}"
mkdir -p "$BACKUP_DIR"

cp local_data/kpi_intelligence.sqlite3* "$BACKUP_DIR"/
ls -la "$BACKUP_DIR"
```

> [!IMPORTANT]
> Always verify that `kpi_intelligence.sqlite3`, `kpi_intelligence.sqlite3-wal` (if present), and `kpi_intelligence.sqlite3-shm` (if present) are copied together into the backup folder.

---

### Step 3: Run a Read-Only Integrity Check Against the Backup
Perform an integrity check on the **backup copy**, never on the live store.

#### Option A: Using the SQLite Command-Line Interface (CLI)
Check if `sqlite3` CLI is available:
```bash
sqlite3 --version
```
If available, execute `quick_check` and `integrity_check`:
```bash
sqlite3 "file:local_data/backups_<timestamp>/kpi_intelligence.sqlite3?mode=ro" "PRAGMA quick_check;"
sqlite3 "file:local_data/backups_<timestamp>/kpi_intelligence.sqlite3?mode=ro" "PRAGMA integrity_check;"
```

#### Option B: Using Python (Zero External Dependencies)
If the `sqlite3` CLI is not installed, run this built-in Python diagnostic:
```bash
python -c "
import sqlite3, sys
backup_path = sys.argv[1]
print(f'Checking integrity of backup: {backup_path}')
conn = sqlite3.connect(f'file:{backup_path}?mode=ro', uri=True)
cur = conn.cursor()
cur.execute('PRAGMA quick_check;')
print('PRAGMA quick_check:', cur.fetchall())
cur.execute('PRAGMA integrity_check;')
print('PRAGMA integrity_check (first 5):', cur.fetchall()[:5])
conn.close()
" "local_data/backups_<timestamp>/kpi_intelligence.sqlite3"
```

---

### Step 4: Recover to a NEW Output Database File (Never in Place)
Never attempt to write or execute repair commands directly on the corrupted file. Always export recovered data into a fresh database.

#### Method 1: SQLite CLI `.recover` Command (Recommended for SQLite >= 3.29)
The `.recover` command traverses B-tree pages and extracts undamaged data into SQL statements:
```bash
# Windows / macOS / Linux:
sqlite3 "local_data/backups_<timestamp>/kpi_intelligence.sqlite3" ".recover" | sqlite3 "local_data/kpi_recovered.sqlite3"
```

#### Method 2: SQLite CLI `.dump` Pipeline (Fallback)
If `.recover` is not supported in older SQLite versions:
```bash
sqlite3 "local_data/backups_<timestamp>/kpi_intelligence.sqlite3" ".dump" | sqlite3 "local_data/kpi_recovered.sqlite3"
```

#### Method 3: Standard Python Recovery Script
If the `sqlite3` CLI tool is unavailable, use this standard library Python script to safely copy rows from healthy pages into a new database:
```python
# Save as scripts/recover_sqlite.py and run: python scripts/recover_sqlite.py <source_backup> <destination_db>
import sys, sqlite3, os

source_path = os.path.abspath(sys.argv[1])
dest_path = os.path.abspath(sys.argv[2])
print(f"Recovering from: {source_path}")
print(f"Target file:     {dest_path}")

src_conn = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
dst_conn = sqlite3.connect(dest_path)

# Extract table definitions
src_cur = src_conn.cursor()
src_cur.execute("SELECT name, sql FROM sqlite_master WHERE type='table' AND sql IS NOT NULL;")
tables = src_cur.fetchall()

for tbl_name, tbl_sql in tables:
    if tbl_name.startswith("sqlite_"):
        continue
    try:
        dst_conn.execute(tbl_sql)
        print(f"Created table schema: {tbl_name}")
    except Exception as e:
        print(f"Schema creation error on {tbl_name}: {e}")

dst_conn.commit()

# Recover rows table-by-table
for tbl_name, _ in tables:
    if tbl_name.startswith("sqlite_"):
        continue
    try:
        src_cur.execute(f"SELECT * FROM [{tbl_name}];")
        rows = src_cur.fetchall()
        if rows:
            placeholders = ", ".join(["?"] * len(rows[0]))
            dst_conn.executemany(f"INSERT OR REPLACE INTO [{tbl_name}] VALUES ({placeholders});", rows)
            dst_conn.commit()
            print(f"Recovered {len(rows)} records from table: {tbl_name}")
    except Exception as e:
        print(f"Warning: Corrupted read on table '{tbl_name}': {e}. Continuing with remaining tables...")

src_conn.close()
dst_conn.close()
print("Recovery pass completed.")
```

---

### Step 5: Validate the Recovered Database
Verify that the new database file passes all integrity checks and has valid document counts.

```bash
python -c "
import sqlite3
conn = sqlite3.connect('local_data/kpi_recovered.sqlite3')
cur = conn.cursor()
cur.execute('PRAGMA integrity_check;')
print('Recovered DB Integrity:', cur.fetchall())
cur.execute('SELECT COUNT(*) FROM cosmos_documents;')
print('cosmos_documents count:', cur.fetchone()[0])
conn.close()
"
```

---

### Step 6: Safely Switch Application Configuration
Once the recovered database is verified healthy:

1. **Keep the original corrupted database and backup folder** intact for audit purposes.
2. Update `.env` to point to the validated recovered database:
   ```dotenv
   KPI_SQLITE_PATH=local_data/kpi_recovered.sqlite3
   ```
   *(Or move `kpi_recovered.sqlite3` to a safe local non-synchronized directory outside OneDrive, such as `C:\kpi_data\kpi_intelligence.sqlite3`)*.
3. Start the FastAPI backend:
   ```bash
   uvicorn backend.api.app:app --port 8080 --reload
   ```
4. Verify the storage diagnostics endpoint:
   ```bash
   curl http://127.0.0.1:8080/api/v1/storage/diagnostics
   ```
   Expected response:
   ```json
   {
     "success": true,
     "backend": "sqlite",
     "diagnostics": {
       "status": "healthy",
       "healthy": true,
       "diagnostic": "PRAGMA quick_check;",
       "messages": ["ok"]
     }
   }
   ```
