-- Point-in-Time Analytical Feature Store Extraction Query
-- Evaluates 90-day lookback behavioral features and 60-day forward churn target without data leakage


-- Configuration: Set observation cutoff date (T_CUTOFF)
-- In production, this can be parameterized in stored procedures or Python queries.
DECLARE @CutoffDate DATE = '2025-10-31';

WITH active_accounts_at_cutoff AS (
    -- Step 1: Filter to accounts that signed up before the cutoff and were still active on cutoff date
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
        DATEDIFF(day, a.signup_date, @CutoffDate) AS tenure_days,
        
        -- Target Label: Did the account churn within 60 days following the cutoff date?
        CASE 
            WHEN a.churn_date IS NOT NULL 
                 AND a.churn_date > @CutoffDate 
                 AND a.churn_date <= DATEADD(day, 60, @CutoffDate) 
            THEN 1 
            ELSE 0 
        END AS churn_next_60d
    FROM dim_accounts a
    INNER JOIN dim_plans p 
        ON a.current_plan_id = p.plan_id
    WHERE a.signup_date <= @CutoffDate
      AND (a.churn_date IS NULL OR a.churn_date > @CutoffDate)
),

transaction_features AS (
    -- Step 2: Compute 30-day and 90-day payment volume, counts, and failure rates
    SELECT
        account_id,
        -- 30-day metrics
        SUM(CASE WHEN transaction_date >= DATEADD(day, -30, @CutoffDate) THEN gross_payment_volume_usd ELSE 0.0 END) AS tx_volume_30d,
        SUM(CASE WHEN transaction_date >= DATEADD(day, -30, @CutoffDate) THEN total_tx_count ELSE 0 END) AS tx_count_30d,
        SUM(CASE WHEN transaction_date >= DATEADD(day, -30, @CutoffDate) THEN failed_tx_count ELSE 0 END) AS failed_tx_count_30d,
        SUM(CASE WHEN transaction_date >= DATEADD(day, -30, @CutoffDate) THEN fees_collected_usd ELSE 0.0 END) AS fees_collected_30d,
        
        -- 90-day metrics
        SUM(gross_payment_volume_usd) AS tx_volume_90d,
        SUM(total_tx_count) AS tx_count_90d,
        SUM(failed_tx_count) AS failed_tx_count_90d,
        SUM(fees_collected_usd) AS fees_collected_90d
    FROM fact_transactions
    WHERE transaction_date BETWEEN DATEADD(day, -90, @CutoffDate) AND @CutoffDate
    GROUP BY account_id
),

balance_features AS (
    -- Step 3: Compute closing balance, 30d/90d averages, and cash volatility
    SELECT
        account_id,
        -- Most recent balance at cutoff
        MAX(CASE WHEN balance_date = @CutoffDate THEN closing_balance_usd ELSE NULL END) AS current_balance_usd,
        
        -- 30-day balance metrics
        AVG(CASE WHEN balance_date >= DATEADD(day, -30, @CutoffDate) THEN closing_balance_usd ELSE NULL END) AS avg_balance_30d,
        STDEV(CASE WHEN balance_date >= DATEADD(day, -30, @CutoffDate) THEN closing_balance_usd ELSE NULL END) AS balance_volatility_30d,
        
        -- 90-day balance metrics
        AVG(closing_balance_usd) AS avg_balance_90d
    FROM fact_daily_balances
    WHERE balance_date BETWEEN DATEADD(day, -90, @CutoffDate) AND @CutoffDate
    GROUP BY account_id
),

telemetry_features AS (
    -- Step 4: Compute platform usage, login frequencies, and recency
    SELECT
        account_id,
        -- 30-day activity
        SUM(CASE WHEN log_date >= DATEADD(day, -30, @CutoffDate) THEN api_call_count ELSE 0 END) AS api_calls_30d,
        SUM(CASE WHEN log_date >= DATEADD(day, -30, @CutoffDate) THEN dashboard_logins ELSE 0 END) AS logins_30d,
        SUM(CASE WHEN log_date >= DATEADD(day, -30, @CutoffDate) THEN exports_count ELSE 0 END) AS exports_30d,
        
        -- 90-day activity
        SUM(api_call_count) AS api_calls_90d,
        SUM(dashboard_logins) AS logins_90d,
        
        -- Recency metrics
        DATEDIFF(day, MAX(CASE WHEN api_call_count > 0 THEN log_date ELSE NULL END), @CutoffDate) AS days_since_last_api_call,
        DATEDIFF(day, MAX(CASE WHEN dashboard_logins > 0 THEN log_date ELSE NULL END), @CutoffDate) AS days_since_last_login
    FROM fact_telemetry
    WHERE log_date BETWEEN DATEADD(day, -90, @CutoffDate) AND @CutoffDate
    GROUP BY account_id
)

-- Step 5: Master Feature Store Output with derived velocity and interaction ratios
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
    
    -- Transaction Volume & Velocity
    ISNULL(t.tx_volume_30d, 0.0) AS tx_volume_30d,
    ISNULL(t.tx_volume_90d, 0.0) AS tx_volume_90d,
    ISNULL(t.tx_count_30d, 0) AS tx_count_30d,
    ISNULL(t.tx_count_90d, 0) AS tx_count_90d,
    ISNULL(t.fees_collected_30d, 0.0) AS fees_collected_30d,
    ISNULL(t.fees_collected_90d, 0.0) AS fees_collected_90d,
    
    -- Velocity Ratio: 30d spend vs normalized 90d spend (Ratio < 1.0 indicates spending deceleration)
    CASE 
        WHEN ISNULL(t.tx_volume_90d, 0.0) > 0.0 
        THEN ROUND(ISNULL(t.tx_volume_30d, 0.0) / (t.tx_volume_90d / 3.0), 4)
        ELSE 1.0000 
    END AS tx_volume_velocity_ratio,
    
    -- Failed Transaction Rate (Leading indicator of technical or cash issues)
    CASE 
        WHEN ISNULL(t.tx_count_30d, 0) > 0 
        THEN ROUND(CAST(t.failed_tx_count_30d AS FLOAT) / t.tx_count_30d, 4)
        ELSE 0.0000 
    END AS failed_tx_rate_30d,
    
    -- Balance & Cash Dynamics
    ISNULL(b.current_balance_usd, a.initial_deposit_usd) AS current_balance_usd,
    ISNULL(b.avg_balance_30d, a.initial_deposit_usd) AS avg_balance_30d,
    ISNULL(b.avg_balance_90d, a.initial_deposit_usd) AS avg_balance_90d,
    ISNULL(b.balance_volatility_30d, 0.0) AS balance_volatility_30d,
    
    -- Balance Decay: % change in balance from 90d baseline to recent 30d (Negative = burning cash)
    CASE 
        WHEN ISNULL(b.avg_balance_90d, 0.0) > 0.0 
        THEN ROUND((ISNULL(b.avg_balance_30d, 0.0) - b.avg_balance_90d) / b.avg_balance_90d, 4)
        ELSE 0.0000 
    END AS balance_decay_pct,
    
    -- Telemetry & Engagement
    ISNULL(tel.api_calls_30d, 0) AS api_calls_30d,
    ISNULL(tel.api_calls_90d, 0) AS api_calls_90d,
    ISNULL(tel.logins_30d, 0) AS logins_30d,
    ISNULL(tel.logins_90d, 0) AS logins_90d,
    ISNULL(tel.exports_30d, 0) AS exports_30d,
    ISNULL(tel.days_since_last_api_call, 90) AS days_since_last_api_call,
    ISNULL(tel.days_since_last_login, 90) AS days_since_last_login,
    
    -- Telemetry Velocity: 30d API calls vs normalized 90d (Ratio < 1.0 indicates disengagement)
    CASE 
        WHEN ISNULL(tel.api_calls_90d, 0) > 0 
        THEN ROUND(CAST(ISNULL(tel.api_calls_30d, 0) AS FLOAT) / (tel.api_calls_90d / 3.0), 4)
        ELSE 1.0000 
    END AS telemetry_velocity_ratio,
    
    -- Target Label
    a.churn_next_60d
FROM active_accounts_at_cutoff a
LEFT JOIN transaction_features t ON a.account_id = t.account_id
LEFT JOIN balance_features b ON a.account_id = b.account_id
LEFT JOIN telemetry_features tel ON a.account_id = tel.account_id;
