import os
import re
import cv2
import json
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

from utils import read_image_safe, normalize_name, get_initial_points, extract_frame_signature
from models import ImageSceneData, MaskObjectData
from constants import DEFAULT_PALETTE, SEMANTIC_COLORS

def load_existing_json(folder_path):
    json_path = os.path.join(folder_path, "final_data.json")
    registry = {}
    if os.path.exists(json_path):
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f) 
            for entry in data:
                for obj in entry.get('objects', []):
                    name = obj.get('name')
                    # Тут ми просто відновлюємо загальні налаштування, якщо треба
                    pass
        except Exception as e:
            print(f"Error loading JSON history: {e}")
    return registry

def determine_color(name):
    import hashlib
    hash_object = hashlib.md5(name.encode())
    hex_hash = hash_object.hexdigest()
    r = int(hex_hash[0:2], 16)
    g = int(hex_hash[2:4], 16)
    b = int(hex_hash[4:6], 16)
    return QColor(min(r + 50, 255), min(g + 50, 255), min(b + 50, 255))

def parse_smart_name(filename, frame_sig):
    """
    Розумний парсер.
    filename: "1_house 2 apartment 10001.jpg"
    frame_sig: "0001" (взято з основного файлу)
    
    Логіка: видаляємо "0001" з кінця назви, отримуємо "1_house 2 apartment 1".
    Парсимо це.
    """
    name_clean = os.path.splitext(filename)[0]
    
    # 1. ВІДРІЗАЄМО НОМЕР КАДРУ
    if frame_sig and name_clean.endswith(frame_sig):
        name_clean = name_clean[:-len(frame_sig)]
    
    # Зачищаємо можливі пробіли/підкреслення в кінці після обрізки
    name_clean = name_clean.strip(" _")

    # 2. ПАРСИМО РЕШТУ (House X ... Apartment Y)
    # Шукаємо House + число ... Apartment + число
    match_full = re.search(r'house\s*(\d+).*?apartment\s*(\d+)', name_clean, re.IGNORECASE)
    if match_full:
        return f"House {match_full.group(1)} - Apt {match_full.group(2)}"
    
    # Якщо тільки House
    match_house = re.search(r'house\s*(\d+)', name_clean, re.IGNORECASE)
    if match_house:
        return f"House {match_house.group(1)}"

    # Якщо нічого не знайшли, просто чистимо назву
    return normalize_name(filename)

def scan_directory(folder_path, epsilon_factor=0.002):
    try:
        files = os.listdir(folder_path)
    except Exception as e:
        raise Exception(f"Не вдалося прочитати папку: {e}")

    # Шукаємо основні файли (10001.jpg...)
    main_files = [f for f in files if 
                  re.search(r'\d+\.(jpg|png|jpeg)$', f, re.IGNORECASE) 
                  and "house" not in f.lower() 
                  and "apartment" not in f.lower()]
    
    # Сортуємо
    main_files.sort(key=lambda x: x) # Просте сортування за іменем зазвичай ок для 10001...

    if not main_files:
        return [], {}, set()

    scenes = []
    global_registry = {}
    all_unique_names = set()

    mask_files = [f for f in files if "house" in f.lower() or "apartment" in f.lower()]

    for main_f in main_files:
        full_main_path = os.path.join(folder_path, main_f)
        
        # ОТРИМУЄМО ПІДПИС КАДРУ (наприклад "0001")
        frame_sig = extract_frame_signature(main_f)
        if not frame_sig: continue

        scene = ImageSceneData(full_main_path)
        
        for f in mask_files:
            # Перевіряємо, чи маска закінчується на цей підпис (або підпис+розширення)
            # Наприклад "apartment 1 0001.jpg" закінчується на "0001.jpg"
            if os.path.splitext(f)[0].endswith(frame_sig):
                
                # --- ПЕРЕДАЄМО ПІДПИС У ПАРСЕР ---
                display_name = parse_smart_name(f, frame_sig)
                
                mask_path = os.path.join(folder_path, f)
                mask_img = read_image_safe(mask_path, cv2.IMREAD_GRAYSCALE)
                if mask_img is None: continue
                
                _, thresh = cv2.threshold(mask_img, 127, 255, cv2.THRESH_BINARY)
                contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                
                if contours:
                    c = max(contours, key=cv2.contourArea)
                    points = get_initial_points(c, epsilon_factor)
                    
                    if display_name not in global_registry:
                        color = determine_color(display_name)
                        global_registry[display_name] = {'color': color, 'visible': True}
                    
                    settings = global_registry[display_name]
                    all_unique_names.add(display_name)
                    
                    obj = MaskObjectData(
                        original_filename=f,
                        visual_points=points, 
                        json_points=points,   
                        color=settings['color'],
                        display_name=display_name,
                        is_visible=settings['visible']
                    )
                    scene.objects.append(obj)
        
        # Сортування: House 1 Apt 1, House 1 Apt 2...
        def sort_key(obj):
            # Розбиваємо ім'я на числа для натурального сортування
            return [int(text) if text.isdigit() else text.lower()
                    for text in re.split('([0-9]+)', obj.display_name)]
            
        scene.objects.sort(key=sort_key)
        scenes.append(scene)
    
    return scenes, global_registry, all_unique_names