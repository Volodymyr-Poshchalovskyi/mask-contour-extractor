import os
import re
import cv2
from PyQt6.QtCore import Qt # Для кольорів за замовчуванням
from utils import read_image_safe, normalize_name
from models import ImageSceneData, MaskObjectData
from constants import VISUAL_EPSILON, JSON_EPSILON, DEFAULT_PALETTE

def scan_directory(folder_path):
    """
    Сканує папку і повертає:
    1. scenes (список сцен)
    2. global_registry (словник налаштувань)
    3. all_unique_names (множина всіх імен)
    """
    try:
        files = os.listdir(folder_path)
    except Exception as e:
        raise Exception(f"Не вдалося прочитати папку: {e}")

    main_files = [f for f in files if re.match(r'^1\d{4}\.(jpg|png|jpeg)$', f, re.IGNORECASE)]
    main_files.sort()

    if not main_files:
        return [], {}, set()

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
                    
                    # Points Calculation
                    ep_vis = VISUAL_EPSILON * cv2.arcLength(c, True)
                    approx_vis = cv2.approxPolyDP(c, ep_vis, True)
                    pts_vis = approx_vis.reshape(-1, 2).tolist()
                    
                    ep_json = JSON_EPSILON * cv2.arcLength(c, True)
                    approx_json = cv2.approxPolyDP(c, ep_json, True)
                    pts_json = approx_json.reshape(-1, 2).tolist()

                    clean_name = normalize_name(f)
                    all_unique_names.add(clean_name)
                    
                    # Global Settings Logic
                    if clean_name not in global_registry:
                        color = DEFAULT_PALETTE[palette_idx % len(DEFAULT_PALETTE)]
                        palette_idx += 1
                        global_registry[clean_name] = {'color': color, 'visible': True}
                    
                    settings = global_registry[clean_name]
                    
                    obj = MaskObjectData(
                        original_filename=f,
                        visual_points=pts_vis,
                        json_points=pts_json,
                        color=settings['color'],
                        display_name=clean_name,
                        is_visible=settings['visible']
                    )
                    scene.objects.append(obj)
        
        scenes.append(scene)
    
    return scenes, global_registry, all_unique_names