using 'main.bicep'

// ──────────────────────────────────────────────────────────────────────────────
// KAIA Researcher — Bicep Parameters
// NOTE: Sensitive values use getSecret() from Key Vault or must be provided
//       at deploy time via --parameters openaiApiKey=<value>
// ──────────────────────────────────────────────────────────────────────────────

param baseName = 'kaia-researcher'
param location = 'eastus'
param swaLocation = 'eastus2'
param imageTag = 'v17'
param searchModel = 'gpt-4-1-nano'
param llmModel = 'gpt-4o-mini'

// These must be provided at deploy time:
// az deployment group create ... --parameters openaiApiKey=<KEY> anthropicApiKey=<KEY>
param openaiApiKey = ''
param anthropicApiKey = ''
