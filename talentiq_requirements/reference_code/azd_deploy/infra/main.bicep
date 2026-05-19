// Basic agent setup 
@description('The name of the Azure AI Foundry resource.')
@maxLength(9)
param aiServicesName string = 'foundry'

@description('The name of your project')
param projectName string = 'project'

@description('The description of your project')
param projectDescription string = 'some description'

@description('The display name of your project')
param projectDisplayName string = 'project_display_name'

// Create a short, unique suffix that is stable across deployments (based only on resource group)
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
@description('The Azure region where your AI Foundry resource and project will be created.')
param location string = 'eastus'

@description('The name of the OpenAI model you want to deploy')
param modelName string = 'gpt-4.1'

@description('The model format of the model you want to deploy. Example: OpenAI')
param modelFormat string = 'OpenAI'

@description('The version of the model you want to deploy. Example: 2024-11-20')
param modelVersion string = '2025-04-14'

@description('The SKU name for the model deployment. Example: GlobalStandard')
param modelSkuName string = 'GlobalStandard'

@description('The capacity of the model deployment in TPM.')
param modelCapacity int = 40

@description('Tags for all resources')
param tags object = {}

// ACR and VNet Parameters
@description('Deploy ACR with VNet and private endpoint')
param deployAcrVnet bool = true

@description('The prefix for the Virtual Network name')
param vnetNamePrefix string = 'vnet'

@description('The prefix for the Azure Container Registry name')
param acrNamePrefix string = 'acr'

// Generate globally unique names
var vnetName = '${vnetNamePrefix}-${uniqueSuffix}'
var acrName = toLower('${acrNamePrefix}${uniqueSuffix}')

// PostgreSQL Parameters
@description('Deploy PostgreSQL Flexible Server with Apache AGE')
param deployPostgresql bool = true

@description('The prefix for the PostgreSQL server name')
param postgresqlServerNamePrefix string = 'pgsql'

@description('The administrator login for PostgreSQL')
param postgresqlAdminLogin string = 'pgadmin'

@description('The administrator password for PostgreSQL')
@secure()
param postgresqlAdminPassword string

@description('PostgreSQL version')
param postgresqlVersion string = '16'

@description('PostgreSQL SKU name')
param postgresqlSkuName string = 'Standard_B2s'

@description('PostgreSQL SKU tier')
param postgresqlSkuTier string = 'GeneralPurpose'

@description('PostgreSQL storage size in GB')
param postgresqlStorageSizeGB int = 32

@description('Enable private endpoint for PostgreSQL (requires VNet deployment)')
param postgresqlEnablePrivateEndpoint bool = true

@description('Client IP address to allow through PostgreSQL firewall (for deployment scripts)')
param clientIpAddress string = ''

// Redis Parameters
@description('Deploy Azure Cache for Redis for SSE pub/sub')
param deployRedis bool = true

@description('The prefix for the Azure Cache for Redis name')
param redisNamePrefix string = 'redis'

@description('The SKU for Azure Cache for Redis')
@allowed(['Basic', 'Standard', 'Premium'])
param redisSkuName string = 'Basic'

@description('The SKU capacity for Azure Cache for Redis (0=250MB for Basic/Standard)')
param redisSkuCapacity int = 0

// MCP Server Container Build Parameters
@description('Build and push MCP server container to ACR')
param buildMcpServerContainer bool = true

@description('The name of the MCP server container image')
param mcpServerImageName string = 'mcp-server'

@description('The tag for the MCP server container image')
param mcpServerImageTag string = 'latest'

// FastAPI Container Build Parameters
@description('Build and push FastAPI container to ACR')
param buildFastApiContainer bool = true

@description('The name of the FastAPI container image')
param fastApiImageName string = 'af-fastapi'

@description('The tag for the FastAPI container image')
param fastApiImageTag string = 'latest'

// Webapp Container Build Parameters
@description('Build and push webapp container to ACR')
param buildWebappContainer bool = true

@description('The name of the webapp container image')
param webappImageName string = 'webapp'

@description('The tag for the webapp container image')
param webappImageTag string = 'latest'

// Container Apps Parameters
@description('Deploy MCP server to Container Apps')
param deployContainerApp bool = false

@description('Deploy Container Apps environment only (without apps)')
param deployContainerAppsEnv bool = true

@description('Deploy MCP Server Container App')
param deployMcpServerContainerApp bool = false

@description('Deploy FastAPI Container App')
param deployFastApiContainerApp bool = false

@description('Deploy Webapp Container App')
param deployWebappContainerApp bool = false

@description('The prefix for the Container Apps Environment name')
param containerAppsEnvNamePrefix string = 'cae'

@description('The prefix for the Container App name')
param containerAppNamePrefix string = 'mcp-server'

@description('Enable external ingress for the Container App')
param containerAppExternalIngress bool = false

@description('CPU cores for the Container App')
param containerAppCpu string = '0.5'

@description('Memory for the Container App')
param containerAppMemory string = '1Gi'

// MCP Server Environment Variables (from .env)
@description('Azure OpenAI endpoint')
param azureOpenAiEndpoint string = ''

@description('Azure OpenAI API version')
param azureOpenAiApiVersion string = '2025-02-01-preview'

@description('Azure OpenAI Chat deployment name')
param azureOpenAiChatDeploymentName string = ''

@description('Azure Search service endpoint')
param azureSearchServiceEndpoint string = ''

@description('Azure Search index name')
param azureSearchIndex string = ''

@description('Application Insights connection string')
param appInsightsConnectionString string = ''

@description('Graph name for PostgreSQL AGE')
param graphName string = 'customer_graph'

// FastAPI Container App Parameters
@description('The prefix for the FastAPI Container App name')
param fastApiContainerAppNamePrefix string = 'fastapi'

@description('Enable external ingress for FastAPI Container App')
param fastApiExternalIngress bool = false

@description('CPU cores for FastAPI Container App')
param fastApiCpu string = '0.5'

@description('Memory for FastAPI Container App')
param fastApiMemory string = '1Gi'

// Webapp Container App Parameters
@description('The prefix for the Webapp Container App name')
param webappContainerAppNamePrefix string = 'webapp'

@description('Enable external ingress for Webapp Container App')
param webappExternalIngress bool = true

@description('CPU cores for Webapp Container App')
param webappCpu string = '0.25'

@description('Memory for Webapp Container App')
param webappMemory string = '0.5Gi'

// Generate unique names
var postgresqlServerName = toLower('${postgresqlServerNamePrefix}${uniqueSuffix}')
var redisName = toLower('${redisNamePrefix}${uniqueSuffix}')
var containerAppsEnvName = '${containerAppsEnvNamePrefix}-${uniqueSuffix}'
var containerAppName = '${containerAppNamePrefix}-${uniqueSuffix}'
var fastApiContainerAppName = '${fastApiContainerAppNamePrefix}-${uniqueSuffix}'
var webappContainerAppName = '${webappContainerAppNamePrefix}-${uniqueSuffix}'

// AI Services Account Module
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

// AI Project Module
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

// Model Deployment Module
module modelDeployment 'modules/ai-model-deployment.bicep' = {
  name: 'model-deployment'
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

// ACR with VNet and Private Endpoint Module
module acrVnet 'modules/acr-vnet.bicep' = if (deployAcrVnet) {
  name: 'acr-vnet-deployment'
  params: {
    location: location
    vnetName: vnetName
    acrName: acrName
    enableAcrBuildTasks: buildMcpServerContainer
    tags: tags
  }
}

// PostgreSQL Flexible Server with Apache AGE Module
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
    allowAzureServices: !postgresqlEnablePrivateEndpoint // Disable if using private endpoint
    clientIpAddress: clientIpAddress
    tags: tags
  }
}

// Private Endpoint for PostgreSQL (requires VNet to be deployed)
module postgresqlPrivateEndpoint 'modules/private-endpoint.bicep' = if (deployPostgresql && postgresqlEnablePrivateEndpoint && deployAcrVnet) {
  name: 'postgresql-private-endpoint-deployment'
  params: {
    location: location
    privateEndpointName: '${postgresqlServerName}-pe'
    subnetId: acrVnet!.outputs.privateEndpointSubnetId
    privateLinkServiceId: postgresql!.outputs.id
    groupIds: ['postgresqlServer']
    privateDnsZoneName: 'privatelink.postgres.database.azure.com'
    vnetId: acrVnet!.outputs.vnetId
    vnetName: acrVnet!.outputs.vnetName
    tags: tags
  }
}

// Azure Cache for Redis (SSE pub/sub for multi-node sessions)
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

// Reference Redis resource for key retrieval (used in Container App secrets)
resource redisAccount 'Microsoft.Cache/redis@2024-03-01' existing = if (deployRedis) {
  name: redisName
  dependsOn: [redisCache]
}

// Container Apps Environment (VNet integrated, allows external ingress for specific apps)
module containerAppsEnv 'modules/container-apps-environment.bicep' = if ((deployContainerAppsEnv || deployContainerApp || deployMcpServerContainerApp || deployFastApiContainerApp || deployWebappContainerApp) && deployAcrVnet) {
  name: 'container-apps-env-deployment'
  params: {
    location: location
    containerAppsEnvironmentName: containerAppsEnvName
    subnetId: acrVnet!.outputs.containerAppsSubnetId
    internalOnly: false  // Allow external ingress for webapp while keeping other apps internal
    tags: tags
  }
}

// MCP Server Container App
module mcpServerContainerApp 'modules/container-app.bicep' = if ((deployMcpServerContainerApp || deployContainerApp) && deployAcrVnet) {
  name: 'mcp-server-container-app-deployment'
  params: {
    location: location
    containerAppName: containerAppName
    containerAppsEnvironmentId: containerAppsEnv!.outputs.id
    containerImage: '${acrVnet!.outputs.acrLoginServer}/${mcpServerImageName}:${mcpServerImageTag}'
    acrName: acrVnet!.outputs.acrName
    targetPort: 3002
    externalIngress: containerAppExternalIngress
    cpu: containerAppCpu
    memory: containerAppMemory
    minReplicas: 1
    maxReplicas: 3
    environmentVariables: [
      // PostgreSQL configuration (from Bicep deployment)
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
        name: 'PGUSER'
        value: postgresqlAdminLogin
      }
      {
        name: 'PGPASSWORD'
        secretRef: 'pg-password'
      }
      {
        name: 'GRAPH_NAME'
        value: graphName
      }
      // Azure OpenAI configuration
      {
        name: 'AZURE_OPENAI_ENDPOINT'
        value: !empty(azureOpenAiEndpoint) ? azureOpenAiEndpoint : aiServices.outputs.endpoint
      }
      {
        name: 'AZURE_OPENAI_API_VERSION'
        value: azureOpenAiApiVersion
      }
      {
        name: 'AZURE_OPENAI_CHAT_DEPLOYMENT_NAME'
        value: !empty(azureOpenAiChatDeploymentName) ? azureOpenAiChatDeploymentName : modelName
      }
      // Azure Search configuration
      {
        name: 'AZURE_SEARCH_SERVICE_ENDPOINT'
        value: azureSearchServiceEndpoint
      }
      {
        name: 'AZURE_SEARCH_INDEX'
        value: azureSearchIndex
      }
      // Application Insights
      {
        name: 'AZURE_APP_INSIGHTS_CONNECTION_STRING'
        value: appInsightsConnectionString
      }
      // Container App revision info
      {
        name: 'CONTAINER_APP_REVISION'
        value: 'revision'
      }
    ]
    secrets: [
      {
        name: 'pg-password'
        value: postgresqlAdminPassword
      }
    ]
    tags: tags
  }
}

// FastAPI Container App
module fastApiContainerApp 'modules/container-app.bicep' = if ((deployFastApiContainerApp || deployContainerApp) && deployAcrVnet && buildFastApiContainer) {
  name: 'fastapi-container-app-deployment'
  params: {
    location: location
    containerAppName: fastApiContainerAppName
    containerAppsEnvironmentId: containerAppsEnv!.outputs.id
    containerImage: '${acrVnet!.outputs.acrLoginServer}/${fastApiImageName}:${fastApiImageTag}'
    acrName: acrVnet!.outputs.acrName
    targetPort: 8080
    externalIngress: fastApiExternalIngress
    cpu: fastApiCpu
    memory: fastApiMemory
    minReplicas: 1
    maxReplicas: 3
    environmentVariables: [
      // PostgreSQL configuration
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
        name: 'PGUSER'
        value: postgresqlAdminLogin
      }
      {
        name: 'PGPASSWORD'
        secretRef: 'pg-password'
      }
      {
        name: 'GRAPH_NAME'
        value: graphName
      }
      // Azure OpenAI configuration
      {
        name: 'AZURE_OPENAI_ENDPOINT'
        value: !empty(azureOpenAiEndpoint) ? azureOpenAiEndpoint : aiServices.outputs.endpoint
      }
      {
        name: 'ENDPOINT_URL'
        value: !empty(azureOpenAiEndpoint) ? azureOpenAiEndpoint : aiServices.outputs.endpoint
      }
      {
        name: 'AZURE_OPENAI_API_VERSION'
        value: azureOpenAiApiVersion
      }
      {
        name: 'AZURE_OPENAI_CHAT_DEPLOYMENT_NAME'
        value: !empty(azureOpenAiChatDeploymentName) ? azureOpenAiChatDeploymentName : modelName
      }
      {
        name: 'DEPLOYMENT_NAME'
        value: !empty(azureOpenAiChatDeploymentName) ? azureOpenAiChatDeploymentName : modelName
      }
      // MCP Server endpoint (internal) - must include /mcp path
      {
        name: 'MCP_ENDPOINT'
        value: 'https://${containerAppName}.internal.${containerAppsEnv!.outputs.defaultDomain}/mcp'
      }
      // Redis URL for SSE pub/sub (multi-node session support)
      {
        name: 'REDIS_URL'
        secretRef: 'redis-url'
      }
      // Azure Search configuration
      {
        name: 'AZURE_SEARCH_SERVICE_ENDPOINT'
        value: azureSearchServiceEndpoint
      }
      {
        name: 'AZURE_SEARCH_INDEX'
        value: azureSearchIndex
      }
      // Application Insights
      {
        name: 'AZURE_APP_INSIGHTS_CONNECTION_STRING'
        value: appInsightsConnectionString
      }
    ]
    secrets: [
      {
        name: 'pg-password'
        value: postgresqlAdminPassword
      }
      {
        name: 'redis-url'
        value: deployRedis ? 'rediss://:${redisAccount!.listKeys().primaryKey}@${redisCache!.outputs.hostName}:${redisCache!.outputs.sslPort}/0' : ''
      }
    ]
    tags: tags
  }
}

resource aiServicesAccount 'Microsoft.CognitiveServices/accounts@2025-04-01-preview' existing = {
  name: accountName
}

// Grant FastAPI managed identity permission to call Azure OpenAI chat completions.
// Uses the identity principal ID output from the container-app module to ensure
// the identity is created before this role assignment runs.
resource fastApiOpenAiUserRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if ((deployFastApiContainerApp || deployContainerApp) && deployAcrVnet && buildFastApiContainer) {
  name: guid(accountName, fastApiContainerAppName, 'cognitive-services-openai-user')
  scope: aiServicesAccount
  properties: {
    principalId: fastApiContainerApp!.outputs.identityPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd') // Cognitive Services OpenAI User
  }
}

// Webapp Container App
module webappContainerApp 'modules/container-app.bicep' = if ((deployWebappContainerApp || deployContainerApp) && deployAcrVnet && buildWebappContainer && (deployFastApiContainerApp || deployContainerApp)) {
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
        name: 'FASTAPI_BACKEND_URL'
        value: 'https://${fastApiContainerAppName}.internal.${containerAppsEnv!.outputs.defaultDomain}'
      }
      {
        name: 'FASTAPI_BACKEND_HOST'
        value: '${fastApiContainerAppName}.internal.${containerAppsEnv!.outputs.defaultDomain}'
      }
    ]
    secrets: []
    tags: tags
  }
}

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
output postgresqlPrivateEndpointId string = (deployPostgresql && postgresqlEnablePrivateEndpoint && deployAcrVnet) ? postgresqlPrivateEndpoint!.outputs.privateEndpointId : ''
output mcpServerImageName string = mcpServerImageName
output mcpServerImageTag string = mcpServerImageTag
output mcpServerFullImageName string = deployAcrVnet ? '${acrVnet!.outputs.acrLoginServer}/${mcpServerImageName}:${mcpServerImageTag}' : ''
output buildMcpServerContainer string = string(buildMcpServerContainer)
output fastApiImageName string = fastApiImageName
output fastApiImageTag string = fastApiImageTag
output fastApiFullImageName string = deployAcrVnet ? '${acrVnet!.outputs.acrLoginServer}/${fastApiImageName}:${fastApiImageTag}' : ''
output buildFastApiContainer string = string(buildFastApiContainer)
output webappImageName string = webappImageName
output webappImageTag string = webappImageTag
output webappFullImageName string = deployAcrVnet ? '${acrVnet!.outputs.acrLoginServer}/${webappImageName}:${webappImageTag}' : ''
output buildWebappContainer string = string(buildWebappContainer)
output graphName string = graphName
output containerAppsEnvName string = ((deployContainerAppsEnv || deployContainerApp || deployMcpServerContainerApp || deployFastApiContainerApp || deployWebappContainerApp) && deployAcrVnet) ? containerAppsEnv!.outputs.name : ''
output containerAppsEnvDefaultDomain string = ((deployContainerAppsEnv || deployContainerApp || deployMcpServerContainerApp || deployFastApiContainerApp || deployWebappContainerApp) && deployAcrVnet) ? containerAppsEnv!.outputs.defaultDomain : ''
output mcpServerContainerAppName string = ((deployMcpServerContainerApp || deployContainerApp) && deployAcrVnet) ? mcpServerContainerApp!.outputs.name : ''
output mcpServerContainerAppFqdn string = ((deployMcpServerContainerApp || deployContainerApp) && deployAcrVnet) ? mcpServerContainerApp!.outputs.fqdn : ''
output fastApiContainerAppName string = ((deployFastApiContainerApp || deployContainerApp) && deployAcrVnet && buildFastApiContainer) ? fastApiContainerApp!.outputs.name : ''
output fastApiContainerAppFqdn string = ((deployFastApiContainerApp || deployContainerApp) && deployAcrVnet && buildFastApiContainer) ? fastApiContainerApp!.outputs.fqdn : ''
output webappContainerAppName string = ((deployWebappContainerApp || deployContainerApp) && deployAcrVnet && buildWebappContainer && (deployFastApiContainerApp || deployContainerApp)) ? webappContainerApp!.outputs.name : ''
output webappContainerAppFqdn string = ((deployWebappContainerApp || deployContainerApp) && deployAcrVnet && buildWebappContainer && (deployFastApiContainerApp || deployContainerApp)) ? webappContainerApp!.outputs.fqdn : ''
output redisName string = deployRedis ? redisCache!.outputs.name : ''
output redisHostName string = deployRedis ? redisCache!.outputs.hostName : ''
