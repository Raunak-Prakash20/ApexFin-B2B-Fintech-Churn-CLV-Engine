# Microsoft Azure Serverless Architecture Guide

This guide explains how the data platform is deployed on **Microsoft Azure** using serverless configurations with strict cost controls.

---

## 1. Always-Free Services & Free Offers Utilized

| Azure Service | Tier / Plan | Free Allocation | How We Guarantee $0 Cost |
| :--- | :--- | :--- | :--- |
| **Azure SQL Database** | General Purpose Serverless (Gen5) | **32 GB Storage** & **100,000 vCore-seconds/month** | We pass `--use-free-limit true` and `--free-limit-exhaustion-behavior AutoPause`. When the monthly quota is reached, compute pauses automatically rather than billing. |
| **Azure Blob Storage** | Standard LRS (Hot/Cool) | **5 GB LRS Storage** (First 12 months) | Used only for staging raw transactional CSVs (<50 MB total). |
| **Azure Functions** | Consumption Plan | **1,000,000 executions/month** | Used for weekly batch inference (only runs ~4 times/month = ~4 executions). |
| **Azure App Service** | F1 Free Tier | **1 GB RAM, 1 GB Storage** | Can be used to host the Streamlit dashboard 24/7 for free. |

---

## 2. Step-by-Step Deployment (PowerShell or Bash)

### Option A: Using PowerShell (Windows)
```powershell
# 1. Login to Azure CLI
az login

# 2. Run automated zero-cost provisioning script
.\azure\deploy_free_tier.ps1
```

### Option B: Using Bash (Linux / macOS)
```bash
# 1. Login to Azure CLI
az login

# 2. Run automated zero-cost provisioning script
chmod +x azure/deploy_free_tier.sh
./azure/deploy_free_tier.sh
```

---

## 3. How the Azure SQL Serverless Free Offer Works

Microsoft provides **one free Azure SQL Database per Azure subscription for the lifetime of the subscription**.

### Key Technical Parameters:
- **Compute Model**: Serverless (vCores scale dynamically from 0.5 to 1 vCore based on query demand).
- **Auto-Pause Delay**: Set to `60 minutes`. If no queries hit the database for 60 minutes, the compute node shuts down completely (0 vCores running), consuming 0 vCore seconds.
- **Auto-Resume**: When a new connection arrives (e.g. from Streamlit or Python), Azure wakes the database up automatically within 15-30 seconds.
- **Free Limit Exhaustion Behavior**: Set to `AutoPause`. If your queries consume 100,000 vCore seconds in a calendar month, Azure freezes compute until the 1st of the next month. **No charges can ever be billed.**

---

## 4. Local Hybrid Fallback (No Azure Account Required)

If evaluating locally without active Azure cloud credentials, the project automatically detects the absence of Azure credentials in `.env` and defaults to an in-process, high-performance **DuckDB** local data warehouse.

- **100% Free**: No cloud account or credit card needed.
- **Zero Latency**: Executes all T-SQL/Postgres window functions, CTEs, and cohort matrices locally in milliseconds.
- **Seamless Switch**: Simply fill in `.env` to point to Azure SQL whenever ready!

