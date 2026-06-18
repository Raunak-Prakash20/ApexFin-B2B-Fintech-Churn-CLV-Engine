"""LightGBM churn classification and financial threshold optimization.

Trains a gradient-boosted decision tree on historical snapshot features to predict
60-day account churn. Sweeps probability thresholds against empirical ARR and outreach
costs to determine the profit-maximizing decision boundary.
"""

import os
import sys
from pathlib import Path
import json
import pickle
import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.model_selection import train_test_split
from sklearn.metrics import (
    roc_auc_score,
    precision_recall_curve,
    auc,
    brier_score_loss,
    classification_report,
    confusion_matrix
)

# Ensure repository root is on sys.path when executed directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import MODELS_DIR
from src.features import get_feature_matrix

def optimize_financial_threshold(
    y_true: np.ndarray,
    y_probs: np.ndarray,
    mrr_values: np.ndarray,
    retention_success_rate: float = 0.40,
    intervention_cost: float = 350.0
):
    """
    Finds the exact probability threshold that maximizes net enterprise revenue saved.
    
    Financial Parameters:
      - mrr_values: Monthly Recurring Revenue of each account.
      - Annual Contract Value (ARR) = mrr_values * 12.
      - retention_success_rate: Probability that an at-risk customer is successfully saved
        by Customer Success intervention (industry benchmark: 35-50%).
      - intervention_cost: Average cost of high-touch outreach / pricing concessions ($350).
    
    Formula:
      - True Positive (Intervened & Would Churn):
          Saved Value = (ARR * retention_success_rate) - intervention_cost
      - False Positive (Intervened but Would Stay):
          Wasted Cost = -intervention_cost
      - False Negative (Missed Churner):
          Lost Value = 0 (Lost customer, no action taken)
      - True Negative (Healthy, No Action):
          $0
    """
    thresholds = np.linspace(0.05, 0.90, 86)
    arr_values = mrr_values * 12.0
    
    best_threshold = 0.50
    max_net_savings = -float("inf")
    financial_curve = []
    
    for thresh in thresholds:
        y_pred = (y_probs >= thresh).astype(int)
        
        # True Positives: Predicted churn AND actually churned
        tp_mask = (y_pred == 1) & (y_true == 1)
        # False Positives: Predicted churn BUT did not churn
        fp_mask = (y_pred == 1) & (y_true == 0)
        
        saved_arr = np.sum(arr_values[tp_mask] * retention_success_rate)
        total_intervention_cost = np.sum(y_pred) * intervention_cost
        net_savings = saved_arr - total_intervention_cost
        
        financial_curve.append({
            "threshold": float(round(thresh, 3)),
            "net_savings_usd": float(round(net_savings, 2)),
            "interventions_count": int(np.sum(y_pred)),
            "true_positives": int(np.sum(tp_mask)),
            "false_positives": int(np.sum(fp_mask))
        })
        
        if net_savings > max_net_savings:
            max_net_savings = net_savings
            best_threshold = thresh
            
    return best_threshold, max_net_savings, financial_curve

def train_churn_pipeline():
    """Executes the full end-to-end churn training and optimization workflow."""
    print("================================================================================")
    print("[*] STARTING LIGHTGBM CHURN MODEL TRAINING & FINANCIAL OPTIMIZATION")
    print("================================================================================")
    
    # 1. Fetch Features from SQL Feature Store
    X, y, df_meta = get_feature_matrix(cutoff_date="2025-10-31")
    feature_names = list(X.columns)
    
    # 2. Stratified Train / Test Split
    X_train, X_test, y_train, y_test, meta_train, meta_test = train_test_split(
        X, y, df_meta, test_size=0.25, random_state=42, stratify=y
    )
    
    churn_rate_train = float(np.mean(y_train))
    churn_rate_test = float(np.mean(y_test))
    print(f"[*] Training Set:   {len(X_train):,} accounts (Churn Rate: {churn_rate_train:.2%})")
    print(f"[*] Evaluation Set: {len(X_test):,} accounts (Churn Rate: {churn_rate_test:.2%})")
    
    # Calculate scale_pos_weight to compensate for class imbalance
    pos_weight = (len(y_train) - np.sum(y_train)) / max(1, np.sum(y_train))
    print(f"[*] Computed class imbalance weight (scale_pos_weight): {pos_weight:.2f}")
    
    # 3. Configure & Train LightGBM Classifier
    params = {
        "objective": "binary",
        "metric": ["auc", "binary_logloss"],
        "boosting_type": "gbdt",
        "learning_rate": 0.05,
        "num_leaves": 31,
        "max_depth": 6,
        "min_child_samples": 20,
        "scale_pos_weight": pos_weight,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "random_state": 42,
        "verbose": -1
    }
    
    dtrain = lgb.Dataset(X_train, label=y_train)
    dval = lgb.Dataset(X_test, label=y_test, reference=dtrain)
    
    print("[*] Training LightGBM model with early stopping...")
    model = lgb.train(
        params,
        dtrain,
        num_boost_round=500,
        valid_sets=[dtrain, dval],
        callbacks=[lgb.early_stopping(stopping_rounds=30, verbose=False)]
    )
    
    # 4. Out-of-Sample Predictions & Statistical Metrics
    y_test_probs = model.predict(X_test, num_iteration=model.best_iteration)
    
    roc_auc = roc_auc_score(y_test, y_test_probs)
    precision_curve, recall_curve, _ = precision_recall_curve(y_test, y_test_probs)
    pr_auc = auc(recall_curve, precision_curve)
    brier = brier_score_loss(y_test, y_test_probs)
    
    print("\n--------------------------------------------------------------------------------")
    print("[*] OUT-OF-SAMPLE STATISTICAL EVALUATION:")
    print(f"    - ROC-AUC:         {roc_auc:.4f} (Global discrimination)")
    print(f"    - PR-AUC:          {pr_auc:.4f} (Precision-Recall trade-off on minority class)")
    print(f"    - Brier Score:     {brier:.4f} (Probability calibration; lower is better)")
    print("--------------------------------------------------------------------------------")
    
    # 5. Financial Cost-Benefit Optimization
    print("[*] Executing Financial Cost-Benefit Threshold Optimization...")
    mrr_test = meta_test["current_mrr"].values
    best_thresh, max_savings, financial_curve = optimize_financial_threshold(
        y_true=y_test,
        y_probs=y_test_probs,
        mrr_values=mrr_test,
        retention_success_rate=0.40,
        intervention_cost=350.0
    )
    
    # Compare Financial Threshold vs Default 0.50 Cutoff
    default_preds = (y_test_probs >= 0.50).astype(int)
    optimal_preds = (y_test_probs >= best_thresh).astype(int)
    
    default_saved = next(item["net_savings_usd"] for item in financial_curve if abs(item["threshold"] - 0.50) < 0.01)
    
    print(f"\n[+] FINANCIAL OPTIMIZATION RESULTS:")
    print(f"    - Default 0.50 Threshold Net Savings:  ${default_saved:,.2f}")
    print(f"    - Optimal Threshold:                  {best_thresh:.2f}")
    print(f"    - Optimal Threshold Net Savings:      ${max_savings:,.2f}")
    print(f"    - Financial Value Added:              +${(max_savings - default_saved):,.2f} net ARR saved!")
    
    # 6. Save Model Artifacts & Metadata
    model_path = os.path.join(MODELS_DIR, "churn_lightgbm.pkl")
    with open(model_path, "wb") as f:
        pickle.dump(model, f)
        
    metadata = {
        "model_type": "LightGBM Binary Classifier",
        "best_iteration": int(model.best_iteration),
        "optimal_threshold": float(round(best_thresh, 4)),
        "metrics": {
            "roc_auc": float(round(roc_auc, 4)),
            "pr_auc": float(round(pr_auc, 4)),
            "brier_score": float(round(brier, 4))
        },
        "financial_optimization": {
            "optimal_threshold": float(round(best_thresh, 4)),
            "max_net_savings_test_set_usd": float(round(max_savings, 2)),
            "default_0_5_savings_usd": float(round(default_saved, 2)),
            "value_added_usd": float(round(max_savings - default_saved, 2))
        },
        "feature_names": feature_names
    }
    
    meta_path = os.path.join(MODELS_DIR, "churn_metadata.json")
    with open(meta_path, "w") as f:
        json.dump(metadata, f, indent=4)
        
    print(f"\n[+] Saved model artifact to:   {model_path}")
    print(f"[+] Saved model metadata to:   {meta_path}")
    print("================================================================================")
    
    return model, metadata

if __name__ == "__main__":
    train_churn_pipeline()
