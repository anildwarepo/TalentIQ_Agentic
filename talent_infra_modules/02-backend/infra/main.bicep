// 02-backend / main.bicep — Backend (FastAPI) Container App + MCP sidecar.
//
// Topology (matches talent_infra_v2/infra/main.bicep with mcpServerSidecar=true):
//   - ONE Container App with TWO containers (backend on :8000 external,
//     mcp-server on :3002 intra-pod).
//   - Both containers share the same UAMI; the module injects AZURE_CLIENT_ID
//     into each so DefaultAzureCredential picks up the SAME identity.
//   - PGUSER on both = `<backendAppName>-identity` (the backend UAMI's name).
//   - AZURE_TENANT_ID is DELIBERATELY NOT SET — this is the auth-disable
//     contract documented in talent_infra_modules/AUTH-DISABLED.md
//     (talent_backend/auth.py short-circuits to dev mode without it).
//
// Role assignments handled here (UAMI principalId comes from the module):
//   - Cognitive Services OpenAI User on the Foundry account.
//   - Cosmos DB Built-in Data Contributor (control-plane Contributor as in v2)
//     on the Cosmos DB account when one is supplied.
//   - AcrPull is created inside the container-app module — not duplicated here.
//
// PG Entra admin registration for the new UAMI is performed in deploy.ps1
// via `az postgres flexible-server microsoft-entra-admin create` AFTER this
// template deploys — that operation needs the UAMI's principalId, which is a
// post-deploy output, and is also a control-plane API not modeled in Bicep.

targetScope = 'resourceGroup'

@description('Azure region for the Container App + UAMI')
param location string = resourceGroup().location

@description('Name of the backend Container App. Drives the UAMI name (`<this>-identity`).')
param backendAppName string

@description('Full backend container image reference (e.g. acrxyz.azurecr.io/backend:<tag>)')
param backendImage string

@description('Full MCP server container image reference (e.g. acrxyz.azurecr.io/mcp-server:<tag>)')
param mcpImage string

@description('Resource ID of the pre-existing Azure Container Apps Managed Environment')
param containerAppsEnvironmentId string

@description('Name of the pre-existing Azure Container Registry (must be in the deployment RG)')
param acrName string

@description('PostgreSQL Flexible Server FQDN (private endpoint FQDN when PE is in use)')
param pgFqdn string

@description('PostgreSQL database name. The backend opens `postgres` by default.')
param pgDatabase string = 'postgres'

@description('AGE graph name the backend / MCP issue queries against')
param graphName string = 'talent_graph'

@description('Azure OpenAI / Foundry endpoint (Cognitive Services route, *.openai.azure.com)')
param foundryEndpoint string

@description('Name of the pre-existing Azure AI Foundry / Cognitive Services account (used for RBAC scope). Must be in the deployment RG.')
param foundryAccountName string

@description('Name of the chat-completion model deployment (e.g. gpt-4.1)')
param chatModelDeployment string = 'gpt-4.1'

@description('Optional Cosmos DB endpoint (https://<acct>.documents.azure.com:443/). Leave empty to disable chat-history persistence.')
param cosmosEndpoint string = ''

@description('Optional Cosmos DB account name (required for the role assignment when cosmosEndpoint is set). Must be in the deployment RG.')
param cosmosAccountName string = ''

@description('Cosmos DB database name for chat history')
param cosmosDatabase string = 'talent_db'

@description('Cosmos DB container name for chat history')
param cosmosContainer string = 'chat_history_db'

@description('Optional Application Insights connection string')
param appInsightsConnectionString string = ''

@description('CPU cores for the backend container')
param backendCpu string = '0.5'

@description('Memory for the backend container')
param backendMemory string = '1Gi'

@description('CPU cores for the MCP sidecar container')
param mcpCpu string = '0.5'

@description('Memory for the MCP sidecar container')
param mcpMemory string = '1Gi'

@description('Backend ingress port (uvicorn)')
param backendTargetPort int = 8000

@description('Enable external (public) ingress for the backend Container App')
param backendExternalIngress bool = true

@description('Minimum number of replicas')
param minReplicas int = 1

@description('Maximum number of replicas')
param maxReplicas int = 3

@description('Tags applied to all created resources')
param tags object = {}

var hasCosmos = !empty(cosmosEndpoint) && !empty(cosmosAccountName)

// Existing infra references (all same-RG)
resource foundryAccount 'Microsoft.CognitiveServices/accounts@2025-04-01-preview' existing = {
  name: foundryAccountName
}

resource cosmosAccount 'Microsoft.DocumentDB/databaseAccounts@2024-05-15' existing = if (hasCosmos) {
  name: cosmosAccountName
}

// Shared env vars for BOTH containers. AZURE_TENANT_ID is intentionally
// omitted — see AUTH-DISABLED.md.
var sharedPgEnv = [
  {
    name: 'PGHOST'
    value: pgFqdn
  }
  {
    name: 'PGPORT'
    value: '5432'
  }
  {
    name: 'PGDATABASE'
    value: pgDatabase
  }
  {
    // Both containers authenticate to PG as the backend UAMI's role.
    // The PG role name is the UAMI's name, which is `<backendAppName>-identity`.
    name: 'PGUSER'
    value: '${backendAppName}-identity'
  }
  {
    name: 'GRAPH_NAME'
    value: graphName
  }
]

var foundryEnv = [
  {
    name: 'AZURE_OPENAI_ENDPOINT'
    value: foundryEndpoint
  }
  {
    name: 'AZURE_OPENAI_CHAT_DEPLOYMENT_NAME'
    value: chatModelDeployment
  }
]

var telemetryEnv = empty(appInsightsConnectionString) ? [] : [
  {
    name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
    value: appInsightsConnectionString
  }
]

// Cosmos env vars are only injected when a Cosmos endpoint is supplied.
// Container Apps rejects empty values on some env keys, so omit (not blank).
var cosmosEnv = hasCosmos ? [
  {
    name: 'COSMOS_CHAT_ENDPOINT'
    value: cosmosEndpoint
  }
  {
    name: 'COSMOS_CHAT_DATABASE'
    value: cosmosDatabase
  }
  {
    name: 'COSMOS_CHAT_CONTAINER'
    value: cosmosContainer
  }
] : []

// Backend-only env vars: MCP endpoint over pod loopback.
var backendOnlyEnv = [
  {
    name: 'MCP_ENDPOINT'
    value: 'http://localhost:3002/mcp'
  }
]

var backendEnv = concat(sharedPgEnv, foundryEnv, cosmosEnv, telemetryEnv, backendOnlyEnv)

// MCP sidecar gets PG + Foundry endpoint + telemetry, but NOT MCP_ENDPOINT
// (it IS the MCP server) and NOT the chat-deployment name (irrelevant).
var mcpEnv = concat(sharedPgEnv, [
  {
    name: 'AZURE_OPENAI_ENDPOINT'
    value: foundryEndpoint
  }
], telemetryEnv)

module backend 'modules/container-app.bicep' = {
  params: {
    location: location
    containerAppName: backendAppName
    containerAppsEnvironmentId: containerAppsEnvironmentId
    containerImage: backendImage
    acrName: acrName
    targetPort: backendTargetPort
    externalIngress: backendExternalIngress
    cpu: backendCpu
    memory: backendMemory
    minReplicas: minReplicas
    maxReplicas: maxReplicas
    environmentVariables: backendEnv
    secrets: []
    // MCP sidecar in the SAME pod, shares the backend UAMI via the module's
    // automatic AZURE_CLIENT_ID injection.
    sidecarContainer: {
      name: 'mcp-server'
      image: mcpImage
      cpu: mcpCpu
      memory: mcpMemory
      env: mcpEnv
    }
    tags: tags
  }
}

// Grant the backend UAMI Cognitive Services OpenAI User on the Foundry account.
// Role definition: 5e0bd9bd-7b93-4f28-af87-19fc36ad61bd
// `name` uses param values (calculable at deployment start) to avoid BCP120.
resource foundryOpenAiUserRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(foundryAccount.id, backendAppName, 'cognitive-services-openai-user')
  scope: foundryAccount
  properties: {
    principalId: backend.outputs.identityPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd')
  }
}

// Optional Cosmos DB role — preserves the v2 main.bicep choice of the
// control-plane Contributor role rather than a data-plane SQL role.
// Role definition: b24988ac-6180-42a0-ab88-20f7382dd24c (Contributor)
resource cosmosContributorRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (hasCosmos) {
  name: guid(cosmosAccount.id, backendAppName, 'cosmos-db-data-contributor')
  scope: cosmosAccount
  properties: {
    principalId: backend.outputs.identityPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'b24988ac-6180-42a0-ab88-20f7382dd24c')
  }
}

output backendContainerAppName string = backend.outputs.name
output backendContainerAppFqdn string = backend.outputs.fqdn
output backendContainerAppId string = backend.outputs.id
output backendUamiName string = backend.outputs.identityName
output backendUamiClientId string = backend.outputs.identityClientId
output backendUamiPrincipalId string = backend.outputs.identityPrincipalId
output backendLatestRevisionName string = backend.outputs.latestRevisionName
