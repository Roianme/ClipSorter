# Agent Instruction: Subject Detection QC Rewrite

## Branch
Work on branch `feature/subject-detection-qc`. Do not touch `main`.

---

## Goal
Simplify the photo QC pipeline. Remove all pixel-quality checks. Replace with two checks only:

1. **Motion blur detection** — reject if image is too blurry to see a subject
2. **Subject detection (YOLO)** — reject if no person or object is detected. This is the primary check.

---

## Remove These Checks Entirely
Delete all logic and config keys related to:

- `contrast_threshold`
- `exposure_low_threshold`
- `exposure_high_threshold`
- `exposure_reject_ratio`
- `exposure_review_ratio`
- `content_variance_threshold`
- `saturation_threshold`
- `saturation_reject_ratio`
- `histogram_entropy_threshold`
- `histogram_entropy_reject`

---

## Keep These Checks
Do not remove or modify:

- `blur_threshold: 60.0`
- `blur_reject_ratio: 0.6`
- `shake_threshold: 30.0`
- Duplicate detection
- Burst detection
- Audio checks

---

## Add to config.json

```json
"subject_detection_enabled": true,
"subject_detection_model": "yolov8n",
"subject_detection_min_confidence": 0.35,
"subject_detection_classes": ["person", "face"],
"subject_detection_fallback_classes": ["chair", "table", "laptop", "microphone"],
"subject_detection_min_area_ratio": 0.01
```

---

## Decision Logic — Implement in qc_photo.py

```
IMAGE IN
   │
   ├─ Motion blur > threshold? ──────────────────→ DEFECT
   │
   ↓ pass
   │
   ├─ YOLO: person or face detected
   │  with confidence >= 0.35?   ──────────────→ USABLE
   │
   ↓ no
   │
   ├─ YOLO: fallback object detected
   │  (chair, table, laptop, mic)?  ──────────→ REVIEW
   │
   ↓ no
   │
   └─ Nothing detected  ────────────────────────→ DEFECT
```

---

## Files to Update

### `config.json`
- Remove all keys listed in the **Remove** section above
- Add all keys listed in the **Add to config.json** section above

### `src/config_loader.py`
- Remove defaults and validation for old exposure/contrast/entropy/saturation keys
- Add defaults and validation for all new `subject_detection_*` keys

### `src/qc_photo.py`
- Remove all exposure, contrast, entropy, and saturation logic
- Implement YOLO subject detection using the `ultralytics` library
- Install dependency: `pip install ultralytics`
- Model (`yolov8n`) downloads automatically on first run

### `src/classifier.py`
- Update result classification to handle the new `review` state produced by fallback object detection

### `tests/test_qc_photo.py`
- Remove all exposure and contrast tests
- Add the following test cases:
  - No subject detected → `defect`
  - Person detected → `usable`
  - Fallback object detected, no person → `review`
  - Blurry image with no subject → `defect`
  - Underexposed image with person detected → `usable`

---

## Important Notes

> **Exposure is no longer a rejection criterion.**
> Underexposed or overexposed photos that have a visible subject must pass as `usable`. Do not penalize for lighting.

> **Wide crowd shots must pass.**
> Use `subject_detection_min_area_ratio: 0.01` so even small detected persons in wide shots are counted as valid subjects.

> **Use yolov8n (nano) for speed.**
> It is the smallest and fastest YOLO model. Accuracy is sufficient for people/event photography. The model downloads automatically via `ultralytics` on first run — no manual setup needed.

> **Run the full test suite after changes.**
> ```bash
> python -m pytest tests/ -v
> ```

---

## Summary of Outcome

| Scenario | Old Result | New Result |
|---|---|---|
| Underexposed but has person | defect / review | **usable** |
| Plain gray / no subject | usable (bug) | **defect** |
| Motion streak / no subject | usable (bug) | **defect** |
| Blurry, no subject | defect | **defect** |
| Sharp crowd shot | usable | **usable** |
| Fallback object only | varies | **review** |