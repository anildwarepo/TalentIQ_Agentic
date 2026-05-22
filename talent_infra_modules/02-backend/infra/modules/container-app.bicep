// Container App + UAMI module — copied from talent_infra_v2/infra/modules/container-app.bicep
// on 2026-05-21 with two output additions for talent_infra_modules use:
//   1. `identityClientId` so the parent template (and downstream scripts) can
//      read the UAMI's clientId without a second `existing` ref.
//   2. `identityName` so the deploy.ps1 PG registration step knows the exact
//      UAMI name to pass as --display-name.
// Everything else is intentionally unchanged so the sidecar wiring stays
// identical to the v2 topology that has been proven against multiple envs.
//
// ACR must be in the SAME resource group as the Container App deployment
// because the inline AcrPull role assignment cannot target a cross-RG
// resource without a tunneling sub-module. The deploy.ps1 enforces this.

@description('The location for the Container App')
param location string

@description('The name of the Container App')
param containerAppName string

@description('The resource ID of the Container Apps Environment')
param containerAppsEnvironmentId string

@description('The container image to deploy')
param containerImage string

@description('The name of the Azure Container Registry (must be in the deployment RG)')
param acrName string

@description('The target port for the container')
param targetPort int = 3002

@description('Enable external ingress')
param externalIngress bool = false

@description('CPU cores for the container')
param cpu string = '0.5'

@description('Memory for the container')
param memory string = '1Gi'

@description('Minimum replicas')
param minReplicas int = 1

@description('Maximum replicas')
param maxReplicas int = 3

@description('Environment variables for the container')
param environmentVariables array = []

@description('Secrets for the container (array of {name, value} objects)')
param secrets array = []

@description('Optional sidecar container to run inside the same Container App pod alongside the main container. When non-empty, it MUST include: name (string), image (string), cpu (string, e.g. \'0.25\'), memory (string, e.g. \'0.5Gi\'), and env (array of {name,value|secretRef} objects). The main container\'s UAMI client ID is auto-injected as AZURE_CLIENT_ID so the sidecar can use DefaultAzureCredential against the SAME identity. Sidecars share the pod\'s network namespace, so the main container reaches them via http://localhost:<sidecar-port>. Default {} = no sidecar.')
param sidecarContainer object = {}

@description('Allow insecure (HTTP) ingress traffic without redirect to HTTPS')
param allowInsecure bool = false

@description('Tags for the resources')
param tags object = {}

// Reference existing ACR (same RG as the Container App deployment)
resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: acrName
}

// User-assigned managed identity for ACR pull (+ PG / Foundry / Cosmos)
resource acrPullIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${containerAppName}-identity'
  location: location
  tags: tags
}

// Role assignment for ACR pull - created BEFORE container app to avoid the
// well-known startup race (`failed to pull image: unauthorized`) that hits
// when the Container App spins up before AcrPull propagates.
resource acrPullRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, acrPullIdentity.id, 'acrpull')
  scope: acr
  properties: {
    principalId: acrPullIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d') // AcrPull
  }
}

// Single optional sidecar pattern. Bicep BCP182 forbids referencing
// `acrPullIdentity.properties.clientId` inside a for-body, so instead of a
// dynamic-length sidecar array we accept ONE optional sidecar object. The
// MCP server is currently the only sidecar use-case; expand to a fixed
// number of named sidecar params if more are needed later.
var hasSidecar = !empty(sidecarContainer)

resource containerApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: containerAppName
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${acrPullIdentity.id}': {}
    }
  }
  dependsOn: [
    acrPullRole
  ]
  properties: {
    managedEnvironmentId: containerAppsEnvironmentId
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: externalIngress
        targetPort: targetPort
        transport: 'auto'
        allowInsecure: allowInsecure
      }
      registries: [
        {
          server: acr.properties.loginServer
          identity: acrPullIdentity.id
        }
      ]
      secrets: secrets
    }
    template: {
      containers: hasSidecar ? [
        {
          name: containerAppName
          image: containerImage
          resources: {
            cpu: json(cpu)
            memory: memory
          }
          env: concat([
            {
              name: 'AZURE_CLIENT_ID'
              value: acrPullIdentity.properties.clientId
            }
          ], environmentVariables)
        }
        {
          name: sidecarContainer.name
          image: sidecarContainer.image
          resources: {
            cpu: json(sidecarContainer.cpu)
            memory: sidecarContainer.memory
          }
          env: concat([
            {
              name: 'AZURE_CLIENT_ID'
              value: acrPullIdentity.properties.clientId
            }
          ], contains(sidecarContainer, 'env') ? sidecarContainer.env : [])
        }
      ] : [
        {
          name: containerAppName
          image: containerImage
          resources: {
            cpu: json(cpu)
            memory: memory
          }
          env: concat([
            {
              name: 'AZURE_CLIENT_ID'
              value: acrPullIdentity.properties.clientId
            }
          ], environmentVariables)
        }
      ]
      scale: {
        minReplicas: minReplicas
        maxReplicas: maxReplicas
      }
    }
  }
}

output id string = containerApp.id
output name string = containerApp.name
output fqdn string = containerApp.properties.configuration.ingress.fqdn
output identityId string = acrPullIdentity.id
output identityName string = acrPullIdentity.name
output identityPrincipalId string = acrPullIdentity.properties.principalId
output identityClientId string = acrPullIdentity.properties.clientId
output latestRevisionName string = containerApp.properties.latestRevisionName
