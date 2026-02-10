# deploy.ps1 - Azure deployment script for Researcher platform (PowerShell)
# Usage: .\deploy.ps1 -ResourceGroup Researcher -Location eastus2

param(
    [string]$ResourceGroup = "Researcher",
    [string]$Location = "eastus2",
    [string]$TemplateFile = "infrastructure/main.bicep",
    [string]$ParamsFile = "infrastructure/main.bicepparam"
)

Write-Host "=== Researcher Platform Deployment ===" -ForegroundColor Cyan
Write-Host "Resource Group: $ResourceGroup"
Write-Host "Location: $Location"
Write-Host ""

# Check prerequisites
Write-Host "Checking prerequisites..." -ForegroundColor Yellow
$tools = @("az", "docker", "npm")
foreach ($tool in $tools) {
    if (!(Get-Command $tool -ErrorAction SilentlyContinue)) {
        Write-Error "$tool is required but not installed."
        exit 1
    }
}

# Check Azure login
$account = az account show 2>$null | ConvertFrom-Json
if (!$account) {
    Write-Error "Please login with 'az login' first"
    exit 1
}

# Create resource group
Write-Host "Creating resource group..." -ForegroundColor Yellow
az group create --name $ResourceGroup --location $Location --output none

# Deploy infrastructure
Write-Host "Deploying infrastructure (this may take 5-10 minutes)..." -ForegroundColor Yellow
$deployment = az deployment group create `
    --resource-group $ResourceGroup `
    --template-file $TemplateFile `
    --parameters $ParamsFile `
    --query 'properties.outputs' `
    -o json | ConvertFrom-Json

# Extract outputs
$acrName = $deployment.acrName.value
$acrLoginServer = $deployment.acrLoginServer.value
$containerAppUrl = $deployment.containerAppUrl.value
$staticWebAppName = $deployment.staticWebAppUrl.value.Split('.')[0]
$keyVaultName = $deployment.keyVaultName.value

Write-Host ""
Write-Host "=== Infrastructure Deployed ===" -ForegroundColor Green
Write-Host "ACR: $acrLoginServer"
Write-Host "Key Vault: $keyVaultName"
Write-Host "Container App: $containerAppUrl"
Write-Host ""

# Build and push container image
Write-Host "Building container image..." -ForegroundColor Yellow
docker build -t "${acrLoginServer}/researcher-api:v39" -f backend/Dockerfile backend

Write-Host "Pushing to ACR..." -ForegroundColor Yellow
az acr login --name $acrName
docker push "${acrLoginServer}/researcher-api:v39"

Write-Host "Updating Container App with image..." -ForegroundColor Yellow
$containerAppName = $ResourceGroup.ToLower() + "-api"
az containerapp update `
    --name $containerAppName `
    --resource-group $ResourceGroup `
    --image "${acrLoginServer}/researcher-api:v39" `
    --output none

# Get SWA deployment token
Write-Host "Getting Static Web App deployment token..." -ForegroundColor Yellow
$swaToken = az staticwebapp secrets list `
    --name $staticWebAppName `
    --resource-group $ResourceGroup `
    --query "properties.apiKey" `
    -o tsv

# Build and deploy frontend
Write-Host "Building frontend..." -ForegroundColor Yellow
Set-Location frontend
npm install
npm run build

Write-Host "Deploying frontend..." -ForegroundColor Yellow
npx @azure/static-web-apps-cli@2.0.8 deploy `
    ./dist `
    --deployment-token $swaToken `
    --env production `
    --output-location ./dist

Set-Location ..

Write-Host ""
Write-Host "=== DEPLOYMENT COMPLETE ===" -ForegroundColor Green
Write-Host ""
Write-Host "Frontend URL: https://$staticWebAppName.azurestaticapps.net"
Write-Host "Backend API:  https://$containerAppUrl"
Write-Host ""
Write-Host "Test the deployment:"
Write-Host "  curl https://$containerAppUrl/health"
Write-Host ""
