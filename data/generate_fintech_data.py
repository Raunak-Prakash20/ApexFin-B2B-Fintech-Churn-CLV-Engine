"""B2B Fintech SaaS relational synthetic data generator.

Simulates corporate customer accounts, subscription lifecycles, payment processing
transactions across payment rails (Credit Card, ACH, Wire), daily ledger balances,
and platform telemetry events.
"""

import os
import random
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

# Set deterministic random seed for full reproducibility
SEED = 42
random.seed(SEED)
np.random.seed(SEED)

# Output directory
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "raw")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Simulation Parameters
START_DATE = datetime(2024, 1, 1)
END_DATE = datetime(2025, 12, 31)
TOTAL_DAYS = (END_DATE - START_DATE).days
IS_CI = os.getenv("CI", "false").lower() == "true"
NUM_ACCOUNTS = int(os.getenv("NUM_ACCOUNTS", "500" if IS_CI else "5000"))

print(f"[*] Initializing B2B Fintech SaaS Data Generator...")
print(f"[*] Simulation Horizon: {START_DATE.strftime('%Y-%m-%d')} to {END_DATE.strftime('%Y-%m-%d')} ({TOTAL_DAYS} days)")
print(f"[*] Target Accounts: {NUM_ACCOUNTS:,}")

# ------------------------------------------------------------------------------
# 1. GENERATE DIM_PLANS (Subscription Pricing & Take Rates)
# ------------------------------------------------------------------------------
plans_data = [
    {
        "plan_id": 1,
        "plan_name": "Starter",
        "monthly_fee": 99.00,
        "take_rate_pct": 0.019,   # 1.9% fee on processed transactions
        "included_seats": 5,
        "api_rate_limit_per_min": 120
    },
    {
        "plan_id": 2,
        "plan_name": "Growth",
        "monthly_fee": 499.00,
        "take_rate_pct": 0.015,   # 1.5% fee on processed transactions
        "included_seats": 25,
        "api_rate_limit_per_min": 600
    },
    {
        "plan_id": 3,
        "plan_name": "Enterprise",
        "monthly_fee": 1999.00,
        "take_rate_pct": 0.011,   # 1.1% fee on processed transactions
        "included_seats": 100,
        "api_rate_limit_per_min": 3000
    }
]
df_plans = pd.DataFrame(plans_data)

# ------------------------------------------------------------------------------
# 2. GENERATE DIM_ACCOUNTS (Company Demographic Profiles)
# ------------------------------------------------------------------------------
industries = ["B2B SaaS", "E-Commerce", "HealthTech", "Logistics & Supply Chain", "Digital Media & Agency"]
industry_weights = [0.35, 0.30, 0.15, 0.12, 0.08]

company_sizes = ["Small (1-20)", "Mid-Market (21-100)", "Enterprise (101-500)", "Large Enterprise (500+)"]
size_weights = [0.50, 0.32, 0.13, 0.05]

countries = ["United States", "United Kingdom", "Canada", "Germany", "Australia"]
country_weights = [0.65, 0.15, 0.08, 0.07, 0.05]

account_rows = []
for i in range(1, NUM_ACCOUNTS + 1):
    account_id = f"ACC-{i:05d}"
    
    # Staggered signup date over the first 18 months to enable cohort retention analysis
    days_offset = int(np.random.beta(2, 2) * (TOTAL_DAYS - 180))
    signup_date = START_DATE + timedelta(days=days_offset)
    
    industry = np.random.choice(industries, p=industry_weights)
    size = np.random.choice(company_sizes, p=size_weights)
    country = np.random.choice(countries, p=country_weights)
    
    # Assign plan tier correlated with company size
    if size == "Small (1-20)":
        plan_id = np.random.choice([1, 2], p=[0.85, 0.15])
    elif size == "Mid-Market (21-100)":
        plan_id = np.random.choice([1, 2, 3], p=[0.20, 0.65, 0.15])
    elif size == "Enterprise (101-500)":
        plan_id = np.random.choice([2, 3], p=[0.25, 0.75])
    else:
        plan_id = 3
        
    initial_deposit = round(float(np.random.lognormal(mean=9.5 if plan_id==1 else 11.5 if plan_id==2 else 13.5, sigma=0.8)), 2)
    
    # Assign latent churn archetype for realistic causal signaling:
    # Archetype 0: Healthy & Sticky (70%)
    # Archetype 1: Cash Flow Deterioration (12%)
    # Archetype 2: Operational Friction / Failed Payments (10%)
    # Archetype 3: Disengagement / Abandonment (8%)
    archetype = np.random.choice([0, 1, 2, 3], p=[0.70, 0.12, 0.10, 0.08])
    
    account_rows.append({
        "account_id": account_id,
        "company_name": f"Corp_{account_id}",
        "industry": industry,
        "company_size": size,
        "country": country,
        "initial_plan_id": plan_id,
        "current_plan_id": plan_id,
        "signup_date": signup_date.strftime("%Y-%m-%d"),
        "initial_deposit_usd": initial_deposit,
        "latent_archetype": archetype
    })

df_accounts = pd.DataFrame(account_rows)

# ------------------------------------------------------------------------------
# 3. GENERATE FACT_SUBSCRIPTIONS (MRR Waterfall & Churn Events)
# ------------------------------------------------------------------------------
subscription_rows = []
for idx, acc in df_accounts.iterrows():
    acc_id = acc["account_id"]
    signup = datetime.strptime(acc["signup_date"], "%Y-%m-%d")
    current_plan = acc["initial_plan_id"]
    archetype = acc["latent_archetype"]
    
    # Calculate months active
    current_month_start = datetime(signup.year, signup.month, 1)
    is_churned = False
    churn_date = None
    
    # Churn probability based on archetype with realistic commercial stochasticity
    if archetype != 0:
        # ~75% of distressed accounts proceed to churn, while ~25% stabilize/recover
        if random.random() < 0.75:
            active_tenure_months = random.randint(3, 14)
            potential_churn_date = signup + timedelta(days=active_tenure_months * 30)
            if potential_churn_date <= END_DATE:
                is_churned = True
                churn_date = potential_churn_date
    else:
        # Healthy accounts carry a baseline ~4% exogenous churn rate (M&A, vendor consolidation)
        if random.random() < 0.04:
            active_tenure_months = random.randint(6, 18)
            potential_churn_date = signup + timedelta(days=active_tenure_months * 30)
            if potential_churn_date <= END_DATE:
                is_churned = True
                churn_date = potential_churn_date
            
    # Monthly subscription billing records
    curr_date = current_month_start
    prev_mrr = 0.0
    
    while curr_date <= END_DATE:
        if is_churned and curr_date > churn_date:
            # Generate churn event record
            subscription_rows.append({
                "subscription_id": f"SUB-{acc_id}-{curr_date.strftime('%Y%m')}",
                "account_id": acc_id,
                "billing_month": curr_date.strftime("%Y-%m-01"),
                "plan_id": current_plan,
                "mrr_amount": 0.00,
                "billing_status": "Churned",
                "mrr_change_type": "Churn",
                "mrr_change_amount": -prev_mrr
            })
            break
            
        plan_fee = df_plans.loc[df_plans["plan_id"] == current_plan, "monthly_fee"].values[0]
        
        # Determine MRR movement type
        if prev_mrr == 0.0:
            change_type = "New"
            change_amount = plan_fee
        else:
            # Potential upgrade/downgrade for healthy accounts
            if archetype == 0 and random.random() < 0.02 and current_plan < 3:
                current_plan += 1
                new_fee = df_plans.loc[df_plans["plan_id"] == current_plan, "monthly_fee"].values[0]
                change_type = "Expansion"
                change_amount = new_fee - plan_fee
                plan_fee = new_fee
            elif archetype != 0 and random.random() < 0.04 and current_plan > 1:
                current_plan -= 1
                new_fee = df_plans.loc[df_plans["plan_id"] == current_plan, "monthly_fee"].values[0]
                change_type = "Contraction"
                change_amount = new_fee - plan_fee
                plan_fee = new_fee
            else:
                change_type = "Retained"
                change_amount = 0.00
                
        subscription_rows.append({
            "subscription_id": f"SUB-{acc_id}-{curr_date.strftime('%Y%m')}",
            "account_id": acc_id,
            "billing_month": curr_date.strftime("%Y-%m-01"),
            "plan_id": current_plan,
            "mrr_amount": plan_fee,
            "billing_status": "Paid",
            "mrr_change_type": change_type,
            "mrr_change_amount": change_amount
        })
        
        prev_mrr = plan_fee
        # Increment by one month
        if curr_date.month == 12:
            curr_date = datetime(curr_date.year + 1, 1, 1)
        else:
            curr_date = datetime(curr_date.year, curr_date.month + 1, 1)

df_subscriptions = pd.DataFrame(subscription_rows)

# Update df_accounts with final status and churn date
churn_map = df_subscriptions[df_subscriptions["billing_status"] == "Churned"].set_index("account_id")["billing_month"].to_dict()
df_accounts["churn_date"] = df_accounts["account_id"].map(churn_map)
df_accounts["is_churned"] = df_accounts["churn_date"].notnull().astype(int)

# ------------------------------------------------------------------------------
# 4. GENERATE FACT_TRANSACTIONS, BALANCES & TELEMETRY
# ------------------------------------------------------------------------------
CUTOFF_WINDOW_START = END_DATE - timedelta(days=90 if IS_CI else 180)

transaction_rows = []
balance_rows = []
telemetry_rows = []

print("[*] Generating daily transactions, cash balances, and telemetry signals...")

tx_counter = 1
tel_counter = 1

for idx, acc in df_accounts.iterrows():
    acc_id = acc["account_id"]
    signup = datetime.strptime(acc["signup_date"], "%Y-%m-%d")
    plan_id = acc["initial_plan_id"]
    archetype = acc["latent_archetype"]
    is_churned = acc["is_churned"]
    churn_dt = datetime.strptime(acc["churn_date"], "%Y-%m-%d") if is_churned else None
    
    # Base transaction parameters based on plan tier
    if plan_id == 1:
        base_daily_tx_count = random.randint(3, 15)
        base_avg_tx_val = random.uniform(50, 300)
        curr_balance = acc["initial_deposit_usd"] * 0.4
    elif plan_id == 2:
        base_daily_tx_count = random.randint(15, 60)
        base_avg_tx_val = random.uniform(150, 800)
        curr_balance = acc["initial_deposit_usd"] * 0.6
    else:
        base_daily_tx_count = random.randint(60, 250)
        base_avg_tx_val = random.uniform(400, 2500)
        curr_balance = acc["initial_deposit_usd"] * 0.8
        
    start_sim = max(signup, CUTOFF_WINDOW_START)
    active_days = (END_DATE - start_sim).days
    
    for day_i in range(active_days):
        current_day = start_sim + timedelta(days=day_i)
        
        # If churned and past churn date, activity stops
        if is_churned and current_day >= churn_dt:
            break
            
        days_until_churn = (churn_dt - current_day).days if is_churned else 999
        
        # --- Causal Signal Modulation based on Latent Archetype ---
        # 1. Cash Flow Deterioration (Archetype 1)
        if archetype == 1 and days_until_churn <= 60:
            decay_factor = max(0.05, days_until_churn / 60.0)
            curr_balance *= (0.95 + random.uniform(-0.02, 0.01))
            daily_tx_count = int(base_daily_tx_count * decay_factor)
            failure_rate = 0.08 + (1.0 - decay_factor) * 0.25 # Failed payments spike
        # 2. Operational Friction (Archetype 2)
        elif archetype == 2 and days_until_churn <= 45:
            daily_tx_count = base_daily_tx_count
            failure_rate = 0.18 + random.uniform(0.05, 0.15) # Very high failure rate
            curr_balance += random.uniform(-500, 500)
        # 3. Disengagement / Abandonment (Archetype 3)
        elif archetype == 3 and days_until_churn <= 60:
            decay_factor = max(0.02, days_until_churn / 60.0)
            daily_tx_count = int(base_daily_tx_count * decay_factor)
            failure_rate = 0.02
            curr_balance += random.uniform(-100, 100)
        # Healthy accounts (Archetype 0)
        else:
            daily_tx_count = int(base_daily_tx_count * random.uniform(0.7, 1.3))
            failure_rate = random.uniform(0.01, 0.03)
            net_daily_flow = random.uniform(-0.02, 0.03) * curr_balance
            curr_balance = max(100.0, curr_balance + net_daily_flow)
            
        # Daily Balance Record
        balance_rows.append({
            "account_id": acc_id,
            "balance_date": current_day.strftime("%Y-%m-%d"),
            "closing_balance_usd": round(curr_balance, 2)
        })
        
        # Telemetry Record
        if archetype == 3 and days_until_churn <= 60:
            tel_activity = max(0.0, days_until_churn / 60.0)
            daily_api_calls = int(random.randint(100, 1500) * tel_activity)
            daily_logins = int(random.randint(2, 10) * tel_activity)
        else:
            daily_api_calls = random.randint(100, 2000) if plan_id > 1 else random.randint(20, 300)
            daily_logins = random.randint(1, 15)
            
        telemetry_rows.append({
            "telemetry_id": tel_counter,
            "account_id": acc_id,
            "log_date": current_day.strftime("%Y-%m-%d"),
            "api_call_count": daily_api_calls,
            "dashboard_logins": daily_logins,
            "exports_count": 1 if random.random() < 0.2 else 0
        })
        tel_counter += 1
        
        # Transactions aggregation for the day across payment methods
        # Payment rail distribution by plan tier:
        # Starter: 75% Credit Card, 25% ACH
        # Growth:  45% Credit Card, 45% ACH, 10% Wire
        # Enterprise: 15% Corporate Card, 50% ACH, 35% Wire
        if plan_id == 1:
            rail_weights = [0.75, 0.25, 0.00]
        elif plan_id == 2:
            rail_weights = [0.45, 0.45, 0.10]
        else:
            rail_weights = [0.15, 0.50, 0.35]
            
        payment_rails = ["Credit Card", "ACH Direct Debit", "Wire Transfer"]
        
        if daily_tx_count > 0:
            # Distribute daily transactions across payment rails
            tx_counts_per_rail = np.random.multinomial(daily_tx_count, rail_weights)
            
            for rail_idx, rail_tx_count in enumerate(tx_counts_per_rail):
                if rail_tx_count == 0:
                    continue
                    
                rail_name = payment_rails[rail_idx]
                
                # Rail-specific failure dynamics
                if rail_name == "Credit Card":
                    rail_failure_rate = failure_rate * (1.2 if archetype == 2 else 0.8)
                    fail_reason = "Card Expired / Limit Reached"
                elif rail_name == "ACH Direct Debit":
                    rail_failure_rate = failure_rate * (1.5 if archetype == 1 else 0.7)
                    fail_reason = "Non-Sufficient Funds (NSF)"
                else: # Wire Transfer
                    rail_failure_rate = failure_rate * 0.3 # Wires fail less often
                    fail_reason = "Compliance / Routing Error"
                    
                rail_failed = int(rail_tx_count * min(0.9, rail_failure_rate))
                rail_success = rail_tx_count - rail_failed
                
                # Average transaction size varies by rail
                if rail_name == "Credit Card":
                    rail_avg_val = base_avg_tx_val * 0.5
                elif rail_name == "ACH Direct Debit":
                    rail_avg_val = base_avg_tx_val * 1.5
                else:
                    rail_avg_val = base_avg_tx_val * 5.0
                    
                rail_vol = round(float(np.random.gamma(shape=rail_tx_count, scale=rail_avg_val)), 2)
                take_rate = df_plans.loc[df_plans["plan_id"] == plan_id, "take_rate_pct"].values[0]
                fees_collected = round(rail_vol * take_rate, 2)
                
                transaction_rows.append({
                    "transaction_batch_id": tx_counter,
                    "account_id": acc_id,
                    "transaction_date": current_day.strftime("%Y-%m-%d"),
                    "payment_method": rail_name,
                    "total_tx_count": rail_tx_count,
                    "successful_tx_count": rail_success,
                    "failed_tx_count": rail_failed,
                    "primary_failure_reason": fail_reason if rail_failed > 0 else "None",
                    "gross_payment_volume_usd": rail_vol,
                    "fees_collected_usd": fees_collected
                })
                tx_counter += 1

df_transactions = pd.DataFrame(transaction_rows)
df_balances = pd.DataFrame(balance_rows)
df_telemetry = pd.DataFrame(telemetry_rows)

# ------------------------------------------------------------------------------
# 5. EXPORT CLEAN CSVs TO DATA/RAW
# ------------------------------------------------------------------------------
print("[*] Exporting datasets to data/raw/...")
df_plans.to_csv(os.path.join(OUTPUT_DIR, "dim_plans.csv"), index=False)
df_accounts.to_csv(os.path.join(OUTPUT_DIR, "dim_accounts.csv"), index=False)
df_subscriptions.to_csv(os.path.join(OUTPUT_DIR, "fact_subscriptions.csv"), index=False)
df_transactions.to_csv(os.path.join(OUTPUT_DIR, "fact_transactions.csv"), index=False)
df_balances.to_csv(os.path.join(OUTPUT_DIR, "fact_daily_balances.csv"), index=False)
df_telemetry.to_csv(os.path.join(OUTPUT_DIR, "fact_telemetry.csv"), index=False)

print(f"[+] Successfully generated B2B Fintech SaaS Data Warehouse tables:")
print(f"    - dim_plans:           {len(df_plans):,} rows")
print(f"    - dim_accounts:        {len(df_accounts):,} rows (Overall Churn Rate: {df_accounts['is_churned'].mean():.2%})")
print(f"    - fact_subscriptions:  {len(df_subscriptions):,} rows")
print(f"    - fact_transactions:   {len(df_transactions):,} rows")
print(f"    - fact_daily_balances: {len(df_balances):,} rows")
print(f"    - fact_telemetry:      {len(df_telemetry):,} rows")
print(f"[*] All files saved to: {OUTPUT_DIR}")
