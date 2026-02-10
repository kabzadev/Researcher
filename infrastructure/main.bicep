@description('Base name for all resources')
param baseName string = 'researcher'

@description('Azure region')
param location string = resourceGroup().location

@description('Environment name')
param environment string = 'prod'

@description('Container image tag to deploy')
param containerImageTag string = 'v39'

@description('App password for the application (will be stored in Key Vault)')
@secure()
param appPassword string

@description('Anthropic API key')
@secure()
param anthropicApiKey string

@description('Tavily API key')
@secure()
param tavilyApiKey string

@description('OpenAI API key')
@secure()
param openaiApiKey string

@description('Enable OpenAI web search as primary search backend')
param enableOpenAiSearch bool = false

@description('Container App CPU cores')
param cpuCores string = '0.5'

@description('Container App memory')
param memory string = '1.0Gi'

@description('Min replicas for Container App')
param minReplicas int = 1

@description('Max replicas for Container App')
param maxReplicas int = 3

// Resource naming
var acrName = '${baseName}acr${uniqueString(resourceGroup().id)}'
var kvName = '${baseName}-kv-${uniqueString(resourceGroup().id)}'
var appInsightsName = '${baseName}-insights'
var logAnalyticsName = '${baseName}-law'
var containerAppEnvName = '${baseName}-env'
var containerAppName = '${baseName}-api'
var staticWebAppName = '${baseName}-web'

// Create Container Registry
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

// Create Log Analytics Workspace
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

// Create Application Insights
resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: appInsightsName
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logAnalytics.id
    publicNetworkAccessForIngestion: 'Enabled'
    publicNetworkAccessForQuery: 'Enabled'
  }
}

// Create Key Vault
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

// Add secrets to Key Vault
resource kvSecretAppPassword 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'apppass'
  properties: {
    value: appPassword
  }
}

resource kvSecretAnthropic 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'anthropic'
  properties: {
    value: anthropicApiKey
  }
}

resource kvSecretTavily 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'tavily'
  properties: {
    value: tavilyApiKey
  }
}

resource kvSecretOpenAi 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'openai'
  properties: {
    value: openaiApiKey
  }
}

resource kvSecretAppInsights 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'appinsights'
  properties: {
    value: appInsights.properties.ConnectionString
  }
}

// Create Container App Environment
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

// Create Container App with User-Assigned Identity
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
          name: 'anthropic-api-key'
          keyVaultUrl: kvSecretAnthropic.properties.secretUri
          identity: 'System'
        }
        {
          name: 'tavily-api-key'
          keyVaultUrl: kvSecretTavily.properties.secretUri
          identity: 'System'
        }
        {
          name: 'openai-api-key'
          keyVaultUrl: kvSecretOpenAi.properties.secretUri
          identity: 'System'
        }
        {
          name: 'app-password'
          keyVaultUrl: kvSecretAppPassword.properties.secretUri
          identity: 'System'
        }
        {
          name: 'appinsights-connection'
          keyVaultUrl: kvSecretAppInsights.properties.secretUri
          identity: 'System'
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
          image: '${acr.properties.loginServer}/researcher-api:${containerImageTag}'
          resources: {
            cpu: json(cpuCores)
            memory: memory
          }
          env: [
            {
              name: 'ANTHROPIC_API_KEY'
              secretRef: 'anthropic-api-key'
            }
            {
              name: 'TAVILY_API_KEY'
              secretRef: 'tavily-api-key'
            }
            {
              name: 'OPENAI_API_KEY'
              secretRef: 'openai-api-key'
            }
            {
              name: 'RESEARCHER_APP_PASSWORD'
              secretRef: 'app-password'
            }
            {
              name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
              secretRef: 'appinsights-connection'
            }
            {
              name: 'DEFAULT_LLM_PROVIDER'
              value: enableOpenAiSearch ? 'openai' : 'anthropic'
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

// Grant Container App access to Key Vault
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

// Create Static Web App
resource staticWebApp 'Microsoft.Web/staticSites@2023-01-01' = {
  name: staticWebAppName
  location: location
  sku: {
    name: 'Free'
    tier: 'Free'
  }
  properties: {}
}

// Outputs
output acrLoginServer string = acr.properties.loginServer
output acrName string = acr.name
output keyVaultName string = keyVault.name
output containerAppUrl string = containerApp.properties.configuration.ingress.fqdn
output staticWebAppUrl string = staticWebApp.properties.defaultHostname
output appInsightsConnectionString string = appInsights.properties.ConnectionString
output logAnalyticsWorkspaceId string = logAnalytics.properties.customerId
output deploymentInstructions string = '''

=== DEPLOYMENT INSTRUCTIONS ===

1. BUILD AND PUSH DOCKER IMAGE:
   az acr login --name <acr-name>
   docker build -t <acr-login-server>/researcher-api:v39 -f backend/Dockerfile backend
   docker push <acr-login-server>/researcher-api:v39

2. GET STATIC WEB APP DEPLOYMENT TOKEN:
   az staticwebapp secrets list --name <static-web-app-name> --query "properties.apiKey" -o tsv

3. DEPLOY FRONTEND:
   cd frontend
   npm install
   npm run build
   npx @azure/static-web-apps-cli deploy ./dist --deployment-token <token> --env production

4. ACCESS APPLICATION:
   - Frontend: https://<static-web-app-hostname>
   - Backend API: https://<container-app-fqdn>
   - Password: (the value you provided for appPassword parameter)

=== NEXT STEPS ===

- Configure custom domain on Static Web App (optional)
- Set up CI/CD pipeline for automated deployments
- Configure monitoring alerts in Application Insights
- Review and adjust autoscaling settings

'''
