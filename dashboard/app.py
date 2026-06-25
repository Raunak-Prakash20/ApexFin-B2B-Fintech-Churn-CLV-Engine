"""Interactive Streamlit executive and customer success retention dashboard.

Renders MRR waterfalls, cohort retention matrices, customer-level risk diagnostics,
TreeSHAP explainability breakdowns, and downloadable account intervention lists.
"""

import os
import sys
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# Add project root to Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import get_duckdb_connection, IS_AZURE_CONFIGURED, get_database_engine

# Page Configuration
st.set_page_config(
    page_title="ApexFin | B2B Fintech Churn & CLV Engine",
    page_icon="💳",
    layout="wide"
)

# Custom CSS for modern styling
st.markdown("""
<style>
    .metric-card {
        background-color: #1e2530;
        border-radius: 10px;
        padding: 15px;
        border-left: 5px solid #4CAF50;
    }
    .metric-title { font-size: 0.9rem; color: #a0aec0; }
    .metric-value { font-size: 1.8rem; font-weight: bold; color: #ffffff; }
    .risk-critical { color: #ff4b4b; font-weight: bold; }
    .risk-high { color: #ffa726; font-weight: bold; }
    .risk-medium { color: #ffee58; font-weight: bold; }
    .risk-low { color: #66bb6a; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

@st.cache_data(ttl=300)
def load_dashboard_data():
    """Loads pre-aggregated warehouse data for fast dashboard rendering."""
    conn = get_duckdb_connection()
    
    # 1. Scored Accounts
    df_scored = conn.execute("""
        SELECT 
            s.*,
            a.company_name,
            a.industry,
            a.company_size,
            a.country,
            p.plan_name,
            p.monthly_fee AS current_mrr
        FROM analytics_account_risk_scores s
        JOIN dim_accounts a ON s.account_id = a.account_id
        JOIN dim_plans p ON a.current_plan_id = p.plan_id;
    """).df()
    
    # 2. MRR Waterfall
    df_waterfall = conn.execute("""
        WITH monthly_subs AS (
            SELECT 
                account_id, billing_month, mrr_amount, billing_status,
                LAG(mrr_amount, 1, 0.00) OVER (PARTITION BY account_id ORDER BY billing_month) AS prev_mrr
            FROM fact_subscriptions
        )
        SELECT
            billing_month,
            SUM(CASE WHEN prev_mrr = 0 AND mrr_amount > 0 THEN mrr_amount ELSE 0 END) AS new_mrr,
            SUM(CASE WHEN prev_mrr > 0 AND mrr_amount > prev_mrr THEN mrr_amount - prev_mrr ELSE 0 END) AS expansion_mrr,
            SUM(CASE WHEN prev_mrr > 0 AND mrr_amount < prev_mrr AND mrr_amount > 0 THEN prev_mrr - mrr_amount ELSE 0 END) AS contraction_mrr,
            SUM(CASE WHEN prev_mrr > 0 AND (mrr_amount = 0 OR billing_status = 'Churned') THEN prev_mrr ELSE 0 END) AS churned_mrr,
            SUM(mrr_amount) AS total_mrr
        FROM monthly_subs
        GROUP BY billing_month
        ORDER BY billing_month;
    """).df()
    
    # 3. Cohort Retention Matrix
    df_cohorts = conn.execute("""
        WITH cohort_base AS (
            SELECT 
                account_id, 
                CAST(DATE_TRUNC('month', CAST(signup_date AS DATE)) AS VARCHAR) AS cohort_month
            FROM dim_accounts
        ),
        activity AS (
            SELECT 
                c.cohort_month,
                s.account_id,
                date_diff('month', CAST(c.cohort_month AS DATE), CAST(s.billing_month AS DATE)) AS month_idx
            FROM cohort_base c
            JOIN fact_subscriptions s ON c.account_id = s.account_id
            WHERE s.mrr_amount > 0 AND s.billing_status = 'Paid'
        ),
        cohort_counts AS (
            SELECT cohort_month, COUNT(DISTINCT account_id) AS total_signed_up
            FROM cohort_base
            GROUP BY cohort_month
        )
        SELECT 
            a.cohort_month,
            a.month_idx,
            ROUND(COUNT(DISTINCT a.account_id) * 100.0 / c.total_signed_up, 1) AS retention_pct
        FROM activity a
        JOIN cohort_counts c ON a.cohort_month = c.cohort_month
        WHERE a.month_idx <= 12
        GROUP BY a.cohort_month, a.month_idx, c.total_signed_up
        ORDER BY a.cohort_month, a.month_idx;
    """).df()
    
    # 4. Payment Rail Analytics
    df_payment_rails = conn.execute("""
        SELECT 
            payment_method,
            SUM(total_tx_count) AS total_transactions,
            SUM(failed_tx_count) AS total_failures,
            ROUND(SUM(failed_tx_count) * 100.0 / NULLIF(SUM(total_tx_count), 0), 2) AS failure_rate_pct,
            ROUND(SUM(gross_payment_volume_usd), 2) AS total_volume_usd
        FROM fact_transactions
        GROUP BY payment_method;
    """).df()
    
    conn.close()
    return df_scored, df_waterfall, df_cohorts, df_payment_rails

@st.cache_data(ttl=300)
def load_account_history(account_id: str):
    """Loads 90-day time-series history for a selected account."""
    conn = get_duckdb_connection()
    df_bal = conn.execute(f"""
        SELECT balance_date, closing_balance_usd
        FROM fact_daily_balances
        WHERE account_id = '{account_id}'
        ORDER BY balance_date;
    """).df()
    
    df_tx = conn.execute(f"""
        SELECT transaction_date, gross_payment_volume_usd, failed_tx_count, total_tx_count
        FROM fact_transactions
        WHERE account_id = '{account_id}'
        ORDER BY transaction_date;
    """).df()
    
    conn.close()
    return df_bal, df_tx

# ------------------------------------------------------------------------------
# APP LAYOUT
# ------------------------------------------------------------------------------
st.title("💳 ApexFin | B2B Fintech SaaS Churn & CLV Engine")
st.markdown("### Executive Risk Monitoring, Explainable AI & Customer Lifetime Value")

try:
    df_scored, df_waterfall, df_cohorts, df_payment_rails = load_dashboard_data()
except Exception as e:
    st.error(f"Error loading warehouse data: {e}")
    st.info("Please ensure data generation, ingestion, model training, and batch scoring are executed.")
    st.stop()

# 1. EXECUTIVE KPI BANNER
col1, col2, col3, col4 = st.columns(4)

total_mrr = df_scored["current_mrr"].sum()
at_risk_df = df_scored[df_scored["risk_tier"].isin(["Critical", "High"])]
at_risk_arr = at_risk_df["current_mrr"].sum() * 12.0
critical_count = len(df_scored[df_scored["risk_tier"] == "Critical"])
total_accounts = len(df_scored)

with col1:
    st.metric("Total Active MRR", f"${total_mrr:,.2f}", delta=f"{total_accounts:,} Active Accounts")
with col2:
    st.metric("Annualized Revenue at Risk (ARR)", f"${at_risk_arr:,.2f}", delta="-High & Critical Risk", delta_color="inverse")
with col3:
    st.metric("Critical Accounts Requiring Action", f"{critical_count:,}", delta=f"{len(at_risk_df):,} Total At-Risk", delta_color="inverse")
with col4:
    st.metric("Avg Predicted 12M CLV", f"${df_scored['predicted_12m_clv_usd'].mean():,.2f}")

st.markdown("---")

# 2. TABS: EXECUTIVE SUMMARY VS ACCOUNT DRILL-DOWN
tab1, tab2, tab3 = st.tabs(["📊 Executive Analytics", "🔍 Account Rescue Drill-Down", "📋 Export Action List"])

with tab1:
    col_left, col_right = st.columns(2)
    
    with col_left:
        st.subheader("B2B SaaS MRR Waterfall")
        fig_waterfall = go.Figure()
        fig_waterfall.add_trace(go.Bar(x=df_waterfall["billing_month"], y=df_waterfall["new_mrr"], name="New MRR", marker_color="#2ecc71"))
        fig_waterfall.add_trace(go.Bar(x=df_waterfall["billing_month"], y=df_waterfall["expansion_mrr"], name="Expansion MRR", marker_color="#3498db"))
        fig_waterfall.add_trace(go.Bar(x=df_waterfall["billing_month"], y=-df_waterfall["contraction_mrr"], name="Contraction MRR", marker_color="#e67e22"))
        fig_waterfall.add_trace(go.Bar(x=df_waterfall["billing_month"], y=-df_waterfall["churned_mrr"], name="Churned MRR", marker_color="#e74c3c"))
        fig_waterfall.update_layout(
            barmode="relative",
            title="Monthly MRR Movement (USD)",
            xaxis_title="Billing Month",
            yaxis_title="MRR Change ($)",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
        )
        st.plotly_chart(fig_waterfall, use_container_width=True)
        
    with col_right:
        st.subheader("Account Risk Tier Distribution")
        tier_counts = df_scored["risk_tier"].value_counts().reset_index()
        tier_counts.columns = ["Risk Tier", "Account Count"]
        
        color_map = {
            "Critical": "#e74c3c",
            "High": "#e67e22",
            "Medium": "#f1c40f",
            "Low": "#2ecc71"
        }
        fig_pie = px.pie(
            tier_counts, 
            values="Account Count", 
            names="Risk Tier",
            color="Risk Tier",
            color_discrete_map=color_map,
            hole=0.45,
            title="Portfolio Risk Segmentation"
        )
        st.plotly_chart(fig_pie, use_container_width=True)
        
    # PAYMENT METHOD BREAKDOWN
    st.subheader("Payment Rail Risk & Volume Analysis (Credit Card vs ACH vs Wire)")
    col_rail1, col_rail2 = st.columns(2)
    with col_rail1:
        fig_rail_vol = px.bar(
            df_payment_rails,
            x="payment_method",
            y="total_volume_usd",
            title="Total Payment Volume by Rail (USD)",
            color="payment_method",
            text_auto=True
        )
        st.plotly_chart(fig_rail_vol, use_container_width=True)
    with col_rail2:
        fig_rail_fail = px.bar(
            df_payment_rails,
            x="payment_method",
            y="failure_rate_pct",
            title="Payment Failure Rate by Rail (%) - Involuntary Churn Risk",
            color="payment_method",
            color_discrete_sequence=["#e74c3c", "#f39c12", "#3498db"],
            text_auto=True
        )
        st.plotly_chart(fig_rail_fail, use_container_width=True)
        
    st.subheader("Cohort Retention Heatmap (Logo Retention %)")
    cohort_pivot = df_cohorts.pivot(index="cohort_month", columns="month_idx", values="retention_pct")
    fig_heatmap = px.imshow(
        cohort_pivot,
        labels=dict(x="Months Since Signup", y="Cohort Month", color="Retention %"),
        x=cohort_pivot.columns,
        y=cohort_pivot.index,
        color_continuous_scale="Blues",
        text_auto=True
    )
    st.plotly_chart(fig_heatmap, use_container_width=True)

with tab2:
    st.subheader("Account-Level Churn Diagnosis & Explainable AI (SHAP)")
    
    # Filter selection
    selected_tier = st.selectbox("Filter Accounts by Risk Tier:", ["Critical", "High", "Medium", "Low"], index=0)
    filtered_accounts = df_scored[df_scored["risk_tier"] == selected_tier]
    
    if len(filtered_accounts) == 0:
        st.info("No accounts in this risk tier.")
    else:
        selected_acc_id = st.selectbox(
            "Select Account to Inspect:",
            options=filtered_accounts["account_id"].tolist(),
            format_func=lambda x: f"{x} - {filtered_accounts.loc[filtered_accounts['account_id']==x, 'company_name'].values[0]} ({filtered_accounts.loc[filtered_accounts['account_id']==x, 'plan_name'].values[0]} - ${filtered_accounts.loc[filtered_accounts['account_id']==x, 'current_mrr'].values[0]:,.0f}/mo)"
        )
        
        acc_data = filtered_accounts[filtered_accounts["account_id"] == selected_acc_id].iloc[0]
        
        # Account Summary Card
        card_col1, card_col2, card_col3, card_col4 = st.columns(4)
        with card_col1:
            st.metric("Churn Probability", f"{acc_data['churn_probability']:.1%}")
        with card_col2:
            st.metric("Risk Tier", acc_data["risk_tier"])
        with card_col3:
            st.metric("Current MRR", f"${acc_data['current_mrr']:,.2f}")
        with card_col4:
            st.metric("Predicted 12M CLV", f"${acc_data['predicted_12m_clv_usd']:,.2f}")
            
        # SHAP Explainability Box
        st.info(f"""
        **🧠 Explainable AI (SHAP) Churn Drivers:**
        - **Primary Driver:** {acc_data['primary_churn_driver']}
        - **Secondary Driver:** {acc_data['secondary_churn_driver']}
        
        **🎯 Recommended Customer Success Action:**  
        👉 *{acc_data['recommended_action']}*
        """)
        
        # Load historical time series
        df_bal, df_tx = load_account_history(selected_acc_id)
        
        ts_col1, ts_col2 = st.columns(2)
        with ts_col1:
            st.markdown("#### 90-Day Cash Balance Trajectory")
            if len(df_bal) > 0:
                fig_bal = px.line(df_bal, x="balance_date", y="closing_balance_usd", title="Daily Ledger Balance ($ USD)", color_discrete_sequence=["#3498db"])
                st.plotly_chart(fig_bal, use_container_width=True)
            else:
                st.write("No balance history found.")
                
        with ts_col2:
            st.markdown("#### Daily Transaction Volume & Failures")
            if len(df_tx) > 0:
                fig_tx = px.bar(df_tx, x="transaction_date", y="gross_payment_volume_usd", title="Gross Payment Volume ($ USD)", color_discrete_sequence=["#2ecc71"])
                st.plotly_chart(fig_tx, use_container_width=True)
            else:
                st.write("No transaction history found.")

with tab3:
    st.subheader("Download Actionable Retention List for Customer Success")
    st.markdown("Export prioritized accounts with contact metadata, predicted CLV, and reason codes:")
    
    export_df = df_scored[[
        "account_id", "company_name", "industry", "company_size", "country",
        "plan_name", "current_mrr", "churn_probability", "risk_tier",
        "predicted_12m_clv_usd", "primary_churn_driver", "recommended_action"
    ]].sort_values(by="churn_probability", ascending=False)
    
    st.dataframe(export_df, use_container_width=True, height=400)
    
    csv = export_df.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="📥 Download Prioritized Rescue List (CSV)",
        data=csv,
        file_name="apexfin_high_risk_accounts.csv",
        mime="text/csv"
    )
