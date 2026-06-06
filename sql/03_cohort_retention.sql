-- Cohort Retention and Net Revenue Retention (NRR) Analysis
-- Computes customer logo retention and dollar retention normalized by cohort tenure


WITH account_cohorts AS (
    -- Step 1: Assign each account to a signup cohort (First day of signup month)
    SELECT
        account_id,
        signup_date,
        CAST(DATEADD(month, DATEDIFF(month, 0, signup_date), 0) AS DATE) AS cohort_month
    FROM dim_accounts
),

account_monthly_activity AS (
    -- Step 2: Join subscriptions to cohort data and compute month_offset (0, 1, 2... N)
    SELECT
        c.cohort_month,
        c.account_id,
        s.billing_month,
        s.mrr_amount,
        s.billing_status,
        -- Month index relative to cohort signup (Month 0 is the join month)
        DATEDIFF(month, c.cohort_month, s.billing_month) AS month_number
    FROM account_cohorts c
    INNER JOIN fact_subscriptions s
        ON c.account_id = s.account_id
    WHERE s.mrr_amount > 0.00 AND s.billing_status = 'Paid'
),

cohort_sizes AS (
    -- Step 3: Compute the baseline size (Month 0 active accounts and Month 0 starting MRR)
    SELECT
        cohort_month,
        COUNT(DISTINCT account_id) AS cohort_total_accounts,
        SUM(mrr_amount) AS cohort_starting_mrr
    FROM account_monthly_activity
    WHERE month_number = 0
    GROUP BY cohort_month
),

cohort_retention_raw AS (
    -- Step 4: Aggregate active accounts and retained MRR for each (cohort_month, month_number)
    SELECT
        a.cohort_month,
        a.month_number,
        COUNT(DISTINCT a.account_id) AS active_accounts,
        SUM(a.mrr_amount) AS retained_mrr
    FROM account_monthly_activity a
    GROUP BY a.cohort_month, a.month_number
)

-- Final Output: Calculate Logo Retention % and Net Revenue Retention % (NRR)
SELECT
    r.cohort_month,
    s.cohort_total_accounts,
    ROUND(s.cohort_starting_mrr, 2) AS cohort_starting_mrr,
    r.month_number,
    r.active_accounts,
    ROUND(r.retained_mrr, 2) AS retained_mrr,
    
    -- Logo Retention % = (Active Accounts in Month N / Initial Accounts in Month 0) * 100
    ROUND((r.active_accounts * 100.0) / s.cohort_total_accounts, 2) AS logo_retention_pct,
    
    -- Net Revenue Retention % (NRR) = (Retained MRR in Month N / Starting MRR in Month 0) * 100
    -- If > 100%, indicates that expansion within surviving accounts outpaces churn
    ROUND((r.retained_mrr * 100.0) / s.cohort_starting_mrr, 2) AS net_revenue_retention_pct
FROM cohort_retention_raw r
INNER JOIN cohort_sizes s
    ON r.cohort_month = s.cohort_month
ORDER BY 
    r.cohort_month ASC, 
    r.month_number ASC;
