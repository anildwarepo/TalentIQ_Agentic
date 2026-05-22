@description('The location for all resources')
param location string

@description('The resource group of the existing Virtual Network')
param vnetResourceGroup string

@description('The name of the existing Virtual Network')
param vnetName string

@description('The name of the existing default subnet')
param defaultSubnetName string = 'default'

@description('The name of the existing private endpoint subnet')
param privateEndpointSubnetName string = 'pe-subnet'

@description('The name of the Container Apps subnet (created if it does not exist)')
param containerAppsSubnetName string = 'talentiq-aca'

@description('The address prefix for the Container Apps subnet')
param containerAppsSubnetAddressPrefix string = '10.0.6.0/23'

@description('The name of the Azure Container Registry')
param acrName string

@description('Enable ACR build tasks (requires public network access)')
param enableAcrBuildTasks bool = true

@description('Resource ID of an existing privatelink.azurecr.io DNS zone. When set, the ACR private endpoint is registered against this zone instead of creating a new one and linking it to the VNet. Required when the target VNet is already linked to a privatelink.azurecr.io zone elsewhere (Azure forbids linking one VNet to two zones with the same namespace).')
param existingAcrDnsZoneId string = ''

@description('Tags for all resources')
param tags object = {}

// Reference existing VNet (cross-resource-group)
resource existingVnet 'Microsoft.Network/virtualNetworks@2024-05-01' existing = {
  name: vnetName
  scope: resourceGroup(vnetResourceGroup)
}

// Reference existing default subnet
resource defaultSubnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' existing = {
  name: defaultSubnetName
  parent: existingVnet
}

// Reference existing private endpoint subnet
resource peSubnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' existing = {
  name: privateEndpointSubnetName
  parent: existingVnet
}

// Create Container Apps subnet in the existing VNet (cross-RG deployment)
module acaSubnet 'aca-subnet.bicep' = {
  name: 'aca-subnet-deployment'
  scope: resourceGroup(vnetResourceGroup)
  params: {
    vnetName: vnetName
    subnetName: containerAppsSubnetName
    addressPrefix: containerAppsSubnetAddressPrefix
  }
}

// Azure Container Registry Module
module acr 'acr.bicep' = {
  name: 'acr-deployment'
  params: {
    location: location
    acrName: acrName
    adminUserEnabled: false
    publicNetworkAccess: enableAcrBuildTasks ? 'Enabled' : 'Disabled'
    networkRuleBypassOptions: 'AzureServices'
    zoneRedundancy: 'Disabled'
    tags: tags
  }
}

// Private Endpoint Module for ACR
module acrPrivateEndpoint 'private-endpoint.bicep' = {
  name: 'acr-private-endpoint-deployment'
  params: {
    location: location
    privateEndpointName: '${acrName}-pe'
    subnetId: peSubnet.id
    privateLinkServiceId: acr.outputs.id
    groupIds: ['registry']
    privateDnsZoneName: 'privatelink.azurecr.io'
    existingPrivateDnsZoneId: existingAcrDnsZoneId
    vnetId: existingVnet.id
    vnetName: existingVnet.name
    tags: tags
  }
}

// Outputs
output vnetId string = existingVnet.id
output vnetName string = existingVnet.name
output defaultSubnetId string = defaultSubnet.id
output privateEndpointSubnetId string = peSubnet.id
output containerAppsSubnetId string = acaSubnet.outputs.subnetId
output acrId string = acr.outputs.id
output acrName string = acr.outputs.name
output acrLoginServer string = acr.outputs.loginServer
output privateEndpointId string = acrPrivateEndpoint.outputs.privateEndpointId
