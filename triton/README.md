# Triton model repository

Place the exported ONNX file (and its external data files if applicable) in:

```
triton/model_repository/detection/1/model.onnx
```

The directory is mounted read-only into Triton. The repository is empty in Git on purpose. Do not commit weights; distribute from an agreed artifact location, verify SHA-256 and record the model version. No `config.pbtxt` is included: compatible ONNX exports can be autoconfigured; otherwise the ML engineer must supply a minimal config. Check actual model metadata before writing the adapter. The GPU overlay is Linux/NVIDIA only. See `docs/ml-inference.md`.
