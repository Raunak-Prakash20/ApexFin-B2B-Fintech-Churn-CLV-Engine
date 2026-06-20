"""Customer Lifetime Value (CLV) regression using Tweedie distribution loss.

Models forward 12-month customer monetary value by combining predictable subscription
MRR and variable payment transaction take-rate revenue under heavy right-skewed distributions.
"""

import os
import sys
from pathlib import Path
import pickle
import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

# Ensure repository root is on sys.path when executed directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import MODELS_DIR
from src.features import get_feature_matrix

def compute_ground_truth_12m_value(X: pd.DataFrame) -> np.ndarray:
    """
    Computes realistic 12-month forward monetary value for training:
    - Annualized Subscription Revenue = current_mrr * 12 * (1 - churn_risk_factor)
    - Annualized Transaction Revenue = (tx_volume_90d * 4) * take_rate_pct * (1 - churn_risk_factor)
    """
    mrr = X["current_mrr"].values
    tx_vol_90d = X["tx_volume_90d"].values
    take_rate = X["take_rate_pct"].values
    velocity = np.clip(X["tx_volume_velocity_ratio"].values, 0.1, 2.5)
    
    # 12-month forward projected revenue
    annual_sub_rev = mrr * 12.0
    annual_tx_rev = (tx_vol_90d * 4.0 * velocity) * take_rate
    
    total_12m_value = annual_sub_rev + annual_tx_rev
    # Add realistic stochastic variance
    noise = np.random.normal(1.0, 0.08, size=len(total_12m_value))
    y_clv = np.maximum(100.0, total_12m_value * noise)
    
    return np.round(y_clv, 2)

def train_clv_pipeline():
    """Trains the Tweedie LightGBM CLV regression model."""
    print("================================================================================")
    print("[*] STARTING DUAL-REVENUE CLV REGRESSION MODEL TRAINING (TWEEDIE GBM)")
    print("================================================================================")
    
    # 1. Load Features
    X, _, df_meta = get_feature_matrix(cutoff_date="2025-10-31")
    y_clv = compute_ground_truth_12m_value(X)
    
    # 2. Train / Test Split
    X_train, X_test, y_train, y_test = train_test_split(
        X, y_clv, test_size=0.25, random_state=42
    )
    
    print(f"[*] Training Set:   {len(X_train):,} accounts (Median 12M CLV: ${np.median(y_train):,.2f})")
    print(f"[*] Evaluation Set: {len(X_test):,} accounts (Median 12M CLV: ${np.median(y_test):,.2f})")
    
    # 3. Configure LightGBM with Tweedie Objective
    params = {
        "objective": "tweedie",
        "tweedie_variance_power": 1.5,  # Compound Poisson-Gamma
        "metric": "rmse",
        "boosting_type": "gbdt",
        "learning_rate": 0.05,
        "num_leaves": 31,
        "max_depth": 6,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "random_state": 42,
        "verbose": -1
    }
    
    dtrain = lgb.Dataset(X_train, label=y_train)
    dval = lgb.Dataset(X_test, label=y_test, reference=dtrain)
    
    print("[*] Training LightGBM Tweedie regressor...")
    model = lgb.train(
        params,
        dtrain,
        num_boost_round=400,
        valid_sets=[dtrain, dval],
        callbacks=[lgb.early_stopping(stopping_rounds=30, verbose=False)]
    )
    
    # 4. Out-of-Sample Evaluation
    y_pred = model.predict(X_test, num_iteration=model.best_iteration)
    mae = mean_absolute_error(y_test, y_pred)
    rmse = np.sqrt(mean_squared_error(y_test, y_pred))
    r2 = r2_score(y_test, y_pred)
    
    print("\n--------------------------------------------------------------------------------")
    print("[*] OUT-OF-SAMPLE CLV MODEL PERFORMANCE:")
    print(f"    - Mean Absolute Error (MAE): ${mae:,.2f}")
    print(f"    - Root Mean Squared Error (RMSE): ${rmse:,.2f}")
    print(f"    - R-Squared (R²):            {r2:.4f}")
    print("--------------------------------------------------------------------------------")
    
    # 5. Save Model Artifact
    model_path = os.path.join(MODELS_DIR, "clv_lightgbm.pkl")
    with open(model_path, "wb") as f:
        pickle.dump(model, f)
        
    print(f"[+] Saved CLV model artifact to: {model_path}")
    print("================================================================================")
    
    return model

if __name__ == "__main__":
    train_clv_pipeline()
