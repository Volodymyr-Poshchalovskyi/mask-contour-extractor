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

# --- ЗМІНА ТУТ ---
def get_initial_points(contour, epsilon_factor=0.002):
    """
    Генерує точки з заданою точністю.
    epsilon_factor: Менше (0.001) = більше точок/деталей. Більше (0.005) = пряміші лінії.
    """
    epsilon = epsilon_factor * cv2.arcLength(contour, True)
    approx = cv2.approxPolyDP(contour, epsilon, True)
    return approx.reshape(-1, 2).tolist()