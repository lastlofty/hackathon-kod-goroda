# ML integration / DevSecOps

Base snapshot: `ecc1726`. Existing media, jobs, findings, annotations, 2GIS and inspection feed remain in place. No new DB tables or API changes for existing routes. SAM is offline annotation assistance, not an inference dependency.

## Local run (Mac ARM64)

```bash
# No copy of .env required for mock; retain existing local settings.
make dev
# wait for backend health before smoke test
docker compose ps
curl -fsS http://127.0.0.1:8080/health
bash scripts/smoke_inference.sh /path/to/image.jpg
```

Mock is enabled only explicitly. Default `docker compose up` keeps inference disabled. Mock creates a synthetic bbox labelled `DEMO / MOCK`, with category `mock_detection`, source `mock` and attributes.synthetic=true. Use only a separate demo workspace. The smoke script creates a new workspace and leaves data for inspection. PostgreSQL and backend are bound to localhost by default. Set `BACKEND_BIND=0.0.0.0` only if you intentionally need network access, with appropriate access control. Current API has no production authentication, DB credentials are the existing dev defaults, and backend container still uses the existing root user. Do not expose this configuration to untrusted networks. Don't use `docker compose down -v` if you want to preserve data.

## Actual API contract

1. `POST /api/v1/media/upload` multipart `workspace_id`, `file` (+ optional GPS).
2. `POST /api/v1/jobs` JSON `{ "workspace_id": "UUID", "media_id": "UUID", "pipeline": "detection" }`.
3. `POST /api/v1/jobs/{job_id}/run` (no body). An explicit, synchronous executor for already queued detection jobs. Successful HTTP 200 returns JobRead with `status=succeeded` or `status=failed` and `error_message` when the inference attempt fails. HTTP 409 means state/pipeline conflict, 422 invalid local media, 503 disabled.
4. `GET /api/v1/findings?job_id=UUID`; existing `GET /api/v1/inspection/frames?workspace=slug` and `/inspection/stream` expose persisted findings to the frontend.

Only locally uploaded image URLs are accepted; remote URLs are intentionally not fetched. For the MVP, results are written transactionally with job completion. Normal repeat calls to `/run` are rejected after claiming. There is no automatic worker, retry or lease: a crash may leave a job running. Do not manually modify a managed running job using the generic PATCH/DELETE API or reset completed jobs to queued; create a new job for a deliberate re-run. The frontend must explicitly call the new run route if it wants this executor; existing upload/job creation behaviour is unchanged. No frontend changes in this patch.

## CV engineer: exact integration points

- `app/cv/adapter.py`: implement `preprocess` and `postprocess`. They intentionally raise `AdapterNotConfigured` until the actual model contract is known.
- `app/services/inference.py`, function `evaluate`: actual call to Triton and receipt of results. No database or HTTP API changes required by CV engineer.
- `app/integrations/triton.py`: versioned Triton V2 HTTP/JSON transport. Input list uses `name`, `shape`, `datatype`, flattened `data`; outputs are keyed by tensor name and contain `shape`, `datatype`, `data`. This is a lightweight initial protocol, not binary/grpc optimized transport. Numeric model tensors only; CV can use NumPy after agreeing dependencies. If using numpy arrays convert to flattened lists for JSON. Use actual tensor names and model contract, not dummy names.
- `Detection` objects returned by postprocess must have category (e.g. pole/manhole once agreed), label, score (0..1), normalized x/y/width/height relative to original image, optional attributes/severity/recommendation. Undo letterboxing; clip boxes to original boundaries. Only bbox is implemented in this MVP; polygon/polyline can be added later following `docs/inspection-feed.md`. Source, job/media/workspace links and model version are populated by service. GPS stays on the media record; no invented coordinates for detected objects.

## NVIDIA GPU host

Linux host with compatible NVIDIA GPU/driver and NVIDIA Container Toolkit. Default image tag 25.06-py3 is a provisional baseline (CUDA 12.9; standard driver 575 or newer); check current driver and hardware, then select compatible validated tag via TRITON_IMAGE. See https://docs.nvidia.com/deeplearning/triton-inference-server/release-notes/rel-25-06.html. Before deployment evaluate current NVIDIA security updates. No claim that this tag is the newest or verified on your hardware.

```bash
nvidia-smi
mkdir -p triton/model_repository/detection/1
# copy actual model.onnx and its companion external-data files here
# verify model hash against the ML engineer's value
sha256sum triton/model_repository/detection/1/model.onnx
make gpu
# backend starts independently; model readiness must be verified separately
docker compose -f docker-compose.yml -f docker-compose.gpu.yml logs --tail=100 triton
docker compose -f docker-compose.yml -f docker-compose.gpu.yml exec -T backend python - <<'PY'
import os, json, urllib.request
base = os.environ['TRITON_URL']
model = os.environ['TRITON_MODEL_NAME']
version = os.environ['TRITON_MODEL_VERSION']
for path in ['/v2/health/ready', f'/v2/models/{model}/versions/{version}/ready', f'/v2/models/{model}/versions/{version}', f'/v2/models/{model}/versions/{version}/config']:
    with urllib.request.urlopen(base + path, timeout=10) as response:
        print(path, response.status, response.read().decode())
PY
```

Change model name/version env values to match repository. No GPU ports published. Model readiness is separate from backend health (liveness). Server may report not ready until actual weights are provided. No hard dependency on Triton so CRUD and uploads remain available during inference outages. Once adapter implemented, run the smoke script with a real test image and verify results on frontend. This configuration has not been launched on a GPU yet.

## CI and limitations

Workflow `ml-infra-ci.yml` runs backend tests, Compose config validation and dependency consistency. It does not run GPU workloads or vulnerability scans. Local tests exercise SQLite (the existing fixture), mock end-to-end, HTTP fake Triton, and error paths. Real PostgreSQL persistence and GPU model execution still need to be verified on target hosts. Production authentication, job queue, resource controls, CI security scan, image/digest locking, DB password rotation, and non-root container are follow-up items. No SAM, anomaly model, external image retrieval, entity matching or model training in this patch.
