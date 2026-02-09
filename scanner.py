import os
import re
import cv2
import json
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

# Імпорти з ваших файлів
from utils import read_image_safe, normalize_name, get_initial_points
from models import ImageSceneData, MaskObjectData
from constants import DEFAULT_PALETTE, SEMANTIC_COLORS

def load_existing_json(folder_path):
    """
    Шукає final_data.json, щоб відновити назви та налаштування видимості.
    """
    json_path = os.path.join(folder_path, "final_data.json")
    registry = {}
    
    if os.path.exists(json_path):
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            for entry in data:
                for obj in entry.get('objects', []):
                    name = obj.get('name') 
                    original = obj.get('original_mask') 
                    
                    if original:
                        norm_orig = normalize_name(original)
                        registry[norm_orig] = {
                            'rename_to': name,   # Як користувач перейменував об'єкт
                            'visible': True,     # У JSON зазвичай зберігаються тільки видимі
                            'color': None        # Колір відновимо через семантику або палітру
                        }
        except Exception as e:
            print(f"Error loading JSON history: {e}")
            
    return registry

def determine_color(name):
    """Підбирає колір на основі ключових слів (вікно -> блакитне, дах -> червоний)"""
    name_lower = name.lower()
    for key, color in SEMANTIC_COLORS.items():
        if key in name_lower:
            return color
    return None

def scan_directory(folder_path):
    """
    Головна функція сканування папки.
    Повертає список сцен, глобальний реєстр налаштувань та список всіх імен.
    """
    try:
        files = os.listdir(folder_path)
    except Exception as e:
        raise Exception(f"Не вдалося прочитати папку: {e}")

    # Шукаємо основні файли (1XXXX.jpg)
    main_files = [f for f in files if re.match(r'^1\d{4}\.(jpg|png|jpeg)$', f, re.IGNORECASE)]
    main_files.sort()

    if not main_files:
        return [], {}, set()

    # Завантажуємо історію редагування (якщо є)
    existing_data = load_existing_json(folder_path)

    scenes = []
    global_registry = {}
    all_unique_names = set()
    palette_idx = 0

    for main_f in main_files:
        full_main_path = os.path.join(folder_path, main_f)
        base_name = os.path.splitext(main_f)[0]
        identifier = base_name[-4:] # Останні 4 цифри (наприклад "0000")

        scene = ImageSceneData(full_main_path)
        
        # Шукаємо маски для цього кадру
        for f in files:
            if f == main_f: continue
            f_base = os.path.splitext(f)[0]
            
            # Якщо файл закінчується на той самий ID (наприклад "...0000")
            if f_base.endswith(identifier):
                mask_path = os.path.join(folder_path, f)
                
                # Читаємо маску
                mask_img = read_image_safe(mask_path, cv2.IMREAD_GRAYSCALE)
                if mask_img is None: continue
                
                # Знаходимо контур
                _, thresh = cv2.threshold(mask_img, 127, 255, cv2.THRESH_BINARY)
                contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                
                if contours:
                    c = max(contours, key=cv2.contourArea)
                    
                    # --- ГЕНЕРАЦІЯ ТОЧОК ---
                    # Використовуємо базове спрощення. Далі користувач править руками.
                    points = get_initial_points(c)
                    
                    # --- ВИЗНАЧЕННЯ ІМЕНІ ТА КОЛЬОРУ ---
                    raw_norm_name = normalize_name(f)
                    final_display_name = raw_norm_name
                    is_visible = True
                    color = None

                    # А. Перевіряємо історію (JSON)
                    if raw_norm_name in existing_data:
                        saved = existing_data[raw_norm_name]
                        final_display_name = saved['rename_to'] # Відновлюємо перейменування
                        is_visible = saved['visible']
                    
                    # Б. Глобальний реєстр поточної сесії
                    if final_display_name not in global_registry:
                        # Пріоритет кольору: Семантика -> Палітра
                        semantic_color = determine_color(final_display_name)
                        if semantic_color:
                            color = semantic_color
                        else:
                            color = DEFAULT_PALETTE[palette_idx % len(DEFAULT_PALETTE)]
                            palette_idx += 1
                        
                        global_registry[final_display_name] = {'color': color, 'visible': is_visible}
                    
                    settings = global_registry[final_display_name]
                    all_unique_names.add(final_display_name)
                    
                    # Створюємо об'єкт
                    # visual_points і json_points тепер ідентичні на старті,
                    # оскільки ми редагуємо саме json_points на канвасі.
                    obj = MaskObjectData(
                        original_filename=f,
                        visual_points=points, 
                        json_points=points,   
                        color=settings['color'],
                        display_name=final_display_name,
                        is_visible=settings['visible']
                    )
                    scene.objects.append(obj)
        
        scenes.append(scene)
    
    return scenes, global_registry, all_unique_names