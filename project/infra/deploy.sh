#!/usr/bin/env bash
# Two-phase deploy (bash). Usage: API_KEYS='{"k":"C-1"}' LANGFUSE_PUBLIC_KEY=.. LANGFUSE_SECRET_KEY=.. REDIS_URL=.. \
#                                  ./deploy.sh rg-supportops-prod swedencentral
set -euo pipefail
RG="${1:?resource group}"; LOC="${2:-swedencentral}"; PREFIX="${NAME_PREFIX:-supportops}"; ENVN="${APP_ENV:-prod}"
TAG="${TAG:-$(git rev-parse --short HEAD)}"; HERE="$(cd "$(dirname "$0")" && pwd)"

params() {  # $1=deployApp(true|false) $2=image ; writes secrets to a temp file (deleted by caller)
  python3 - "$1" "$2" <<'PY'
import json, os, sys, tempfile
deploy, image = sys.argv[1] == "true", sys.argv[2]
p = {"namePrefix": os.environ.get("NAME_PREFIX", "supportops"), "appEnv": os.environ.get("APP_ENV", "prod"),
     "deployApp": deploy, "image": image, "apiKeysJson": os.environ.get("API_KEYS", "{}")}
for env, key in [("LANGFUSE_PUBLIC_KEY", "langfusePublicKey"), ("LANGFUSE_SECRET_KEY", "langfuseSecretKey"),
                 ("LANGFUSE_HOST", "langfuseHost"), ("REDIS_URL", "redisUrl")]:
    if os.environ.get(env): p[key] = os.environ[env]
doc = {"$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
       "contentVersion": "1.0.0.0", "parameters": {k: {"value": v} for k, v in p.items()}}
f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False); json.dump(doc, f); print(f.name)
PY
}

az group create -n "$RG" -l "$LOC" >/dev/null
echo "== Phase 1: platform"
F1=$(params false ""); trap 'rm -f "$F1" "${F2:-}"' EXIT
az deployment group what-if -g "$RG" -f "$HERE/main.bicep" -p "@$F1"
ACR=$(az deployment group create -g "$RG" -f "$HERE/main.bicep" -p "@$F1" --query properties.outputs.acrName.value -o tsv)
LOGIN=$(az acr show -n "$ACR" --query loginServer -o tsv)
echo "== Build image in ACR: $TAG"
az acr build -r "$ACR" -t "supportops-agent:$TAG" "$HERE/.."
echo "== Phase 2: container app"
F2=$(params true "$LOGIN/supportops-agent:$TAG")
FQDN=$(az deployment group create -g "$RG" -f "$HERE/main.bicep" -p "@$F2" --query properties.outputs.appFqdn.value -o tsv)
sleep 20; curl -fsS "https://$FQDN/readyz" && echo && echo "Done: https://$FQDN"
