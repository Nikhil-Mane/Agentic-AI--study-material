<#
 Two-phase deploy to Azure Container Apps.  Run from the repo's project/infra folder:
   $env:API_KEYS='{"prod-key-abc":"C-1"}'
   $env:LANGFUSE_PUBLIC_KEY='pk-lf-...'; $env:LANGFUSE_SECRET_KEY='sk-lf-...'
   $env:REDIS_URL='rediss://:<key>@<host>:6380/0'        # required for >1 replica
   ./deploy.ps1 -ResourceGroup rg-supportops-prod -Location swedencentral

 Secrets come from environment variables, are written to a temp parameters file, and are deleted afterwards.
 Prereqs: az login ; az account set -s <subscription> ; Azure OpenAI access approved for the subscription.
#>
param(
  [Parameter(Mandatory)] [string] $ResourceGroup,
  [string] $Location = "swedencentral",
  [string] $NamePrefix = "supportops",
  [string] $AppEnv = "prod",
  [string] $Tag = (git rev-parse --short HEAD)
)
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

function New-ParamsFile([bool] $DeployApp, [string] $Image) {
  $p = [ordered]@{
    namePrefix = @{ value = $NamePrefix }
    appEnv     = @{ value = $AppEnv }
    deployApp  = @{ value = $DeployApp }
    image      = @{ value = $Image }
    apiKeysJson = @{ value = $(if ($env:API_KEYS) { $env:API_KEYS } else { '{}' }) }
  }
  if ($env:LANGFUSE_PUBLIC_KEY) { $p.langfusePublicKey = @{ value = $env:LANGFUSE_PUBLIC_KEY } }
  if ($env:LANGFUSE_SECRET_KEY) { $p.langfuseSecretKey = @{ value = $env:LANGFUSE_SECRET_KEY } }
  if ($env:LANGFUSE_HOST)       { $p.langfuseHost       = @{ value = $env:LANGFUSE_HOST } }
  if ($env:REDIS_URL)           { $p.redisUrl           = @{ value = $env:REDIS_URL } }
  $file = New-TemporaryFile
  @{ '$schema' = 'https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#'
     contentVersion = '1.0.0.0'; parameters = $p } | ConvertTo-Json -Depth 6 | Set-Content $file -Encoding utf8
  return $file
}

az group create -n $ResourceGroup -l $Location | Out-Null

Write-Host "== Phase 1: platform (identity, ACR, Key Vault, Azure OpenAI, Log Analytics, Container Apps env)"
$f1 = New-ParamsFile $false ""
try {
  az deployment group what-if -g $ResourceGroup -f "$here/main.bicep" -p "@$f1" | Out-Host     # review before applying
  $out = az deployment group create -g $ResourceGroup -f "$here/main.bicep" -p "@$f1" --query properties.outputs -o json | ConvertFrom-Json
} finally { Remove-Item $f1 -Force }
$acr = $out.acrName.value; $login = $out.acrLoginServer.value

Write-Host "== Build image in ACR (no local Docker needed), tag $Tag"
az acr build -r $acr -t "supportops-agent:$Tag" "$here/.." | Out-Host

Write-Host "== Phase 2: container app"
$image = "$login/supportops-agent:$Tag"
$f2 = New-ParamsFile $true $image
try {
  $out2 = az deployment group create -g $ResourceGroup -f "$here/main.bicep" -p "@$f2" --query properties.outputs -o json | ConvertFrom-Json
} finally { Remove-Item $f2 -Force }

$fqdn = $out2.appFqdn.value
Write-Host "== Smoke test https://$fqdn/readyz"
Start-Sleep 20
Invoke-RestMethod "https://$fqdn/readyz"
Write-Host "Done. App: https://$fqdn   Key Vault: $($out2.keyVaultName.value)"
