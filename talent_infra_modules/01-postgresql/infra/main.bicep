// 01-postgresql/infra/main.bicep
//
// Single-purpose template for talent_infra_modules/01-postgresql/.
// Deploys ONE Azure Database for PostgreSQL Flexible Server with:
//   * AGE / VECTOR / PG_TRGM / PG_DISKANN extensions allow-listed
//   * shared_preload_libraries = age (deploy.ps1 restarts the server after)
//   * Entra ID auth enabled, password auth retained by default
//   * Optional Private Endpoint into an existing VNet + pe-subnet
//
// The first Entra administrator is registered via the AZURE CONTROL PLANE
// from deploy.ps1 — NOT via the Bicep `administrators` child resource.
// Passing empty entraAdminObjectId / entraAdminPrincipalName here skips the
// child resource and avoids the AadAuthOperationCannotBePerformedWhenServer-
// IsNotAccessible re-PUT race documented in
// /memories/repo/talentiq-azd-deploy.md.

targetScope = 'resourceGroup'

@description('Name of the PostgreSQL Flexible Server (3-63 chars, globally unique).')
@minLength(3)
@maxLength(63)
param serverName string

@description('Azure region for the PostgreSQL server.')
param location string = resourceGroup().location

@description('Password-auth admin login name (kept for break-glass even when Entra auth is on).')
param administratorLogin string = 'pgadmin'

@description('Password-auth admin password. Must satisfy Azure PostgreSQL complexity rules.')
@secure()
param administratorLoginPassword string

@description('PostgreSQL major version.')
@allowed([
  '16'
  '15'
  '14'
  '13'
])
param postgresqlVersion string = '16'

@description('SKU name. Must be compatible with skuTier: Burstable=Standard_B* (e.g. Standard_B2ms), GeneralPurpose=Standard_D*ds_v4/v5 (e.g. Standard_D4ds_v5), MemoryOptimized=Standard_E*ds_v4/v5. Default mirrors talent_infra_v2/infra/main.parameters.json.')
param skuName string = 'Standard_D4ds_v5'

@description('SKU tier. Must match skuName family — Burstable for Standard_B*, GeneralPurpose for Standard_D*, MemoryOptimized for Standard_E*. Mismatched pairs produce ServerEditionIncompatibleWithSkuSize at deploy time.')
@allowed([
  'Burstable'
  'GeneralPurpose'
  'MemoryOptimized'
])
param skuTier string = 'GeneralPurpose'

@description('Storage size in GB (32 - 16384).')
@minValue(32)
@maxValue(16384)
param storageSizeGB int = 32

@description('Backup retention in days (7 - 35).')
@minValue(7)
@maxValue(35)
param backupRetentionDays int = 7

@description('Disable PostgreSQL password authentication (Entra-only). Only safe once all clients are registered as Entra principals.')
param disablePasswordAuth bool = false

@description('Deployer public IP to whitelist on the server firewall. Empty = no client firewall rule.')
param clientIpAddress string = ''

@description('Allow all Azure-service IPs through the firewall. Typically false when a Private Endpoint is in use.')
param allowAzureServices bool = false

@description('Provision a Private Endpoint into the supplied VNet/subnet.')
param enablePrivateEndpoint bool = true

@description('Resource group holding the existing VNet (defaults to the current resource group). Used when enablePrivateEndpoint is true.')
param vnetResourceGroup string = resourceGroup().name

@description('Name of the existing VNet. Required when enablePrivateEndpoint is true.')
param vnetName string = ''

@description('Name of the existing subnet inside the VNet where the Private Endpoint NIC lands.')
param peSubnetName string = 'pe-subnet'

@description('Optional resource ID of an existing privatelink.postgres.database.azure.com DNS zone. Empty = create a new zone and link it to the VNet.')
param existingPrivateDnsZoneId string = ''

@description('Whether the existing Private DNS zone (when existingPrivateDnsZoneId is set) is already linked to the target VNet. When true (default), no link is created. When false, the private-endpoint module creates the link in the existing zone\'s RG via a nested module. Ignored when existingPrivateDnsZoneId is empty.')
param existingPrivateDnsZoneLinked bool = true

@description('Tags applied to all resources.')
param tags object = {}

// Existing VNet + PE subnet — only referenced when enablePrivateEndpoint is true.
resource vnet 'Microsoft.Network/virtualNetworks@2023-11-01' existing = if (enablePrivateEndpoint) {
  name: vnetName
  scope: resourceGroup(vnetResourceGroup)
}

resource peSubnet 'Microsoft.Network/virtualNetworks/subnets@2023-11-01' existing = if (enablePrivateEndpoint) {
  parent: vnet
  name: peSubnetName
}

// PostgreSQL Flexible Server (extensions + Entra auth enabled).
// entraAdminObjectId/entraAdminPrincipalName intentionally empty — admin
// registration happens via control plane in deploy.ps1.
module postgresql './modules/postgresql-flexible-server.bicep' = {
  params: {
    serverName: serverName
    location: location
    administratorLogin: administratorLogin
    administratorLoginPassword: administratorLoginPassword
    postgresqlVersion: postgresqlVersion
    skuName: skuName
    skuTier: skuTier
    storageSizeGB: storageSizeGB
    backupRetentionDays: backupRetentionDays
    enableAgeExtension: true
    allowAzureServices: allowAzureServices
    clientIpAddress: clientIpAddress
    enableEntraAuth: true
    disablePasswordAuth: disablePasswordAuth
    entraAdminObjectId: ''
    entraAdminPrincipalName: ''
    tags: tags
  }
}

// Private Endpoint into the supplied VNet (optional).
module postgresqlPrivateEndpoint './modules/private-endpoint.bicep' = if (enablePrivateEndpoint) {
  params: {
    location: location
    privateEndpointName: '${serverName}-pe'
    subnetId: peSubnet!.id
    privateLinkServiceId: postgresql.outputs.id
    groupIds: ['postgresqlServer']
    privateDnsZoneName: 'privatelink.postgres.database.azure.com'
    existingPrivateDnsZoneId: existingPrivateDnsZoneId
    existingPrivateDnsZoneLinked: existingPrivateDnsZoneLinked
    vnetId: vnet!.id
    vnetName: vnetName
    tags: tags
  }
}

output serverName string = postgresql.outputs.name
output serverFqdn string = postgresql.outputs.fqdn
output serverId string = postgresql.outputs.id
output tenantId string = postgresql.outputs.tenantId
output privateFqdn string = '${serverName}.privatelink.postgres.database.azure.com'
output privateEndpointId string = enablePrivateEndpoint ? postgresqlPrivateEndpoint!.outputs.privateEndpointId : ''
output privateDnsZoneId string = enablePrivateEndpoint ? postgresqlPrivateEndpoint!.outputs.privateDnsZoneId : ''
