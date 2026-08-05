// ---------------------------------------------------------------------------
// TTB COLA Search - Azure Container Apps infrastructure (resource-group scope)
//
// Creates: Log Analytics, Container Apps managed environment, a user-assigned
// managed identity, and the Container App. The image is pulled from an existing
// shared ACR using admin credentials; the app authenticates to Postgres (Entra
// token) and Blob Storage using the user-assigned identity - no DB passwords.
//
// Deploy:  az deployment group create -g <rg> -f infra/main.bicep -p @infra/main.parameters.json
// ---------------------------------------------------------------------------

targetScope = 'resourceGroup'

@description('Location for all resources.')
param location string = resourceGroup().location

@description('Short prefix for generated resource names (lowercase letters, numbers, hyphens; no underscores).')
@minLength(3)
@maxLength(17)
param namePrefix string = 'ttb-pcr'

@description('Container image to run. On first infra deploy leave the placeholder; the deploy workflow updates it to the ACR-built image.')
param containerImage string = 'mcr.microsoft.com/k8se/quickstart:latest'

@description('Container ingress/target port (the port uvicorn listens on).')
param targetPort int = 8000

// --- Existing container registry (shared; admin auth) ----------------------
@description('Login server of the existing ACR, e.g. myregistry.azurecr.io')
param acrLoginServer string
@description('Admin username for the existing ACR.')
param acrUsername string
@description('Admin password for the existing ACR. Stored as a Container App secret.')
@secure()
param acrPassword string

// --- Postgres (Entra token auth; no password) ------------------------------
param postgresHost string
param postgresPort int = 5432
param postgresDb string
param postgresSchema string = 'pcr-prod'
@description('Entra principal used to log in to Postgres. Use the managed identity name so the app connects as the identity created here.')
param postgresUser string
@description('Postgres SSL mode.')
param postgresSslmode string = 'verify-full'

// --- Blob storage (private label images) -----------------------------------
param blobAccountUrl string
param blobContainer string

// --- Embedding provider ----------------------------------------------------
param embeddingProvider string = 'gemini'
param embeddingModel string = 'gemini-embedding-2'
param embeddingDim int = 768

@description('API key for the embedding provider. Stored as a Container App secret. Pass an empty string if not used yet.')
@secure()
param geminiApiKey string = ''

// --- App behaviour ---------------------------------------------------------
@description('Comma-separated CORS origins. Same-origin SPA needs none; "*" is fine while iterating.')
param corsOrigins string = '*'

param minReplicas int = 1
param maxReplicas int = 3
param containerCpu string = '0.5'
param containerMemory string = '1.0Gi'

// ---------------------------------------------------------------------------
// Names
// ---------------------------------------------------------------------------
var logName = '${namePrefix}-logs'
var envName = '${namePrefix}-env'
var identityName = '${namePrefix}-app-id'
var appName = '${namePrefix}-app'

// ---------------------------------------------------------------------------
// Observability
// ---------------------------------------------------------------------------
resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: logName
  location: location
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
  }
}

// ---------------------------------------------------------------------------
// User-assigned managed identity (app runtime: Postgres + Blob auth)
// ---------------------------------------------------------------------------
resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: identityName
  location: location
}

// ---------------------------------------------------------------------------
// Container Apps managed environment
// ---------------------------------------------------------------------------
resource env 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: envName
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logs.properties.customerId
        sharedKey: logs.listKeys().primarySharedKey
      }
    }
  }
}

// ---------------------------------------------------------------------------
// Container App
// ---------------------------------------------------------------------------
resource app 'Microsoft.App/containerApps@2024-03-01' = {
  name: appName
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${identity.id}': {}
    }
  }
  properties: {
    managedEnvironmentId: env.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: targetPort
        transport: 'auto'
        allowInsecure: false
      }
      registries: [
        {
          server: acrLoginServer
          username: acrUsername
          passwordSecretRef: 'acr-password'
        }
      ]
      secrets: concat(
        [
          {
            name: 'acr-password'
            value: acrPassword
          }
        ],
        empty(geminiApiKey) ? [] : [
          {
            name: 'gemini-api-key'
            value: geminiApiKey
          }
        ]
      )
    }
    template: {
      containers: [
        {
          name: 'api'
          image: containerImage
          resources: {
            cpu: json(containerCpu)
            memory: containerMemory
          }
          env: concat(
            [
              { name: 'PORT', value: string(targetPort) }
              { name: 'SPA_DIR', value: '/app/frontend/dist' }
              { name: 'AZURE_CLIENT_ID', value: identity.properties.clientId }
              { name: 'POSTGRES_HOST', value: postgresHost }
              { name: 'POSTGRES_PORT', value: string(postgresPort) }
              { name: 'POSTGRES_DB', value: postgresDb }
              { name: 'POSTGRES_SCHEMA', value: postgresSchema }
              { name: 'POSTGRES_AUTH_METHOD', value: 'entra' }
              { name: 'POSTGRES_USER', value: postgresUser }
              { name: 'POSTGRES_SSLMODE', value: postgresSslmode }
              { name: 'BLOB_ACCOUNT_URL', value: blobAccountUrl }
              { name: 'BLOB_CONTAINER', value: blobContainer }
              { name: 'EMBEDDING_PROVIDER', value: embeddingProvider }
              { name: 'EMBEDDING_MODEL', value: embeddingModel }
              { name: 'EMBEDDING_DIM', value: string(embeddingDim) }
              { name: 'CORS_ORIGINS', value: corsOrigins }
            ],
            empty(geminiApiKey) ? [] : [
              { name: 'GEMINI_API_KEY', secretRef: 'gemini-api-key' }
            ]
          )
          probes: [
            {
              type: 'Readiness'
              httpGet: {
                path: '/api/health'
                port: targetPort
              }
              initialDelaySeconds: 10
              periodSeconds: 30
            }
          ]
        }
      ]
      scale: {
        minReplicas: minReplicas
        maxReplicas: maxReplicas
      }
    }
  }
}

// ---------------------------------------------------------------------------
// Outputs (consumed by the deploy workflow)
// ---------------------------------------------------------------------------
output containerAppName string = app.name
output containerAppFqdn string = app.properties.configuration.ingress.fqdn
output managedIdentityName string = identity.name
output managedIdentityClientId string = identity.properties.clientId
output managedIdentityPrincipalId string = identity.properties.principalId
