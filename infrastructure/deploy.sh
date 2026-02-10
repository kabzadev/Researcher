#!/bin/bash
# deploy.sh - Azure deployment script for Researcher platform
# Usage: ./deploy.sh <resource-group> <location>

set -e

RESOURCE_GROUP=${1:-Researcher}
LOCATION=${2:-eastus2}
TEMPLATE_FILE="infrastructure/main.bicep"
PARAMS_FILE="infrastructure/main.bicepparam"

echo "=== Researcher Platform Deployment ==="
echo "Resource Group: $RESOURCE_GROUP"
echo "Location: $LOCATION"
echo ""

# Check prerequisites
echo "Checking prerequisites..."
command -v az >/dev/null 2>&1 || { echo "Azure CLI required. Install: https://aka.ms/installazurecli"; exit 1; }
command -v docker >/dev/null 2>&1 || { echo "Docker required. Install: https://docs.docker.com/get-docker"; exit 1; }
command -v npm >/dev/null 2>&1 || { echo "Node.js/npm required. Install: https://nodejs.org"; exit 1; }

# Check if logged in
az account show >/dev/null 2>&1 || { echo "Please login with 'az login' first"; exit 1; }

# Create resource group
echo "Creating resource group..."
az group create --name "$RESOURCE_GROUP" --location "$LOCATION" --output none

# Deploy infrastructure
echo "Deploying infrastructure (this may take 5-10 minutes)..."
DEPLOYMENT_OUTPUT=$(az deployment group create \
  --resource-group "$RESOURCE_GROUP" \
  --template-file "$TEMPLATE_FILE" \
  --parameters "$PARAMS_FILE" \
  --query 'properties.outputs' \
  -o json)

# Extract outputs
ACR_NAME=$(echo "$DEPLOYMENT_OUTPUT" | jq -r '.acrName.value')
ACR_LOGIN_SERVER=$(echo "$DEPLOYMENT_OUTPUT" | jq -r '.acrLoginServer.value')
CONTAINER_APP_URL=$(echo "$DEPLOYMENT_OUTPUT" | jq -r '.containerAppUrl.value')
STATIC_WEB_APP_NAME=$(echo "$DEPLOYMENT_OUTPUT" | jq -r '.staticWebAppUrl.value' | cut -d'.' -f1)
KEY_VAULT_NAME=$(echo "$DEPLOYMENT_OUTPUT" | jq -r '.keyVaultName.value')

echo ""
echo "=== Infrastructure Deployed ==="
echo "ACR: $ACR_LOGIN_SERVER"
echo "Key Vault: $KEY_VAULT_NAME"
echo "Container App: $CONTAINER_APP_URL"
echo ""

# Build and push container image
echo "Building container image..."
docker build -t "${ACR_LOGIN_SERVER}/researcher-api:v39" -f backend/Dockerfile backend

echo "Pushing to ACR..."
az acr login --name "$ACR_NAME"
docker push "${ACR_LOGIN_SERVER}/researcher-api:v39"

echo "Updating Container App with image..."
az containerapp update \
  --name "${RESOURCE_GROUP,,}-api" \
  --resource-group "$RESOURCE_GROUP" \
  --image "${ACR_LOGIN_SERVER}/researcher-api:v39" \
  --output none

# Get SWA deployment token
echo "Getting Static Web App deployment token..."
SWA_TOKEN=$(az staticwebapp secrets list \
  --name "$STATIC_WEB_APP_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --query "properties.apiKey" \
  -o tsv)

# Build and deploy frontend
echo "Building frontend..."
cd frontend
npm install
npm run build

echo "Deploying frontend..."
npx @azure/static-web-apps-cli@2.0.8 deploy \
  ./dist \
  --deployment-token "$SWA_TOKEN" \
  --env production \
  --output-location ./dist

cd ..

echo ""
echo "=== DEPLOYMENT COMPLETE ==="
echo ""
echo "Frontend URL: https://$STATIC_WEB_APP_NAME.azurestaticapps.net"
echo "Backend API:  https://$CONTAINER_APP_URL"
echo ""
echo "Test the deployment:"
echo "  curl https://$CONTAINER_APP_URL/health"
echo ""
