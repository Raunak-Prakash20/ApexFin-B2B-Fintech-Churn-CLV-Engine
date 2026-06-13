"""Data warehouse schema integrity and constraint tests."""

import os
import pytest
import pandas as pd
from src.config import get_duckdb_connection, DATA_RAW_DIR

TABLES = [
    "dim_plans",
    "dim_accounts",
    "fact_subscriptions",
    "fact_transactions",
    "fact_daily_balances",
    "fact_telemetry"
]

def test_raw_csv_files_exist():
    """Ensure all required raw data files are generated."""
    for table in TABLES:
        csv_file = os.path.join(DATA_RAW_DIR, f"{table}.csv")
        assert os.path.exists(csv_file), f"Missing raw CSV file: {csv_file}"
        assert os.path.getsize(csv_file) > 0, f"Raw CSV file is empty: {csv_file}"

def test_dim_accounts_uniqueness():
    """Assert that account_id is unique and non-null."""
    conn = get_duckdb_connection()
    df_acc = conn.execute("SELECT account_id FROM dim_accounts;").df()
    conn.close()
    
    assert len(df_acc) > 0, "dim_accounts is empty!"
    assert df_acc["account_id"].is_unique, "Duplicate account_id found in dim_accounts!"
    assert df_acc["account_id"].notnull().all(), "Null account_id found in dim_accounts!"

def test_mrr_values_non_negative():
    """Assert that all subscription MRR amounts are non-negative."""
    conn = get_duckdb_connection()
    min_mrr = conn.execute("SELECT MIN(mrr_amount) FROM fact_subscriptions;").fetchone()[0]
    conn.close()
    
    assert min_mrr >= 0.0, f"Negative MRR amount found: {min_mrr}"

def test_transaction_volumes_positive():
    """Assert that gross payment volume is strictly non-negative."""
    conn = get_duckdb_connection()
    min_gpv = conn.execute("SELECT MIN(gross_payment_volume_usd) FROM fact_transactions;").fetchone()[0]
    conn.close()
    
    assert min_gpv >= 0.0, f"Negative GPV found: {min_gpv}"
