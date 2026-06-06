-- Monthly Recurring Revenue (MRR) Waterfall Analysis
-- Decomposes month-over-month MRR movements into New, Expansion, Contraction, and Churn


WITH monthly_account_subscriptions AS (
    -- Step 1: Extract every account's monthly MRR and fetch prior month's MRR using LAG()
    SELECT
        account_id,
        billing_month,
        mrr_amount,
        billing_status,
        LAG(mrr_amount, 1, 0.00) OVER (
            PARTITION BY account_id 
            ORDER BY billing_month
        ) AS previous_mrr_amount,
        LAG(billing_status, 1, 'None') OVER (
            PARTITION BY account_id 
            ORDER BY billing_month
        ) AS previous_billing_status
    FROM fact_subscriptions
),

mrr_movements_classified AS (
    -- Step 2: Categorize every transition into standard SaaS movement buckets
    SELECT
        account_id,
        billing_month,
        previous_mrr_amount,
        mrr_amount AS current_mrr_amount,
        
        -- New MRR: Account had 0 prior MRR and now has active MRR
        CASE 
            WHEN previous_mrr_amount = 0.00 AND mrr_amount > 0.00 THEN mrr_amount
            ELSE 0.00 
        END AS new_mrr,
        
        -- Expansion MRR: Existing account paying more than prior month
        CASE 
            WHEN previous_mrr_amount > 0.00 AND mrr_amount > previous_mrr_amount THEN (mrr_amount - previous_mrr_amount)
            ELSE 0.00 
        END AS expansion_mrr,
        
        -- Contraction MRR: Existing account paying less than prior month (but not 0)
        CASE 
            WHEN previous_mrr_amount > 0.00 AND mrr_amount < previous_mrr_amount AND mrr_amount > 0.00 THEN (previous_mrr_amount - mrr_amount)
            ELSE 0.00 
        END AS contraction_mrr,
        
        -- Churned MRR: Account had prior MRR and now has 0 MRR
        CASE 
            WHEN previous_mrr_amount > 0.00 AND (mrr_amount = 0.00 OR billing_status = 'Churned') THEN previous_mrr_amount
            ELSE 0.00 
        END AS churned_mrr
    FROM monthly_account_subscriptions
),

monthly_waterfall_summary AS (
    -- Step 3: Aggregate across all accounts to compute the corporate MRR waterfall per month
    SELECT
        billing_month,
        SUM(new_mrr) AS total_new_mrr,
        SUM(expansion_mrr) AS total_expansion_mrr,
        SUM(contraction_mrr) AS total_contraction_mrr,
        SUM(churned_mrr) AS total_churned_mrr,
        SUM(current_mrr_amount) AS total_ending_mrr,
        
        -- Net New MRR = (New + Expansion) - (Contraction + Churn)
        (SUM(new_mrr) + SUM(expansion_mrr)) - (SUM(contraction_mrr) + SUM(churned_mrr)) AS net_new_mrr
    FROM mrr_movements_classified
    GROUP BY billing_month
)

-- Final Output: Ordered by calendar month with growth rates
SELECT
    billing_month,
    total_ending_mrr - net_new_mrr AS starting_mrr,
    total_new_mrr,
    total_expansion_mrr,
    total_contraction_mrr,
    total_churned_mrr,
    net_new_mrr,
    total_ending_mrr,
    CASE 
        WHEN (total_ending_mrr - net_new_mrr) > 0 
        THEN ROUND((net_new_mrr * 100.0) / (total_ending_mrr - net_new_mrr), 2)
        ELSE 0.00 
    END AS mrr_growth_rate_pct
FROM monthly_waterfall_summary
ORDER BY billing_month ASC;
