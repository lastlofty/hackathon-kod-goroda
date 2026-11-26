# MGTS Ubuntu preflight

Run locally on the dedicated Ubuntu deployment host as the same non-root user
that will deploy the application. No sudo is used by the playbook. The GPU probe
may pull a public Ubuntu image into the Docker cache; it removes its temporary
container. It does not install drivers, restart Docker or start the application.

Install Ansible using the OS package manager if absent (`sudo apt install ansible`
after updating apt indexes), and prepare Git, GitHub CLI, Docker Engine with Compose
v2 and NVIDIA Container Toolkit as appropriate. Docker access is root-equivalent;
use only an authorized deployment account. Do not blindly reinstall a working driver.

From the repository root:

```bash
ansible-playbook -i infra/ansible/inventory.yml infra/ansible/site.yml --syntax-check
ansible-playbook -i infra/ansible/inventory.yml infra/ansible/site.yml -e mgts_mode=mock
ansible-playbook -i infra/ansible/inventory.yml infra/ansible/site.yml -e mgts_mode=gpu
```

The default 40 GiB free on the checkout filesystem is a provisional minimum,
not a guarantee. Inspect the Docker Root Dir filesystem as well; model weights,
build caches and datasets may require substantially more space. GPU availability
via nvidia-smi is not proof of CUDA/Triton or model compatibility. Validate the
actual NVIDIA image, backend adapter and model end to end before enabling CD.

If dependencies are missing, consult the upstream installation instructions:
- https://docs.docker.com/engine/install/ubuntu/
- https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html

After preflight passes, use the repository's `make dev` or `make gpu` and verify
health and real inference. Use the separate `deploy/README.md` procedure (once
merged) to install the pull-based CD timer after checking CI, backups, and the
initial deployment. Never enable automatic updates during a live demonstration.
