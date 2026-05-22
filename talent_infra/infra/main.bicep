// ============================================================================
// TalentIQ — Main Bicep Template
// Pattern: Two-phase deployment (infra first, containers via postprovision hook)
// ============================================================================

// ── AI Services Parameters ──────────────────────────────────
@description('The name of the Azure AI Foundry resource.')
@maxLength(9)
param aiServicesName string = 'tiqai'

@description('The name of your project')
param projectName string = 'talentiq'

@description('The description of your project')
param projectDescription string = 'TalentIQ Agentic HR Platform'

@description('The display name of your project')
param projectDisplayName string = 'TalentIQ'

// Create a short, unique suffix that is stable across deployments
var uniqueSuffix = substring(uniqueString(resourceGroup().id), 0, 4)
var accountName = toLower('${aiServicesName}${uniqueSuffix}')

@allowed([
  'australiaeast'
  'canadaeast'
  'eastus'
  'eastus2'
  'francecentral'
  'japaneast'
  'koreacentral'
  'norwayeast'
  'polandcentral'
  'southindia'
  'swedencentral'
  'switzerlandnorth'
  'uaenorth'
  'uksouth'
  'westus'
  'westus2'
  'westus3'
  'westeurope'
  'southeastasia'
  'brazilsouth'
  'germanywestcentral'
  'italynorth'
  'southafricanorth'
  'southcentralus'
])
@description('The Azure region for all resources.')
param location string = 'eastus'

@description('The name of the OpenAI model to deploy')
param modelName string = 'gpt-4.1'

@description('The model format')
param modelFormat string = 'OpenAI'

@description('The model version')
param modelVersion string = '2025-04-14'

@description('The SKU name for the model deployment')
param modelSkuName string = 'GlobalStandard'

@description('The capacity of the model deployment in TPM')
param modelCapacity int = 40

@description('The name of the embedding model to deploy')
param embeddingModelName string = 'text-embedding-ada-002'

@description('The embedding model version')
param embeddingModelVersion string = '2'

@description('The SKU name for the embedding model deployment')
param embeddingModelSkuName string = 'Standard'

@description('The capacity of the embedding model deployment in TPM (thousands)')
param embeddingModelCapacity int = 20

@description('Tags for all resources')
param tags object = {}

// ── ACR and VNet Parameters ─────────────────────────────────
@description('Deploy ACR with VNet and private endpoint')
param deployAcrVnet bool = true

@description('The resource group of the existing Virtual Network')
param vnetResourceGroup string

@description('The name of the existing Virtual Network')
param vnetName string

@description('The name of the existing default subnet')
param defaultSubnetName string = 'default'

@description('The name of the existing private endpoint subnet')
param peSubnetName string = 'pe-subnet'

@description('The name of the Container Apps subnet (created if missing)')
param acaSubnetName string = 'talentiq-aca'

@description('The address prefix for the Container Apps subnet')
param acaSubnetAddressPrefix string = '10.0.6.0/23'

@description('The prefix for the Azure Container Registry name')
param acrNamePrefix string = 'acr'

// Generate globally unique names
var acrName = toLower('${acrNamePrefix}${uniqueSuffix}')

// ── PostgreSQL Parameters ───────────────────────────────────
@description('Deploy PostgreSQL Flexible Server with Apache AGE')
param deployPostgresql bool = true

@description('The prefix for the PostgreSQL server name')
param postgresqlServerNamePrefix string = 'pgsql'

@description('The administrator login for PostgreSQL')
param postgresqlAdminLogin string = 'pgadmin'

@description('The administrator password for PostgreSQL')
@secure()
param postgresqlAdminPassword string

@description('Disable PostgreSQL password authentication entirely (force Entra-only). Only flip to true once all clients are registered as Entra principals.')
param postgresqlDisablePasswordAuth bool = false

@description('Object ID of the deploying user or admin group to register as the initial Entra ID administrator on the PostgreSQL server. Empty = postprovision hook will set it.')
param postgresqlEntraAdminObjectId string = ''

@description('Principal name (UPN for User, displayName otherwise) of the initial Entra ID administrator')
param postgresqlEntraAdminPrincipalName string = ''

@description('Principal type of the initial Entra ID administrator')
@allowed([
  'User'
  'Group'
  'ServicePrincipal'
])
param postgresqlEntraAdminPrincipalType string = 'User'

@description('PostgreSQL version')
param postgresqlVersion string = '16'

@description('PostgreSQL SKU name')
param postgresqlSkuName string = 'Standard_B2s'

@description('PostgreSQL SKU tier')
param postgresqlSkuTier string = 'GeneralPurpose'

@description('PostgreSQL storage size in GB')
param postgresqlStorageSizeGB int = 32

@description('Enable private endpoint for PostgreSQL')
param postgresqlEnablePrivateEndpoint bool = true

@description('Resource ID of an existing Private DNS Zone for PostgreSQL. If empty, a new zone is created.')
param postgresqlExistingDnsZoneId string = ''

@description('Client IP address to allow through PostgreSQL firewall')
param clientIpAddress string = ''

// ── Redis Parameters ────────────────────────────────────────
@description('Deploy Azure Cache for Redis for SSE pub/sub')
param deployRedis bool = true

@description('The prefix for the Redis name')
param redisNamePrefix string = 'redis'

@description('The SKU for Redis')
@allowed(['Basic', 'Standard', 'Premium'])
param redisSkuName string = 'Basic'

@description('The SKU capacity for Redis')
param redisSkuCapacity int = 0

// ── Cosmos DB Parameters ────────────────────────────────────
@description('Deploy Cosmos DB for chat history')
param deployCosmos bool = true

@description('The prefix for the Cosmos DB account name')
param cosmosAccountNamePrefix string = 'cosmos'

@description('Cosmos DB database name')
param cosmosDatabaseName string = 'talent_db'

@description('Cosmos DB container name')
param cosmosContainerName string = 'chat_history_db'

// ── Key Vault Parameters ────────────────────────────────────
@description('Deploy Key Vault')
param deployKeyVault bool = true

@description('The prefix for the Key Vault name')
param keyVaultNamePrefix string = 'kv'

// ── MCP Server Container Build Parameters ───────────────────
@description('Build and push MCP server container to ACR')
param buildMcpServerContainer bool = true

@description('The name of the MCP server container image')
param mcpServerImageName string = 'mcp-server'

@description('The tag for the MCP server container image')
param mcpServerImageTag string = 'latest'

// ── Backend Container Build Parameters ──────────────────────
@description('Build and push backend container to ACR')
param buildBackendContainer bool = true

@description('The name of the backend container image')
param backendImageName string = 'backend'

@description('The tag for the backend container image')
param backendImageTag string = 'latest'

// ── Webapp Container Build Parameters ───────────────────────
@description('Build and push webapp container to ACR')
param buildWebappContainer bool = true

@description('The name of the webapp container image')
param webappImageName string = 'webapp'

@description('The tag for the webapp container image')
param webappImageTag string = 'latest'

// ── Container Apps Parameters ───────────────────────────────
@description('Deploy Container Apps environment only (without apps)')
param deployContainerAppsEnv bool = true

@description('Deploy MCP Server Container App')
param deployMcpServerContainerApp bool = false

@description('Run MCP as a sidecar inside the backend Container App instead of as its own Container App. When true (default), the backend Container App is created with the MCP container co-located and MCP_ENDPOINT is set to http://localhost:3002/mcp. The standalone mcpServerContainerApp module and its OpenAI role are skipped. This eliminates the MCP→backend restart cascade, internal FQDN resolution, and the separate UAMI/PG-role for MCP. Set to false to keep the legacy two-app topology.')
param mcpServerSidecar bool = true

@description('Deploy Backend Container App')
param deployBackendContainerApp bool = false

@description('Deploy Webapp Container App')
param deployWebappContainerApp bool = false

@description('The prefix for the Container Apps Environment name')
param containerAppsEnvNamePrefix string = 'cae'

@description('The prefix for the MCP Server Container App name')
param mcpServerContainerAppNamePrefix string = 'mcp-server'

@description('Enable external ingress for MCP Server')
param mcpServerExternalIngress bool = false

@description('CPU cores for MCP Server')
param mcpServerCpu string = '0.5'

@description('Memory for MCP Server')
param mcpServerMemory string = '1Gi'

@description('The prefix for the Backend Container App name')
param backendContainerAppNamePrefix string = 'backend'

@description('Enable external ingress for Backend')
param backendExternalIngress bool = true

@description('CPU cores for Backend')
param backendCpu string = '0.5'

@description('Memory for Backend')
param backendMemory string = '1Gi'

@description('The prefix for the Webapp Container App name')
param webappContainerAppNamePrefix string = 'webapp'

@description('Enable external ingress for Webapp')
param webappExternalIngress bool = true

@description('CPU cores for Webapp')
param webappCpu string = '0.25'

@description('Memory for Webapp')
param webappMemory string = '0.5Gi'

// ── App Environment Variables (overrides) ───────────────────
@description('Azure OpenAI endpoint (overrides AI Services output)')
param azureOpenAiEndpoint string = ''

@description('Azure OpenAI Chat deployment name')
param azureOpenAiChatDeploymentName string = ''

@description('Application Insights connection string')
param appInsightsConnectionString string = ''

@description('Graph name prefix for PostgreSQL AGE. The actual graph name is `{prefix}_{uniqueSuffix}` to allow multiple deployments in the same database.')
param graphNamePrefix string = 'talent_graph'

// ── Generate unique names ───────────────────────────────────
var postgresqlServerName = toLower('${postgresqlServerNamePrefix}${uniqueSuffix}')
var redisName = toLower('${redisNamePrefix}${uniqueSuffix}')
var cosmosAccountName = toLower('${cosmosAccountNamePrefix}${uniqueSuffix}')
var keyVaultName = toLower('${keyVaultNamePrefix}-tiq-${uniqueSuffix}')
var containerAppsEnvName = '${containerAppsEnvNamePrefix}-${uniqueSuffix}'
var mcpServerContainerAppName = '${mcpServerContainerAppNamePrefix}-${uniqueSuffix}'
var backendContainerAppName = '${backendContainerAppNamePrefix}-${uniqueSuffix}'
var webappContainerAppName = '${webappContainerAppNamePrefix}-${uniqueSuffix}'
var graphName = toLower('${graphNamePrefix}_${uniqueSuffix}')

// ============================================================================
// MODULE DEPLOYMENTS
// ============================================================================

// ── AI Services ─────────────────────────────────────────────
module aiServices 'modules/ai-services.bicep' = {
  name: 'ai-services-deployment'
  params: {
    accountName: accountName
    location: location
    skuName: 'S0'
    publicNetworkAccess: 'Enabled'
    disableLocalAuth: true
    tags: tags
  }
}

module aiProject 'modules/ai-project.bicep' = {
  name: 'ai-project-deployment'
  params: {
    accountName: aiServices.outputs.name
    projectName: projectName
    location: location
    projectDescription: projectDescription
    projectDisplayName: projectDisplayName
    tags: tags
  }
}

// Chat model deployment. dependsOn aiProject because both modules modify the
// same Cognitive Services account in parallel — ARM uses optimistic concurrency
// (ETag/If-Match) on the parent account and rejects the racing write with
// 'IfMatchPreconditionFailed'. Serializing project → chat → embedding avoids it.
module modelDeployment 'modules/ai-model-deployment.bicep' = {
  name: 'model-deployment'
  dependsOn: [ aiProject ]
  params: {
    accountName: aiServices.outputs.name
    deploymentName: modelName
    modelName: modelName
    modelFormat: modelFormat
    modelVersion: modelVersion
    skuName: modelSkuName
    capacity: modelCapacity
  }
}

// Embedding model deployment — required for vector_search (MCP server) and the
// data pipeline's embedding generator. dependsOn the chat deployment because
// Azure OpenAI accounts reject concurrent deployment ops on the same parent.
module embeddingModelDeployment 'modules/ai-model-deployment.bicep' = {
  name: 'embedding-model-deployment'
  dependsOn: [ modelDeployment ]
  params: {
    accountName: aiServices.outputs.name
    deploymentName: embeddingModelName
    modelName: embeddingModelName
    modelFormat: modelFormat
    modelVersion: embeddingModelVersion
    skuName: embeddingModelSkuName
    capacity: embeddingModelCapacity
  }
}

// ── ACR with existing VNet ──────────────────────────────────
module acrVnet 'modules/acr-vnet.bicep' = if (deployAcrVnet) {
  name: 'acr-vnet-deployment'
  params: {
    location: location
    vnetResourceGroup: vnetResourceGroup
    vnetName: vnetName
    defaultSubnetName: defaultSubnetName
    privateEndpointSubnetName: peSubnetName
    containerAppsSubnetName: acaSubnetName
    containerAppsSubnetAddressPrefix: acaSubnetAddressPrefix
    acrName: acrName
    enableAcrBuildTasks: buildMcpServerContainer
    tags: tags
  }
}

// ── PostgreSQL ──────────────────────────────────────────────
module postgresql 'modules/postgresql-flexible-server.bicep' = if (deployPostgresql) {
  name: 'postgresql-deployment'
  params: {
    serverName: postgresqlServerName
    location: location
    administratorLogin: postgresqlAdminLogin
    administratorLoginPassword: postgresqlAdminPassword
    postgresqlVersion: postgresqlVersion
    skuName: postgresqlSkuName
    skuTier: postgresqlSkuTier
    storageSizeGB: postgresqlStorageSizeGB
    enableAgeExtension: true
    allowAzureServices: !postgresqlEnablePrivateEndpoint
    clientIpAddress: clientIpAddress
    enableEntraAuth: true
    disablePasswordAuth: postgresqlDisablePasswordAuth
    entraAdminObjectId: postgresqlEntraAdminObjectId
    entraAdminPrincipalName: postgresqlEntraAdminPrincipalName
    entraAdminPrincipalType: postgresqlEntraAdminPrincipalType
    tags: tags
  }
}

// Private Endpoint for PostgreSQL
module postgresqlPrivateEndpoint 'modules/private-endpoint.bicep' = if (deployPostgresql && postgresqlEnablePrivateEndpoint && deployAcrVnet) {
  name: 'postgresql-private-endpoint-deployment'
  params: {
    location: location
    privateEndpointName: '${postgresqlServerName}-pe'
    subnetId: acrVnet!.outputs.privateEndpointSubnetId
    privateLinkServiceId: postgresql!.outputs.id
    groupIds: ['postgresqlServer']
    privateDnsZoneName: 'privatelink.postgres.database.azure.com'
    existingPrivateDnsZoneId: postgresqlExistingDnsZoneId
    vnetId: acrVnet!.outputs.vnetId
    vnetName: acrVnet!.outputs.vnetName
    tags: tags
  }
}

// ── Redis ───────────────────────────────────────────────────
module redisCache 'modules/redis-cache.bicep' = if (deployRedis) {
  name: 'redis-cache-deployment'
  params: {
    redisName: redisName
    location: location
    skuName: redisSkuName
    skuFamily: redisSkuName == 'Premium' ? 'P' : 'C'
    skuCapacity: redisSkuCapacity
    tags: tags
  }
}

// Reference Redis resource for key retrieval
resource redisAccount 'Microsoft.Cache/redis@2024-03-01' existing = if (deployRedis) {
  name: redisName
  dependsOn: [redisCache]
}

// ── Cosmos DB ───────────────────────────────────────────────
module cosmosDb 'modules/cosmos-db.bicep' = if (deployCosmos) {
  name: 'cosmos-db-deployment'
  params: {
    accountName: cosmosAccountName
    location: location
    databaseName: cosmosDatabaseName
    containerName: cosmosContainerName
    tags: tags
  }
}

// ── Key Vault ───────────────────────────────────────────────
module keyVault 'modules/key-vault.bicep' = if (deployKeyVault) {
  name: 'key-vault-deployment'
  params: {
    keyVaultName: keyVaultName
    location: location
    tags: tags
  }
}

// ── Container Apps Environment ──────────────────────────────
module containerAppsEnv 'modules/container-apps-environment.bicep' = if ((deployContainerAppsEnv || deployMcpServerContainerApp || deployBackendContainerApp || deployWebappContainerApp) && deployAcrVnet) {
  name: 'container-apps-env-deployment'
  params: {
    location: location
    containerAppsEnvironmentName: containerAppsEnvName
    subnetId: acrVnet!.outputs.containerAppsSubnetId
    internalOnly: false
    tags: tags
  }
}

// ── MCP Server Container App ────────────────────────────────
// ── MCP Server Container App (legacy standalone topology) ──────────
// Only deployed when mcpServerSidecar = false. Default (sidecar=true) skips
// this entirely and runs MCP inside the backend Container App.
module mcpServerContainerApp 'modules/container-app.bicep' = if (deployMcpServerContainerApp && !mcpServerSidecar && deployAcrVnet) {
  name: 'mcp-server-container-app-deployment'
  params: {
    location: location
    containerAppName: mcpServerContainerAppName
    containerAppsEnvironmentId: containerAppsEnv!.outputs.id
    containerImage: '${acrVnet!.outputs.acrLoginServer}/${mcpServerImageName}:${mcpServerImageTag}'
    acrName: acrVnet!.outputs.acrName
    targetPort: 3002
    externalIngress: mcpServerExternalIngress
    cpu: mcpServerCpu
    memory: mcpServerMemory
    minReplicas: 1
    maxReplicas: 3
    environmentVariables: [
      {
        name: 'PGHOST'
        value: deployPostgresql ? (postgresqlEnablePrivateEndpoint ? '${postgresqlServerName}.privatelink.postgres.database.azure.com' : postgresql!.outputs.fqdn) : ''
      }
      {
        name: 'PGPORT'
        value: '5432'
      }
      {
        name: 'PGDATABASE'
        value: 'postgres'
      }
      {
        // Entra ID auth: this username must match the PG role registered for
        // the container app's user-assigned managed identity (UAMI display name
        // is `<containerAppName>-identity`, set in container-app.bicep). The
        // postprovision hook creates that role via
        // `pgaadauth_create_principal_with_oid`. The OSSRDBMS bearer token is
        // acquired at runtime by `DefaultAzureCredential` (picks up the UAMI
        // via the AZURE_CLIENT_ID env var that container-app.bicep injects).
        name: 'PGUSER'
        value: '${mcpServerContainerAppName}-identity'
      }
      {
        name: 'GRAPH_NAME'
        value: graphName
      }
      {
        name: 'AZURE_OPENAI_ENDPOINT'
        value: !empty(azureOpenAiEndpoint) ? azureOpenAiEndpoint : aiServices.outputs.endpoint
      }
      {
        name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
        value: appInsightsConnectionString
      }
    ]
    secrets: []
    tags: tags
  }
}

// ── Backend (FastAPI) Container App ─────────────────────────
module backendContainerApp 'modules/container-app.bicep' = if (deployBackendContainerApp && deployAcrVnet && buildBackendContainer) {
  name: 'backend-container-app-deployment'
  params: {
    location: location
    containerAppName: backendContainerAppName
    containerAppsEnvironmentId: containerAppsEnv!.outputs.id
    containerImage: '${acrVnet!.outputs.acrLoginServer}/${backendImageName}:${backendImageTag}'
    acrName: acrVnet!.outputs.acrName
    targetPort: 8000
    externalIngress: backendExternalIngress
    cpu: backendCpu
    memory: backendMemory
    minReplicas: 1
    maxReplicas: 3
    environmentVariables: [
      // PostgreSQL
      {
        name: 'PGHOST'
        value: deployPostgresql ? (postgresqlEnablePrivateEndpoint ? '${postgresqlServerName}.privatelink.postgres.database.azure.com' : postgresql!.outputs.fqdn) : ''
      }
      {
        name: 'PGPORT'
        value: '5432'
      }
      {
        name: 'PGDATABASE'
        value: 'postgres'
      }
      {
        // Entra ID auth: PGUSER must match the PG role registered for the
        // backend container app's UAMI (`<containerAppName>-identity`).
        // See the MCP server section above for the full rationale.
        name: 'PGUSER'
        value: '${backendContainerAppName}-identity'
      }
      {
        name: 'GRAPH_NAME'
        value: graphName
      }
      // Azure OpenAI
      {
        name: 'AZURE_OPENAI_ENDPOINT'
        value: !empty(azureOpenAiEndpoint) ? azureOpenAiEndpoint : aiServices.outputs.endpoint
      }
      {
        name: 'AZURE_OPENAI_CHAT_DEPLOYMENT_NAME'
        value: !empty(azureOpenAiChatDeploymentName) ? azureOpenAiChatDeploymentName : modelName
      }
      // Cosmos DB (chat history)
      {
        name: 'COSMOS_CHAT_ENDPOINT'
        value: deployCosmos ? cosmosDb!.outputs.endpoint : ''
      }
      {
        name: 'COSMOS_CHAT_DATABASE'
        value: cosmosDatabaseName
      }
      {
        name: 'COSMOS_CHAT_CONTAINER'
        value: cosmosContainerName
      }
      // MCP Server endpoint (internal). When sidecar mode is on, MCP runs
      // in the same pod as backend, reachable via localhost. Otherwise we
      // resolve the standalone MCP Container App's internal FQDN.
      {
        name: 'MCP_ENDPOINT'
        value: mcpServerSidecar ? 'http://localhost:3002/mcp' : 'https://${mcpServerContainerAppName}.internal.${containerAppsEnv!.outputs.defaultDomain}/mcp'
      }
      // Application Insights
      {
        name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
        value: appInsightsConnectionString
      }
      // Redis for SSE pub/sub — only injected when Redis is actually deployed.
      // Container Apps rejects empty secretRefs, so we must omit (not blank) the entry.
      ...(deployRedis ? [{
        name: 'REDIS_URL'
        secretRef: 'redis-url'
      }] : [])
    ]
    secrets: deployRedis ? [
      {
        name: 'redis-url'
        value: 'rediss://:${redisAccount!.listKeys().primaryKey}@${redisCache!.outputs.hostName}:${redisCache!.outputs.sslPort}/0'
      }
    ] : []
    // ── MCP Sidecar ───────────────────────────────────
    // When mcpServerSidecar=true, the MCP server runs as a second container
    // inside this Container App. Backend reaches it via http://localhost:3002.
    // Both containers share the backend UAMI (AZURE_CLIENT_ID is injected by
    // the container-app module), so MCP uses the SAME PG role as backend
    // (`<backendContainerAppName>-identity`). This eliminates the separate
    // MCP UAMI, MCP PG role, MCP→backend restart cascade, and internal FQDN
    // resolution that the legacy two-app topology required.
    sidecarContainer: mcpServerSidecar ? {
      name: 'mcp-server'
      image: '${acrVnet!.outputs.acrLoginServer}/${mcpServerImageName}:${mcpServerImageTag}'
      cpu: mcpServerCpu
      memory: mcpServerMemory
      env: [
        {
          name: 'PGHOST'
          value: deployPostgresql ? (postgresqlEnablePrivateEndpoint ? '${postgresqlServerName}.privatelink.postgres.database.azure.com' : postgresql!.outputs.fqdn) : ''
        }
        {
          name: 'PGPORT'
          value: '5432'
        }
        {
          name: 'PGDATABASE'
          value: 'postgres'
        }
        {
          // Shared PG role with backend — both containers authenticate as
          // `<backendContainerAppName>-identity` using the backend UAMI.
          name: 'PGUSER'
          value: '${backendContainerAppName}-identity'
        }
        {
          name: 'GRAPH_NAME'
          value: graphName
        }
        {
          name: 'AZURE_OPENAI_ENDPOINT'
          value: !empty(azureOpenAiEndpoint) ? azureOpenAiEndpoint : aiServices.outputs.endpoint
        }
        {
          name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
          value: appInsightsConnectionString
        }
      ]
    } : {}
    tags: tags
  }
}

// Reference AI Services account for RBAC
resource aiServicesAccount 'Microsoft.CognitiveServices/accounts@2025-04-01-preview' existing = {
  name: accountName
}

// Grant Backend managed identity Cognitive Services OpenAI User role
resource backendOpenAiUserRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (deployBackendContainerApp && deployAcrVnet && buildBackendContainer) {
  name: guid(accountName, backendContainerAppName, 'cognitive-services-openai-user')
  scope: aiServicesAccount
  properties: {
    principalId: backendContainerApp!.outputs.identityPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd')
  }
}

// Reference Cosmos DB account for RBAC
resource cosmosDbAccount 'Microsoft.DocumentDB/databaseAccounts@2024-05-15' existing = if (deployCosmos) {
  name: cosmosAccountName
  dependsOn: [cosmosDb]
}

// Grant Backend managed identity Cosmos DB Built-in Data Contributor role (for chat history)
resource cosmosDataRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (deployBackendContainerApp && deployCosmos && deployAcrVnet && buildBackendContainer) {
  name: guid(cosmosAccountName, backendContainerAppName, 'cosmos-db-data-contributor')
  scope: cosmosDbAccount
  properties: {
    principalId: backendContainerApp!.outputs.identityPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'b24988ac-6180-42a0-ab88-20f7382dd24c') // Contributor
  }
}

// Grant MCP Server managed identity Cognitive Services OpenAI User role.
// Skipped when MCP is a sidecar (the backend UAMI already has this role and
// the sidecar uses the same UAMI client ID via AZURE_CLIENT_ID injection).
resource mcpServerOpenAiUserRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (deployMcpServerContainerApp && !mcpServerSidecar && deployAcrVnet) {
  name: guid(accountName, mcpServerContainerAppName, 'cognitive-services-openai-user')
  scope: aiServicesAccount
  properties: {
    principalId: mcpServerContainerApp!.outputs.identityPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd')
  }
}

// ── Webapp Container App ────────────────────────────────────
module webappContainerApp 'modules/container-app.bicep' = if (deployWebappContainerApp && deployAcrVnet && buildWebappContainer && deployBackendContainerApp) {
  name: 'webapp-container-app-deployment'
  params: {
    location: location
    containerAppName: webappContainerAppName
    containerAppsEnvironmentId: containerAppsEnv!.outputs.id
    containerImage: '${acrVnet!.outputs.acrLoginServer}/${webappImageName}:${webappImageTag}'
    acrName: acrVnet!.outputs.acrName
    targetPort: 80
    externalIngress: webappExternalIngress
    cpu: webappCpu
    memory: webappMemory
    minReplicas: 1
    maxReplicas: 3
    environmentVariables: [
      {
        name: 'BACKEND_URL'
        value: 'https://${backendContainerAppName}.internal.${containerAppsEnv!.outputs.defaultDomain}'
      }
      {
        name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
        value: appInsightsConnectionString
      }
    ]
    secrets: []
    tags: tags
  }
}

// ============================================================================
// OUTPUTS — mapped to azd env vars via azure.yaml
// ============================================================================

output accountName string = aiServices.outputs.name
output projectName string = aiProject.outputs.name
output accountEndpoint string = aiServices.outputs.endpoint
output vnetId string = deployAcrVnet ? acrVnet!.outputs.vnetId : ''
output vnetName string = deployAcrVnet ? acrVnet!.outputs.vnetName : ''
output acrName string = deployAcrVnet ? acrVnet!.outputs.acrName : ''
output acrLoginServer string = deployAcrVnet ? acrVnet!.outputs.acrLoginServer : ''
output postgresqlServerName string = deployPostgresql ? postgresql!.outputs.name : ''
output postgresqlServerFqdn string = deployPostgresql ? postgresql!.outputs.fqdn : ''
output postgresqlAdminLogin string = postgresqlAdminLogin
output graphName string = graphName
output cosmosEndpoint string = deployCosmos ? cosmosDb!.outputs.endpoint : ''
output cosmosDatabaseName string = cosmosDatabaseName
output cosmosContainerName string = cosmosContainerName
output keyVaultName string = deployKeyVault ? keyVault!.outputs.name : ''
output appInsightsConnectionString string = appInsightsConnectionString
output mcpServerImageName string = mcpServerImageName
output mcpServerImageTag string = mcpServerImageTag
output mcpServerFullImageName string = deployAcrVnet ? '${acrVnet!.outputs.acrLoginServer}/${mcpServerImageName}:${mcpServerImageTag}' : ''
output buildMcpServerContainer string = string(buildMcpServerContainer)
output backendImageName string = backendImageName
output backendImageTag string = backendImageTag
output backendFullImageName string = deployAcrVnet ? '${acrVnet!.outputs.acrLoginServer}/${backendImageName}:${backendImageTag}' : ''
output buildBackendContainer string = string(buildBackendContainer)
output webappImageName string = webappImageName
output webappImageTag string = webappImageTag
output webappFullImageName string = deployAcrVnet ? '${acrVnet!.outputs.acrLoginServer}/${webappImageName}:${webappImageTag}' : ''
output buildWebappContainer string = string(buildWebappContainer)
output containerAppsEnvName string = ((deployContainerAppsEnv || deployMcpServerContainerApp || deployBackendContainerApp || deployWebappContainerApp) && deployAcrVnet) ? containerAppsEnv!.outputs.name : ''
output containerAppsEnvDefaultDomain string = ((deployContainerAppsEnv || deployMcpServerContainerApp || deployBackendContainerApp || deployWebappContainerApp) && deployAcrVnet) ? containerAppsEnv!.outputs.defaultDomain : ''
output mcpServerContainerAppName string = (deployMcpServerContainerApp && !mcpServerSidecar && deployAcrVnet) ? mcpServerContainerApp!.outputs.name : ''
output mcpServerContainerAppFqdn string = (deployMcpServerContainerApp && !mcpServerSidecar && deployAcrVnet) ? mcpServerContainerApp!.outputs.fqdn : ''
output mcpServerSidecar string = string(mcpServerSidecar)
output backendContainerAppName string = (deployBackendContainerApp && deployAcrVnet && buildBackendContainer) ? backendContainerApp!.outputs.name : ''
output backendContainerAppFqdn string = (deployBackendContainerApp && deployAcrVnet && buildBackendContainer) ? backendContainerApp!.outputs.fqdn : ''
output webappContainerAppName string = (deployWebappContainerApp && deployAcrVnet && buildWebappContainer && deployBackendContainerApp) ? webappContainerApp!.outputs.name : ''
output webappContainerAppFqdn string = (deployWebappContainerApp && deployAcrVnet && buildWebappContainer && deployBackendContainerApp) ? webappContainerApp!.outputs.fqdn : ''
output redisName string = deployRedis ? redisCache!.outputs.name : ''
output redisHostName string = deployRedis ? redisCache!.outputs.hostName : ''
