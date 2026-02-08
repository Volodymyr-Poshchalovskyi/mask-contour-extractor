import os
import cv2
import re
import numpy as np
from constants import OPTIMIZATION_MODES

def read_image_safe(path, mode=cv2.IMREAD_COLOR):
    try:
        stream = open(path, "rb")
        bytes = bytearray(stream.read())
        numpyarray = np.asarray(bytes, dtype=np.uint8)
        return cv2.imdecode(numpyarray, mode)
    except Exception as e:
        print(f"Error reading {path}: {e}")
        return None

def normalize_name(filename):
    base = os.path.splitext(filename)[0]
    base = re.sub(r'^\d+_', '', base)
    base = re.sub(r'\d{4}$', '', base).strip()
    return base.capitalize() if base else "Object"

def process_contour(contour, mode_name):
    """
    Генерує точки контуру залежно від обраного режиму.
    """
    mode = OPTIMIZATION_MODES.get(mode_name, OPTIMIZATION_MODES["Balanced"])
    
    if mode["type"] == "rect":
        # Знаходимо мінімальний прямокутник будь-якої орієнтації
        rect = cv2.minAreaRect(contour)
        box = cv2.boxPoints(rect)
        box = np.int32(box) # або np.int0 у старіших версіях
        return box.reshape(-1, 2).tolist()
    
    else:
        # Стандартний метод approxPolyDP
        epsilon = mode["epsilon"] * cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, epsilon, True)
        return approx.reshape(-1, 2).tolist()