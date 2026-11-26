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

## Stage 2: physical asset review

```bash
python ml/data/review_assets.py ~/Projects/mgts-data/v1
open ~/Projects/mgts-data/v1/review/index.html # macOS
```

Review all images and candidate pairs. The local HTML and CSV contain only
heuristic candidates (64-bit dHash Hamming distance, two nearest neighbors
per image and identical filenames/bytes); they do not prove identity and can
miss repeated objects from different viewpoints. Use `asset_review.csv` to
record physical asset groups and review notes, including uncertainty. Keep
suspected related samples together or exclude ambiguous samples from evaluation.
Do not overwrite the manifest or create splits until groups are reviewed.
The report has no external dependencies and does not modify source data.
Keep generated reports and photos outside Git. Existing review output is never
overwritten; rename it if a rerun is necessary.
