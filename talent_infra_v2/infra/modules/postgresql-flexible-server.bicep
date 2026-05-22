@description('The name of the PostgreSQL Flexible Server')
param serverName string

@description('Location for all resources')
param location string

@description('The administrator login username for the PostgreSQL server')
param administratorLogin string

@description('The administrator login password for the PostgreSQL server')
@secure()
param administratorLoginPassword string

@description('PostgreSQL version')
@allowed([
  '16'
  '15'
  '14'
  '13'
])
param postgresqlVersion string = '16'

@description('The SKU name for the PostgreSQL Flexible Server')
param skuName string = 'Standard_B2s'

@description('The tier of the SKU')
@allowed([
  'Burstable'
  'GeneralPurpose'
  'MemoryOptimized'
])
param skuTier string = 'GeneralPurpose'

@description('Storage size in GB')
@minValue(32)
@maxValue(16384)
param storageSizeGB int = 32

@description('Backup retention days')
@minValue(7)
@maxValue(35)
param backupRetentionDays int = 7

@description('Enable geo-redundant backup')
param geoRedundantBackup bool = false

@description('Enable high availability')
param highAvailabilityEnabled bool = false

@description('Enable Apache AGE extension for graph database')
param enableAgeExtension bool = true

@description('Allow Azure services to access the server')
param allowAzureServices bool = true

@description('Client IP address to allow through firewall (for deployment scripts)')
param clientIpAddress string = ''

@description('Enable Microsoft Entra ID (Azure AD) authentication for the server')
param enableEntraAuth bool = true

@description('Disable PostgreSQL password authentication (force Entra-only). Only safe once all clients/identities have been provisioned as Entra principals.')
param disablePasswordAuth bool = false

@description('Object ID of the first Entra ID administrator (typically the deploying user or a security group). When empty, no administrator child resource is created — the postprovision hook is expected to add one.')
param entraAdminObjectId string = ''

@description('Principal name (UPN for User, displayName for Group/ServicePrincipal) of the first Entra ID administrator')
param entraAdminPrincipalName string = ''

@description('Principal type of the first Entra ID administrator')
@allowed([
  'User'
  'Group'
  'ServicePrincipal'
])
param entraAdminPrincipalType string = 'User'

@description('Tenant ID for Entra ID authentication. Defaults to the subscription tenant.')
param entraTenantId string = subscription().tenantId

@description('Tags for the resources')
param tags object = {}

// PostgreSQL Flexible Server
resource postgresqlServer 'Microsoft.DBforPostgreSQL/flexibleServers@2023-12-01-preview' = {
  name: serverName
  location: location
  tags: tags
  sku: {
    name: skuName
    tier: skuTier
  }
  properties: {
    version: postgresqlVersion
    administratorLogin: administratorLogin
    administratorLoginPassword: administratorLoginPassword
    storage: {
      storageSizeGB: storageSizeGB
    }
    backup: {
      backupRetentionDays: backupRetentionDays
      geoRedundantBackup: geoRedundantBackup ? 'Enabled' : 'Disabled'
    }
    highAvailability: {
      mode: highAvailabilityEnabled ? 'ZoneRedundant' : 'Disabled'
    }
    authConfig: {
      activeDirectoryAuth: enableEntraAuth ? 'Enabled' : 'Disabled'
      passwordAuth: disablePasswordAuth ? 'Disabled' : 'Enabled'
      tenantId: enableEntraAuth ? entraTenantId : null
    }
  }
}

// First Entra ID administrator (idempotent — replays as no-op).
// The deploying user (or a designated group) is added here so the
// postprovision hook can connect with an Entra token and then provision
// additional principals (container app managed identities, app users, etc.).
//
// dependsOn the config resources because PG flex server allows only ONE
// data-plane operation at a time; if the admin PUT fires while azureExtensions
// or sharedPreloadLibraries is still applying, it fails with
// 'AadAuthOperationCannotBePerformedWhenServerIsNotAccessible'.
resource entraAdministrator 'Microsoft.DBforPostgreSQL/flexibleServers/administrators@2023-12-01-preview' = if (enableEntraAuth && !empty(entraAdminObjectId)) {
  parent: postgresqlServer
  name: entraAdminObjectId
  properties: {
    principalType: entraAdminPrincipalType
    principalName: empty(entraAdminPrincipalName) ? entraAdminObjectId : entraAdminPrincipalName
    tenantId: entraTenantId
  }
  dependsOn: [
    sharedPreloadLibraries
    azureExtensions
  ]
}

// Server Parameter: azure.extensions - Enable AGE, vector, pg_trgm, pg_diskann extensions.
// NOTE: pg_diskann does NOT require shared_preload_libraries (per
// https://learn.microsoft.com/en-us/azure/postgresql/extensions/how-to-use-pgdiskann).
// It only needs to be allow-listed here and then created with CREATE EXTENSION ... CASCADE.
resource azureExtensions 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2023-12-01-preview' = if (enableAgeExtension) {
  parent: postgresqlServer
  name: 'azure.extensions'
  properties: {
    value: 'AGE,VECTOR,PG_TRGM,PG_DISKANN'
    source: 'user-override'
  }
}

// Server Parameter: shared_preload_libraries - Preload AGE library only.
// pgvector, pg_trgm, and pg_diskann do not need to be preloaded.
resource sharedPreloadLibraries 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2023-12-01-preview' = if (enableAgeExtension) {
  parent: postgresqlServer
  name: 'shared_preload_libraries'
  properties: {
    value: 'age'
    source: 'user-override'
  }
  dependsOn: [
    azureExtensions
  ]
}

// Firewall rule to allow Azure services
resource allowAzureServicesRule 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2023-12-01-preview' = if (allowAzureServices) {
  parent: postgresqlServer
  name: 'AllowAllAzureServicesAndResourcesWithinAzureIps'
  properties: {
    startIpAddress: '0.0.0.0'
    endIpAddress: '0.0.0.0'
  }
  dependsOn: [
    sharedPreloadLibraries
  ]
}

// Firewall rule to allow client IP (for deployment scripts)
resource allowClientIpRule 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2023-12-01-preview' = if (!empty(clientIpAddress)) {
  parent: postgresqlServer
  name: 'AllowClientIp'
  properties: {
    startIpAddress: clientIpAddress
    endIpAddress: clientIpAddress
  }
  dependsOn: [
    allowAzureServicesRule
    sharedPreloadLibraries
  ]
}

// Outputs
output id string = postgresqlServer.id
output name string = postgresqlServer.name
output fqdn string = postgresqlServer.properties.fullyQualifiedDomainName
output entraAuthEnabled bool = enableEntraAuth
output tenantId string = entraTenantId
