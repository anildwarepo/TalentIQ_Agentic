// 03-frontend — talent_ui (React/Vite + nginx) Container App.
//
// Deploys a single Azure Container App that serves the static SPA on port
// 80 with external HTTPS ingress, plus the user-assigned managed identity
// it needs to pull from ACR. The UAMI is intentionally minimal-scope:
// AcrPull only (assigned inside modules/container-app.bicep). No
// PostgreSQL, Cosmos, Foundry, or Key Vault roles — the frontend never
// talks directly to those data planes; it only talks to the backend
// Container App via its public FQDN (the browser fetches; nginx in the
// pod proxies /api/* and /af/*).
//
// The auth-disable contract (VITE_DISABLE_AUTH=true) is enforced at the
// container image layer (build args supplied by ../deploy.ps1) and via
// the absence of any MSAL env vars on the Container App itself. See
// ../../AUTH-DISABLED.md.
//
// The module file at modules/container-app.bicep is copied verbatim from
// talent_infra_v2/infra/modules/container-app.bicep. We do NOT pass a
// sidecarContainer here — single-container mode only.

targetScope = 'resourceGroup'

@description('Azure region for the Container App.')
param location string = resourceGroup().location

@description('Full resource ID of the existing Azure Container Apps managed environment.')
param containerAppsEnvironmentId string

@description('Name of the existing Azure Container Registry. The ACR is assumed to be in the same resource group as this deployment (the copied container-app.bicep module references it via an existing-resource lookup in the deployment scope). If your ACR is in a different RG, see deploy.ps1 for the validation that catches this case.')
param acrName string

@description('Name of the Container App to create (e.g. tiq-webapp-abcde). Must be unique within the Container Apps environment.')
@minLength(2)
@maxLength(32)
param webappAppName string

@description('Fully-qualified container image reference, e.g. acrxyz.azurecr.io/webapp:abc1234. Build and push happens in deploy.ps1 before this template is deployed.')
param webappImage string

@description('Public FQDN of the backend Container App (no scheme, no trailing slash). Used to set the BACKEND_URL env var that nginx reads at container start to proxy /api/* and /af/* to the backend.')
param backendFqdn string

@description('Optional Application Insights connection string. Set to empty to skip — the frontend has no telemetry SDK currently, so this is a forward-compatible no-op.')
param appInsightsConnectionString string = ''

@description('Container listen port. nginx in this image listens on 80; do not change unless the Dockerfile changes.')
param targetPort int = 80

@description('Expose external HTTPS ingress. Must be true for the user-facing frontend.')
param externalIngress bool = true

@description('vCPU cores (string, e.g. \'0.25\').')
param cpu string = '0.25'

@description('Memory (e.g. \'0.5Gi\').')
param memory string = '0.5Gi'

@description('Minimum replicas.')
@minValue(0)
param minReplicas int = 1

@description('Maximum replicas.')
@minValue(1)
param maxReplicas int = 3

@description('Tags applied to the Container App and its UAMI.')
param tags object = {}

// Environment variables injected into the Container App.
//
// BACKEND_URL is consumed by talent_ui/docker-entrypoint.sh (envsubst-renders
// nginx.conf at container start) to point nginx's /api/ and /af/ proxy
// locations at the backend. The frontend's browser-side code does NOT read
// BACKEND_URL — its backend target is baked at Vite build time via
// VITE_API_BASE (passed as a Docker build-arg in deploy.ps1).
//
// AZURE_CLIENT_ID is auto-injected by the module from the UAMI's clientId.
// No AZURE_TENANT_ID is set — the frontend does no Entra ID work in
// auth-disabled mode.
var envVars = concat(
  [
    {
      name: 'BACKEND_URL'
      value: 'https://${backendFqdn}'
    }
  ],
  empty(appInsightsConnectionString) ? [] : [
    {
      name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
      value: appInsightsConnectionString
    }
  ]
)

module webapp 'modules/container-app.bicep' = {
  params: {
    location: location
    containerAppName: webappAppName
    containerAppsEnvironmentId: containerAppsEnvironmentId
    containerImage: webappImage
    acrName: acrName
    targetPort: targetPort
    externalIngress: externalIngress
    cpu: cpu
    memory: memory
    minReplicas: minReplicas
    maxReplicas: maxReplicas
    environmentVariables: envVars
    secrets: []
    tags: tags
  }
}

output webappContainerAppId string = webapp.outputs.id
output webappContainerAppName string = webapp.outputs.name
output webappContainerAppFqdn string = webapp.outputs.fqdn
output webappUamiId string = webapp.outputs.identityId
output webappUamiPrincipalId string = webapp.outputs.identityPrincipalId
output webappLatestRevisionName string = webapp.outputs.latestRevisionName
