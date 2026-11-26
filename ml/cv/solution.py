"""МГТС «Код города»: оценка состояния ТКШ и РЩ по фото.

Пайплайн:
  1. detect   — zero-shot детекция шкафов (OWLv2 или Grounding DINO), вырезы + превью.
  2. evaluate — эмбеддинги вырезов (DINOv2 / CLIP), логрегрессии, кросс-валидация
                (leave-one-out) и zero-shot CLIP как базовая линия.
  3. train    — обучение голов на всём датасете, сохранение models/heads.joblib.
  4. predict  — новые фото -> result.json по контракту сервиса (статус, приоритет P1–P4,
                рекомендация), report.csv для бригады, картинки с рамками.

Примеры:
  python solution.py detect   --data data --out runs/det --detector owlv2
  python solution.py evaluate --data data --det runs/det --out runs/eval
  python solution.py train    --data data --det runs/det --out models
  python solution.py predict  --images new_photos --models models --out runs/pred
"""
from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageOps

# ---------------------------------------------------------------- константы

OBJECT_NAMES = {"TKSH": "ТКШ", "RSH": "РЩ"}

# Тексты для zero-shot детектора: (запрос, подсказка типа / None / NEG).
# NEG-запросы «перетягивают» на себя рамки деталей (решётка, столб, автоматы внутри),
# такие рамки отбрасываются: OWLv2 присваивает рамке лучший из запросов.
OWL_QUERIES = [
    ("a large telecommunication climate cabinet with a ventilation grille", "TKSH"),
    ("a large metal outdoor climate cabinet mounted on a pole", "TKSH"),
    ("a small electrical distribution box", "RSH"),
    ("a small grey electrical box mounted on a pole", "RSH"),
    ("an electrical cabinet", None),
    ("a ventilation grille", "NEG"),
    ("a utility pole", "NEG"),
    ("circuit breakers and wires", "NEG"),
]
GDINO_TEXT = ("telecommunication cabinet . electrical distribution box . electrical cabinet . "
              "ventilation grille . utility pole .")
GDINO_HINTS = {"telecommunication": "TKSH", "distribution": "RSH", "grille": "NEG", "pole": "NEG"}

# Задачи классификации: колонка labels.csv -> описание
TASKS = {
    "object_type": "тип объекта (ТКШ / РЩ)",
    "defect_any": "есть дефект",
    "defect_lkp": "повреждение ЛКП (коррозия)",
    "defect_mp": "механическое повреждение",
    "mp_mount": "нарушение крепления",
}
MIN_POSITIVES = 5  # меньше — задачу не учим, только сообщаем

CLIP_PROMPTS = {
    "defect_lkp": (["a photo of a rusty corroded metal cabinet", "a metal box with peeling paint and rust"],
                   ["a photo of a clean painted metal cabinet", "a metal box with intact paint"]),
    "defect_mp": (["a photo of a dented deformed broken electrical box", "a damaged electrical cabinet with a missing door"],
                  ["a photo of an intact undamaged electrical box", "a closed electrical cabinet in good condition"]),
    "defect_any": (["a damaged, rusty or broken electrical cabinet"],
                   ["a new clean electrical cabinet in good condition"]),
}

DINO_MODELS = {"dinov2-small": "facebook/dinov2-small", "dinov2-base": "facebook/dinov2-base",
               "dinov2-large": "facebook/dinov2-large"}
CLIP_MODEL = "openai/clip-vit-large-patch14"
OWL_MODEL = "google/owlv2-base-patch16-ensemble"
GDINO_MODEL = "IDEA-Research/grounding-dino-base"


# ---------------------------------------------------------------- утилиты

def device_of(name: str | None):
    import torch
    if name:
        return torch.device(name)
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def load_image(path: Path) -> Image.Image:
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im)  # фото с телефонов: учитываем ориентацию
        return im.convert("RGB")


def read_labels(data: Path) -> list[dict]:
    with open(data / "labels.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["object_type_bin"] = int(r["object_type"] == "TKSH")
        r["defect_any"] = int(r["condition"] == "defect")
        for k in ("defect_lkp", "defect_mp", "mp_deformation", "mp_mount", "mp_door_missing"):
            r[k] = int(r[k])
    return rows


def image_key(rel_path: str) -> str:
    return Path(rel_path).stem


def nms(boxes: np.ndarray, scores: np.ndarray, iou_thr: float) -> list[int]:
    order = scores.argsort()[::-1]
    keep = []
    while order.size:
        i = order[0]
        keep.append(int(i))
        if order.size == 1:
            break
        xx1 = np.maximum(boxes[i, 0], boxes[order[1:], 0])
        yy1 = np.maximum(boxes[i, 1], boxes[order[1:], 1])
        xx2 = np.minimum(boxes[i, 2], boxes[order[1:], 2])
        yy2 = np.minimum(boxes[i, 3], boxes[order[1:], 3])
        inter = np.clip(xx2 - xx1, 0, None) * np.clip(yy2 - yy1, 0, None)
        area = lambda b: (b[..., 2] - b[..., 0]) * (b[..., 3] - b[..., 1])  # noqa: E731
        iou = inter / (area(boxes[i]) + area(boxes[order[1:]]) - inter + 1e-9)
        order = order[1:][iou < iou_thr]
    return keep


def crop_box(img: Image.Image, box, pad: float = 0.06) -> Image.Image:
    w, h = img.size
    x1, y1, x2, y2 = box
    px, py = (x2 - x1) * pad, (y2 - y1) * pad
    return img.crop((max(0, x1 - px), max(0, y1 - py), min(w, x2 + px), min(h, y2 + py)))


# ---------------------------------------------------------------- детекция

@dataclass
class Detector:
    kind: str
    device: object
    threshold: float

    def __post_init__(self):
        from transformers import AutoProcessor
        if self.kind == "owlv2":
            from transformers import Owlv2ForObjectDetection
            self.processor = AutoProcessor.from_pretrained(OWL_MODEL)
            self.model = Owlv2ForObjectDetection.from_pretrained(OWL_MODEL).to(self.device).eval()
        elif self.kind == "gdino":
            from transformers import AutoModelForZeroShotObjectDetection
            self.processor = AutoProcessor.from_pretrained(GDINO_MODEL)
            self.model = AutoModelForZeroShotObjectDetection.from_pretrained(GDINO_MODEL).to(self.device).eval()
        else:
            raise ValueError(self.kind)

    def __call__(self, img: Image.Image, max_boxes: int = 8, min_area: float = 0.002) -> list[dict]:
        import torch
        w, h = img.size
        with torch.no_grad():
            if self.kind == "owlv2":
                texts = [q for q, _ in OWL_QUERIES]
                inputs = self.processor(text=[texts], images=img, return_tensors="pt").to(self.device)
                out = self.model(**inputs)
                side = max(w, h)  # OWLv2 дополняет картинку до квадрата
                ts = torch.tensor([[side, side]], device=self.device)
                pp = getattr(self.processor, "post_process_object_detection", None) \
                    or self.processor.post_process_grounded_object_detection
                res = pp(outputs=out, threshold=self.threshold, target_sizes=ts)[0]
                labels = [OWL_QUERIES[int(i)] for i in res["labels"].tolist()]
                hints = [hint for _, hint in labels]
                names = [q for q, _ in labels]
            else:
                inputs = self.processor(images=img, text=GDINO_TEXT, return_tensors="pt").to(self.device)
                out = self.model(**inputs)
                kw = dict(target_sizes=[(h, w)], text_threshold=0.25)
                try:
                    res = self.processor.post_process_grounded_object_detection(
                        out, inputs.input_ids, threshold=self.threshold, **kw)[0]
                except TypeError:  # старые версии transformers
                    res = self.processor.post_process_grounded_object_detection(
                        out, inputs.input_ids, box_threshold=self.threshold, **kw)[0]
                names = [str(x) for x in res.get("text_labels", res["labels"])]
                hints = [next((v for k, v in GDINO_HINTS.items() if k in n), None) for n in names]
        boxes = res["boxes"].float().cpu().numpy()
        scores = res["scores"].float().cpu().numpy()
        if len(boxes) == 0:
            return []
        boxes[:, [0, 2]] = boxes[:, [0, 2]].clip(0, w)
        boxes[:, [1, 3]] = boxes[:, [1, 3]].clip(0, h)
        area = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1]) / (w * h)
        ok = (area >= min_area) & np.array([hint != "NEG" for hint in hints], dtype=bool)
        boxes, scores = boxes[ok], scores[ok]
        hints = [x for x, k in zip(hints, ok) if k]
        names = [x for x, k in zip(names, ok) if k]
        keep = nms(boxes, scores, 0.5)[:max_boxes]
        return [{"box": [round(float(v), 1) for v in boxes[i]], "score": round(float(scores[i]), 4),
                 "query": names[i], "type_hint": hints[i]} for i in keep]


_FONT_CANDIDATES = ["DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                    "/usr/share/fonts/TTF/DejaVuSans.ttf", "Arial.ttf", "C:/Windows/Fonts/arial.ttf"]


def _font(size: int = 14):
    """TTF-шрифт с кириллицей (встроенный шрифт PIL её не рисует)."""
    from PIL import ImageFont
    for f in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            continue
    return ImageFont.load_default()


def draw_preview(img: Image.Image, dets: list[dict], target: int | None, path: Path, labels=None):
    im = img.copy()
    im.thumbnail((1280, 1280))
    s = im.width / img.width
    d = ImageDraw.Draw(im)
    font = _font(14)
    for k, det in enumerate(dets):
        x1, y1, x2, y2 = [v * s for v in det["box"]]
        color = (255, 40, 40) if k == target else {"TKSH": (0, 160, 255), "RSH": (255, 200, 0)}.get(det.get("type_hint"), (200, 200, 200))
        d.rectangle([x1, y1, x2, y2], outline=color, width=4 if k == target else 2)
        text = labels[k] if labels else f"#{k} {det.get('type_hint') or '?'} {det['score']:.2f}"
        tw = d.textlength(text, font=font)
        d.rectangle([x1, max(0, y1 - 18), x1 + tw + 4, y1], fill=color)
        d.text((x1 + 2, max(0, y1 - 17)), text, fill=(0, 0, 0), font=font)
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path, quality=88)


def _area(b) -> float:
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def _inside(inner, outer) -> float:
    """Доля площади inner, лежащая внутри outer."""
    ix = max(0.0, min(inner[2], outer[2]) - max(inner[0], outer[0]))
    iy = max(0.0, min(inner[3], outer[3]) - max(inner[1], outer[1]))
    return ix * iy / (_area(inner) + 1e-9)


def is_pole_like(box, size) -> bool:
    """Узкая рамка через пол-кадра — обычно столб, а не шкаф."""
    w, h = box[2] - box[0], box[3] - box[1]
    return h > 2.8 * w and h > 0.5 * size[1]


def expand_to_container(dets: list[dict], idx: int, size, contain=0.85, max_ratio=8.0) -> int:
    """Если рамка — деталь (решётка, дверца) внутри рамки шкафа, берём объемлющую рамку."""
    while True:
        b = dets[idx]["box"]
        cands = [j for j, d in enumerate(dets)
                 if j != idx and _area(b) < _area(d["box"]) <= max_ratio * _area(b)
                 and _inside(b, d["box"]) >= contain and not is_pole_like(d["box"], size)
                 and d["score"] >= 0.5 * dets[idx]["score"]]
        if not cands:
            return idx
        idx = min(cands, key=lambda j: _area(dets[j]["box"]))  # ближайший объемлющий


def clean_detections(dets: list[dict], size) -> list[dict]:
    """Для инференса без меток: убираем столбы и «групповые» рамки вокруг нескольких шкафов."""
    keep = []
    for i, d in enumerate(dets):
        if is_pole_like(d["box"], size):
            continue
        inner = [o["box"] for j, o in enumerate(dets)
                 if j != i and _area(o["box"]) < _area(d["box"]) and _inside(o["box"], d["box"]) >= 0.85]
        disjoint = any(_inside(a, b) < 0.3 and _inside(b, a) < 0.3
                       for k, a in enumerate(inner) for b in inner[k + 1:])
        if not disjoint:  # внутри два и более отдельных объекта — это группа, а не шкаф
            keep.append(d)
    return keep


def select_target(dets: list[dict], object_type: str, size=None) -> int | None:
    """Какая рамка соответствует метке снимка (метки у нас на уровне фото)."""
    if not dets:
        return None
    pool = [i for i in range(len(dets)) if size is None or not is_pole_like(dets[i]["box"], size)] \
        or list(range(len(dets)))
    same = [i for i in pool if dets[i]["type_hint"] == object_type]
    best = max(same or pool, key=lambda i: dets[i]["score"])
    return expand_to_container(dets, best, size) if size else best


def cmd_detect(a):
    data, out = Path(a.data), Path(a.out)
    rows = read_labels(data)
    det = Detector(a.detector, device_of(a.device), a.threshold)
    overrides = {}
    # ручная правка: {"<stem>": индекс рамки или [x1,y1,x2,y2]}; --overrides "" — без правок
    ov_path = Path(a.overrides) if a.overrides is not None else data / "target_overrides.json"
    if a.overrides != "" and ov_path.exists():
        overrides = {k: v for k, v in json.loads(ov_path.read_text(encoding="utf-8")).items()
                     if not k.startswith("_")}
        unknown = set(overrides) - {image_key(r["image"]) for r in rows}
        if unknown:
            print("! в target_overrides.json неизвестные снимки:", sorted(unknown))
    results, fallback = {}, []
    for i, r in enumerate(rows, 1):
        key = image_key(r["image"])
        img = load_image(data / r["image"])
        dets = det(img)
        tgt = select_target(dets, r["object_type"], img.size)
        ov = overrides.get(key)
        if isinstance(ov, int) and not isinstance(ov, bool):
            if not 0 <= ov < len(dets):
                raise SystemExit(f"target_overrides.json: {key}: индекс {ov} вне диапазона (рамок {len(dets)})")
            tgt = ov
        elif isinstance(ov, list):
            if len(ov) != 4:
                raise SystemExit(f"target_overrides.json: {key}: нужно [x1, y1, x2, y2]")
            dets.append({"box": ov, "score": 1.0, "query": "manual", "type_hint": r["object_type"]})
            tgt = len(dets) - 1
        if tgt is None or not any(d["type_hint"] == r["object_type"] for d in dets):
            fallback.append(key)
        target_box = dets[tgt]["box"] if tgt is not None else [0, 0, img.width, img.height]
        (out / "crops").mkdir(parents=True, exist_ok=True)
        crop_box(img, target_box).save(out / "crops" / f"{key}.jpg", quality=92)
        for k, d in enumerate(dets):
            crop_box(img, d["box"]).save(out / "crops" / f"{key}__{k}.jpg", quality=92)
        draw_preview(img, dets, tgt, out / "preview" / f"{key}.jpg")
        results[key] = {"image": r["image"], "size": list(img.size), "detections": dets, "target": tgt,
                        "target_source": "override" if ov is not None else "auto"}
        print(f"[{i}/{len(rows)}] {key}: {len(dets)} рамок, цель={tgt}")
    (out / "detections.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nГотово: {out}/detections.json, превью в {out}/preview")
    print(f"Без рамки нужного типа (проверьте глазами, при необходимости target_overrides.json): {len(fallback)}")
    for k in fallback:
        print("  -", k)


# ---------------------------------------------------------------- эмбеддинги

def _proj(out):
    """CLIP get_*_features: тензор в transformers 4.x, объект с pooler_output (= проекция) в 5.x."""
    return out if hasattr(out, "float") else out.pooler_output


class Embedder:
    def __init__(self, backbone: str, device):
        import torch
        from transformers import AutoImageProcessor, AutoModel, CLIPModel, CLIPProcessor
        self.device, self.torch = device, torch
        self.dino_proc = AutoImageProcessor.from_pretrained(DINO_MODELS[backbone])
        self.dino = AutoModel.from_pretrained(DINO_MODELS[backbone]).to(device).eval()
        self.clip_proc = CLIPProcessor.from_pretrained(CLIP_MODEL)
        self.clip = CLIPModel.from_pretrained(CLIP_MODEL).to(device).eval()

    def image(self, imgs: list[Image.Image]) -> dict[str, np.ndarray]:
        torch = self.torch
        with torch.no_grad():
            x = self.dino_proc(images=imgs, return_tensors="pt").to(self.device)
            hs = self.dino(**x).last_hidden_state
            dino = torch.cat([hs[:, 0], hs[:, 1:].mean(1)], dim=1)
            c = self.clip_proc(images=imgs, return_tensors="pt").to(self.device)
            clip = _proj(self.clip.get_image_features(**c))
        norm = lambda t: torch.nn.functional.normalize(t.float(), dim=-1).cpu().numpy()  # noqa: E731
        return {"dino": norm(dino), "clip": norm(clip)}

    def text(self, texts: list[str]) -> np.ndarray:
        torch = self.torch
        with torch.no_grad():
            t = self.clip_proc(text=texts, return_tensors="pt", padding=True).to(self.device)
            f = _proj(self.clip.get_text_features(**t))
        return torch.nn.functional.normalize(f.float(), dim=-1).cpu().numpy()


def embed_dataset(data: Path, det: Path, cache: Path, backbone: str, device, batch: int = 8):
    """Эмбеддинги целевых вырезов и целых кадров (для сравнения), с кешем."""
    cache_file = cache / f"emb_{backbone}.npz"
    rows = read_labels(data)
    keys = [image_key(r["image"]) for r in rows]
    import hashlib  # кеш привязан к содержимому вырезов: после нового detect он пересчитается
    h = hashlib.sha1()
    for k in keys:
        h.update(k.encode())
        h.update((det / "crops" / f"{k}.jpg").read_bytes())
    sig = h.hexdigest()
    if cache_file.exists():
        z = np.load(cache_file, allow_pickle=True)
        if list(z["keys"]) == keys and "sig" in z.files and str(z["sig"]) == sig:
            print(f"эмбеддинги из кеша {cache_file}")
            return rows, {k: z[k] for k in z.files if k not in ("keys", "sig")}
    emb = Embedder(backbone, device_of(device))
    feats = {f"{src}_{m}": [] for src in ("crop", "full") for m in ("dino", "clip")}
    for s in range(0, len(rows), batch):
        part = rows[s:s + batch]
        crops = [load_image(det / "crops" / f"{image_key(r['image'])}.jpg") for r in part]
        fulls = [load_image(data / r["image"]) for r in part]
        for src, imgs in (("crop", crops), ("full", fulls)):
            e = emb.image(imgs)
            for m in ("dino", "clip"):
                feats[f"{src}_{m}"].append(e[m])
        print(f"эмбеддинги {min(s + batch, len(rows))}/{len(rows)}")
    feats = {k: np.concatenate(v) for k, v in feats.items()}
    for task, (pos, neg) in CLIP_PROMPTS.items():
        feats[f"text_{task}_pos"] = emb.text(pos)
        feats[f"text_{task}_neg"] = emb.text(neg)
    cache.mkdir(parents=True, exist_ok=True)
    np.savez(cache_file, keys=np.array(keys), sig=np.array(sig), **feats)
    return rows, feats


def features(feats, src: str, kind: str) -> np.ndarray:
    if kind == "both":
        return np.concatenate([feats[f"{src}_dino"], feats[f"{src}_clip"]], axis=1)
    return feats[f"{src}_{kind}"]


def task_target(rows, task) -> np.ndarray:
    col = "object_type_bin" if task == "object_type" else task
    return np.array([r[col] for r in rows])


# ---------------------------------------------------------------- модели

def make_head(C: float = 0.5):
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    return make_pipeline(StandardScaler(), LogisticRegression(C=C, class_weight="balanced", max_iter=5000))


def loo_proba(X, y, C=0.5) -> np.ndarray:
    from sklearn.model_selection import LeaveOneOut
    p = np.zeros(len(y))
    for tr, te in LeaveOneOut().split(X):
        if len(set(y[tr])) < 2:
            p[te] = y[tr].mean()
            continue
        m = make_head(C).fit(X[tr], y[tr])
        p[te] = m.predict_proba(X[te])[:, 1]
    return p


def metrics(y, p, thr=0.5) -> dict:
    from sklearn.metrics import confusion_matrix, f1_score, precision_score, recall_score, roc_auc_score
    yhat = (p >= thr).astype(int)
    out = {"n": int(len(y)), "positives": int(y.sum()),
           "accuracy": round(float((yhat == y).mean()), 3),
           "recall": round(float(recall_score(y, yhat, zero_division=0)), 3),
           "precision": round(float(precision_score(y, yhat, zero_division=0)), 3),
           "f1": round(float(f1_score(y, yhat, zero_division=0)), 3),
           "confusion[[tn,fp],[fn,tp]]": confusion_matrix(y, yhat, labels=[0, 1]).tolist()}
    try:
        out["roc_auc"] = round(float(roc_auc_score(y, p)), 3)
    except ValueError:
        out["roc_auc"] = None
    return out


def clip_zero_shot(feats, src, task) -> np.ndarray:
    img = feats[f"{src}_clip"]
    pos, neg = feats[f"text_{task}_pos"].mean(0), feats[f"text_{task}_neg"].mean(0)
    logits = 100.0 * np.stack([img @ neg, img @ pos], axis=1)
    e = np.exp(logits - logits.max(1, keepdims=True))
    return e[:, 1] / e.sum(1)


def cmd_evaluate(a):
    data, det, out = Path(a.data), Path(a.det), Path(a.out)
    rows, feats = embed_dataset(data, det, out, a.backbone, a.device)
    report, per_image = {}, {image_key(r["image"]): {"class_dir": r["class_dir"]} for r in rows}
    for task, title in TASKS.items():
        y = task_target(rows, task)
        if task != "object_type" and y.sum() < MIN_POSITIVES:
            report[task] = {"skipped": f"всего {int(y.sum())} положительных примеров"}
            continue
        res = {"title": title}
        for src in ("crop", "full"):
            for kind in ("dino", "clip", "both"):
                p = loo_proba(features(feats, src, kind), y, a.C)
                res[f"{src}/{kind}"] = metrics(y, p)
                if src == "crop" and kind == a.features:
                    for r, pi in zip(rows, p):
                        per_image[image_key(r["image"])][task] = round(float(pi), 3)
            if task in CLIP_PROMPTS:
                res[f"{src}/clip_zero_shot"] = metrics(y, clip_zero_shot(feats, src, task))
        report[task] = res
    det_json = json.loads((det / "detections.json").read_text(encoding="utf-8"))
    hint_ok = [d["target"] is not None and d["detections"][d["target"]]["type_hint"] == r["object_type"]
               for r, d in ((r, det_json[image_key(r["image"])]) for r in rows)]
    report["detector_type_hint_accuracy"] = round(float(np.mean(hint_ok)), 3)
    out.mkdir(parents=True, exist_ok=True)
    (out / "metrics.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "loo_predictions.json").write_text(json.dumps(per_image, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\nLeave-one-out, {len(rows)} снимков. Колонки: AUC / recall / precision")
    print(f"zero-shot тип от детектора: точность {report['detector_type_hint_accuracy']}")
    for task, res in report.items():
        if not isinstance(res, dict):
            continue
        if "skipped" in res:
            print(f"\n{task}: пропущено ({res['skipped']})")
            continue
        print(f"\n{task} — {res['title']}")
        for k, m in res.items():
            if isinstance(m, dict):
                print(f"  {k:22s} {m['roc_auc']!s:>6} / {m['recall']:.2f} / {m['precision']:.2f}")
    print(f"\nПодробно: {out}/metrics.json; ошибки по снимкам: {out}/loo_predictions.json")


def cmd_train(a):
    """Модель v2: мульти-разрешение + ансамбль с zero-shot CLIP; пороги — из cv_metrics.json (полнота 90%)."""
    import joblib
    data, det, out, cache = Path(a.data), Path(a.det), Path(a.out), Path(a.cache)
    rows, feats = embed_dataset(data, det, cache, a.backbone, a.device)
    multi = embed_multires(data, det, cache, a.backbone, a.device, tuple(a.sizes))
    views = [{"dino": feats["crop_dino"], "clip": feats["crop_clip"]}, *multi.values()]
    X = np.concatenate([_X(v, a.features) for v in views])
    Cl = np.concatenate([v["clip"] for v in views])
    text = text_pairs(feats)
    tasks = {}
    for task in TASKS:
        y = task_target(rows, task)
        if task != "object_type" and y.sum() < MIN_POSITIVES:
            print(f"{task}: пропуск, мало примеров ({int(y.sum())})")
            continue
        zs = text.get(task) if task in ENSEMBLE_TASKS else None
        tasks[task] = fit_task(X, Cl, np.concatenate([y] * len(views)), zs, a.C)
        print(f"{task}: обучено на {len(y)} снимках x {len(views)} разрешений ({int(y.sum())} положительных)"
              + (" + zero-shot CLIP" if zs is not None else ""))
    thresholds = {}
    cv_file = cache / "cv_metrics.json"
    if cv_file.exists():
        thresholds = {t: m["threshold"] for t, m in json.loads(cv_file.read_text(encoding="utf-8"))["thresholds"].items()}
        print("пороги (полнота 90% по групповой CV):", thresholds)
    else:
        print("! нет cv_metrics.json — пороги 0.5 (сначала запустите: python solution.py cv)")
    out.mkdir(parents=True, exist_ok=True)
    joblib.dump({"version": 2, "tasks": tasks, "thresholds": thresholds, "backbone": a.backbone,
                 "features": a.features, "detector": a.detector, "threshold": a.threshold}, out / "heads.joblib")
    print(f"сохранено: {out}/heads.joblib")


# ---------------------------------------------------------------- инференс

# Приоритет объекта (1 — самый срочный) -> статус сервиса, подпись, рекомендация.
# Критерии взяты из разметки кейса: крепление > МП > коррозия > нет дефекта.
PRIORITY = {
    1: {"name": "Критический", "status": "urgent",
        "recommendation": "Немедленный выезд: нарушено крепление, угроза падения шкафа. "
                          "Оградить место, восстановить крепление или демонтировать шкаф."},
    2: {"name": "Высокий", "status": "urgent",
        "recommendation": "Ремонт или замена корпуса/двери в ближайший выезд бригады: "
                          "механическое повреждение, нарушена защита оболочки."},
    3: {"name": "Средний", "status": "review",
        "recommendation": "Плановая антикоррозийная обработка и окраска корпуса."},
    4: {"name": "Нет", "status": "normal", "recommendation": None},
}
DEFECT_NAMES = {"mp_mount": "Нарушение крепления", "defect_mp": "Механическое повреждение",
                "defect_lkp": "Коррозия / повреждение ЛКП", "defect_any": "Дефект (тип не определён)"}
DEFECT_LEVEL = {"mp_mount": 1, "defect_mp": 2, "defect_lkp": 3, "defect_any": 3}
LEVEL_WEIGHT = {1: 1.0, 2: 0.75, 3: 0.5, 4: 0.0}
UNCERTAIN_REC = "Осмотреть при ближайшем выезде: модель не уверена в состоянии объекта."
UNSPECIFIED_REC = "Осмотреть при ближайшем выезде: есть признаки дефекта, тип не определён."
STATUS_RANK = {"urgent": 0, "review": 1, "normal": 2}
# «Срочно» = внеплановый выезд, он дороже осмотра: туда только при p >= 0.5. Между порогом полноты
# и 0.5 — «На проверку» (бригада посмотрит при ближайшем выезде), полнота отправки на проверку сохраняется.
URGENT_MIN = 0.5
STATUS_NAMES = {"urgent": "Срочно", "review": "На проверку", "normal": "Без замечаний"}
VERDICT_NAMES = {"ok": "В норме", "defect": "Повреждён", "unknown": "Требует проверки"}


def assess(p: dict, thr: dict | None = None) -> dict:
    """Вероятности -> вердикт, приоритет, статус сервиса, рекомендация.
    thr — пороги по задачам (подобраны на полноту 90%); уверенно, если p >= (1 + порог) / 2;
    сомнение, если p > порог / 2."""
    thr = {t: (thr or {}).get(t, 0.5) for t in ("mp_mount", "defect_mp", "defect_lkp", "defect_any")}
    found = [t for t in ("mp_mount", "defect_mp", "defect_lkp") if p.get(t, 0) >= thr[t]]
    if not found and p.get("defect_any", 0) >= thr["defect_any"]:
        found = ["defect_any"]
    found.sort(key=lambda t: (DEFECT_LEVEL[t], -p[t]))
    level = DEFECT_LEVEL[found[0]] if found else 4
    conf = p[found[0]] if found else 1 - max(p.get(t, 0) for t in ("defect_any", "defect_lkp", "defect_mp"))
    pr = PRIORITY[level]
    status, rec = pr["status"], pr["recommendation"]
    if found == ["defect_any"]:
        rec = UNSPECIFIED_REC
    if status == "urgent" and conf < URGENT_MIN:
        status = "review"
        rec = f"Осмотреть при ближайшем выезде: возможно — {DEFECT_NAMES[found[0]].lower()}."
    if found:
        verdict = "defect" if conf >= (1 + thr[found[0]]) / 2 else "unknown"
    else:
        doubt = any(p.get(t, 0) > thr[t] / 2 for t in ("defect_any", "defect_lkp", "defect_mp"))
        verdict = "unknown" if doubt else "ok"
        if doubt:
            status, rec = "review", UNCERTAIN_REC
    return {
        "verdict": verdict, "status": status, "priority_level": level, "priority_name": pr["name"],
        "defect": DEFECT_NAMES[found[0]] if found else None,
        "defects": [DEFECT_NAMES[t] for t in found],
        "defect_score": round(float(p.get(found[0], p.get("defect_any", 0)) if found else p.get("defect_any", 0)), 3),
        "severity": round(LEVEL_WEIGHT[level] * float(conf), 3),  # «оценка опасности» для сортировки
        "recommendation": rec,
    }


class Analyzer:
    """Детектор + эмбеддер + головы, загружаются один раз. Выход — контракт сервиса (docs/operator-contract.md)."""

    def __init__(self, models="models", device=None, detector=None, threshold=None):
        import joblib
        self.bundle = joblib.load(Path(models) / "heads.joblib")
        dev = device_of(device)
        self.det = Detector(detector or self.bundle["detector"], dev, threshold or self.bundle["threshold"])
        self.emb = Embedder(self.bundle["backbone"], dev)
        self.model_name = f"{self.det.kind}+{self.bundle['backbone']}+clip-l14/logreg"

    def frame(self, img: Image.Image, frame_id: str, next_id):
        w, h = img.size
        dets = clean_detections(self.det(img), img.size)
        frame = {"frame_id": frame_id, "detections": []}
        objects, labels = [], []
        if dets:
            e = self.emb.image([crop_box(img, d["box"]) for d in dets])
            f = self.bundle["features"]
            X = np.concatenate([e["dino"], e["clip"]], 1) if f == "both" else e[f]
            for k, d in enumerate(dets):
                if "tasks" in self.bundle:  # v2: ансамбль голова + zero-shot CLIP
                    probs = {t: float(task_proba(m, X[k:k + 1], e["clip"][k:k + 1])[0])
                             for t, m in self.bundle["tasks"].items()}
                else:
                    probs = {t: float(m.predict_proba(X[k:k + 1])[0, 1]) for t, m in self.bundle["heads"].items()}
                p_tksh = probs.pop("object_type", 0.5)
                cls = "TKSH" if p_tksh >= 0.5 else "RSH"
                a = assess(probs, self.bundle.get("thresholds"))
                det_id, obj_id = f"{frame_id}#{k}", next_id()
                x1, y1, x2, y2 = d["box"]
                bw, bh = (x2 - x1) / w, (y2 - y1) / h
                frame["detections"].append({
                    "det_id": det_id, "object_id": obj_id, "class": cls, "score": round(d["score"], 4),
                    "bbox": [round(min(max((x1 + x2) / 2 / w, 0), 1), 5), round(min(max((y1 + y2) / 2 / h, 0), 1), 5),
                             round(min(bw, 1), 5), round(min(bh, 1), 5)],  # YOLO: центр x, центр y, ширина, высота
                    "defect": a["defect"], "defect_score": a["defect_score"],
                    "inference": {"model_name": self.model_name, "label": f"{OBJECT_NAMES[cls]} · P{a['priority_level']}",
                                  "severity": a["severity"], "recommendation": a["recommendation"]},
                })
                objects.append({
                    "object_id": obj_id, "class": cls, "verdict": a["verdict"], "status": a["status"],
                    "priority_level": a["priority_level"], "priority_name": a["priority_name"],
                    "defect": a["defect"], "defects": a["defects"], "defect_score": a["defect_score"],
                    "severity": a["severity"], "recommendation": a["recommendation"],
                    "type_score": round(max(p_tksh, 1 - p_tksh), 3), "scores": {t: round(v, 3) for t, v in probs.items()},
                    "observations": [det_id], "best_det_id": det_id,
                })
                labels.append(f"{OBJECT_NAMES[cls]} P{a['priority_level']} {a['defect'] or VERDICT_NAMES[a['verdict']]}")
        return frame, objects, dets, labels

    def analyze(self, items, progress=None, annotate_dir: Path | None = None) -> dict:
        """items: [(frame_id, путь к фото)] -> {"frames": [...], "objects": [...]}."""
        frames, objects, counter = [], [], iter(range(1, 10 ** 9))
        next_id = lambda: f"OBJ-{next(counter):04d}"  # noqa: E731
        for n, (frame_id, path) in enumerate(items, 1):
            img = load_image(Path(path))
            fr, objs, dets, labels = self.frame(img, frame_id, next_id)
            frames.append(fr)
            objects += objs
            if annotate_dir:
                draw_preview(img, dets, None, Path(annotate_dir) / f"{Path(frame_id).stem}.jpg", labels or None)
            print(f"[{n}/{len(items)}] {frame_id}: {len(dets)} объектов")
            if progress:
                progress(int(100 * n / len(items)))
        objects.sort(key=lambda o: (STATUS_RANK[o["status"]], o["priority_level"], -o["severity"],
                                    -(o["defect_score"] or 0)))  # как сортирует реестр сервиса
        return {"frames": frames, "objects": objects}


REPORT_FIELDS = ["priority_level", "priority_name", "status", "verdict", "object_id", "class", "frame_id",
                 "defect", "defects", "defect_score", "severity", "recommendation", "bbox_cxcywh"]


def write_report(result: dict, path: Path):
    """Таблица для бригады: объекты по приоритету, человекочитаемые поля."""
    det = {d["det_id"]: (f["frame_id"], d) for f in result["frames"] for d in f["detections"]}
    with open(path, "w", newline="", encoding="utf-8-sig") as f:  # BOM — чтобы Excel открыл кириллицу
        wr = csv.DictWriter(f, REPORT_FIELDS, delimiter=";")
        wr.writeheader()
        for o in result["objects"]:
            frame_id, d = det[o["best_det_id"]]
            wr.writerow({"priority_level": o["priority_level"], "priority_name": o["priority_name"],
                         "status": STATUS_NAMES[o["status"]], "verdict": VERDICT_NAMES[o["verdict"]],
                         "object_id": o["object_id"], "class": OBJECT_NAMES[o["class"]], "frame_id": frame_id,
                         "defect": o["defect"] or "", "defects": ", ".join(o["defects"]),
                         "defect_score": o["defect_score"], "severity": o["severity"],
                         "recommendation": o["recommendation"] or "", "bbox_cxcywh": " ".join(map(str, d["bbox"]))})


def cmd_predict(a):
    root = Path(a.images)
    paths = sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"})
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    result = Analyzer(a.models, a.device, a.detector, a.threshold).analyze(
        [(p.relative_to(root).as_posix(), p) for p in paths], annotate_dir=out / "annotated")
    (out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    write_report(result, out / "report.csv")
    from collections import Counter
    c = Counter(o["priority_level"] for o in result["objects"])
    print(f"\nобъектов {len(result['objects'])}: " + ", ".join(f"P{k} {PRIORITY[k]['name']} — {c[k]}" for k in sorted(PRIORITY)))
    print(f"результат: {out}/result.json, таблица: {out}/report.csv, картинки: {out}/annotated")


# ---------------------------------------------------------------- устойчивость к разрешению

def downscale(img: Image.Image, side: int, jpeg_quality: int = 85):
    """Уменьшить до длинной стороны side (+ пересжатие JPEG, как у реальных камер). 0 — исходник."""
    if not side or max(img.size) <= side:
        return img, 1.0
    f = side / max(img.size)
    im = img.resize((max(1, round(img.width * f)), max(1, round(img.height * f))), Image.BICUBIC)
    import io
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=jpeg_quality)
    buf.seek(0)
    return Image.open(buf).convert("RGB"), f


def _iou(a, b) -> float:
    inter = _inside(a, b) * _area(a)
    return inter / (_area(a) + _area(b) - inter + 1e-9)


def cmd_robustness(a):
    """Качество в зависимости от разрешения фото: детекция (попадание в эталонную рамку) и
    классификация (LOO: обучение на исходниках или на нескольких разрешениях, проверка на уменьшенных)."""
    data, det_dir, out = Path(a.data), Path(a.det), Path(a.out)
    rows = read_labels(data)
    det_json = json.loads((det_dir / "detections.json").read_text(encoding="utf-8"))
    sizes = a.sizes
    dev = device_of(a.device)
    emb = Embedder(a.backbone, dev)
    detector = None if a.no_detect else Detector(a.detector, dev, a.threshold)
    crops = {s: [] for s in sizes}
    crop_side = {s: [] for s in sizes}
    hits = {s: [] for s in sizes}
    for i, r in enumerate(rows, 1):
        key = image_key(r["image"])
        d = det_json[key]
        gt = d["detections"][d["target"]]["box"]
        img = load_image(data / r["image"])
        for s in sizes:
            im, f = downscale(img, s)
            box = [v * f for v in gt]
            c = crop_box(im, box)
            crops[s].append(c)
            crop_side[s].append(min(c.size))
            if detector:
                dets = detector(im)
                t = select_target(dets, r["object_type"], im.size)
                hits[s].append(t is not None and _iou(dets[t]["box"], box) >= 0.5)
        print(f"[{i}/{len(rows)}] {key}")
    feats = {}
    for s in sizes:
        parts = [emb.image(crops[s][j:j + 8]) for j in range(0, len(rows), 8)]
        e = {m: np.concatenate([p[m] for p in parts]) for m in ("dino", "clip")}
        feats[s] = np.concatenate([e["dino"], e["clip"]], 1) if a.features == "both" else e[a.features]
    base = sizes[0]
    report = {"sizes": sizes, "features": a.features,
              "median_crop_min_side_px": {str(s): int(np.median(crop_side[s])) for s in sizes}}
    if detector:
        report["detection_hit_rate"] = {str(s): round(float(np.mean(hits[s])), 3) for s in sizes}
    tasks = [t for t in TASKS if t != "mp_mount"]
    for task in tasks:
        y = task_target(rows, task)
        res = {}
        for mode in ("train_full", "train_multires"):
            for s in sizes:
                p = np.zeros(len(y))
                for i in range(len(y)):
                    tr = np.array([j for j in range(len(y)) if j != i])
                    if mode == "train_full":
                        Xtr, ytr = feats[base][tr], y[tr]
                    else:
                        Xtr = np.concatenate([feats[ss][tr] for ss in sizes])
                        ytr = np.concatenate([y[tr]] * len(sizes))
                    p[i] = make_head(a.C).fit(Xtr, ytr).predict_proba(feats[s][i:i + 1])[0, 1]
                res[f"{mode}/{s or 'orig'}"] = metrics(y, p)
        report[task] = res
    out.mkdir(parents=True, exist_ok=True)
    (out / "resolution_metrics.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    names = [str(s or "исходник") for s in sizes]
    print("\nДлинная сторона фото:     " + " ".join(f"{n:>9s}" for n in names))
    print("медиана мин. стороны выреза" + "".join(f"{report['median_crop_min_side_px'][str(s)]:>9d}" for s in sizes))
    if detector:
        print("детекция: попадание       " + "".join(f"{report['detection_hit_rate'][str(s)]:>9.2f}" for s in sizes))
    for task in tasks:
        for mode, title in (("train_full", "обуч. на исходниках"), ("train_multires", "обуч. мульти-разреш.")):
            print(f"{task:11s} AUC {title:20s}" + "".join(
                f"{report[task][mode + '/' + str(s or 'orig')]['roc_auc']:>9.3f}" for s in sizes))
    print(f"\nподробно: {out}/resolution_metrics.json")


# ---------------------------------------------------------------- модель v2: группы, ансамбль, пороги

ZS_TASKS = ("defect_any", "defect_lkp", "defect_mp")  # где есть промпты zero-shot CLIP
# Ансамбль только там, где zero-shot CLIP силён сам по себе (групповая CV: ЛКП 0.91; МП 0.57 — портит голову).
ENSEMBLE_TASKS = ("defect_lkp",)
TARGET_RECALL = 0.9  # пропуск повреждения дороже лишнего выезда


def image_groups(rows) -> np.ndarray:
    """Почти одинаковые снимки одного объекта имеют соседние номера файлов (35453688/89, 42123333/34...).
    Объединяем номера с разницей <= 30 в группу, чтобы они не попадали одновременно в обучение и проверку."""
    nums = []
    for r in rows:
        digits = "".join(ch for ch in Path(r["original_name"]).stem if ch.isdigit())
        nums.append(int(digits) if digits else -1)
    order = np.argsort(nums)
    groups, g, prev = np.zeros(len(rows), int), 0, None
    for i in order:
        if prev is not None and (nums[i] < 0 or nums[i] - prev > 30):
            g += 1
        groups[i], prev = g, nums[i]
    return groups


def zs_logit(clip: np.ndarray, pos: np.ndarray, neg: np.ndarray) -> np.ndarray:
    return 100.0 * (clip @ pos - clip @ neg)


def fit_task(X, clip, y, text=None, C=0.5) -> dict:
    """Голова (logreg) + при наличии промптов zero-shot CLIP с калибровкой Platt; итог — среднее вероятностей."""
    from sklearn.linear_model import LogisticRegression
    m = {"head": make_head(C).fit(X, y)}
    if text is not None:
        d = zs_logit(clip, *text)[:, None]
        m["text"], m["platt"] = text, LogisticRegression().fit(d, y)
    return m


def task_proba(m: dict, X, clip, mode="ensemble") -> np.ndarray:
    p_head = m["head"].predict_proba(X)[:, 1]
    if "platt" not in m or mode == "head":
        return p_head
    p_zs = m["platt"].predict_proba(zs_logit(clip, *m["text"])[:, None])[:, 1]
    return p_zs if mode == "zeroshot" else (p_head + p_zs) / 2


def threshold_for_recall(y, p, recall=TARGET_RECALL) -> float:
    """Наибольший порог, при котором полнота по классу 1 не ниже заданной."""
    pos = np.sort(p[y == 1])
    k = int(np.floor((1 - recall) * len(pos)))
    return float(min(0.5, pos[k] - 1e-6)) if len(pos) else 0.5


def text_pairs(feats) -> dict:
    return {t: (feats[f"text_{t}_pos"].mean(0), feats[f"text_{t}_neg"].mean(0)) for t in ZS_TASKS}


def embed_multires(data: Path, det: Path, cache: Path, backbone: str, device, sizes=(1024, 512)) -> dict:
    """Эмбеддинги эталонных вырезов из уменьшенных фото (аугментация и проверка устойчивости)."""
    rows = read_labels(data)
    det_json = json.loads((det / "detections.json").read_text(encoding="utf-8"))
    sig = __import__("hashlib").sha1(json.dumps(
        [det_json[image_key(r["image"])]["detections"][det_json[image_key(r["image"])]["target"]]["box"]
         for r in rows]).encode()).hexdigest()
    out, todo = {}, []
    for s in sizes:
        f = cache / f"emb_{backbone}_{s}px.npz"
        if f.exists() and str(np.load(f)["sig"]) == sig:
            z = np.load(f)
            out[s] = {"dino": z["dino"], "clip": z["clip"]}
        else:
            todo.append(s)
    if todo:
        emb = Embedder(backbone, device_of(device))
        crops = {s: [] for s in todo}
        for r in rows:
            d = det_json[image_key(r["image"])]
            gt = d["detections"][d["target"]]["box"]
            img = load_image(data / r["image"])
            for s in todo:
                im, k = downscale(img, s)
                crops[s].append(crop_box(im, [v * k for v in gt]))
        cache.mkdir(parents=True, exist_ok=True)
        for s in todo:
            parts = [emb.image(crops[s][j:j + 8]) for j in range(0, len(rows), 8)]
            out[s] = {m: np.concatenate([p[m] for p in parts]) for m in ("dino", "clip")}
            np.savez(cache / f"emb_{backbone}_{s}px.npz", sig=np.array(sig), **out[s])
            print(f"эмбеддинги вырезов {s}px готовы")
    return out


def _X(d: dict, kind: str) -> np.ndarray:
    return np.concatenate([d["dino"], d["clip"]], 1) if kind == "both" else d[kind]


def cmd_cv(a):
    """Честная оценка: групповая CV, голова / zero-shot / ансамбль, обучение на исходниках или мульти-разрешении,
    проверка на исходных и уменьшенных вырезах, порог на полноту 90%."""
    from sklearn.model_selection import LeaveOneGroupOut
    data, det, out = Path(a.data), Path(a.det), Path(a.out)
    rows, feats = embed_dataset(data, det, out, a.backbone, a.device)
    sizes = tuple(a.sizes)
    multi = embed_multires(data, det, out, a.backbone, a.device, sizes)
    groups = image_groups(rows)
    text = text_pairs(feats)
    views = {"orig": {"dino": feats["crop_dino"], "clip": feats["crop_clip"]}, **{f"{s}px": multi[s] for s in sizes}}
    report = {"n_images": len(rows), "n_groups": int(groups.max() + 1), "target_recall": TARGET_RECALL}
    print(f"{len(rows)} снимков, {report['n_groups']} групп (почти одинаковые снимки одного объекта — в одной группе)")
    oof_store = {}
    for task in [t for t in TASKS if t != "mp_mount"]:
        y = task_target(rows, task)
        res = {}
        modes = ("head", "zeroshot", "ensemble") if task in ZS_TASKS else ("head",)
        for train_mode in ("orig", "multires"):
            p = {(mode, v): np.zeros(len(y)) for mode in modes for v in views}
            tv = ["orig"] if train_mode == "orig" else list(views)
            for tr, te in LeaveOneGroupOut().split(rows, y, groups):  # одна модель на фолд, режимы — из неё
                Xtr = np.concatenate([_X({k: views[v][k][tr] for k in ("dino", "clip")}, a.features) for v in tv])
                Ctr = np.concatenate([views[v]["clip"][tr] for v in tv])
                m = fit_task(Xtr, Ctr, np.concatenate([y[tr]] * len(tv)), text.get(task), a.C)
                for v in views:
                    Xte = _X({k: views[v][k][te] for k in ("dino", "clip")}, a.features)
                    for mode in modes:
                        p[(mode, v)][te] = task_proba(m, Xte, views[v]["clip"][te], mode)
            for mode in modes:
                for v in views:
                    res[f"{train_mode}/{mode}/{v}"] = metrics(y, p[(mode, v)])
                oof_store[(task, train_mode, mode)] = p[(mode, "orig")]
        report[task] = res
    # порог на полноту 90% для итоговой конфигурации (мульти-разрешение + ансамбль), подбирается по OOF
    best_mode = lambda t: "ensemble" if t in ENSEMBLE_TASKS else "head"  # noqa: E731
    report["thresholds"] = {}
    for task in [t for t in TASKS if t not in ("mp_mount", "object_type")]:
        y = task_target(rows, task)
        p = oof_store[(task, "multires", best_mode(task))]
        thr = threshold_for_recall(y, p)
        report["thresholds"][task] = {"threshold": round(thr, 3), **metrics(y, p, thr)}
    out.mkdir(parents=True, exist_ok=True)
    (out / "cv_metrics.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    vs = list(views)
    print("\nГрупповая CV, AUC. Столбцы — на чём проверяем: " + ", ".join(vs))
    for task in [t for t in TASKS if t != "mp_mount"]:
        print(task)
        for k in sorted({k.rsplit("/", 1)[0] for k in report[task]}):
            print(f"  {k:22s}" + "".join(f"{report[task][k + '/' + v]['roc_auc']:>8.3f}" for v in vs))
    print("\nПорог на полноту >= 90% (мульти-разрешение; ансамбль только для ЛКП; OOF):")
    for t, m in report["thresholds"].items():
        print(f"  {t:12s} порог {m['threshold']:.3f}  recall {m['recall']:.2f}  precision {m['precision']:.2f}")
    print(f"\nподробно: {out}/cv_metrics.json")


# ---------------------------------------------------------------- CLI

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p, det_args=True):
        p.add_argument("--device", default=None, help="cuda / cpu (по умолчанию cuda, если есть)")
        if det_args:
            p.add_argument("--detector", choices=["owlv2", "gdino"], default="owlv2")
            p.add_argument("--threshold", type=float, default=None)

    p = sub.add_parser("detect")
    p.add_argument("--data", default="data")
    p.add_argument("--out", default="runs/det")
    p.add_argument("--overrides", default=None,
                   help='файл ручных правок (по умолчанию <data>/target_overrides.json; "" — без правок)')
    common(p)

    for name in ("evaluate", "train", "cv"):
        p = sub.add_parser(name)
        p.add_argument("--data", default="data")
        p.add_argument("--det", default="runs/det")
        p.add_argument("--out", default="models" if name == "train" else "runs/eval")
        p.add_argument("--cache", default="runs/eval")
        p.add_argument("--backbone", choices=list(DINO_MODELS), default="dinov2-base")
        p.add_argument("--features", choices=["dino", "clip", "both"], default="both")
        p.add_argument("--C", type=float, default=0.5)
        p.add_argument("--sizes", type=int, nargs="+", default=[1024, 512],
                       help="(train, cv) длинная сторона уменьшенных копий для мульти-разрешения")
        common(p)

    p = sub.add_parser("robustness", help="качество в зависимости от разрешения фото")
    p.add_argument("--data", default="data")
    p.add_argument("--det", default="runs/det")
    p.add_argument("--out", default="runs/robust")
    p.add_argument("--sizes", type=int, nargs="+", default=[0, 1600, 1024, 768, 512, 384],
                   help="длинная сторона в px; 0 — исходник (должен идти первым)")
    p.add_argument("--backbone", choices=list(DINO_MODELS), default="dinov2-base")
    p.add_argument("--features", choices=["dino", "clip", "both"], default="both")
    p.add_argument("--C", type=float, default=0.5)
    p.add_argument("--no-detect", action="store_true")
    common(p)

    p = sub.add_parser("predict")
    p.add_argument("--images", required=True)
    p.add_argument("--models", default="models")
    p.add_argument("--out", default="runs/pred")
    p.add_argument("--device", default=None)
    p.add_argument("--detector", choices=["owlv2", "gdino"], default=None)
    p.add_argument("--threshold", type=float, default=None)

    a = ap.parse_args()
    if getattr(a, "threshold", "x") is None and a.cmd != "predict":
        a.threshold = 0.15 if a.detector == "owlv2" else 0.3
    {"detect": cmd_detect, "evaluate": cmd_evaluate, "train": cmd_train, "predict": cmd_predict,
     "robustness": cmd_robustness, "cv": cmd_cv}[a.cmd](a)


if __name__ == "__main__":
    main()
