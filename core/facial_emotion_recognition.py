from __future__ import annotations

import base64
import json
from datetime import datetime
from typing import Any, Dict

try:
    import cv2
except Exception:
    cv2 = None

try:
    import numpy as np
except Exception:
    np = None

try:
    from deepface import DeepFace
except Exception:
    DeepFace = None


def analyze_face(frame: Any) -> Dict[str, Any]:
    if DeepFace is None:
        return {
            "status": "visual_engine_unavailable",
            "dominant_emotion": "",
            "reason": "DeepFace is not installed in this Python environment.",
        }
    try:
        result = DeepFace.analyze(frame, actions=["emotion"], enforce_detection=False)
        item = result[0] if isinstance(result, list) else result
        return {
            "status": "analyzed",
            "dominant_emotion": item.get("dominant_emotion", ""),
            "emotion_scores": item.get("emotion", {}),
        }
    except Exception as exc:
        return {
            "status": "visual_analysis_error",
            "dominant_emotion": "",
            "reason": str(exc),
        }


def analyze_image_bytes(image_bytes: bytes) -> Dict[str, Any]:
    if cv2 is None or np is None:
        return {
            "status": "visual_engine_unavailable",
            "dominant_emotion": "",
            "reason": "OpenCV and NumPy are required for browser snapshot analysis.",
        }
    try:
        buffer = np.frombuffer(image_bytes, dtype=np.uint8)
        frame = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
        if frame is None:
            return {"status": "visual_decode_error", "dominant_emotion": ""}
        return analyze_face(frame)
    except Exception as exc:
        return {
            "status": "visual_decode_error",
            "dominant_emotion": "",
            "reason": str(exc),
        }


def analyze_image_data_url(data_url: str) -> Dict[str, Any]:
    if not data_url:
        return {"status": "not_provided", "dominant_emotion": ""}
    try:
        payload = data_url.split(",", 1)[1] if "," in data_url else data_url
        image_bytes = base64.b64decode(payload)
    except Exception as exc:
        return {
            "status": "visual_decode_error",
            "dominant_emotion": "",
            "reason": str(exc),
        }
    return analyze_image_bytes(image_bytes)


def start_camera_session(user_id: str = "user-local") -> None:
    if cv2 is None:
        print("InnerLight Visual Engine requires OpenCV for a local camera session.")
        return
    cap = cv2.VideoCapture(0)
    print(f"InnerLight Visual Engine initialized for: {user_id}")

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        result = analyze_face(frame)
        emotion = result.get("dominant_emotion", "")
        timestamp = datetime.utcnow().isoformat()
        log = {
            "timestamp": timestamp,
            "user_id": user_id,
            "emotion_detected": emotion,
            "status": result.get("status"),
        }
        print(json.dumps(log, indent=2))

        cv2.putText(
            frame,
            f"Emotion: {emotion or result.get('status', 'unknown')}",
            (30, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            1,
            (0, 255, 0),
            2,
        )
        cv2.imshow("InnerLight - Facial Emotion Recognition", frame)

        if cv2.waitKey(1) & 0xFF == ord("q"):
            print("Session terminated by user.")
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    start_camera_session()
