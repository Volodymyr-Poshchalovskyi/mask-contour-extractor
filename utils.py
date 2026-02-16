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
    base = re.sub(r'\s*\d{4,5}$', '', base) # Видаляє 4-5 цифр в кінці
    base = re.sub(r'^\d+_', '', base)
    base = base.replace('_', ' ').strip().title()
    return base if base else "Object"

def extract_frame_signature(filename):
    """
    Повертає останні 4 цифри імені файлу як РЯДОК (наприклад '0001').
    Це критично для правильного розрізнення 'Apartment 1' на кадрі '0001'.
    """
    base = os.path.splitext(filename)[0]
    # Шукаємо 4 цифри в самому кінці рядка
    match = re.search(r'(\d{4})$', base.strip())
    if match:
        return match.group(1)
    # Fallback: якщо цифр менше (наприклад 1.jpg)
    match_short = re.search(r'(\d+)$', base.strip())
    if match_short:
        return match_short.group(1)
    return None

def get_initial_points(contour, epsilon_factor=0.002):
    epsilon = epsilon_factor * cv2.arcLength(contour, True)
    approx = cv2.approxPolyDP(contour, epsilon, True)
    return approx.reshape(-1, 2).tolist()