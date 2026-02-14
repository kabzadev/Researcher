// ┌──────────────────────────────────────────────────────────────────────────────┐
// │  KAIA Researcher — Infrastructure as Code (Bicep)                           │
// │  Resource Group: Kantar                                                     │
// │  Last synced with production: 2026-02-13 (backend v17)                      │
// └──────────────────────────────────────────────────────────────────────────────┘

targetScope = 'resourceGroup'

// ──────────────────────────────────────────────────────────────────────────────
// Parameters
// ──────────────────────────────────────────────────────────────────────────────

@description('Base name prefix for all resources')
param baseName string = 'kaia-researcher'

@description('Primary region for compute and AI resources')
param location string = 'eastus'

@description('Region for Static Web App (limited availability)')
param swaLocation string = 'eastus2'

@description('Container image tag to deploy')
param imageTag string = 'v17'

@description('OpenAI API key (stored in Key Vault)')
@secure()
param openaiApiKey string

@description('Anthropic API key (optional, stored in Key Vault)')
@secure()
param anthropicApiKey string = ''

@description('App-level bearer token for API authentication')
@secure()
param appBearerToken string = 'KantarResearch'

@description('Default model for web search grounding')
param searchModel string = 'gpt-4-1-nano'

@description('Default model for non-search LLM calls')
param llmModel string = 'gpt-4o-mini'

// ──────────────────────────────────────────────────────────────────────────────
// Variables
// ──────────────────────────────────────────────────────────────────────────────

var uniqueSuffix = uniqueString(resourceGroup().id)
var acrName = '${replace(baseName, '-', '')}${uniqueSuffix}'
var kvName = '${baseName}-kv${uniqueSuffix}'

// ──────────────────────────────────────────────────────────────────────────────
// Log Analytics Workspace
// ──────────────────────────────────────────────────────────────────────────────

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${baseName}-law'
  location: location
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
  }
}

// ──────────────────────────────────────────────────────────────────────────────
// Key Vault
// ──────────────────────────────────────────────────────────────────────────────

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: kvName
  location: location
  properties: {
    sku: {
      family: 'A'
      name: 'standard'
    }
    tenantId: subscription().tenantId
    enabledForDeployment: false
    enabledForDiskEncryption: false
    enabledForTemplateDeployment: true
    enableRbacAuthorization: true
    softDeleteRetentionInDays: 7
  }
}

resource secretOpenAI 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'openai-api-key'
  properties: {
    value: openaiApiKey
  }
}

resource secretAnthropic 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (anthropicApiKey != '') {
  parent: keyVault
  name: 'anthropic-api-key'
  properties: {
    value: anthropicApiKey
  }
}

// ──────────────────────────────────────────────────────────────────────────────
// Container Registry (ACR)
// ──────────────────────────────────────────────────────────────────────────────

resource acr 'Microsoft.ContainerRegistry/registries@2023-11-01-preview' = {
  name: acrName
  location: location
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: true
  }
}

// ──────────────────────────────────────────────────────────────────────────────
// Azure OpenAI
// ──────────────────────────────────────────────────────────────────────────────

resource openai 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: '${baseName}-openai'
  location: location
  kind: 'OpenAI'
  sku: {
    name: 'S0'
  }
  properties: {
    customSubDomainName: '${baseName}-openai'
    publicNetworkAccess: 'Enabled'
  }
}

// Model deployments
var modelDeployments = [
  { name: 'gpt-4o', model: 'gpt-4o', version: '2024-08-06', sku: 'Standard', capacity: 80 }
  { name: 'gpt-4o-latest', model: 'gpt-4o', version: '2024-11-20', sku: 'Standard', capacity: 70 }
  { name: 'gpt-4-1', model: 'gpt-4.1', version: '2025-04-14', sku: 'Standard', capacity: 50 }
  { name: 'gpt-4-1-mini', model: 'gpt-4.1-mini', version: '2025-04-14', sku: 'Standard', capacity: 50 }
  { name: 'gpt-4-1-nano', model: 'gpt-4.1-nano', version: '2025-04-14', sku: 'GlobalStandard', capacity: 50 }
  { name: 'gpt-5-mini', model: 'gpt-5-mini', version: '2025-08-07', sku: 'GlobalStandard', capacity: 50 }
  { name: 'gpt-5-nano', model: 'gpt-5-nano', version: '2025-08-07', sku: 'GlobalStandard', capacity: 50 }
]

@batchSize(1)
resource openaiDeployments 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = [
  for dep in modelDeployments: {
    parent: openai
    name: dep.name
    sku: {
      name: dep.sku
      capacity: dep.capacity
    }
    properties: {
      model: {
        format: 'OpenAI'
        name: dep.model
        version: dep.version
      }
    }
  }
]

// ──────────────────────────────────────────────────────────────────────────────
// Container Apps Environment
// ──────────────────────────────────────────────────────────────────────────────

resource containerEnv 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: '${baseName}-env'
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

// ──────────────────────────────────────────────────────────────────────────────
// Container App (API)
// ──────────────────────────────────────────────────────────────────────────────

resource containerApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: '${baseName}-api'
  location: location
  properties: {
    managedEnvironmentId: containerEnv.id
    configuration: {
      registries: [
        {
          server: acr.properties.loginServer
          username: acr.listCredentials().username
          passwordSecretRef: 'acr-password'
        }
      ]
      secrets: [
        {
          name: 'acr-password'
          value: acr.listCredentials().passwords[0].value
        }
        {
          name: 'openai-api-key'
          value: openaiApiKey
        }
        {
          name: 'anthropic-api-key'
          value: anthropicApiKey
        }
        {
          name: 'app-bearer-token'
          value: appBearerToken
        }
      ]
      ingress: {
        external: true
        targetPort: 8000
        transport: 'http'
        corsPolicy: {
          allowedOrigins: [
            'https://delightful-glacier-01802140f.4.azurestaticapps.net'
            'http://localhost:5173'
          ]
          allowedMethods: [
            'GET'
            'POST'
            'PUT'
            'DELETE'
            'OPTIONS'
          ]
          allowedHeaders: [ '*' ]
          allowCredentials: false
        }
      }
    }
    template: {
      containers: [
        {
          name: '${baseName}-api'
          image: '${acr.properties.loginServer}/kaia-researcher-api:${imageTag}'
          resources: {
            cpu: json('1.0')
            memory: '2Gi'
          }
          env: [
            { name: 'AZURE_OPENAI_ENDPOINT', value: openai.properties.endpoint }
            { name: 'AZURE_OPENAI_API_VERSION', value: '2025-03-01-preview' }
            { name: 'OPENAI_API_KEY', secretRef: 'openai-api-key' }
            { name: 'ANTHROPIC_API_KEY', secretRef: 'anthropic-api-key' }
            { name: 'OPENAI_SEARCH_MODEL', value: searchModel }
            { name: 'OPENAI_MODEL', value: llmModel }
            { name: 'LOG_ANALYTICS_WORKSPACE_ID', value: logAnalytics.properties.customerId }
            { name: 'APP_BEARER_TOKEN', secretRef: 'app-bearer-token' }
          ]
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 3
        rules: [
          {
            name: 'http-scaling'
            http: {
              metadata: {
                concurrentRequests: '10'
              }
            }
          }
        ]
      }
    }
  }
}

// ──────────────────────────────────────────────────────────────────────────────
// Static Web App (Frontend)
// ──────────────────────────────────────────────────────────────────────────────

resource staticWebApp 'Microsoft.Web/staticSites@2023-12-01' = {
  name: baseName
  location: swaLocation
  sku: {
    name: 'Free'
    tier: 'Free'
  }
  properties: {
    stagingEnvironmentPolicy: 'Enabled'
    allowConfigFileUpdates: true
    buildProperties: {
      skipGithubActionWorkflowGeneration: true
    }
  }
}

// ──────────────────────────────────────────────────────────────────────────────
// Outputs
// ──────────────────────────────────────────────────────────────────────────────

output acrLoginServer string = acr.properties.loginServer
output apiUrl string = 'https://${containerApp.properties.configuration.ingress.fqdn}'
output swaUrl string = 'https://${staticWebApp.properties.defaultHostname}'
output openaiEndpoint string = openai.properties.endpoint
output logAnalyticsWorkspaceId string = logAnalytics.properties.customerId
output keyVaultName string = keyVault.name
