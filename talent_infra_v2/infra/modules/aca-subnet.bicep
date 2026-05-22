// Creates a Container Apps subnet in an existing VNet
// Deployed to the VNet's resource group via cross-RG scope

@description('The name of the existing Virtual Network')
param vnetName string

@description('The name of the subnet to create')
param subnetName string

@description('The address prefix for the subnet')
param addressPrefix string

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' existing = {
  name: vnetName
}

resource subnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' = {
  parent: vnet
  name: subnetName
  properties: {
    addressPrefix: addressPrefix
    delegations: [
      {
        name: 'Microsoft.App.environments'
        properties: {
          serviceName: 'Microsoft.App/environments'
        }
      }
    ]
  }
}

output subnetId string = subnet.id
output subnetName string = subnet.name
