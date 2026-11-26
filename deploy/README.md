# Pull-based CD (Ubuntu demo host)

GitHub-hosted CI remains unchanged. The Ubuntu host fetches `origin/main` and checks
successful **push** runs of both `ml-infra-ci.yml` and `security-ci.yml` for its exact
SHA via GitHub API. Pending, missing or failed checks do not deploy. Reports-only
security checks are not a vulnerability-free guarantee. Historical Gitleaks failures
must be remediated, not bypassed.

Use a dedicated deployment checkout/account, not the team's working tree. Docker
access is effectively root-equivalent; only trusted, reviewed main code may run.
No inbound SSH, self-hosted GitHub runner, or GitHub write token is needed. Use a
fine-grained token restricted to this repository with Contents: read and Actions:
read (and implicit Metadata: read). Authenticate interactively as the deployment
user (`gh auth login --hostname github.com --with-token`, feed token via stdin,
never paste into shell history or repo; `gh auth setup-git` for HTTPS). Protect
credentials and local data. Enable branch protection and required reviews.

Prerequisites: Ubuntu, Bash, git, gh, Docker Engine with Compose v2 supporting
`--wait`, flock, and, for gpu, NVIDIA driver/toolkit already tested with Docker.
Choose a fresh dedicated checkout and fixed project name. Do not share the same
Compose project between independent checkouts or different modes. Set up `.env`
from `.env.example`, insert local credentials privately, keep BACKEND_BIND on
loopback unless a separately secured network path is configured. Default app DB
credentials are demo-only; do not expose PostgreSQL or unauthenticated API to WAN.

From the trusted checkout containing this patch:

```bash
mkdir -p ~/.local/bin ~/.config/systemd/user ~/.config/mgts-deploy
chmod 700 ~/.config/mgts-deploy
install -m 700 deploy/autodeploy.sh ~/.local/bin/mgts-autodeploy
install -m 644 deploy/systemd/mgts-deploy.{service,timer} ~/.config/systemd/user/
cat > ~/.config/mgts-deploy/deploy.env <<'CONF'
MGTS_MODE=mock
MGTS_PROJECT=mgts-demo
CONF
chmod 600 ~/.config/mgts-deploy/deploy.env
```

Default checkout is `$HOME/Projects/hackathon-kod-goroda`; set `MGTS_REPO_DIR`
to an absolute path if different. For actual GPU deployment choose `MGTS_MODE=gpu`
**before** enabling, deliver the approved model repository and set its name/version
in local `.env`. First run `COMPOSE_PROJECT_NAME=mgts-demo make gpu` (or the chosen project name) and verify real inference manually. Do not
run experiments concurrently with deployment if GPU memory is insufficient.

```bash
# Check-only: uses mock defaults unless environment is passed explicitly
MGTS_PROJECT=mgts-demo MGTS_MODE=mock ~/.local/bin/mgts-autodeploy --check
systemctl --user daemon-reload
systemctl --user start mgts-deploy.service
journalctl --user -u mgts-deploy.service -n 80 --no-pager
# Enable only after successful initial deployment and a smoke test
systemctl --user enable --now mgts-deploy.timer
```

The installed deploy script is intentionally not updated automatically; review and
reinstall it when changed. Timer runs while the user manager is active; use an
approved linger configuration if required. Pause for rehearsals:

```bash
systemctl --user stop mgts-deploy.timer
systemctl --user status mgts-deploy.service
```

Stopping the timer does not stop the containers or an already running deployment.
Wait for the service to finish before manual changes. After reboot, explicitly
start the existing stack if stopped; this timer updates versions, not service
supervision. Keep the project name stable. The current Compose files are not
modified and their restart policies are unchanged.

A deployment saves a PostgreSQL dump if its container exists and is running;
if the dump fails, deployment stops. Backups contain potentially sensitive data,
are stored locally with restricted permissions and require manual retention and
restore testing. Uploads and weights are not backed up by this script. Never use
`docker compose down -v` or `git clean -fdx`. Failed deployment leaves an attempted
marker (`~/.local/state/mgts-deploy/attempted`); inspect logs, fix the issue and
explicitly remove that marker before retrying the same SHA. No automatic DB/code
rollback: Alembic migrations may be irreversible. Restore only after coordinating
with the team. The timer does not deploy when main has no successful security run.

Scope: Backend/PostgreSQL/Triton only. Frontend build and end-to-end smoke test
must be wired to its actual current launch contract; not part of this patch.
