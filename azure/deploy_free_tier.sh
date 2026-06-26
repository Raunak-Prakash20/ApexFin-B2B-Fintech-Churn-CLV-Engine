#!/usr/bin/env bash
# Automated Azure CLI provisioning script for serverless architecture
set -e

RESOURCE_GROUP="rg-fintech-analytics"
LOCATION="eastus"
RAND_SUFFIX=$((1000 + RANDOM % 9000))
SQL_SERVER="sql-fintech-srv-${RAND_SUFFIX}"
SQL_DATABASE="fintech-dw"
SQL_USER="fintechadmin"
SQL_PASSWORD="P@ssw0rd${RAND_SUFFIX}!"

echo "================================================================================"
echo "[*] Provisioning Azure data platform infrastructure..."
echo "================================================================================"

# 1. Create Resource Group
echo "[*] Creating Resource Group: ${RESOURCE_GROUP}..."
az group create --name "${RESOURCE_GROUP}" --location "${LOCATION}" --output none

# 2. Create Azure SQL Server
echo "[*] Creating Azure SQL Server: ${SQL_SERVER}..."
az sql server create \
    --name "${SQL_SERVER}" \
    --resource-group "${RESOURCE_GROUP}" \
    --location "${LOCATION}" \
    --admin-user "${SQL_USER}" \
    --admin-password "${SQL_PASSWORD}" \
    --output none

# 3. Create Azure SQL Database Free Offer (32GB, 100k vCore-secs, AutoPause)
echo "[*] Provisioning Azure SQL Database Free Offer..."
az sql db create \
    --resource-group "${RESOURCE_GROUP}" \
    --server "${SQL_SERVER}" \
    --name "${SQL_DATABASE}" \
    --edition GeneralPurpose \
    --compute-model Serverless \
    --family Gen5 \
    --capacity 0.5 \
    --auto-pause-delay 60 \
    --use-free-limit true \
    --free-limit-exhaustion-behavior AutoPause \
    --output none

# 4. Firewall Rule for Azure Services
az sql server firewall-rule create \
    --resource-group "${RESOURCE_GROUP}" \
    --server "${SQL_SERVER}" \
    --name "AllowAzureServices" \
    --start-ip-address 0.0.0.0 \
    --end-ip-address 0.0.0.0 \
    --output none

# 5. Write .env
cat <<EOF > .env
AZURE_SQL_SERVER=${SQL_SERVER}.database.windows.net
AZURE_SQL_DATABASE=${SQL_DATABASE}
AZURE_SQL_USER=${SQL_USER}
AZURE_SQL_PASSWORD=${SQL_PASSWORD}
AZURE_SQL_DRIVER=ODBC Driver 18 for SQL Server
EOF

echo "[+] Azure Free Tier Deployment Complete! .env file written."
