{
  "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
  "contentVersion": "1.0.0.0",
  "parameters": {
    "baseName": {
      "value": "researcher"
    },
    "location": {
      "value": "eastus2"
    },
    "environment": {
      "value": "prod"
    },
    "containerImageTag": {
      "value": "v39"
    },
    "appPassword": {
      "value": "CHANGE-ME-TO-A-STRONG-PASSWORD"
    },
    "anthropicApiKey": {
      "value": "sk-ant-api03-..."
    },
    "tavilyApiKey": {
      "value": "tvly-..."
    },
    "openaiApiKey": {
      "value": "sk-proj-..."
    },
    "enableOpenAiSearch": {
      "value": false
    },
    "cpuCores": {
      "value": "0.5"
    },
    "memory": {
      "value": "1.0Gi"
    },
    "minReplicas": {
      "value": 1
    },
    "maxReplicas": {
      "value": 3
    }
  }
}
