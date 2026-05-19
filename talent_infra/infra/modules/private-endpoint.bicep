@description('The location for the Private Endpoint')
param location string

@description('The name of the Private Endpoint')
param privateEndpointName string

@description('The resource ID of the subnet for the Private Endpoint')
param subnetId string

@description('The resource ID of the service to connect to')
param privateLinkServiceId string

@description('The group IDs for the Private Link service')
param groupIds array

@description('The name of the Private DNS Zone')
param privateDnsZoneName string

@description('The resource ID of the Virtual Network for DNS zone link')
param vnetId string

@description('The name of the Virtual Network for DNS zone link naming')
param vnetName string

@description('Use an existing Private DNS Zone instead of creating a new one. Provide the resource ID.')
param existingPrivateDnsZoneId string = ''

@description('Tags for the resources')
param tags object = {}

var useExistingDnsZone = !empty(existingPrivateDnsZoneId)

// Private Endpoint
resource privateEndpoint 'Microsoft.Network/privateEndpoints@2023-11-01' = {
  name: privateEndpointName
  location: location
  tags: tags
  properties: {
    subnet: {
      id: subnetId
    }
    privateLinkServiceConnections: [
      {
        name: '${privateEndpointName}-connection'
        properties: {
          privateLinkServiceId: privateLinkServiceId
          groupIds: groupIds
        }
      }
    ]
  }
}

// Private DNS Zone — only create if not using existing
resource privateDnsZone 'Microsoft.Network/privateDnsZones@2020-06-01' = if (!useExistingDnsZone) {
  name: privateDnsZoneName
  location: 'global'
  tags: tags
}

// Link Private DNS Zone to VNet — only if creating new zone
resource privateDnsZoneVnetLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = if (!useExistingDnsZone) {
  parent: privateDnsZone
  name: '${vnetName}-link'
  location: 'global'
  tags: tags
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: vnetId
    }
  }
}

// Private DNS Zone Group
var resolvedDnsZoneId = useExistingDnsZone ? existingPrivateDnsZoneId : privateDnsZone.id
resource privateDnsZoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2023-11-01' = {
  parent: privateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: replace(privateDnsZoneName, '.', '-')
        properties: {
          privateDnsZoneId: resolvedDnsZoneId
        }
      }
    ]
  }
}

output privateEndpointId string = privateEndpoint.id
output privateEndpointName string = privateEndpoint.name
output privateDnsZoneId string = resolvedDnsZoneId
