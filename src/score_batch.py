"""Production batch scoring and account risk tiering pipeline.

Extracts current snapshot features, runs churn classification and CLV forecasting,
maps accounts into operational risk tiers, and updates the database risk scoring table.
"""

import os
import sys
from pathlib import Path
import json
import pickle
from datetime import datetime
import numpy as np
import pandas as pd

# Ensure repository root is on sys.path when executed directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import (
    MODELS_DIR,
    IS_AZURE_CONFIGURED,
    get_database_engine,
    get_duckdb_connection
)
from src.features import get_feature_matrix
from src.explainability import ChurnExplainabilityEngine

def run_batch_scoring(cutoff_date: str = "2025-10-31"):
    print("================================================================================")
    print(f"[*] EXECUTING PRODUCTION BATCH SCORING PIPELINE (Snapshot: {cutoff_date})")
    print("================================================================================")
    
    # 1. Load Feature Matrix
    X, _, df_meta = get_feature_matrix(cutoff_date=cutoff_date)
    
    # 2. Load Model Artifacts
    churn_model_path = os.path.join(MODELS_DIR, "churn_lightgbm.pkl")
    clv_model_path = os.path.join(MODELS_DIR, "clv_lightgbm.pkl")
    meta_path = os.path.join(MODELS_DIR, "churn_metadata.json")
    
    with open(churn_model_path, "rb") as f:
        churn_model = pickle.load(f)
    with open(clv_model_path, "rb") as f:
        clv_model = pickle.load(f)
    with open(meta_path, "r") as f:
        churn_meta = json.load(f)
        
    optimal_threshold = churn_meta["financial_optimization"]["optimal_threshold"]
    print(f"[*] Loaded models successfully. Using financially optimal threshold: {optimal_threshold:.2f}")
    
    # 3. Model Inference
    print("[*] Generating churn probabilities and 12-month CLV predictions...")
    churn_probs = churn_model.predict(X)
    predicted_clv = np.maximum(50.0, clv_model.predict(X))
    
    # 4. Initialize Explainability Engine for High-Risk Accounts
    explainer = ChurnExplainabilityEngine()
    
    # 5. Build Production Scoring Records
    scored_records = []
    current_ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    
    print("[*] Assigning risk tiers and generating local SHAP reason codes...")
    for i in range(len(X)):
        acc_id = df_meta.iloc[i]["account_id"]
        prob = float(churn_probs[i])
        clv = float(predicted_clv[i])
        mrr = float(df_meta.iloc[i]["current_mrr"])
        plan_id = int(X.iloc[i]["current_plan_id"])
        
        # Risk Tier Classification Logic
        if prob >= 0.65 or (prob >= optimal_threshold and plan_id == 3):
            risk_tier = "Critical"
        elif prob >= optimal_threshold:
            risk_tier = "High"
        elif prob >= 0.15:
            risk_tier = "Medium"
        else:
            risk_tier = "Low"
            
        # For High and Critical risk accounts, compute detailed SHAP explanation
        if risk_tier in ["Critical", "High"]:
            p_driver, s_driver, action = explainer.explain_local_account(X.iloc[i])
        else:
            p_driver = "Stable Usage Patterns"
            s_driver = "Healthy Financial Metrics"
            action = "Routine automated nurture communications."
            
        scored_records.append({
            "account_id": acc_id,
            "score_timestamp": current_ts,
            "churn_probability": round(prob, 4),
            "risk_tier": risk_tier,
            "predicted_12m_clv_usd": round(clv, 2),
            "primary_churn_driver": p_driver,
            "secondary_churn_driver": s_driver,
            "recommended_action": action
        })
        
    df_scored = pd.DataFrame(scored_records)
    
    # 6. Write Results to Database Table
    print(f"[*] Writing {len(df_scored):,} scoring records to analytics_account_risk_scores...")
    if IS_AZURE_CONFIGURED:
        engine = get_database_engine()
        with engine.connect() as conn:
            df_scored.to_sql(
                "analytics_account_risk_scores",
                con=conn,
                if_exists="replace",
                index=False,
                chunksize=5000
            )
        print("    [OK] Successfully updated Azure SQL Database table: analytics_account_risk_scores.")
    else:
        conn = get_duckdb_connection()
        conn.execute("DROP TABLE IF EXISTS analytics_account_risk_scores;")
        conn.execute("CREATE TABLE analytics_account_risk_scores AS SELECT * FROM df_scored;")
        conn.close()
        print("    [OK] Successfully updated local DuckDB table: analytics_account_risk_scores.")
        
    # 7. Print Executive Summary
    tier_counts = df_scored["risk_tier"].value_counts()
    at_risk_mrr = df_meta[df_scored["risk_tier"].isin(["Critical", "High"])]["current_mrr"].sum()
    
    print("\n--------------------------------------------------------------------------------")
    print("[+] BATCH INFERENCE SUMMARY:")
    print(f"    - Total Accounts Scored:  {len(df_scored):,}")
    print(f"    - Critical Risk Accounts: {tier_counts.get('Critical', 0):,}")
    print(f"    - High Risk Accounts:     {tier_counts.get('High', 0):,}")
    print(f"    - Medium Risk Accounts:   {tier_counts.get('Medium', 0):,}")
    print(f"    - Low Risk Accounts:      {tier_counts.get('Low', 0):,}")
    print(f"    - Total MRR at High Risk: ${at_risk_mrr:,.2f} / month")
    print("--------------------------------------------------------------------------------")
    print("================================================================================")
    
    return df_scored

if __name__ == "__main__":
    run_batch_scoring()
