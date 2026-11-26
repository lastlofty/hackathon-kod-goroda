# MGTS dataset preparation (stage 1)

Run from repository root. Keep ZIPs, generated dataset and virtual environment
outside the repository and Docker build context. Do not publish dataset or
reports without authorization from MGTS.

```bash
python3 -m venv ~/Projects/.venv-mgts-data
source ~/Projects/.venv-mgts-data/bin/activate
python -m pip install -r ml/data/requirements.txt
python ml/data/prepare.py \
  ~/Downloads/doc-1795639519.zip ~/Downloads/doc-1795639569.zip \
  --out ~/Projects/mgts-data/v1
```

The output directory must not exist. `images/` preserves original bytes under
stable IDs; `manifest.json` contains provenance and image-level labels, and
`validation.json` lists counts, byte-identical duplicates and filename collisions.
`asset_review.csv` is a worksheet for manual physical-object grouping.

Folder categories represent primary image-level labels, not exhaustive defect
labels. Excel descriptions remain unchanged. Bounding boxes, asset grouping
and geographic coordinates are unset (EXIF GPS is not imported; source images
may still contain it). No training/test split is generated. Image dimensions are
stored before EXIF rotation; apply orientation consistently when annotating.
Review visually similar photographs and possible repeated assets before creating
splits. Unannotated images must not be treated as negative training examples.

For the supplied two archives the expected counts are 62 images, 61 annotated,
1 unannotated, and 6 labelled folder categories.
