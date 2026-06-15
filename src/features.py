"""Feature store extraction and preprocessing interface.

Executes point-in-time SQL feature store queries against Azure SQL or DuckDB,
enforces consistent column schemas, and encodes categorical dimensions for model training
and batch inference.
"""

import os
import sys
from pathlib import Path
import pandas as pd
import numpy as np

# Ensure repository root is on sys.path when executed directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import (
    SQL_DIR,
    IS_AZURE_CONFIGURED,
    get_database_engine,
    get_duckdb_connection
)

FEATURE_COLUMNS = [
    # Firmographics
    "tenure_days",
    "current_plan_id",
    "current_mrr",
    "take_rate_pct",
    "initial_deposit_usd",
    # Transaction Volume & Velocity
    "tx_volume_30d",
    "tx_volume_90d",
    "tx_count_30d",
    "tx_count_90d",
    "fees_collected_30d",
    "fees_collected_90d",
    "tx_volume_velocity_ratio",
    "failed_tx_rate_30d",
    # Payment Rail Specific Dynamics
    "card_vol_share_30d",
    "ach_vol_share_30d",
    "wire_vol_share_30d",
    "card_failure_rate_30d",
    "ach_failure_rate_30d",
    "wire_failure_rate_30d",
    # Balance & Cash Dynamics
    "current_balance_usd",
    "avg_balance_30d",
    "avg_balance_90d",
    "balance_volatility_30d",
    "balance_decay_pct",
    # Telemetry & Engagement
    "api_calls_30d",
    "api_calls_90d",
    "logins_30d",
    "logins_90d",
    "exports_30d",
    "days_since_last_api_call",
    "days_since_last_login",
    "telemetry_velocity_ratio"
]

CATEGORICAL_COLUMNS = [
    "industry",
    "company_size",
    "country"
]

def load_feature_store_from_duckdb(cutoff_date: str = "2025-10-31") -> pd.DataFrame:
    """
    Executes the analytical feature store query directly in DuckDB using
    vectorized SQL window aggregations.
    """
    conn = get_duckdb_connection()
    
    query = f"""
    WITH active_accounts_at_cutoff AS (
        SELECT
            a.account_id,
            a.industry,
            a.company_size,
            a.country,
            a.current_plan_id,
            p.monthly_fee AS current_mrr,
            p.take_rate_pct,
            a.signup_date,
            a.initial_deposit_usd,
            a.churn_date,
            date_diff('day', CAST(a.signup_date AS DATE), CAST('{cutoff_date}' AS DATE)) AS tenure_days,
            CASE 
                WHEN a.churn_date IS NOT NULL 
                     AND CAST(a.churn_date AS DATE) > CAST('{cutoff_date}' AS DATE)
                     AND CAST(a.churn_date AS DATE) <= CAST('{cutoff_date}' AS DATE) + INTERVAL 60 DAYS
                THEN 1 
                ELSE 0 
            END AS churn_next_60d
        FROM dim_accounts a
        INNER JOIN dim_plans p ON a.current_plan_id = p.plan_id
        WHERE CAST(a.signup_date AS DATE) <= CAST('{cutoff_date}' AS DATE)
          AND (a.churn_date IS NULL OR CAST(a.churn_date AS DATE) > CAST('{cutoff_date}' AS DATE))
    ),
    transaction_features AS (
        SELECT
            account_id,
            COALESCE(SUM(CASE WHEN CAST(transaction_date AS DATE) >= CAST('{cutoff_date}' AS DATE) - INTERVAL 30 DAYS THEN gross_payment_volume_usd ELSE 0.0 END), 0.0) AS tx_volume_30d,
            COALESCE(SUM(CASE WHEN CAST(transaction_date AS DATE) >= CAST('{cutoff_date}' AS DATE) - INTERVAL 30 DAYS THEN total_tx_count ELSE 0 END), 0) AS tx_count_30d,
            COALESCE(SUM(CASE WHEN CAST(transaction_date AS DATE) >= CAST('{cutoff_date}' AS DATE) - INTERVAL 30 DAYS THEN failed_tx_count ELSE 0 END), 0) AS failed_tx_count_30d,
            COALESCE(SUM(CASE WHEN CAST(transaction_date AS DATE) >= CAST('{cutoff_date}' AS DATE) - INTERVAL 30 DAYS THEN fees_collected_usd ELSE 0.0 END), 0.0) AS fees_collected_30d,
            COALESCE(SUM(gross_payment_volume_usd), 0.0) AS tx_volume_90d,
            COALESCE(SUM(total_tx_count), 0) AS tx_count_90d,
            COALESCE(SUM(failed_tx_count), 0) AS failed_tx_count_90d,
            COALESCE(SUM(fees_collected_usd), 0.0) AS fees_collected_90d,
            
            -- Payment Rail Specific Volumes (30d)
            COALESCE(SUM(CASE WHEN CAST(transaction_date AS DATE) >= CAST('{cutoff_date}' AS DATE) - INTERVAL 30 DAYS AND payment_method = 'Credit Card' THEN gross_payment_volume_usd ELSE 0.0 END), 0.0) AS card_vol_30d,
            COALESCE(SUM(CASE WHEN CAST(transaction_date AS DATE) >= CAST('{cutoff_date}' AS DATE) - INTERVAL 30 DAYS AND payment_method = 'ACH Direct Debit' THEN gross_payment_volume_usd ELSE 0.0 END), 0.0) AS ach_vol_30d,
            COALESCE(SUM(CASE WHEN CAST(transaction_date AS DATE) >= CAST('{cutoff_date}' AS DATE) - INTERVAL 30 DAYS AND payment_method = 'Wire Transfer' THEN gross_payment_volume_usd ELSE 0.0 END), 0.0) AS wire_vol_30d,
            
            -- Payment Rail Failure Rates (30d)
            COALESCE(SUM(CASE WHEN CAST(transaction_date AS DATE) >= CAST('{cutoff_date}' AS DATE) - INTERVAL 30 DAYS AND payment_method = 'Credit Card' THEN failed_tx_count ELSE 0 END), 0) AS card_failed_30d,
            COALESCE(SUM(CASE WHEN CAST(transaction_date AS DATE) >= CAST('{cutoff_date}' AS DATE) - INTERVAL 30 DAYS AND payment_method = 'Credit Card' THEN total_tx_count ELSE 0 END), 0) AS card_total_30d,
            COALESCE(SUM(CASE WHEN CAST(transaction_date AS DATE) >= CAST('{cutoff_date}' AS DATE) - INTERVAL 30 DAYS AND payment_method = 'ACH Direct Debit' THEN failed_tx_count ELSE 0 END), 0) AS ach_failed_30d,
            COALESCE(SUM(CASE WHEN CAST(transaction_date AS DATE) >= CAST('{cutoff_date}' AS DATE) - INTERVAL 30 DAYS AND payment_method = 'ACH Direct Debit' THEN total_tx_count ELSE 0 END), 0) AS ach_total_30d,
            COALESCE(SUM(CASE WHEN CAST(transaction_date AS DATE) >= CAST('{cutoff_date}' AS DATE) - INTERVAL 30 DAYS AND payment_method = 'Wire Transfer' THEN failed_tx_count ELSE 0 END), 0) AS wire_failed_30d,
            COALESCE(SUM(CASE WHEN CAST(transaction_date AS DATE) >= CAST('{cutoff_date}' AS DATE) - INTERVAL 30 DAYS AND payment_method = 'Wire Transfer' THEN total_tx_count ELSE 0 END), 0) AS wire_total_30d
        FROM fact_transactions
        WHERE CAST(transaction_date AS DATE) BETWEEN CAST('{cutoff_date}' AS DATE) - INTERVAL 90 DAYS AND CAST('{cutoff_date}' AS DATE)
        GROUP BY account_id
    ),
    balance_features AS (
        SELECT
            account_id,
            MAX(CASE WHEN CAST(balance_date AS DATE) = CAST('{cutoff_date}' AS DATE) THEN closing_balance_usd ELSE NULL END) AS current_balance_usd,
            AVG(CASE WHEN CAST(balance_date AS DATE) >= CAST('{cutoff_date}' AS DATE) - INTERVAL 30 DAYS THEN closing_balance_usd ELSE NULL END) AS avg_balance_30d,
            STDDEV_SAMP(CASE WHEN CAST(balance_date AS DATE) >= CAST('{cutoff_date}' AS DATE) - INTERVAL 30 DAYS THEN closing_balance_usd ELSE NULL END) AS balance_volatility_30d,
            AVG(closing_balance_usd) AS avg_balance_90d
        FROM fact_daily_balances
        WHERE CAST(balance_date AS DATE) BETWEEN CAST('{cutoff_date}' AS DATE) - INTERVAL 90 DAYS AND CAST('{cutoff_date}' AS DATE)
        GROUP BY account_id
    ),
    telemetry_features AS (
        SELECT
            account_id,
            COALESCE(SUM(CASE WHEN CAST(log_date AS DATE) >= CAST('{cutoff_date}' AS DATE) - INTERVAL 30 DAYS THEN api_call_count ELSE 0 END), 0) AS api_calls_30d,
            COALESCE(SUM(CASE WHEN CAST(log_date AS DATE) >= CAST('{cutoff_date}' AS DATE) - INTERVAL 30 DAYS THEN dashboard_logins ELSE 0 END), 0) AS logins_30d,
            COALESCE(SUM(CASE WHEN CAST(log_date AS DATE) >= CAST('{cutoff_date}' AS DATE) - INTERVAL 30 DAYS THEN exports_count ELSE 0 END), 0) AS exports_30d,
            COALESCE(SUM(api_call_count), 0) AS api_calls_90d,
            COALESCE(SUM(dashboard_logins), 0) AS logins_90d,
            date_diff('day', MAX(CASE WHEN api_call_count > 0 THEN CAST(log_date AS DATE) ELSE NULL END), CAST('{cutoff_date}' AS DATE)) AS days_since_last_api_call,
            date_diff('day', MAX(CASE WHEN dashboard_logins > 0 THEN CAST(log_date AS DATE) ELSE NULL END), CAST('{cutoff_date}' AS DATE)) AS days_since_last_login
        FROM fact_telemetry
        WHERE CAST(log_date AS DATE) BETWEEN CAST('{cutoff_date}' AS DATE) - INTERVAL 90 DAYS AND CAST('{cutoff_date}' AS DATE)
        GROUP BY account_id
    )
    SELECT
        a.account_id,
        a.tenure_days,
        a.industry,
        a.company_size,
        a.country,
        a.current_plan_id,
        a.current_mrr,
        a.take_rate_pct,
        a.initial_deposit_usd,
        COALESCE(t.tx_volume_30d, 0.0) AS tx_volume_30d,
        COALESCE(t.tx_volume_90d, 0.0) AS tx_volume_90d,
        COALESCE(t.tx_count_30d, 0) AS tx_count_30d,
        COALESCE(t.tx_count_90d, 0) AS tx_count_90d,
        COALESCE(t.fees_collected_30d, 0.0) AS fees_collected_30d,
        COALESCE(t.fees_collected_90d, 0.0) AS fees_collected_90d,
        CASE 
            WHEN COALESCE(t.tx_volume_90d, 0.0) > 0.0 
            THEN ROUND(COALESCE(t.tx_volume_30d, 0.0) / (t.tx_volume_90d / 3.0), 4)
            ELSE 1.0000 
        END AS tx_volume_velocity_ratio,
        CASE 
            WHEN COALESCE(t.tx_count_30d, 0) > 0 
            THEN ROUND(CAST(t.failed_tx_count_30d AS FLOAT) / t.tx_count_30d, 4)
            ELSE 0.0000 
        END AS failed_tx_rate_30d,
        -- Payment Rail Volume Shares
        CASE 
            WHEN COALESCE(t.tx_volume_30d, 0.0) > 0.0 
            THEN ROUND(COALESCE(t.card_vol_30d, 0.0) / t.tx_volume_30d, 4)
            ELSE 0.0000 
        END AS card_vol_share_30d,
        CASE 
            WHEN COALESCE(t.tx_volume_30d, 0.0) > 0.0 
            THEN ROUND(COALESCE(t.ach_vol_30d, 0.0) / t.tx_volume_30d, 4)
            ELSE 0.0000 
        END AS ach_vol_share_30d,
        CASE 
            WHEN COALESCE(t.tx_volume_30d, 0.0) > 0.0 
            THEN ROUND(COALESCE(t.wire_vol_30d, 0.0) / t.tx_volume_30d, 4)
            ELSE 0.0000 
        END AS wire_vol_share_30d,
        -- Payment Rail Specific Failure Rates
        CASE 
            WHEN COALESCE(t.card_total_30d, 0) > 0 
            THEN ROUND(CAST(t.card_failed_30d AS FLOAT) / t.card_total_30d, 4)
            ELSE 0.0000 
        END AS card_failure_rate_30d,
        CASE 
            WHEN COALESCE(t.ach_total_30d, 0) > 0 
            THEN ROUND(CAST(t.ach_failed_30d AS FLOAT) / t.ach_total_30d, 4)
            ELSE 0.0000 
        END AS ach_failure_rate_30d,
        CASE 
            WHEN COALESCE(t.wire_total_30d, 0) > 0 
            THEN ROUND(CAST(t.wire_failed_30d AS FLOAT) / t.wire_total_30d, 4)
            ELSE 0.0000 
        END AS wire_failure_rate_30d,
        COALESCE(b.current_balance_usd, a.initial_deposit_usd) AS current_balance_usd,
        COALESCE(b.avg_balance_30d, a.initial_deposit_usd) AS avg_balance_30d,
        COALESCE(b.avg_balance_90d, a.initial_deposit_usd) AS avg_balance_90d,
        COALESCE(b.balance_volatility_30d, 0.0) AS balance_volatility_30d,
        CASE 
            WHEN COALESCE(b.avg_balance_90d, 0.0) > 0.0 
            THEN ROUND((COALESCE(b.avg_balance_30d, 0.0) - b.avg_balance_90d) / b.avg_balance_90d, 4)
            ELSE 0.0000 
        END AS balance_decay_pct,
        COALESCE(tel.api_calls_30d, 0) AS api_calls_30d,
        COALESCE(tel.api_calls_90d, 0) AS api_calls_90d,
        COALESCE(tel.logins_30d, 0) AS logins_30d,
        COALESCE(tel.logins_90d, 0) AS logins_90d,
        COALESCE(tel.exports_30d, 0) AS exports_30d,
        COALESCE(tel.days_since_last_api_call, 90) AS days_since_last_api_call,
        COALESCE(tel.days_since_last_login, 90) AS days_since_last_login,
        CASE 
            WHEN COALESCE(tel.api_calls_90d, 0) > 0 
            THEN ROUND(CAST(COALESCE(tel.api_calls_30d, 0) AS FLOAT) / (tel.api_calls_90d / 3.0), 4)
            ELSE 1.0000 
        END AS telemetry_velocity_ratio,
        a.churn_next_60d
    FROM active_accounts_at_cutoff a
    LEFT JOIN transaction_features t ON a.account_id = t.account_id
    LEFT JOIN balance_features b ON a.account_id = b.account_id
    LEFT JOIN telemetry_features tel ON a.account_id = tel.account_id;
    """
    
    df = conn.execute(query).df()
    conn.close()
    return df

def get_feature_matrix(cutoff_date: str = "2025-10-31"):
    """
    Fetches the feature store, performs categorical one-hot encoding,
    and returns (X, y, df_metadata).
    """
    print(f"[*] Extracting feature store snapshot as of cutoff: {cutoff_date}...")
    df = load_feature_store_from_duckdb(cutoff_date)
    print(f"    [OK] Extracted {len(df):,} active accounts with {len(df.columns)} raw dimensions.")
    
    # Store account metadata for tracking
    metadata_cols = ["account_id", "industry", "company_size", "country", "current_mrr", "churn_next_60d"]
    df_meta = df[metadata_cols].copy()
    
    # One-Hot Encode categorical dimensions
    df_encoded = pd.get_dummies(df[CATEGORICAL_COLUMNS], drop_first=True)
    
    # Combine numerical features and encoded categoricals
    X = pd.concat([df[FEATURE_COLUMNS], df_encoded], axis=1)
    y = df["churn_next_60d"].values
    
    return X, y, df_meta
