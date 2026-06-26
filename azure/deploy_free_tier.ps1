<#
.SYNOPSIS
    Provisions cloud data infrastructure on Microsoft Azure using serverless allocations.
#>

param (
    [string]$ResourceGroupName = "rg-fintech-analytics",
    [string]$Location = "eastus",
    [string]$SqlServerName = "sql-fintech-srv-$((Get-Random -Minimum 1000 -Maximum 9999))",
    [string]$SqlDatabaseName = "fintech-dw",
    [string]$SqlAdminUser = "fintechadmin",
    [string]$SqlAdminPassword = "P@ssw0rd$((Get-Random -Minimum 1000 -Maximum 9999))!"
)

Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host "[*] PROVISIONING MICROSOFT AZURE ZERO-COST DATA SCIENCE INFRASTRUCTURE" -ForegroundColor Cyan
Write-Host "================================================================================" -ForegroundColor Cyan

# 1. Check Azure CLI Login
Write-Host "[*] Verifying Azure CLI authentication..." -ForegroundColor Yellow
$account = az account show --query "name" -o tsv 2>$null
if (-not $account) {
    Write-Host "[!] You are not logged into Azure CLI. Running 'az login'..." -ForegroundColor Red
    az login
}

# 2. Create Resource Group
Write-Host "[*] Creating Resource Group: $ResourceGroupName in $Location..." -ForegroundColor Yellow
az group create --name $ResourceGroupName --location $Location --output none

# 3. Create Azure SQL Server
Write-Host "[*] Creating Azure SQL Server: $SqlServerName..." -ForegroundColor Yellow
az sql server create `
    --name $SqlServerName `
    --resource-group $ResourceGroupName `
    --location $Location `
    --admin-user $SqlAdminUser `
    --admin-password $SqlAdminPassword `
    --output none

# 4. Create Azure SQL Database with FREE TIER Offer (Serverless 32GB, 100k vCore-secs)
Write-Host "[*] Provisioning Azure SQL Database Free Offer (32GB Free, 100k vCore-secs)..." -ForegroundColor Yellow
az sql db create `
    --resource-group $ResourceGroupName `
    --server $SqlServerName `
    --name $SqlDatabaseName `
    --edition GeneralPurpose `
    --compute-model Serverless `
    --family Gen5 `
    --capacity 0.5 `
    --auto-pause-delay 60 `
    --use-free-limit true `
    --free-limit-exhaustion-behavior AutoPause `
    --output none

# 5. Configure Firewall to Allow Azure Services and Client IP
Write-Host "[*] Configuring Azure SQL Firewall rules..." -ForegroundColor Yellow
# Allow Azure services
az sql server firewall-rule create `
    --resource-group $ResourceGroupName `
    --server $SqlServerName `
    --name "AllowAzureServices" `
    --start-ip-address 0.0.0.0 `
    --end-ip-address 0.0.0.0 `
    --output none

# Allow current public IP
$clientIp = (Invoke-RestMethod -Uri "https://api.ipify.org")
Write-Host "[*] Adding your client IP ($clientIp) to SQL Server firewall..." -ForegroundColor Yellow
az sql server firewall-rule create `
    --resource-group $ResourceGroupName `
    --server $SqlServerName `
    --name "ClientIP" `
    --start-ip-address $clientIp `
    --end-ip-address $clientIp `
    --output none

# 6. Generate .env File
$envContent = @"
# Microsoft Azure SQL Database Configuration (Zero-Cost Free Tier)
AZURE_SQL_SERVER=$SqlServerName.database.windows.net
AZURE_SQL_DATABASE=$SqlDatabaseName
AZURE_SQL_USER=$SqlAdminUser
AZURE_SQL_PASSWORD=$SqlAdminPassword
AZURE_SQL_DRIVER=ODBC Driver 18 for SQL Server
"@

$envPath = Join-Path (Get-Location) ".env"
$envContent | Out-File -FilePath $envPath -Encoding utf8

Write-Host "================================================================================" -ForegroundColor Green
Write-Host "[+] AZURE ZERO-COST PROVISIONING COMPLETE!" -ForegroundColor Green
Write-Host "    - Server:       $SqlServerName.database.windows.net" -ForegroundColor Green
Write-Host "    - Database:     $SqlDatabaseName (Free Tier Active)" -ForegroundColor Green
Write-Host "    - Admin User:   $SqlAdminUser" -ForegroundColor Green
Write-Host "    - .env File:    Successfully generated at $envPath" -ForegroundColor Green
Write-Host "================================================================================" -ForegroundColor Green
