#!/usr/bin/env bash
# Install outside the checkout; only reviewed main commits may be deployed.
set -Eeuo pipefail
umask 077

repo=${MGTS_REPO_DIR:-$HOME/Projects/hackathon-kod-goroda}
state=${MGTS_STATE_DIR:-$HOME/.local/state/mgts-deploy}
project=${MGTS_PROJECT:-hackathon-kod-goroda}
mode=${MGTS_MODE:-mock}
remote=lastlofty/hackathon-kod-goroda
check_only=${1:-}
[[ -z "$check_only" || "$check_only" == --check ]] || { echo 'Usage: mgts-autodeploy [--check]' >&2; exit 2; }
case "$mode" in mock|gpu) ;; *) echo 'MGTS_MODE must be mock or gpu' >&2; exit 2;; esac
for cmd in git gh docker flock; do command -v "$cmd" >/dev/null || { echo "Missing command: $cmd" >&2; exit 1; }; done
mkdir -p "$state/backups"
chmod 700 "$state" "$state/backups"
exec 9>"$state/deploy.lock"
flock -n 9 || { echo 'Another deployment is running'; exit 0; }
cd "$repo"
case "$(git remote get-url origin)" in
  "https://github.com/$remote.git"|"https://github.com/$remote"|"git@github.com:$remote.git"|"git@github.com:$remote") ;;
  *) echo 'Unexpected origin; refusing deployment' >&2; exit 1;;
esac
[[ -z "$(git status --porcelain)" ]] || { echo 'Deployment checkout is dirty; refusing deployment' >&2; exit 1; }
[[ -f .env && -z "$(git ls-files -- .env)" ]] || { echo 'Create an untracked .env first' >&2; exit 1; }
export GIT_TERMINAL_PROMPT=0 GH_PROMPT_DISABLED=1
# No pull requests or arbitrary branches are deployed.
git fetch --no-tags origin refs/heads/main:refs/remotes/origin/main
sha=$(git rev-parse refs/remotes/origin/main)
key="$sha $mode $project"
if [[ -f "$state/applied" ]]; then
  read -r previous previous_mode previous_project < "$state/applied"
  [[ "$previous_mode" == "$mode" && "$previous_project" == "$project" ]] || { echo 'Deployment mode/project changed; use a separate state directory and coordinate stack changes' >&2; exit 1; }
  git merge-base --is-ancestor "$previous" "$sha" || { echo 'Main history diverged; manual review required' >&2; exit 1; }
  if [[ "$(cat "$state/applied")" == "$key" && -z "$check_only" ]]; then
    [[ "$(git rev-parse HEAD)" == "$sha" ]] || { echo 'Deployment checkout changed unexpectedly' >&2; exit 1; }
    echo "Already deployed: $sha"; exit 0
  fi
fi
# API errors are failures, missing/pending/failed runs never authorize deployment.
for workflow in ml-infra-ci.yml security-ci.yml; do
  result=$(gh api --method GET "repos/$remote/actions/workflows/$workflow/runs" \
    -f branch=main -f event=push -f head_sha="$sha" -f per_page=1 \
    --jq '.workflow_runs[0] | if . == null then "missing" else (.status + ":" + (.conclusion // "pending")) end')
  if [[ "$result" != completed:success ]]; then
    echo "Not deploying $sha: $workflow = ${result:-missing}"
    exit 0
  fi
done
echo "Both CI workflows passed for $sha"
[[ "$check_only" != --check ]] || exit 0
if [[ -f "$state/attempted" && "$(cat "$state/attempted")" == "$key" ]]; then
  echo 'This revision previously failed; inspect logs before removing the attempted marker' >&2; exit 1
fi
# Avoid deploying a stale revision if main advanced while checks were read.
git fetch --no-tags origin refs/heads/main:refs/remotes/origin/main
[[ "$(git rev-parse refs/remotes/origin/main)" == "$sha" ]] || { echo 'Main advanced; retry on next tick'; exit 0; }
docker info >/dev/null
compose=(docker compose --project-name "$project" -f docker-compose.yml)
if [[ "$mode" == gpu ]]; then
  command -v nvidia-smi >/dev/null; nvidia-smi >/dev/null
  compose+=(-f docker-compose.gpu.yml)
else
  export INFERENCE_MODE=mock
fi
# Back up existing PostgreSQL before any migration; refuse if dump fails.
pg_id=$("${compose[@]}" ps --all --quiet postgres)
if [[ -n "$pg_id" ]]; then
  backup="$state/backups/$(date -u +%Y%m%dT%H%M%SZ)-${sha:0:12}.dump"
  if ! "${compose[@]}" exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$backup.tmp"; then
    rm -f "$backup.tmp"; echo 'Database backup failed; not deploying' >&2; exit 1
  fi
  [[ -s "$backup.tmp" ]] || { rm -f "$backup.tmp"; echo 'Empty database backup' >&2; exit 1; }
  mv "$backup.tmp" "$backup"
  echo "Database backup: $backup"
fi
printf '%s\n' "$key" > "$state/attempted"
# Never reset --hard, clean, or overwrite ignored local model artifacts.
git checkout --no-overwrite-ignore --detach "$sha"
"${compose[@]}" config --quiet
"${compose[@]}" up -d --build --wait --wait-timeout 180
"${compose[@]}" exec -T backend python -c 'import urllib.request; assert urllib.request.urlopen("http://127.0.0.1:8080/health", timeout=5).status == 200'
if [[ "$mode" == gpu ]]; then
  ready=0
  for ((i=0; i<30; i++)); do
    if "${compose[@]}" exec -T backend python -c 'import os,urllib.request; base=os.environ["TRITON_URL"].rstrip("/"); model=os.environ["TRITON_MODEL_NAME"]; version=os.environ["TRITON_MODEL_VERSION"]; assert urllib.request.urlopen(f"{base}/v2/models/{model}/versions/{version}/ready",timeout=5).status == 200' >/dev/null 2>&1; then ready=1; break; fi
    sleep 5
  done
  [[ "$ready" == 1 ]] || { echo 'Triton model is not ready; inspect logs' >&2; exit 1; }
fi
printf '%s\n' "$key" > "$state/applied.tmp"
mv "$state/applied.tmp" "$state/applied"
rm -f "$state/attempted"
echo "Deployment healthy: $sha ($mode)"
