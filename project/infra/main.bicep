// SupportOps agent on Azure:  Container Apps + Azure OpenAI (Entra-only) + Key Vault + ACR + Log Analytics.
//
// Security model (the important part):
//   * ONE user-assigned managed identity runs the app. No API keys for Azure OpenAI or ACR exist at all:
//       - Azure OpenAI has local (key) auth DISABLED; the app authenticates with Entra ID (role: Cognitive Services OpenAI User)
//       - the app pulls images from ACR with the identity (role: AcrPull), admin user disabled
//       - app secrets live in Key Vault; Container Apps reads them with the identity (role: Key Vault Secrets User)
//   * HTTPS only ingress; app is non-root / read-only FS inside the image.
//
// Two-phase deploy (the image must exist before the app can start):   see deploy.ps1 / deploy.sh
//   phase 1: deployApp=false  -> creates everything except the container app
//   phase 2: deployApp=true   -> after `az acr build`, creates the app with the image
//
// NOT validated against a live subscription by the author - run `az deployment group what-if` first.
// Model/version/SKU availability and quota differ by region: check the Azure OpenAI model table for yours.

targetScope = 'resourceGroup'

@description('Short lowercase prefix used in resource names (3-12 chars).')
@minLength(3)
@maxLength(12)
param namePrefix string = 'supportops'

param location string = resourceGroup().location

@description('Environment label: dev | staging | prod. Shown on Langfuse traces.')
param appEnv string = 'prod'

@description('Create the Container App (phase 2). Phase 1 creates the platform only.')
param deployApp bool = false

@description('Full image reference, e.g. <acr>.azurecr.io/supportops-agent:<git-sha>. Tag = release id; never :latest.')
param image string = ''

@description('Create a new Azure OpenAI account + model deployment. Set false to use an existing account via existingOpenAIName.')
param createOpenAI bool = true
param existingOpenAIName string = ''

param openAIModelName string = 'gpt-4o'
param openAIModelVersion string = '2024-11-20'
@description('Deployment name = what the app passes as `model`. Keep it stable across model upgrades.')
param openAIDeploymentName string = 'support-agent'
@description('Tokens-per-minute quota in thousands (50 = 50K TPM).')
param openAICapacity int = 50
param openAIApiVersion string = '2024-10-21'

@secure()
@description('JSON map of API key -> customer id. Production: replace with Entra ID / JWT auth.')
param apiKeysJson string = '{}'
@secure()
param langfusePublicKey string = ''
@secure()
param langfuseSecretKey string = ''
@description('https://cloud.langfuse.com (EU), https://us.cloud.langfuse.com, or your self-hosted URL.')
param langfuseHost string = 'https://cloud.langfuse.com'
@secure()
@description('Salt for hashing user ids sent to Langfuse.')
param langfuseUserHashSalt string = newGuid()
@secure()
@description('rediss://:<key>@<host>:6380/0  (Azure Cache for Redis / Azure Managed Redis). Empty = in-memory state => forced to 1 replica.')
param redisUrl string = ''

param minReplicas int = 2
param maxReplicas int = 20
@description('Concurrent requests per replica that triggers scale-out (agent calls are slow + I/O bound).')
param concurrentRequestsPerReplica int = 10

var suffix = uniqueString(resourceGroup().id)
var acrName = toLower('${namePrefix}${suffix}')               // ACR names: alphanumeric, globally unique
var kvName = toLower('${take(namePrefix, 8)}-kv-${take(suffix, 8)}')
var openAIName = createOpenAI ? toLower('${namePrefix}-aoai-${take(suffix, 6)}') : existingOpenAIName
var hasRedis = !empty(redisUrl)
var effMin = hasRedis ? minReplicas : 1                       // in-memory state is not shared: 1 replica only!
var effMax = hasRedis ? maxReplicas : 1

// built-in role definition ids
var roleAcrPull = '7f951dda-4ed3-4680-a7ca-43fe172d538d'
var roleKvSecretsUser = '4633458b-17de-408a-b874-0445c86b69e6'
var roleOpenAIUser = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'

// ---------------------------------------------------------------- identity
resource uami 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${namePrefix}-id'
  location: location
}

// ---------------------------------------------------------------- observability (platform logs)
resource law 'Microsoft.OperationalInsights/workspaces@2022-10-01' = {
  name: '${namePrefix}-law'
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

// ---------------------------------------------------------------- registry
resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: acrName
  location: location
  sku: { name: 'Standard' }
  properties: { adminUserEnabled: false }
}

// ---------------------------------------------------------------- secrets
resource kv 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: kvName
  location: location
  properties: {
    tenantId: subscription().tenantId
    sku: { family: 'A', name: 'standard' }
    enableRbacAuthorization: true
    enableSoftDelete: true
    enablePurgeProtection: true
    publicNetworkAccess: 'Enabled'      // tighten with private endpoint + firewall for regulated workloads
  }
}

resource secApiKeys 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: kv
  name: 'api-keys'
  properties: { value: apiKeysJson }
}
resource secLfPublic 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (!empty(langfusePublicKey)) {
  parent: kv
  name: 'langfuse-public-key'
  properties: { value: langfusePublicKey }
}
resource secLfSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (!empty(langfuseSecretKey)) {
  parent: kv
  name: 'langfuse-secret-key'
  properties: { value: langfuseSecretKey }
}
resource secSalt 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: kv
  name: 'langfuse-user-hash-salt'
  properties: { value: langfuseUserHashSalt }
}
resource secRedis 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (hasRedis) {
  parent: kv
  name: 'redis-url'
  properties: { value: redisUrl }
}

// ---------------------------------------------------------------- Azure OpenAI
resource aoaiNew 'Microsoft.CognitiveServices/accounts@2024-10-01' = if (createOpenAI) {
  name: openAIName
  location: location
  kind: 'OpenAI'
  sku: { name: 'S0' }
  properties: {
    customSubDomainName: openAIName     // required for Entra ID auth
    publicNetworkAccess: 'Enabled'      // tighten with private endpoint for regulated workloads
    disableLocalAuth: true              // NO API KEYS: identity-only access
  }
}
resource aoaiExisting 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = if (!createOpenAI) {
  name: existingOpenAIName
}
var aoaiEndpoint = createOpenAI ? aoaiNew.properties.endpoint : aoaiExisting.properties.endpoint

resource aoaiDeployment 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = if (createOpenAI) {
  parent: aoaiNew
  name: openAIDeploymentName
  sku: { name: 'GlobalStandard', capacity: openAICapacity }
  properties: {
    model: { format: 'OpenAI', name: openAIModelName, version: openAIModelVersion }
    versionUpgradeOption: 'NoAutoUpgrade'     // upgrade deliberately: run evals first
  }
}

// ---------------------------------------------------------------- role assignments (least privilege)
resource raAcr 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, uami.id, roleAcrPull)
  scope: acr
  properties: {
    principalId: uami.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleAcrPull)
  }
}
resource raKv 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(kv.id, uami.id, roleKvSecretsUser)
  scope: kv
  properties: {
    principalId: uami.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleKvSecretsUser)
  }
}
resource raOpenAINew 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (createOpenAI) {
  name: guid(aoaiNew.id, uami.id, roleOpenAIUser)
  scope: aoaiNew
  properties: {
    principalId: uami.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleOpenAIUser)
  }
}
resource raOpenAIExisting 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!createOpenAI) {
  name: guid(aoaiExisting.id, uami.id, roleOpenAIUser)
  scope: aoaiExisting
  properties: {
    principalId: uami.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleOpenAIUser)
  }
}

// ---------------------------------------------------------------- Container Apps environment
resource cae 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: '${namePrefix}-env'
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: law.properties.customerId
        sharedKey: law.listKeys().primarySharedKey
      }
    }
  }
}

// ---------------------------------------------------------------- the app (phase 2)
var kvUri = kv.properties.vaultUri
var baseSecrets = [
  { name: 'api-keys', keyVaultUrl: '${kvUri}secrets/api-keys', identity: uami.id }
  { name: 'langfuse-user-hash-salt', keyVaultUrl: '${kvUri}secrets/langfuse-user-hash-salt', identity: uami.id }
]
var langfuseSecrets = (!empty(langfusePublicKey) && !empty(langfuseSecretKey)) ? [
  { name: 'langfuse-public-key', keyVaultUrl: '${kvUri}secrets/langfuse-public-key', identity: uami.id }
  { name: 'langfuse-secret-key', keyVaultUrl: '${kvUri}secrets/langfuse-secret-key', identity: uami.id }
] : []
var redisSecrets = hasRedis ? [
  { name: 'redis-url', keyVaultUrl: '${kvUri}secrets/redis-url', identity: uami.id }
] : []

var baseEnv = [
  { name: 'LLM_PROVIDER', value: 'azure' }
  { name: 'AZURE_OPENAI_ENDPOINT', value: aoaiEndpoint }
  { name: 'AZURE_OPENAI_DEPLOYMENT', value: openAIDeploymentName }
  { name: 'AZURE_OPENAI_API_VERSION', value: openAIApiVersion }
  { name: 'TRACE_MODEL_NAME', value: openAIModelName }             // base model name -> Langfuse cost inference
  { name: 'AZURE_CLIENT_ID', value: uami.properties.clientId }      // tells DefaultAzureCredential which identity to use
  { name: 'APP_ENV', value: appEnv }
  { name: 'APP_VERSION', value: last(split(image, ':')) }           // git sha -> Langfuse "release"
  { name: 'LANGFUSE_HOST', value: langfuseHost }
  { name: 'RATE_PER_SEC', value: '0.5' }
  { name: 'RATE_BURST', value: '5' }
  { name: 'API_KEYS', secretRef: 'api-keys' }
  { name: 'LANGFUSE_USER_HASH_SALT', secretRef: 'langfuse-user-hash-salt' }
]
var langfuseEnv = (!empty(langfusePublicKey) && !empty(langfuseSecretKey)) ? [
  { name: 'LANGFUSE_PUBLIC_KEY', secretRef: 'langfuse-public-key' }
  { name: 'LANGFUSE_SECRET_KEY', secretRef: 'langfuse-secret-key' }
] : []
var redisEnv = hasRedis ? [
  { name: 'REDIS_URL', secretRef: 'redis-url' }
] : []

resource app 'Microsoft.App/containerApps@2024-03-01' = if (deployApp) {
  name: '${namePrefix}-agent'
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${uami.id}': {} }
  }
  properties: {
    managedEnvironmentId: cae.id
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'        // 'Multiple' + traffic weights for canary releases
      maxInactiveRevisions: 5
      ingress: {
        external: true
        targetPort: 8080
        transport: 'auto'
        allowInsecure: false               // HTTPS only
      }
      registries: [ { server: acr.properties.loginServer, identity: uami.id } ]
      secrets: concat(baseSecrets, langfuseSecrets, redisSecrets)
    }
    template: {
      terminationGracePeriodSeconds: 90    // let in-flight agent runs finish on scale-in / deploy
      containers: [
        {
          name: 'api'
          image: image
          resources: { cpu: json('0.5'), memory: '1Gi' }
          env: concat(baseEnv, langfuseEnv, redisEnv)
          probes: [
            { type: 'Startup', httpGet: { path: '/healthz', port: 8080 }, periodSeconds: 3, failureThreshold: 30 }
            { type: 'Liveness', httpGet: { path: '/healthz', port: 8080 }, periodSeconds: 15, timeoutSeconds: 3 }
            { type: 'Readiness', httpGet: { path: '/readyz', port: 8080 }, periodSeconds: 5 }
          ]
        }
      ]
      scale: {
        minReplicas: effMin
        maxReplicas: effMax
        rules: [
          { name: 'http-concurrency', http: { metadata: { concurrentRequests: string(concurrentRequestsPerReplica) } } }
        ]
      }
    }
  }
  dependsOn: [ raAcr, raKv, raOpenAINew, raOpenAIExisting, secApiKeys, secSalt, aoaiDeployment ]
}

output acrName string = acr.name
output acrLoginServer string = acr.properties.loginServer
output keyVaultName string = kv.name
output openAIEndpoint string = aoaiEndpoint
output identityClientId string = uami.properties.clientId
output appFqdn string = deployApp ? app.properties.configuration.ingress.fqdn : ''
output appName string = '${namePrefix}-agent'
