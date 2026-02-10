# Researcher Platform - Azure Deployment Guide

This guide explains how to deploy the Researcher AI-powered brand research platform to a new Azure tenant using Bicep infrastructure-as-code.

## Overview

The Researcher platform consists of:
- **Backend**: Python FastAPI running on Azure Container Apps
- **Frontend**: React/Vite static site on Azure Static Web Apps
- **Secrets**: Azure Key Vault with managed identity
- **Monitoring**: Application Insights + Log Analytics
- **Registry**: Azure Container Registry (ACR)

## Prerequisites

Before deploying, ensure you have:

1. **Azure CLI** installed (`az --version`)
2. **Bicep CLI** installed (`az bicep install`)
3. **Docker** installed (for building container image)
4. **Node.js** (for building frontend)
5. **API Keys** for:
   - Anthropic (Claude API)
   - Tavily (Web search)
   - OpenAI (GPT API + optional web search)

## Deployment Steps

### 1. Create Resource Group

```bash
az group create \
  --name Researcher \
  --location eastus2
```

### 2. Prepare Parameters

Edit `main.bicepparam` with your actual values:

```json
{
  "appPassword": "YourStrongPassword123!",
  "anthropicApiKey": "sk-ant-api03-...",
  "tavilyApiKey": "tvly-...",
  "openaiApiKey": "sk-proj-..."
}
```

**Security Note**: Never commit this file with real secrets to git. Use Azure Key Vault or CI/CD secrets instead.

### 3. Deploy Infrastructure

```bash
az deployment group create \
  --resource-group Researcher \
  --template-file infrastructure/main.bicep \
  --parameters infrastructure/main.bicepparam
```

Or use the Azure Portal:
1. Go to Resource Group → Deployments
2. Click "Deploy with custom template"
3. Upload `main.bicep`
4. Fill in the parameters

### 4. Build and Push Container Image

After deployment, get the ACR name from outputs:

```bash
# Login to ACR
az acr login --name <acr-name>

# Build image
docker build \
  -t <acr-login-server>/researcher-api:v39 \
  -f backend/Dockerfile \
  backend

# Push image
docker push <acr-login-server>/researcher-api:v39
```

### 5. Deploy Frontend

Get the Static Web App deployment token:

```bash
az staticwebapp secrets list \
  --name <static-web-app-name> \
  --resource-group Researcher \
  --query "properties.apiKey" \
  -o tsv
```

Build and deploy:

```bash
cd frontend
npm install
npm run build

# Deploy using SWA CLI
npx @azure/static-web-apps-cli@2.0.8 deploy \
  ./dist \
  --deployment-token <token> \
  --env production
```

Or set the deployment token as an environment variable:

```bash
export AZURE_SWA_TOKEN=<your-token>
node deploy.js
```

## Accessing the Application

After deployment:

- **Frontend**: Check output `staticWebAppUrl` or Azure Portal
- **Backend API**: Check output `containerAppUrl`
- **Password**: The value you set in `appPassword` parameter

### Verify Deployment

```bash
# Test backend health
curl https://<container-app-fqdn>/health

# Test research endpoint
curl -X POST https://<container-app-fqdn>/research \
  -H "Authorization: Bearer <app-password>" \
  -H "Content-Type: application/json" \
  -d '{"question": "Test question", "provider": "anthropic"}'
```

## Architecture

```
┌─────────────────────┐
│  Static Web App     │  ← React Frontend
│  (researcher-web)   │
└─────────┬───────────┘
          │ HTTPS
          ▼
┌─────────────────────┐
│  Container App      │  ← FastAPI Backend
│  (researcher-api)   │
│  - System-assigned  │
│    managed identity │
└─────────┬───────────┘
          │
    ┌─────┴─────┐
    ▼           ▼
┌─────────┐  ┌─────────────┐
│ Key     │  │ Anthropic   │
│ Vault   │  │ Tavily      │
│ Secrets │  │ OpenAI      │
└─────────┘  └─────────────┘
```

## Security Considerations

1. **Secrets**: All API keys stored in Key Vault, referenced by Container App
2. **Managed Identity**: Container App uses system-assigned identity (no credentials in code)
3. **Network**: Container App ingress is external but requires Bearer token
4. **Password**: Use strong password for app-level authentication

## Updating the Application

### Update Backend

```bash
# Build new version
docker build -t <acr-login-server>/researcher-api:v40 -f backend/Dockerfile backend
docker push <acr-login-server>/researcher-api:v40

# Update Container App
az containerapp update \
  --name researcher-api \
  --resource-group Researcher \
  --image <acr-login-server>/researcher-api:v40
```

### Update Frontend

```bash
cd frontend
npm run build
npx @azure/static-web-apps-cli deploy ./dist --deployment-token <token> --env production
```

## Monitoring

- **Application Insights**: Check `appInsightsName` in Azure Portal
- **Logs**: Query Log Analytics workspace for container logs
- **Metrics**: Container App scaling and performance metrics

## Troubleshooting

### Container won't start

```bash
# Check logs
az containerapp logs show \
  --name researcher-api \
  --resource-group Researcher \
  --tail 100
```

### Key Vault access denied

Ensure the Container App's managed identity has access:

```bash
az keyvault set-policy \
  --name <key-vault-name> \
  --object-id <container-app-principal-id> \
  --secret-permissions get list
```

### Frontend 404 errors

Verify the deployment token hasn't expired:

```bash
az staticwebapp secrets list \
  --name <static-web-app-name> \
  --resource-group Researcher
```

## Cost Optimization

- **Container App**: Uses Consumption tier (pay per use)
- **Static Web App**: Free tier (sufficient for most use cases)
- **ACR**: Basic tier (upgrade for geo-replication)
- **Key Vault**: Standard tier

Estimated monthly cost: ~$20-50 USD (depending on usage)

## Cleanup

To remove all resources:

```bash
az group delete --name Researcher --yes
```

## Support

For issues or questions:
- Check GitHub Issues: https://github.com/kabzadev/Researcher/issues
- Review backend logs in Log Analytics
- Verify all API keys are valid and have quota
