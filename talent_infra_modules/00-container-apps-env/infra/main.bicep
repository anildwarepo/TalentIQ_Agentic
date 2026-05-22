// 00-container-apps-env/infra/main.bicep
//
// Single-purpose template for talent_infra_modules/00-container-apps-env/.
// Deploys ONE Azure Container Apps Environment with:
//   * Consumption workload profile
//   * Optional internal-only ingress (vnetConfiguration.internal)
//   * A Log Analytics workspace for app logs (auto-named
//     "${containerAppsEnvironmentName}-logs" unless overridden).
//
// The infrastructure subnet is supplied as a fully-qualified `subnetId`
// parameter — deploy.ps1 resolves it from one of:
//   * Pre-existing subnet inside the supplied VNet (verified delegated
//     to Microsoft.App/environments).
//   * Newly-created subnet, provisioned by deploy.ps1 via a sidecar
//     deployment of ./modules/aca-subnet.bicep into the VNet's RG.
//
// Splitting the subnet decision out of this template keeps the
// "existing or create" branch in PowerShell (where the validation,
// CIDR check, and soft-lock detection already live) and avoids
// Bicep BCP032 around ternary references to conditionally-deployed
// modules vs. conditional `existing` resources.
//
// ACA enforces a 1:1 mapping between a Managed Environment and its
// infrastructure subnet (ManagedEnvironmentSubnetInUse). When an env
// is deleted, Azure holds a soft-lock on the subnet for ~30 minutes
// before another env can claim it. deploy.ps1 pre-validates this on
// the control plane so Bicep does not race.

targetScope = 'resourceGroup'

@description('Azure region for the Container Apps Environment.')
param location string = resourceGroup().location

@description('Name of the Container Apps Environment (2-32 chars, globally unique within the region).')
@minLength(2)
@maxLength(32)
param containerAppsEnvironmentName string

@description('Fully-qualified resource ID of the infrastructure subnet. Resolved by deploy.ps1 from either an existing subnet or a freshly-created one.')
param subnetId string

@description('When true, the Container Apps Environment exposes ingress only on the VNet (no public endpoint). Default is false to mirror the v2 baseline.')
param internalOnly bool = false

@description('Optional name for the Log Analytics workspace. Empty = derived as <containerAppsEnvironmentName>-logs.')
param logAnalyticsWorkspaceName string = ''

@description('Tags applied to all resources.')
param tags object = {}

module env 'modules/container-apps-environment.bicep' = {
  params: {
    location: location
    containerAppsEnvironmentName: containerAppsEnvironmentName
    subnetId: subnetId
    internalOnly: internalOnly
    logAnalyticsWorkspaceName: logAnalyticsWorkspaceName
    tags: tags
  }
}

output containerAppsEnvName string = env.outputs.name
output containerAppsEnvId string = env.outputs.id
output containerAppsEnvDefaultDomain string = env.outputs.defaultDomain
output containerAppsEnvStaticIp string = env.outputs.staticIp
output acaSubnetId string = subnetId
output logAnalyticsWorkspaceId string = env.outputs.logAnalyticsWorkspaceId
