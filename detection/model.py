"""
Object detection model wrapper.

Still the same stock MobileNet-SSD (Caffe) as the original script -- no
custom-trained retail model, because that needs a labeled product image
dataset this project doesn't have (see Implementation Plan: barcode
fallback was considered and explicitly descoped since these products
don't have real barcodes either; camera-only with the stock model's
generic classes is the honest, realistic scope for this milestone).

What changed from the original: CLASSES is now treated as ground truth
for "what this model can possibly output," and the catalog-mapping layer
(see detector.py) validates every product's detection_label against it at
startup -- directly fixing the Phase 1 bug where the demo catalog
referenced a class ("chips_packet") the model could never actually
produce, silently making that product undetectable with no warning
anywhere.
"""
import logging

import cv2
import numpy as np

logger = logging.getLogger("smartcart.model")

# Stock MobileNet-SSD (VOC-trained) classes. This is the actual, complete
# set of labels this specific model can ever output -- if you swap in a
# different/retrained model, update this list to match it exactly.
CLASSES = [
    "background", "aeroplane", "bicycle", "bird", "boat", "bottle", "bus",
    "car", "cat", "chair", "cow", "diningtable", "dog", "horse",
    "motorbike", "person", "pottedplant", "sheep", "sofa", "train", "tvmonitor",
]


class Detector:
    def __init__(self, prototxt_path: str, model_path: str, confidence_threshold: float):
        self.net = cv2.dnn.readNetFromCaffe(prototxt_path, model_path)
        self.confidence_threshold = confidence_threshold

    def detect(self, frame: np.ndarray) -> list[tuple[str, float]]:
        """Runs the model on a single frame, returns [(label, confidence), ...]."""
        blob = cv2.dnn.blobFromImage(frame, 0.007843, (300, 300), 127.5)
        self.net.setInput(blob)
        detections = self.net.forward()

        results = []
        for i in range(detections.shape[2]):
            confidence = float(detections[0, 0, i, 2])
            if confidence > self.confidence_threshold:
                class_id = int(detections[0, 0, i, 1])
                label = CLASSES[class_id] if class_id < len(CLASSES) else "unknown"
                results.append((label, confidence))
        return results
