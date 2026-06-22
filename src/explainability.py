"""TreeSHAP interpretability and operational reason code generator.

Computes exact Shapley attributions for tree ensembles and translates global and
local risk drivers into business reason codes for account teams.
"""

import os
import sys
from pathlib import Path
import json
import pickle
import numpy as np
import pandas as pd
import shap

# Ensure repository root is on sys.path when executed directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import MODELS_DIR
from src.features import get_feature_matrix

# Business dictionary mapping feature names to human-readable explanations & actions
FEATURE_BUSINESS_TRANSLATION = {
    "tx_volume_velocity_ratio": {
        "negative_name": "Sharp Drop in Payment Processing Volume",
        "action": "Investigate if merchant is diverting transaction flow to a competing processor."
    },
    "failed_tx_rate_30d": {
        "negative_name": "Elevated Payment Failure / Decline Rate",
        "action": "Urgent review with Payment Operations to resolve card/ACH processing declines."
    },
    "card_failure_rate_30d": {
        "negative_name": "Card Expired / Limit Decline Spike",
        "action": "Trigger automated card updater and dunning smart retry campaign."
    },
    "ach_failure_rate_30d": {
        "negative_name": "ACH Insufficient Funds (NSF) Crisis",
        "action": "Urgent cash flow check-in; merchant operating cash is dangerously low."
    },
    "wire_failure_rate_30d": {
        "negative_name": "Wire Transfer Compliance / Routing Failure",
        "action": "Enterprise payment operations review to unlock blocked high-value wires."
    },
    "balance_decay_pct": {
        "negative_name": "Significant Cash Flow / Balance Depletion",
        "action": "Schedule financial check-in; discuss flexible credit line or fee restructuring."
    },
    "telemetry_velocity_ratio": {
        "negative_name": "Severe Product Disengagement (API / Dashboard)",
        "action": "Trigger Customer Success re-onboarding and executive outreach."
    },
    "days_since_last_login": {
        "negative_name": "Extended Portal Inactivity",
        "action": "Send proactive engagement email highlighting under-utilized analytics features."
    },
    "balance_volatility_30d": {
        "negative_name": "Erratic Cash Flow Volatility",
        "action": "Review liquidity health and assess risk profile."
    },
    "current_mrr": {
        "negative_name": "High Plan Tier Exposure",
        "action": "Ensure dedicated Technical Account Manager touchpoint for enterprise contract."
    }
}

class ChurnExplainabilityEngine:
    def __init__(self):
        """Initializes the SHAP TreeExplainer from the trained LightGBM model."""
        model_path = os.path.join(MODELS_DIR, "churn_lightgbm.pkl")
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"Model file not found at {model_path}. Run src/train_churn.py first.")
            
        with open(model_path, "rb") as f:
            self.model = pickle.load(f)
            
        self.explainer = shap.TreeExplainer(self.model)
        
    def explain_global(self, X: pd.DataFrame) -> dict:
        """Computes mean absolute SHAP values across all features for global importance."""
        print("[*] Computing global TreeSHAP values across feature space...")
        shap_values = self.explainer.shap_values(X)
        
        # If binary classification returns list [shap_neg, shap_pos], take positive class
        if isinstance(shap_values, list):
            shap_matrix = shap_values[1]
        else:
            shap_matrix = shap_values
            
        mean_abs_shap = np.mean(np.abs(shap_matrix), axis=0)
        feature_importance = pd.DataFrame({
            "feature": X.columns,
            "mean_abs_shap": mean_abs_shap
        }).sort_values(by="mean_abs_shap", ascending=False)
        
        summary_dict = feature_importance.to_dict(orient="records")
        
        # Save to models/
        summary_path = os.path.join(MODELS_DIR, "shap_global_summary.json")
        with open(summary_path, "w") as f:
            json.dump(summary_dict, f, indent=4)
            
        print(f"[+] Global SHAP summary saved to: {summary_path}")
        return summary_dict

    def explain_local_account(self, X_row: pd.Series) -> tuple:
        """
        Explains a single account's risk score by extracting the top 2
        features pushing the prediction toward churn.
        Returns: (primary_driver, secondary_driver, recommended_action)
        """
        row_df = pd.DataFrame([X_row])
        shap_vals = self.explainer.shap_values(row_df)
        
        if isinstance(shap_vals, list):
            row_shap = shap_vals[1][0]
        else:
            row_shap = shap_vals[0]
            
        # Sort features by positive SHAP contribution (pushing toward churn)
        ranked_indices = np.argsort(-row_shap)
        
        top_drivers = []
        for idx in ranked_indices[:3]:
            feat_name = X_row.index[idx]
            feat_shap = row_shap[idx]
            
            if feat_shap > 0: # Only features that actively increased churn risk
                top_drivers.append(feat_name)
                
        primary_feat = top_drivers[0] if len(top_drivers) > 0 else "general_behavior"
        secondary_feat = top_drivers[1] if len(top_drivers) > 1 else "stable_metrics"
        
        primary_info = FEATURE_BUSINESS_TRANSLATION.get(primary_feat, {
            "negative_name": f"Elevated {primary_feat}",
            "action": "Conduct general Customer Success quarterly business review."
        })
        secondary_info = FEATURE_BUSINESS_TRANSLATION.get(secondary_feat, {
            "negative_name": f"Fluctuations in {secondary_feat}",
            "action": "Monitor weekly platform usage."
        })
        
        primary_driver = primary_info["negative_name"]
        secondary_driver = secondary_info["negative_name"]
        recommended_action = primary_info["action"]
        
        return primary_driver, secondary_driver, recommended_action

if __name__ == "__main__":
    engine = ChurnExplainabilityEngine()
    X, _, _ = get_feature_matrix(cutoff_date="2025-10-31")
    engine.explain_global(X)
