"""Photo quality checks: blur and subject detection."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from ultralytics import YOLO

from qc_video import QCResult, _laplacian_variance_gray

logger = logging.getLogger(__name__)

_YOLO_MODELS: dict[str, YOLO] = {}


def _load_yolo_model(model_name: str) -> YOLO:
    model_name = str(model_name)
    model = _YOLO_MODELS.get(model_name)
    if model is None:
        model = YOLO(model_name)
        _YOLO_MODELS[model_name] = model
    return model


def _subject_detection_status(frame: np.ndarray, config: dict[str, Any]) -> tuple[str, list[str]]:
    if not bool(config.get("subject_detection_enabled", True)):
        return "pass", []

    model_name = config["subject_detection_model"]
    min_confidence = float(config["subject_detection_min_confidence"])
    subject_classes = {str(item).lower() for item in config["subject_detection_classes"]}
    fallback_classes = {str(item).lower() for item in config["subject_detection_fallback_classes"]}
    min_area_ratio = float(config["subject_detection_min_area_ratio"])

    model = _load_yolo_model(model_name)
    results = model.predict(frame, conf=min_confidence, verbose=False)
    if not results:
        return "rejected", ["Subject detection failed to produce results"]

    result = results[0]
    boxes = result.boxes
    if len(boxes) == 0:
        return "rejected", ["Subject detection found no objects"]

    image_area = float(frame.shape[0] * frame.shape[1]) or 1.0
    fallback_found = False

    for class_idx, xyxy in zip(boxes.cls.cpu().numpy(), boxes.xyxy.cpu().numpy()):
        class_name = str(result.names.get(int(class_idx), "")).lower()
        x1, y1, x2, y2 = float(xyxy[0]), float(xyxy[1]), float(xyxy[2]), float(xyxy[3])
        box_area = max(0.0, x2 - x1) * max(0.0, y2 - y1)
        if box_area / image_area < min_area_ratio:
            continue

        if class_name in subject_classes:
            return "pass", []
        if class_name in fallback_classes:
            fallback_found = True

    if fallback_found:
        return "review", [
            "Subject detection found only fallback objects; review required",
        ]
    return "rejected", ["Subject detection found no valid subject"]


def analyze_photo(path: Path | str, config: dict[str, Any]) -> QCResult:
    """
    Run photo QC checks.

    duration_check and shake_check are always pass for photos.
    """
    image_path = Path(path)
    reasons: list[str] = []

    frame = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if frame is None:
        reasons.append("OpenCV cannot open photo")
        return QCResult(
            duration_check="pass",
            blur_check="review",
            content_check="review",
            saturation_check="pass",
            entropy_check="pass",
            exposure_check="pass",
            shake_check="pass",
            reasons=reasons,
        )

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    blur_value = _laplacian_variance_gray(gray)
    blur_threshold = float(config["blur_threshold"])
    if blur_value < blur_threshold:
        blur_check = "rejected"
        reasons.append(
            f"Blur: Laplacian variance {blur_value:.2f} below threshold {blur_threshold}",
        )
    else:
        blur_check = "pass"

    subject_check, subject_reasons = _subject_detection_status(frame, config)
    reasons.extend(subject_reasons)

    return QCResult(
        duration_check="pass",
        blur_check=blur_check,
        content_check=subject_check,
        saturation_check="pass",
        entropy_check="pass",
        exposure_check="pass",
        shake_check="pass",
        reasons=reasons,
    )
