// ============================================================================
// KAIA Researcher — Full Infrastructure (self-contained)
// Deploys: Azure OpenAI + Key Vault + ACR + Container App + Log Analytics
// Target RG: Kantar (MCAPS-Hybrid subscription)
// ============================================================================

@description('Base name for all resources')
param baseName string = 'kaia-researcher'

@description('Azure region')
param location string = resourceGroup().location

@description('App password for the application')
@secure()
param appPassword string

@description('Container image tag to deploy')
param containerImageTag string = 'v1'

@description('Azure OpenAI model to deploy')
param openAiModelName string = 'gpt-4o'

@description('Azure OpenAI model version')
param openAiModelVersion string = '2024-08-06'

@description('Azure OpenAI deployment SKU capacity (1000s of tokens per minute)')
param openAiCapacity int = 30

@description('Container App CPU cores')
param cpuCores string = '1.0'

@description('Container App memory')
param memory string = '2.0Gi'

@description('Min replicas for Container App')
param minReplicas int = 1

@description('Max replicas for Container App')
param maxReplicas int = 3

// Resource naming
var suffix = substring(uniqueString(resourceGroup().id), 0, 6)
var acrName = '${replace(baseName, '-', '')}${suffix}'
var kvName = '${baseName}-kv${suffix}'
var openAiName = '${baseName}-openai'
var logAnalyticsName = '${baseName}-law'
var containerAppEnvName = '${baseName}-env'
var containerAppName = '${baseName}-api'

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

resource kvSecretOpenAi 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'openai-api-key'
  properties: {
    value: openAi.listKeys().key1
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
          name: 'openai-api-key'
          value: openAi.listKeys().key1
        }
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
            {
              name: 'OPENAI_API_KEY'
              secretRef: 'openai-api-key'
            }
            {
              name: 'AZURE_OPENAI_ENDPOINT'
              value: openAi.properties.endpoint
            }
            {
              name: 'AZURE_OPENAI_API_VERSION'
              value: '2024-10-21'
            }
            {
              name: 'OPENAI_MODEL'
              value: openAiModelName
            }
            {
              name: 'RESEARCHER_APP_PASSWORD'
              secretRef: 'app-password'
            }
            {
              name: 'DEFAULT_LLM_PROVIDER'
              value: 'openai'
            }
            {
              name: 'ENABLE_OPENAI_SEARCH'
              value: 'true'
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

// ─── Outputs ────────────────────────────────────────────────────────────────

output acrLoginServer string = acr.properties.loginServer
output acrName string = acr.name
output keyVaultName string = keyVault.name
output containerAppUrl string = containerApp.properties.configuration.ingress.fqdn
output openAiEndpoint string = openAi.properties.endpoint
output openAiDeployment string = openAiDeployment.name
output logAnalyticsWorkspaceId string = logAnalytics.properties.customerId
