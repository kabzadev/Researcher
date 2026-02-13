// ============================================================================
// KAIA Researcher — Full Infrastructure (self-contained, customer-ready)
//
// Deploys: Azure OpenAI (with gpt-4o) + Key Vault + ACR + Container App
//          + Log Analytics + RBAC role assignments
//
// PREREQUISITES (run once per subscription before deploying):
//   az feature unregister --name OpenAI.BlockedTools.web_search \
//     --namespace Microsoft.CognitiveServices
//   az provider register -n Microsoft.CognitiveServices
//
// USAGE:
//   az group create -n <rg-name> -l eastus
//   az deployment group create -g <rg-name> \
//     --template-file deploy-kantar.bicep \
//     --parameters appPassword='<password>' containerImageTag='placeholder'
//   # Then: build/push Docker image and update Container App image tag
// ============================================================================

@description('Base name for all resources')
param baseName string = 'kaia-researcher'

@description('Azure region')
param location string = resourceGroup().location

@description('App password for the application')
@secure()
param appPassword string

@description('Container image tag to deploy (use "placeholder" for initial infra-only deploy)')
param containerImageTag string = 'v1'

@description('Azure OpenAI model to deploy')
param openAiModelName string = 'gpt-4o'

@description('Azure OpenAI model version')
param openAiModelVersion string = '2024-08-06'

@description('Azure OpenAI API version for Responses API + web_search_preview')
param openAiApiVersion string = '2025-04-01-preview'

@description('Azure OpenAI deployment SKU capacity (1000s of tokens per minute)')
param openAiCapacity int = 80

@description('Container App CPU cores')
param cpuCores string = '1.0'

@description('Container App memory')
param memory string = '2.0Gi'

@description('Min replicas for Container App')
param minReplicas int = 1

@description('Max replicas for Container App')
param maxReplicas int = 3

// Resource naming (suffix keeps names globally unique but short)
var suffix = substring(uniqueString(resourceGroup().id), 0, 6)
var acrName = '${replace(baseName, '-', '')}${suffix}'
var kvName = '${baseName}-kv${suffix}'
var openAiName = '${baseName}-openai'
var logAnalyticsName = '${baseName}-law'
var containerAppEnvName = '${baseName}-env'
var containerAppName = '${baseName}-api'
var appInsightsName = '${baseName}-appinsights'

// Well-known role definition IDs
var cognitiveServicesOpenAiUserRoleId = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'

// ─── Azure OpenAI ───────────────────────────────────────────────────────────

resource openAi 'Microsoft.CognitiveServices/accounts@2023-10-01-preview' = {
  name: openAiName
  location: location
  kind: 'OpenAI'
  sku: {
    name: 'S0'
  }
  properties: {
    customSubDomainName: openAiName
    publicNetworkAccess: 'Enabled'
    // Note: if subscription policy enforces disableLocalAuth=true,
    // the backend uses Managed Identity (DefaultAzureCredential) instead of API keys
  }
}

resource openAiDeployment 'Microsoft.CognitiveServices/accounts/deployments@2023-10-01-preview' = {
  parent: openAi
  name: openAiModelName
  sku: {
    name: 'Standard'
    capacity: openAiCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: openAiModelName
      version: openAiModelVersion
    }
  }
}

// ─── Log Analytics ──────────────────────────────────────────────────────────

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2022-10-01' = {
  name: logAnalyticsName
  location: location
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
  }
}

// ─── Application Insights ───────────────────────────────────────────────────

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: appInsightsName
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logAnalytics.id
    RetentionInDays: 30
  }
}

// ─── Key Vault ──────────────────────────────────────────────────────────────

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: kvName
  location: location
  properties: {
    sku: {
      family: 'A'
      name: 'standard'
    }
    tenantId: subscription().tenantId
    enableRbacAuthorization: false
    accessPolicies: []
  }
}

resource kvSecretAppPassword 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'app-password'
  properties: {
    value: appPassword
  }
}

// ─── Container Registry ─────────────────────────────────────────────────────

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: acrName
  location: location
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: true
  }
}

// ─── Container App Environment ──────────────────────────────────────────────

resource containerAppEnv 'Microsoft.App/managedEnvironments@2023-11-02-preview' = {
  name: containerAppEnvName
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalytics.properties.customerId
        sharedKey: logAnalytics.listKeys().primarySharedKey
      }
    }
  }
}

// ─── Container App ──────────────────────────────────────────────────────────

resource containerApp 'Microsoft.App/containerApps@2023-11-02-preview' = {
  name: containerAppName
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    managedEnvironmentId: containerAppEnv.id
    configuration: {
      ingress: {
        external: true
        targetPort: 8000
        transport: 'auto'
        allowInsecure: false
      }
      secrets: [
        {
          name: 'app-password'
          value: appPassword
        }
        {
          name: 'acr-password'
          value: acr.listCredentials().passwords[0].value
        }
      ]
      registries: [
        {
          server: acr.properties.loginServer
          username: acr.name
          passwordSecretRef: 'acr-password'
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'researcher-api'
          image: containerImageTag == 'placeholder' ? 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest' : '${acr.properties.loginServer}/kaia-researcher-api:${containerImageTag}'
          resources: {
            cpu: json(cpuCores)
            memory: memory
          }
          env: [
            // Azure OpenAI — uses Managed Identity (DefaultAzureCredential), no API key needed
            {
              name: 'AZURE_OPENAI_ENDPOINT'
              value: openAi.properties.endpoint
            }
            {
              name: 'AZURE_OPENAI_API_VERSION'
              value: openAiApiVersion
            }
            {
              name: 'OPENAI_MODEL'
              value: openAiModelName
            }
            {
              name: 'DEFAULT_LLM_PROVIDER'
              value: 'openai'
            }
            // Application
            {
              name: 'RESEARCHER_APP_PASSWORD'
              secretRef: 'app-password'
            }
            // Observability (Application Insights via OpenTelemetry)
            {
              name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
              value: appInsights.properties.ConnectionString
            }
            {
              name: 'LOG_ANALYTICS_WORKSPACE_ID'
              value: logAnalytics.properties.customerId
            }
          ]
        }
      ]
      scale: {
        minReplicas: minReplicas
        maxReplicas: maxReplicas
      }
    }
  }
}

// ─── RBAC: Container App → Azure OpenAI ─────────────────────────────────────
// Grants the Container App's Managed Identity "Cognitive Services OpenAI User"
// role on the Azure OpenAI resource, enabling Entra ID / token-based auth.

resource openAiRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(containerApp.id, openAi.id, cognitiveServicesOpenAiUserRoleId)
  scope: openAi
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesOpenAiUserRoleId)
    principalId: containerApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// ─── RBAC: Container App → Key Vault ────────────────────────────────────────

resource keyVaultAccessPolicy 'Microsoft.KeyVault/vaults/accessPolicies@2023-07-01' = {
  parent: keyVault
  name: 'add'
  properties: {
    accessPolicies: [
      {
        tenantId: subscription().tenantId
        objectId: containerApp.identity.principalId
        permissions: {
          secrets: [
            'get'
            'list'
          ]
        }
      }
    ]
  }
}

// ─── Outputs ────────────────────────────────────────────────────────────────

output acrLoginServer string = acr.properties.loginServer
output acrName string = acr.name
output keyVaultName string = keyVault.name
output containerAppUrl string = containerApp.properties.configuration.ingress.fqdn
output openAiEndpoint string = openAi.properties.endpoint
output openAiDeployment string = openAiDeployment.name
output logAnalyticsWorkspaceId string = logAnalytics.properties.customerId
output appInsightsConnectionString string = appInsights.properties.ConnectionString

// Post-deployment steps (printed as output for reference)
output postDeploySteps string = '''
=== POST-DEPLOYMENT STEPS ===

1. ENABLE WEB SEARCH (one-time per subscription):
   az feature unregister --name OpenAI.BlockedTools.web_search \
     --namespace Microsoft.CognitiveServices
   az provider register -n Microsoft.CognitiveServices

2. BUILD AND PUSH DOCKER IMAGE:
   az acr login --name <acrName>
   docker build --platform linux/amd64 \
     -t <acrLoginServer>/kaia-researcher-api:v1 \
     -f backend/Dockerfile backend
   docker push <acrLoginServer>/kaia-researcher-api:v1

3. UPDATE CONTAINER APP IMAGE:
   az containerapp update --name kaia-researcher-api \
     --resource-group <rg> \
     --image <acrLoginServer>/kaia-researcher-api:v1

4. UPDATE FRONTEND API_URL:
   Set API_URL in ChatInterface.tsx, Dashboard.tsx, Eval.tsx
   to: https://<containerAppUrl>

5. BUILD AND DEPLOY FRONTEND:
   cd frontend && npm run build
   npx @azure/static-web-apps-cli deploy ./dist \
     --deployment-token <token>

6. UPDATE CORS (add SWA URL to backend/main.py allow_origins)
'''
