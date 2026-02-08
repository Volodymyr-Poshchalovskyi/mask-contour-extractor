import os
import cv2
import re
import numpy as np

def read_image_safe(path, mode=cv2.IMREAD_COLOR):
    """Безпечне читання файлів (навіть якщо шлях містить кирилицю)."""
    try:
        stream = open(path, "rb")
        bytes = bytearray(stream.read())
        numpyarray = np.asarray(bytes, dtype=np.uint8)
        return cv2.imdecode(numpyarray, mode)
    except Exception as e:
        print(f"Error reading {path}: {e}")
        return None

def normalize_name(filename):
    """Перетворює '1_apartment 30000.jpg' -> 'Apartment 3'"""
    base = os.path.splitext(filename)[0]
    base = re.sub(r'^\d+_', '', base)      # Видаляємо префікс "1_"
    base = re.sub(r'\d{4}$', '', base).strip() # Видаляємо суфікс "0000"
    return base.capitalize() if base else "Object"