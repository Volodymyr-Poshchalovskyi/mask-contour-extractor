import os
import json
import cv2
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QLabel, QFileDialog, QMessageBox, 
                             QScrollArea, QStackedWidget, QSizePolicy, QApplication)
from PyQt6.QtGui import QPixmap, QImage, QPainter, QPen, QPolygonF, QColor
from PyQt6.QtCore import Qt, QPointF

# Імпортуємо ваші модулі
from utils import read_image_safe, process_contour
from models import MaskObjectData
from scanner import scan_directory
from widgets import ObjectListItem

class MaskEditorApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.scenes = [] 
        self.current_idx = 0
        self.global_registry = {} 
        self.all_unique_names = set() 
        
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("Smart Mask Editor (WYSIWYG Mode)")
        self.resize(1200, 800)
        self.setStyleSheet("background-color: #2b2b2b; color: #ffffff;")

        self.stacked_widget = QStackedWidget()
        self.setCentralWidget(self.stacked_widget)

        self.init_welcome_screen()
        self.init_editor_screen()

    def init_welcome_screen(self):
        widget = QWidget()
        layout = QVBoxLayout()
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        lbl = QLabel("Оберіть папку для початку роботи")
        lbl.setStyleSheet("font-size: 24px; font-weight: bold; margin-bottom: 20px;")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl)

        btn = QPushButton("📂 Відкрити папку")
        btn.setFixedSize(200, 60)
        btn.setStyleSheet("background-color: #0078d7; font-size: 18px; border-radius: 8px;")
        btn.clicked.connect(self.select_folder)
        layout.addWidget(btn, alignment=Qt.AlignmentFlag.AlignCenter)

        widget.setLayout(layout)
        self.welcome_widget = widget
        self.stacked_widget.addWidget(self.welcome_widget)

    def init_editor_screen(self):
        self.editor_widget = QWidget()
        main_layout = QVBoxLayout(self.editor_widget)

        # Header
        header = QHBoxLayout()
        self.lbl_info = QLabel("File: ...")
        self.lbl_info.setStyleSheet("font-weight: bold; font-size: 16px;")
        header.addWidget(self.lbl_info)
        header.addStretch()

        btn_save = QPushButton("💾 Зберегти JSON")
        btn_save.setStyleSheet("background-color: #28a745; padding: 5px 15px;")
        btn_save.clicked.connect(self.save_json)
        header.addWidget(btn_save)

        btn_reset = QPushButton("🔄 Скинути")
        btn_reset.setStyleSheet("background-color: #dc3545; padding: 5px 15px;")
        btn_reset.clicked.connect(self.reset_app)
        header.addWidget(btn_reset)
        main_layout.addLayout(header)

        # Work Area
        work_area = QHBoxLayout()

        # Left: Image
        img_container = QWidget()
        img_layout = QVBoxLayout(img_container)
        self.lbl_image = QLabel()
        self.lbl_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_image.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        img_layout.addWidget(self.lbl_image)

        nav_layout = QHBoxLayout()
        self.btn_prev = QPushButton("⬅️ Назад")
        self.btn_prev.clicked.connect(self.prev_image)
        self.btn_next = QPushButton("Вперед ➡️")
        self.btn_next.clicked.connect(self.next_image)
        
        nav_layout.addWidget(self.btn_prev)
        self.lbl_counter = QLabel("0 / 0")
        self.lbl_counter.setAlignment(Qt.AlignmentFlag.AlignCenter)
        nav_layout.addWidget(self.lbl_counter)
        nav_layout.addWidget(self.btn_next)
        img_layout.addLayout(nav_layout)
        work_area.addWidget(img_container, stretch=3)

        # Right: List
        right_panel = QWidget()
        right_panel.setFixedWidth(350)
        right_layout = QVBoxLayout(right_panel)
        right_layout.addWidget(QLabel("Глобальний список об'єктів:"))
        
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_content = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll_area.setWidget(self.scroll_content)
        right_layout.addWidget(self.scroll_area)
        work_area.addWidget(right_panel, stretch=1)
        
        main_layout.addLayout(work_area)
        self.stacked_widget.addWidget(self.editor_widget)

    # --- Sync Logic ---

    def sync_visibility(self, name, is_visible):
        if name in self.global_registry:
            self.global_registry[name]['visible'] = is_visible
        for scene in self.scenes:
            for obj in scene.objects:
                if obj.display_name == name:
                    obj.is_visible = is_visible
        self.update_view()

    def sync_color(self, name, color):
        if name in self.global_registry:
            self.global_registry[name]['color'] = color
        for scene in self.scenes:
            for obj in scene.objects:
                if obj.display_name == name:
                    obj.color = color
        self.update_view()

    def sync_name(self, old_name, new_name):
        if old_name in self.global_registry:
            data = self.global_registry.pop(old_name)
            self.global_registry[new_name] = data
        if old_name in self.all_unique_names:
            self.all_unique_names.remove(old_name)
            self.all_unique_names.add(new_name)
        for scene in self.scenes:
            for obj in scene.objects:
                if obj.display_name == old_name:
                    obj.display_name = new_name
        self.update_view()

    def sync_mode(self, name, mode):
        """
        Змінює режим оптимізації і миттєво перераховує точки, 
        щоб це відобразилось на екрані.
        """
        # 1. Оновлюємо глобальний реєстр
        if name in self.global_registry:
            self.global_registry[name]['mode'] = mode
            
        # 2. Оновлюємо об'єкти у всіх сценах
        for scene in self.scenes:
            base_folder = os.path.dirname(scene.main_path)
            
            for obj in scene.objects:
                if obj.display_name == name:
                    obj.optimization_mode = mode
                    
                    # Перераховуємо контур з новим режимом
                    # Читаємо оригінальну маску
                    mask_path = os.path.join(base_folder, obj.original_filename)
                    mask_img = read_image_safe(mask_path, cv2.IMREAD_GRAYSCALE)
                    
                    if mask_img is not None:
                         _, thresh = cv2.threshold(mask_img, 127, 255, cv2.THRESH_BINARY)
                         contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                         if contours:
                             c = max(contours, key=cv2.contourArea)
                             
                             # ВАЖЛИВО: Перезаписуємо json_points новими даними
                             # process_contour повертає прямокутник або спрощену лінію
                             obj.json_points = process_contour(c, mode)

        # 3. Перемальовуємо екран
        self.update_view()

    # --- Actions ---
    def select_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Виберіть папку")
        if folder:
            self.process_folder(folder)

    def process_folder(self, folder):
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.scenes, self.global_registry, self.all_unique_names = scan_directory(folder)
            
            if not self.scenes:
                QMessageBox.warning(self, "Увага", "Не знайдено файлів 1XXXX.jpg")
            else:
                self.current_idx = 0
                self.stacked_widget.setCurrentIndex(1)
                self.update_view()
                
        except Exception as e:
            QMessageBox.critical(self, "Помилка", str(e))
        finally:
            QApplication.restoreOverrideCursor()

    def reset_app(self):
        reply = QMessageBox.question(self, 'Скинути', 'Всі зміни будуть втрачені.',
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.scenes = []
            self.global_registry = {}
            self.all_unique_names = set()
            self.stacked_widget.setCurrentIndex(0)

    def prev_image(self):
        if self.scenes:
            self.current_idx = (self.current_idx - 1 + len(self.scenes)) % len(self.scenes)
            self.update_view()

    def next_image(self):
        if self.scenes:
            self.current_idx = (self.current_idx + 1) % len(self.scenes)
            self.update_view()

    def update_view(self):
        if not self.scenes: return
        scene = self.scenes[self.current_idx]
        self.lbl_info.setText(f"Файл: {os.path.basename(scene.main_path)}")
        self.lbl_counter.setText(f"{self.current_idx + 1} / {len(self.scenes)}")

        # Clear list
        while self.scroll_layout.count():
            child = self.scroll_layout.takeAt(0)
            if child.widget(): child.widget().deleteLater()
        
        # Build global list
        sorted_names = sorted(list(self.all_unique_names))
        for name in sorted_names:
            obj_in_scene = next((o for o in scene.objects if o.display_name == name), None)
            
            if obj_in_scene:
                obj_in_scene.is_present_in_frame = True
                item = ObjectListItem(obj_in_scene, self)
            else:
                settings = self.global_registry.get(name, {
                    'color': Qt.GlobalColor.gray, 
                    'visible': True, 
                    'mode': 'Balanced'
                })
                # Створюємо фіктивний об'єкт для списку
                ghost_obj = MaskObjectData("", [], [], settings['color'], name, settings['visible'], settings['mode'])
                ghost_obj.is_present_in_frame = False
                item = ObjectListItem(ghost_obj, self)
            
            self.scroll_layout.addWidget(item)

        self.redraw_image()

    def redraw_image(self):
        """
        Малює зображення. 
        ВАЖЛИВО: Малюємо json_points, щоб бачити РЕАЛЬНИЙ вигляд ліній (прямі/криві).
        """
        scene = self.scenes[self.current_idx]
        cv_img = read_image_safe(scene.main_path, cv2.IMREAD_COLOR)
        if cv_img is None: return
        
        cv_img = cv2.cvtColor(cv_img, cv2.COLOR_BGR2RGB)
        h, w, ch = cv_img.shape
        q_img = QImage(cv_img.data, w, h, ch * w, QImage.Format.Format_RGB888)
        pixmap = QPixmap.fromImage(q_img)
        canvas = QPixmap(pixmap) 
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        for obj in scene.objects:
            if obj.is_visible and obj.json_points:
                pen = QPen(obj.color)
                pen.setWidth(3)
                painter.setPen(pen)
                
                # Малюємо оптимізовані точки (json_points)
                poly_points = [QPointF(pt[0], pt[1]) for pt in obj.json_points]
                
                if len(poly_points) > 1:
                    painter.drawPolygon(QPolygonF(poly_points))
                    
                # Малюємо точки вершин (кути), щоб бачити структуру
                painter.setBrush(obj.color)
                for pt in poly_points:
                    painter.drawEllipse(pt, 3, 3)

        painter.end()

        if self.lbl_image.width() > 0:
            self.lbl_image.setPixmap(canvas.scaled(self.lbl_image.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        else:
            self.lbl_image.setPixmap(canvas)

    def resizeEvent(self, event):
        if self.stacked_widget.currentIndex() == 1: 
            self.redraw_image()
        super().resizeEvent(event)

    def save_json(self):
        if not self.scenes: return
        folder = os.path.dirname(self.scenes[0].main_path)
        save_path, _ = QFileDialog.getSaveFileName(self, "Зберегти", os.path.join(folder, "final_data.json"), "JSON Files (*.json)")
        if not save_path: return

        output_data = []
        for scene in self.scenes:
            entry = {"image_name": os.path.basename(scene.main_path), "objects": []}
            for obj in scene.objects:
                if obj.is_visible:
                    entry["objects"].append({
                        "name": obj.display_name,
                        "original_mask": obj.original_filename,
                        "points": obj.json_points,
                        "mode": obj.optimization_mode # Зберігаємо режим
                    })
            output_data.append(entry)

        try:
            with open(save_path, 'w', encoding='utf-8') as f:
                json.dump(output_data, f, separators=(',', ':'), ensure_ascii=False)
            QMessageBox.information(self, "Успіх", "JSON збережено!")
        except Exception as e:
            QMessageBox.critical(self, "Помилка", str(e))