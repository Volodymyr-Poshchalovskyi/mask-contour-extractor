import os
import cv2
import re
import numpy as np

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

def get_initial_points(contour):
    """
    Базове спрощення для старту.
    Ми використовуємо дуже малий epsilon, щоб зберегти форму,
    але прибрати 'сходинки' пікселів. Далі користувач править сам.
    """
    epsilon = 0.002 * cv2.arcLength(contour, True)
    approx = cv2.approxPolyDP(contour, epsilon, True)
    return approx.reshape(-1, 2).tolist()