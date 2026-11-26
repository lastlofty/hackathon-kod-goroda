"""Адаптер модели для обработчика обследований сервиса (hackathon-kod-goroda, app/survey_worker.py).

Запуск (из окружения с torch/transformers и зависимостями воркера):
    PYTHONPATH=<путь к сервису>:<путь к этой папке> \\
    MGTS_MODELS=<папка с heads.joblib> \\
    python -m app.survey_worker --api http://127.0.0.1:8080 --adapter mgts_adapter:infer

Видео пока не обрабатываются: в результате есть записи только для фотографий (так требует контракт).
"""
import os
from pathlib import Path

_analyzer = None


def _get_analyzer():
    global _analyzer
    if _analyzer is None:  # модели грузятся один раз на процесс воркера
        from solution import Analyzer
        models = os.environ.get("MGTS_MODELS", str(Path(__file__).with_name("models")))
        _analyzer = Analyzer(models, os.environ.get("MGTS_DEVICE") or None)
    return _analyzer


def infer(inputs, progress, publish_frame):
    """inputs: [{name, kind, id, url, path}] -> {"frames": [...], "objects": [...]} по контракту сервиса."""
    images = [(item["name"], item["path"]) for item in inputs if item["kind"] == "image"]
    if not images:
        return {"frames": [], "objects": []}
    return _get_analyzer().analyze(images, progress=progress)
