# Optional Triton monitoring

Run from the application checkout with the **same Compose project name** as the
running backend/Triton. Do not share a project across independent checkouts. This
overlay adds Prometheus and Grafana; it does not add a GPU dependency to macOS.
Only loopback ports 9090 and 3000 are published. Triton metrics stay internal.
No Docker socket, privileged containers, or host paths other than configuration
files are mounted. Images use explicit version tags (not immutable digests).

Generate a local admin password in the terminal (store privately; never commit):

```bash
export MGTS_GRAFANA_PASSWORD="$(openssl rand -hex 24)"
printf '%s\n' "$MGTS_GRAFANA_PASSWORD"
```

Grafana applies the password only on first initialization of its data volume.
For later use keep the password in a local password manager and export it again.

Mac/mock validation, without starting or recreating the backend:

```bash
docker compose -f docker-compose.yml -f docker-compose.monitoring.yml config --quiet
docker compose -f docker-compose.yml -f docker-compose.monitoring.yml up -d --no-deps prometheus grafana
curl -fsS http://127.0.0.1:9090/-/ready
curl -fsS http://127.0.0.1:3000/api/health
```

Wait for services to start before using curl. Prometheus `/targets` should show
its own target UP; Triton DOWN is expected in mock mode. Grafana dashboard:
http://127.0.0.1:3000/d/mgts-triton (login admin + local password).

Ubuntu GPU mode, after successful `make gpu` and real-model readiness check:

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml -f docker-compose.monitoring.yml config --quiet
docker compose -f docker-compose.yml -f docker-compose.gpu.yml -f docker-compose.monitoring.yml up -d --no-deps prometheus grafana
curl -fsS http://127.0.0.1:9090/api/v1/targets
```

If CD uses `COMPOSE_PROJECT_NAME=mgts-demo`, export that before every Compose
command above; otherwise use the same name as the existing manual GPU stack.
Check Triton target UP, run real inference, and confirm counters increase.
GPU metrics depend on the actual driver, GPU and Triton DCGM support; no data
is not zero. Request counters count model calls rather than unique photos;
latency is mean server-side latency, not p95/p99 or whole-job latency.
No backend instrumentation or alert delivery is included. No model weights or
credentials are needed in Git. CD does not start these optional services.

To stop only monitoring (retain data):

```bash
docker compose -f docker-compose.yml -f docker-compose.monitoring.yml stop prometheus grafana
```

Do not use `down -v` or `--remove-orphans` on the application project.
