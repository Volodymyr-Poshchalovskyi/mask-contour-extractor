import os
import re
import cv2
import json
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from utils import read_image_safe, normalize_name, process_contour
from models import ImageSceneData, MaskObjectData
from constants import VISUAL_EPSILON, DEFAULT_PALETTE, SEMANTIC_COLORS, OPTIMIZATION_MODES

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
                    original = obj.get('original_mask')
                    # Завантажуємо збережений режим, якщо є
                    mode = obj.get('mode', "Balanced") 
                    
                    if original:
                        norm_orig = normalize_name(original)
                        registry[norm_orig] = {
                            'rename_to': name,
                            'visible': True,
                            'color': None,
                            'mode': mode 
                        }
        except Exception:
            pass
    return registry

def determine_color(name):
    name_lower = name.lower()
    for key, color in SEMANTIC_COLORS.items():
        if key in name_lower:
            return color
    return None

def scan_directory(folder_path):
    try:
        files = os.listdir(folder_path)
    except Exception as e:
        raise Exception(f"Не вдалося прочитати папку: {e}")

    main_files = [f for f in files if re.match(r'^1\d{4}\.(jpg|png|jpeg)$', f, re.IGNORECASE)]
    main_files.sort()

    if not main_files:
        return [], {}, set()

    existing_data = load_existing_json(folder_path)
    scenes = []
    global_registry = {}
    all_unique_names = set()
    palette_idx = 0

    for main_f in main_files:
        full_main_path = os.path.join(folder_path, main_f)
        base_name = os.path.splitext(main_f)[0]
        identifier = base_name[-4:] 

        scene = ImageSceneData(full_main_path)
        
        for f in files:
            if f == main_f: continue
            f_base = os.path.splitext(f)[0]
            
            if f_base.endswith(identifier):
                mask_path = os.path.join(folder_path, f)
                mask_img = read_image_safe(mask_path, cv2.IMREAD_GRAYSCALE)
                if mask_img is None: continue
                
                _, thresh = cv2.threshold(mask_img, 127, 255, cv2.THRESH_BINARY)
                contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                
                if contours:
                    c = max(contours, key=cv2.contourArea)
                    
                    # 1. Visual Points (завжди детальні)
                    ep_vis = VISUAL_EPSILON * cv2.arcLength(c, True)
                    approx_vis = cv2.approxPolyDP(c, ep_vis, True)
                    pts_vis = approx_vis.reshape(-1, 2).tolist()
                    
                    # 2. Визначаємо налаштування
                    raw_norm_name = normalize_name(f)
                    final_display_name = raw_norm_name
                    is_visible = True
                    color = None
                    opt_mode = "Balanced" # Дефолтний режим

                    # З JSON історії
                    if raw_norm_name in existing_data:
                        saved = existing_data[raw_norm_name]
                        final_display_name = saved['rename_to']
                        is_visible = saved['visible']
                        opt_mode = saved.get('mode', "Balanced")

                    # Глобальний реєстр сесії
                    if final_display_name not in global_registry:
                        semantic_color = determine_color(final_display_name)
                        if semantic_color:
                            color = semantic_color
                        else:
                            color = DEFAULT_PALETTE[palette_idx % len(DEFAULT_PALETTE)]
                            palette_idx += 1
                        
                        # Якщо в назві є 'window', ставимо режим Rectangle автоматично
                        if "window" in final_display_name.lower():
                            opt_mode = "Rectangle"
                            
                        global_registry[final_display_name] = {
                            'color': color, 
                            'visible': is_visible,
                            'mode': opt_mode
                        }
                    
                    settings = global_registry[final_display_name]
                    
                    # 3. JSON Points (розраховуємо залежно від режиму)
                    pts_json = process_contour(c, settings['mode'])

                    all_unique_names.add(final_display_name)
                    
                    obj = MaskObjectData(
                        original_filename=f,
                        visual_points=pts_vis,
                        json_points=pts_json,
                        color=settings['color'],
                        display_name=final_display_name,
                        is_visible=settings['visible'],
                        optimization_mode=settings['mode']
                    )
                    scene.objects.append(obj)
        
        scenes.append(scene)
    
    return scenes, global_registry, all_unique_names