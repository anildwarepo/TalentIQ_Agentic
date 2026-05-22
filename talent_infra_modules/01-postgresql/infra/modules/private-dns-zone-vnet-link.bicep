// 01-postgresql/infra/modules/private-dns-zone-vnet-link.bicep
//
// Attaches a virtualNetworkLink to an EXISTING Private DNS zone. Used by
// private-endpoint.bicep when the deploy script discovered a pre-existing
// zone of the right name that is not yet linked to the target VNet.
//
// Designed to be deployed via `module ... = { scope: resourceGroup(<zoneRg>) }`
// so the link is created in the zone's resource group (often a shared
// network RG distinct from the per-component deployment RG).
//
// Idempotent: re-running with the same -vnetName/-vnetId is a no-op once
// the link exists.

targetScope = 'resourceGroup'

@description('Name of the EXISTING Private DNS zone to attach the link to. Must already exist in the RG this module is deployed into.')
param privateDnsZoneName string

@description('Full ARM resource ID of the VNet to link.')
param vnetId string

@description('Short VNet name used to compose the link resource name (must be unique within the zone).')
param vnetName string

@description('Tags for the link resource.')
param tags object = {}

resource existingZone 'Microsoft.Network/privateDnsZones@2020-06-01' existing = {
  name: privateDnsZoneName
}

resource vnetLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = {
  parent: existingZone
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

output linkId string = vnetLink.id
output linkName string = vnetLink.name
