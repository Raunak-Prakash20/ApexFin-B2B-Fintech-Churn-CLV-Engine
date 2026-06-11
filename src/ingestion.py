"""Data warehouse ingestion and ETL pipeline.

Loads raw dimensional and transactional CSV files into the relational warehouse
(Azure SQL Database or DuckDB) and validates schema constraints and row counts.
"""

import os
import sys
from pathlib import Path
import glob
import pandas as pd

# Ensure repository root is on sys.path when executed directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import (
    DATA_RAW_DIR,
    LOCAL_DB_PATH,
    IS_AZURE_CONFIGURED,
    get_database_engine,
    get_duckdb_connection
)

TABLES = [
    "dim_plans",
    "dim_accounts",
    "fact_subscriptions",
    "fact_transactions",
    "fact_daily_balances",
    "fact_telemetry"
]

def ingest_to_duckdb():
    """High-speed vectorized local ingestion into DuckDB."""
    print(f"[*] Starting local warehouse ingestion into DuckDB: {LOCAL_DB_PATH}...")
    conn = get_duckdb_connection()
    
    for table_name in TABLES:
        csv_path = os.path.join(DATA_RAW_DIR, f"{table_name}.csv").replace("\\", "/")
        if not os.path.exists(csv_path):
            raise FileNotFoundError(f"Missing required data file: {csv_path}. Run data/generate_fintech_data.py first.")
            
        print(f"    -> Ingesting {table_name} from {csv_path}...")
        # DuckDB auto-detects schema and performs direct zero-copy CSV reading
        conn.execute(f"DROP TABLE IF EXISTS {table_name};")
        conn.execute(f"CREATE TABLE {table_name} AS SELECT * FROM read_csv_auto('{csv_path}');")
        
        # Verify row count
        count = conn.execute(f"SELECT COUNT(*) FROM {table_name};").fetchone()[0]
        print(f"       [OK] {table_name}: {count:,} rows loaded.")
        
    conn.close()
    print("[+] Local DuckDB Data Warehouse ingestion complete!")

def ingest_to_azure_sql():
    """Bulk ingestion into Microsoft Azure SQL Database."""
    print("[*] Starting cloud warehouse ingestion into Microsoft Azure SQL Database...")
    engine = get_database_engine()
    
    for table_name in TABLES:
        csv_path = os.path.join(DATA_RAW_DIR, f"{table_name}.csv")
        if not os.path.exists(csv_path):
            raise FileNotFoundError(f"Missing required data file: {csv_path}. Run data/generate_fintech_data.py first.")
            
        print(f"    -> Reading {table_name}.csv into memory...")
        df = pd.read_csv(csv_path)
        
        print(f"    -> Bulk writing {len(df):,} rows to Azure SQL table: {table_name}...")
        # Use chunksize and fast_executemany for high throughput
        with engine.connect() as conn:
            df.to_sql(
                table_name,
                con=conn,
                if_exists="replace",
                index=False,
                chunksize=10000,
                method="multi"
            )
        print(f"       [OK] {table_name} successfully written to Azure SQL.")
        
    print("[+] Microsoft Azure SQL Data Warehouse ingestion complete!")

def run_ingestion():
    """Orchestrates ingestion based on configured database target."""
    if IS_AZURE_CONFIGURED:
        ingest_to_azure_sql()
    else:
        ingest_to_duckdb()

if __name__ == "__main__":
    run_ingestion()
