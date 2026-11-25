#!/usr/bin/env bash
set -euo pipefail
base="${API_URL:-http://127.0.0.1:8080}"
image="${1:?Usage: bash scripts/smoke_inference.sh image.jpg}"
[[ -f "$image" ]] || { echo 'Image not found' >&2; exit 1; }
case "$image" in
  *.jpg|*.jpeg|*.JPG|*.JPEG) mime=image/jpeg;;
  *.png|*.PNG) mime=image/png;;
  *.webp|*.WEBP) mime=image/webp;;
  *) echo 'Use JPEG, PNG or WebP' >&2; exit 1;;
esac
slug="smoke-$(date +%s)-${RANDOM}"
workspace=$(curl -fsS "$base/api/v1/workspaces" -H 'Content-Type: application/json' \
  -d "$(jq -nc --arg slug "$slug" '{slug:$slug,name:"Inference smoke test"}')" | jq -er '.id')
media=$(curl -fsS "$base/api/v1/media/upload" \
  -F "workspace_id=$workspace" -F "file=@$image;type=$mime" | jq -er '.id')
job=$(curl -fsS "$base/api/v1/jobs" -H 'Content-Type: application/json' \
  -d "$(jq -nc --arg w "$workspace" --arg m "$media" '{workspace_id:$w,media_id:$m,pipeline:"detection"}')" | jq -er '.id')
result=$(curl -fsS -X POST "$base/api/v1/jobs/$job/run")
printf '%s\n' "$result" | jq .
printf '%s\n' "$result" | jq -e '.status == "succeeded"' >/dev/null
curl -fsS "$base/api/v1/findings?job_id=$job" | jq .
echo "Workspace: $slug; job: $job"
