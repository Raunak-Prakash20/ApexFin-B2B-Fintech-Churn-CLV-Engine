"""Integration tests for feature extraction and model inference pipelines."""

import os
import pytest
import numpy as np
from src.config import MODELS_DIR
from src.features import get_feature_matrix
from src.explainability import ChurnExplainabilityEngine

def test_feature_matrix_dimensions():
    """Verify that feature extraction yields valid matrices."""
    X, y, df_meta = get_feature_matrix(cutoff_date="2025-10-31")
    
    assert len(X) > 0, "Feature matrix X is empty!"
    assert len(X) == len(y), "Mismatch between X and y row counts!"
    assert len(X) == len(df_meta), "Mismatch between X and df_meta row counts!"
    assert not X.isnull().values.any(), "Feature matrix contains NaN values!"

def test_churn_predictions_in_range():
    """Verify that churn probabilities are strictly between 0 and 1."""
    import pickle
    model_path = os.path.join(MODELS_DIR, "churn_lightgbm.pkl")
    if not os.path.exists(model_path):
        pytest.skip("Model artifact not yet trained.")
        
    with open(model_path, "rb") as f:
        model = pickle.load(f)
        
    X, _, _ = get_feature_matrix(cutoff_date="2025-10-31")
    sample_X = X.iloc[:50]
    preds = model.predict(sample_X)
    
    assert np.all(preds >= 0.0) and np.all(preds <= 1.0), "Churn probabilities out of [0, 1] range!"

def test_shap_local_explanation():
    """Verify that SHAP generates valid text explanations."""
    model_path = os.path.join(MODELS_DIR, "churn_lightgbm.pkl")
    if not os.path.exists(model_path):
        pytest.skip("Model artifact not yet trained.")
        
    explainer = ChurnExplainabilityEngine()
    X, _, _ = get_feature_matrix(cutoff_date="2025-10-31")
    sample_row = X.iloc[0]
    
    p_driver, s_driver, action = explainer.explain_local_account(sample_row)
    assert isinstance(p_driver, str) and len(p_driver) > 0
    assert isinstance(s_driver, str) and len(s_driver) > 0
    assert isinstance(action, str) and len(action) > 0
