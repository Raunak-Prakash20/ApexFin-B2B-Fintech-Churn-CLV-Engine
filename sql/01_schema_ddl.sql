-- Dimensional Data Warehouse Schema (Kimball Star Schema)
-- Compatible with Microsoft Azure SQL Database (T-SQL) and DuckDB / PostgreSQL


-- Clean up existing tables if re-running DDL
IF OBJECT_ID('analytics_account_risk_scores', 'U') IS NOT NULL DROP TABLE analytics_account_risk_scores;
IF OBJECT_ID('fact_telemetry', 'U') IS NOT NULL DROP TABLE fact_telemetry;
IF OBJECT_ID('fact_daily_balances', 'U') IS NOT NULL DROP TABLE fact_daily_balances;
IF OBJECT_ID('fact_transactions', 'U') IS NOT NULL DROP TABLE fact_transactions;
IF OBJECT_ID('fact_subscriptions', 'U') IS NOT NULL DROP TABLE fact_subscriptions;
IF OBJECT_ID('dim_accounts', 'U') IS NOT NULL DROP TABLE dim_accounts;
IF OBJECT_ID('dim_plans', 'U') IS NOT NULL DROP TABLE dim_plans;

-- ------------------------------------------------------------------------------
-- 1. DIM_PLANS (Subscription Tiers & Take Rates)
-- ------------------------------------------------------------------------------
CREATE TABLE dim_plans (
    plan_id                 INT PRIMARY KEY,
    plan_name               VARCHAR(50) NOT NULL,
    monthly_fee             DECIMAL(10, 2) NOT NULL,
    take_rate_pct           DECIMAL(6, 4) NOT NULL,
    included_seats          INT NOT NULL,
    api_rate_limit_per_min  INT NOT NULL
);

-- ------------------------------------------------------------------------------
-- 2. DIM_ACCOUNTS (Company Demographics & Lifecycle)
-- ------------------------------------------------------------------------------
CREATE TABLE dim_accounts (
    account_id              VARCHAR(20) PRIMARY KEY,
    company_name            VARCHAR(100) NOT NULL,
    industry                VARCHAR(50) NOT NULL,
    company_size            VARCHAR(50) NOT NULL,
    country                 VARCHAR(50) NOT NULL,
    initial_plan_id         INT NOT NULL FOREIGN KEY REFERENCES dim_plans(plan_id),
    current_plan_id         INT NOT NULL FOREIGN KEY REFERENCES dim_plans(plan_id),
    signup_date             DATE NOT NULL,
    initial_deposit_usd     DECIMAL(18, 2) NOT NULL,
    churn_date              DATE NULL,
    is_churned              INT NOT NULL DEFAULT 0,
    latent_archetype        INT NULL
);

CREATE INDEX idx_dim_accounts_signup ON dim_accounts(signup_date);
CREATE INDEX idx_dim_accounts_industry ON dim_accounts(industry);

-- ------------------------------------------------------------------------------
-- 3. FACT_SUBSCRIPTIONS (MRR Waterfall & Plan Migrations)
-- ------------------------------------------------------------------------------
CREATE TABLE fact_subscriptions (
    subscription_id         VARCHAR(50) PRIMARY KEY,
    account_id              VARCHAR(20) NOT NULL FOREIGN KEY REFERENCES dim_accounts(account_id),
    billing_month           DATE NOT NULL,
    plan_id                 INT NOT NULL FOREIGN KEY REFERENCES dim_plans(plan_id),
    mrr_amount              DECIMAL(10, 2) NOT NULL,
    billing_status          VARCHAR(20) NOT NULL,  -- Paid, Failed, Churned
    mrr_change_type         VARCHAR(20) NOT NULL,  -- New, Expansion, Contraction, Churn, Retained
    mrr_change_amount       DECIMAL(10, 2) NOT NULL
);

CREATE INDEX idx_fact_sub_acc_month ON fact_subscriptions(account_id, billing_month);
CREATE INDEX idx_fact_sub_month ON fact_subscriptions(billing_month);

-- ------------------------------------------------------------------------------
-- 4. FACT_TRANSACTIONS (Payment Processing & Failure Logs)
-- ------------------------------------------------------------------------------
CREATE TABLE fact_transactions (
    transaction_batch_id    BIGINT PRIMARY KEY,
    account_id              VARCHAR(20) NOT NULL FOREIGN KEY REFERENCES dim_accounts(account_id),
    transaction_date        DATE NOT NULL,
    payment_method          VARCHAR(30) NOT NULL, -- Credit Card, ACH Direct Debit, Wire Transfer
    total_tx_count          INT NOT NULL,
    successful_tx_count     INT NOT NULL,
    failed_tx_count         INT NOT NULL,
    primary_failure_reason  VARCHAR(50) NOT NULL, -- None, Card Expired, NSF, Compliance
    gross_payment_volume_usd DECIMAL(18, 2) NOT NULL,
    fees_collected_usd      DECIMAL(18, 2) NOT NULL
);

CREATE INDEX idx_fact_tx_acc_date ON fact_transactions(account_id, transaction_date);
CREATE INDEX idx_fact_tx_date ON fact_transactions(transaction_date);

-- ------------------------------------------------------------------------------
-- 5. FACT_DAILY_BALANCES (Cash Ledger & Balance Decay)
-- ------------------------------------------------------------------------------
CREATE TABLE fact_daily_balances (
    account_id              VARCHAR(20) NOT NULL FOREIGN KEY REFERENCES dim_accounts(account_id),
    balance_date            DATE NOT NULL,
    closing_balance_usd     DECIMAL(18, 2) NOT NULL,
    PRIMARY KEY (account_id, balance_date)
);

CREATE INDEX idx_fact_bal_acc_date ON fact_daily_balances(account_id, balance_date);

-- ------------------------------------------------------------------------------
-- 6. FACT_TELEMETRY (Product Usage & Platform Engagement)
-- ------------------------------------------------------------------------------
CREATE TABLE fact_telemetry (
    telemetry_id            BIGINT PRIMARY KEY,
    account_id              VARCHAR(20) NOT NULL FOREIGN KEY REFERENCES dim_accounts(account_id),
    log_date                DATE NOT NULL,
    api_call_count          INT NOT NULL,
    dashboard_logins        INT NOT NULL,
    exports_count           INT NOT NULL
);

CREATE INDEX idx_fact_tel_acc_date ON fact_telemetry(account_id, log_date);

-- ------------------------------------------------------------------------------
-- 7. ANALYTICS_ACCOUNT_RISK_SCORES (Production Inference Serving Table)
-- ------------------------------------------------------------------------------
CREATE TABLE analytics_account_risk_scores (
    account_id              VARCHAR(20) NOT NULL FOREIGN KEY REFERENCES dim_accounts(account_id),
    score_timestamp         DATETIME NOT NULL,
    churn_probability       DECIMAL(6, 4) NOT NULL,
    risk_tier               VARCHAR(20) NOT NULL, -- Low, Medium, High, Critical
    predicted_12m_clv_usd   DECIMAL(18, 2) NOT NULL,
    primary_churn_driver    VARCHAR(100) NOT NULL,
    secondary_churn_driver  VARCHAR(100) NOT NULL,
    recommended_action      VARCHAR(255) NOT NULL,
    PRIMARY KEY (account_id, score_timestamp)
);

CREATE INDEX idx_risk_tier ON analytics_account_risk_scores(risk_tier);
