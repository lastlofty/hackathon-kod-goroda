# Security CI — initial rollout

The existing `ml-infra-ci.yml` remains unchanged. `security-ci.yml` runs on
pull requests, pushes to main and manual dispatches. It does not require a GPU,
registry credentials, GitHub Advanced Security or deployment secrets.

| Check | Scope | Policy |
|---|---|---|
| Gitleaks | Committed snapshot and fetched Git history | Blocking, including scanner errors |
| Ruff | app, tests, migrations | Report findings |
| Bandit | app | Report findings |
| pip-audit | Dependencies resolved from requirements.txt | Report known vulnerabilities; invalid output fails |
| Trivy | Freshly built Backend image (OS and application packages) | Report vulnerabilities; scanner errors fail |
| CycloneDX | Backend image software inventory (SBOM) | Artifact |

Python and image jobs run independently of secret scanning. The secret scanner runs a
synthetic positive test, redacts logs and does not upload secret reports. It scans
Git refs fetched by checkout; it cannot see untracked local files, other repos or
unfetched refs. Rotate/revoke any real leaked credential; removing the file alone
is not remediation. Review false positives individually, never disable an entire
rule merely to turn the check green. Do not rewrite shared history without team
coordination.

## Review

Open the PR Checks tab or the Security checks run in GitHub Actions. Download
`security-python` and `security-container` from the run's Artifacts section.
Reports are kept for seven days and should only be shared with authorized team
members. Reports can contain code snippets and internal dependency details.

The first run establishes a baseline. A green run does not imply zero findings.
Review HIGH/CRITICAL vulnerabilities and fix or document exceptions. Once the
baseline is triaged, make the secret check required in main branch rules and
introduce a reviewed vulnerability threshold. A failing job blocks merging only
if branch rules require that check. CI tool versions are separate from runtime
requirements. Python transitive dependencies and Trivy's image tag are not yet
fully digest/hash locked; verify upstream releases before updating them.

Trivy scans the application image, not PostgreSQL, Triton, the frontend's
separate dependencies or pretrained models. pip-audit resolves the requirements
independently of Docker, so Trivy provides complementary coverage of the actual
build. No image publication or deployment happens here. GPU tests, model
provenance, dependency locking, runtime hardening and registry release remain
separate follow-up work.
