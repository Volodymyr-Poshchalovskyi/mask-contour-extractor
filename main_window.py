import os
import json
import math
import copy
import cv2
import shutil # <--- ВАЖЛИВО: Додано для копіювання файлів
import numpy as np
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QLabel, QFileDialog, QMessageBox, 
                             QScrollArea, QStackedWidget, QSizePolicy, QApplication, 
                             QCheckBox, QLineEdit)
from PyQt6.QtGui import QPixmap, QImage, QPainter, QPen, QPolygonF, QColor, QBrush, QCursor, QAction, QKeySequence
from PyQt6.QtCore import Qt, QPointF, QRectF, pyqtSignal

from utils import read_image_safe
from models import MaskObjectData
from scanner import scan_directory
from widgets import ObjectListItem
from constants import POINT_RADIUS, LINE_WIDTH, HOVER_DIST

class EditorCanvas(QWidget):
    objectSelected = pyqtSignal(str) 

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.parent_app = parent
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        
        self.scene = None
        self.current_image = None
        self.zoom_level = 1.0
        self.offset = QPointF(0, 0)
        
        self.selected_obj = None
        self.drag_active = False
        self.last_mouse_pos = QPointF(0, 0)
        
        self.hovered_point_idx = -1
        self.dragging_point = False
        self.hovered_segment_idx = -1
        self.hovered_segment_point = None

        self.smart_snap_enabled = True
        self.active_guides = [] 
        self.snap_lines = []

        self.undo_stack = []
        self.redo_stack = []

    def set_scene(self, scene):
        self.scene = scene
        self.active_guides = []
        self.snap_lines = []
        self.undo_stack = []
        self.redo_stack = []
        
        if scene:
            cv_img = read_image_safe(scene.main_path, cv2.IMREAD_COLOR)
            if cv_img is not None:
                cv_img = cv2.cvtColor(cv_img, cv2.COLOR_BGR2RGB)
                h, w, ch = cv_img.shape
                bytes_per_line = ch * w
                q_img = QImage(cv_img.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
                self.current_image = QPixmap.fromImage(q_img)
            else:
                self.current_image = None
        else:
            self.current_image = None
        self.update()

    # --- KEYBOARD HANDLING ---
    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Left:
            self.parent_app.prev_image()
        elif event.key() == Qt.Key.Key_Right:
            self.parent_app.next_image()
        elif event.matches(QKeySequence.StandardKey.Undo):
            self.undo()
        elif event.matches(QKeySequence.StandardKey.Redo):
            self.redo()
        else:
            super().keyPressEvent(event)

    # --- UNDO / REDO ---
    def save_state_for_undo(self):
        if self.selected_obj:
            points_copy = copy.deepcopy(self.selected_obj.json_points)
            self.undo_stack.append((self.selected_obj, points_copy))
            self.redo_stack.clear()

    def undo(self):
        if not self.undo_stack: return
        obj, old_points = self.undo_stack.pop()
        current_points = copy.deepcopy(obj.json_points)
        self.redo_stack.append((obj, current_points))
        obj.json_points = old_points
        self.selected_obj = obj
        self.update()

    def redo(self):
        if not self.redo_stack: return
        obj, new_points = self.redo_stack.pop()
        current_points = copy.deepcopy(obj.json_points)
        self.undo_stack.append((obj, current_points))
        obj.json_points = new_points
        self.selected_obj = obj
        self.update()

    # --- COORDINATES ---
    def transform_to_img(self, pos):
        return (pos - self.offset) / self.zoom_level

    def transform_to_screen(self, pos):
        return (pos * self.zoom_level) + self.offset

    # --- PAINTING ---
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#222"))

        if not self.scene or not self.current_image:
            painter.setPen(Qt.GlobalColor.white)
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No Image Loaded")
            return

        # 1. Image
        img_rect = QRectF(self.offset.x(), self.offset.y(), 
                          self.current_image.width() * self.zoom_level, 
                          self.current_image.height() * self.zoom_level)
        painter.drawPixmap(img_rect.toRect(), self.current_image)

        # 2. Objects
        for obj in self.scene.objects:
            if not obj.is_visible or not obj.json_points: continue
            
            screen_points = [self.transform_to_screen(QPointF(p[0], p[1])) for p in obj.json_points]
            polygon = QPolygonF(screen_points)

            pen = QPen(obj.color)
            if obj == self.selected_obj:
                pen.setWidth(LINE_WIDTH + 1)
                pen.setStyle(Qt.PenStyle.SolidLine)
            else:
                pen.setWidth(LINE_WIDTH)
                pen.setColor(obj.color.darker(120))

            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPolygon(polygon)
            
            # --- GUIDES ---
            if obj == self.selected_obj and self.active_guides:
                for p1_img, p2_img, g_type in self.active_guides:
                    s1 = self.transform_to_screen(p1_img)
                    s2 = self.transform_to_screen(p2_img)
                    
                    if g_type == 1: 
                        guide_pen = QPen(QColor("#FFD700"))
                        guide_pen.setWidth(2)
                    else: 
                        guide_pen = QPen(QColor("#00FFFF"))
                        guide_pen.setWidth(1)
                        guide_pen.setStyle(Qt.PenStyle.DashLine)
                    
                    painter.setPen(guide_pen)
                    painter.drawLine(s1, s2)
                    if g_type == 1: painter.drawEllipse(s2, 5, 5)

            # --- POINTS ---
            if obj == self.selected_obj:
                painter.setBrush(obj.color)
                painter.setPen(Qt.PenStyle.NoPen) 
                
                for i, pt in enumerate(screen_points):
                    radius = POINT_RADIUS
                    if i == self.hovered_point_idx:
                        radius += 3
                        painter.setBrush(Qt.GlobalColor.white)
                    else:
                        painter.setBrush(obj.color)
                    painter.drawEllipse(pt, radius, radius)
                
                if self.hovered_segment_point:
                    painter.setBrush(Qt.GlobalColor.yellow)
                    painter.drawEllipse(self.hovered_segment_point, 4, 4)

    # --- MOUSE LOGIC ---
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self.selected_obj:
                if self.hovered_point_idx != -1:
                    self.save_state_for_undo()
                    self.dragging_point = True
                    return
                if self.hovered_segment_idx != -1 and (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
                    self.save_state_for_undo()
                    img_pt = self.transform_to_img(event.position())
                    self.selected_obj.json_points.insert(self.hovered_segment_idx + 1, [img_pt.x(), img_pt.y()])
                    self.hovered_point_idx = self.hovered_segment_idx + 1
                    self.dragging_point = True
                    self.hovered_segment_point = None
                    self.update()
                    return

            clicked_obj = self.find_object_at_pos(event.position())
            if clicked_obj:
                self.selected_obj = clicked_obj
                self.objectSelected.emit(f"Вибрано: {clicked_obj.display_name}")
                self.update()
            else:
                self.drag_active = True
                self.last_mouse_pos = event.position()
                self.update()
        
        elif event.button() == Qt.MouseButton.RightButton:
            if self.selected_obj and self.hovered_point_idx != -1:
                if len(self.selected_obj.json_points) > 3:
                    self.save_state_for_undo()
                    del self.selected_obj.json_points[self.hovered_point_idx]
                    self.hovered_point_idx = -1
                    self.update()

    def mouseMoveEvent(self, event):
        mouse_pos = event.position()
        self.active_guides = []

        if self.dragging_point and self.selected_obj:
            raw_img_pos = self.transform_to_img(mouse_pos)
            final_pos = raw_img_pos
            
            snap_dist_screen = 15
            snapped_to_vertex = False

            # Vertex Snap
            for obj in self.scene.objects:
                if obj == self.selected_obj or not obj.is_visible: continue
                for pt in obj.json_points:
                    pt_screen = self.transform_to_screen(QPointF(pt[0], pt[1]))
                    if (pt_screen - mouse_pos).manhattanLength() < snap_dist_screen:
                        final_pos = QPointF(pt[0], pt[1])
                        snapped_to_vertex = True
                        break
                if snapped_to_vertex: break
            
            # Smart Snap
            if not snapped_to_vertex and self.smart_snap_enabled:
                final_pos = self.apply_smart_intersection_snap(raw_img_pos, mouse_pos)

            self.selected_obj.json_points[self.hovered_point_idx] = [final_pos.x(), final_pos.y()]
            self.update()
            return

        if self.drag_active:
            delta = mouse_pos - self.last_mouse_pos
            self.offset += delta
            self.last_mouse_pos = mouse_pos
            self.update()
            return

        # Hit Testing
        self.hovered_point_idx = -1
        self.hovered_segment_idx = -1
        self.hovered_segment_point = None
        
        if not self.scene: return

        if self.selected_obj and self.selected_obj.is_visible:
            screen_points = [self.transform_to_screen(QPointF(p[0], p[1])) for p in self.selected_obj.json_points]
            
            min_dist = HOVER_DIST
            for i, pt in enumerate(screen_points):
                dist = (pt - mouse_pos).manhattanLength()
                if dist < min_dist:
                    self.hovered_point_idx = i
                    self.update()
                    return
            
            if (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
                for i in range(len(screen_points)):
                    p1 = screen_points[i]
                    p2 = screen_points[(i + 1) % len(screen_points)]
                    dist, projection = self.point_segment_dist(mouse_pos, p1, p2)
                    if dist < min_dist:
                        self.hovered_segment_idx = i
                        self.hovered_segment_point = projection
                        self.update()
                        return
        self.update()

    def mouseReleaseEvent(self, event):
        self.drag_active = False
        self.dragging_point = False
        self.active_guides = []
        self.update()

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta == 0:
            delta = event.pixelDelta().y()
            if delta != 0: delta *= 10 

        if delta == 0: return

        zoom_in = delta > 0
        step = 1.1 if zoom_in else 0.9
        
        old_zoom = self.zoom_level
        self.zoom_level *= step
        
        if self.zoom_level < 0.1: self.zoom_level = 0.1
        if self.zoom_level > 50.0: self.zoom_level = 50.0
        
        mouse_pos = event.position()
        self.offset = mouse_pos - (mouse_pos - self.offset) * (self.zoom_level / old_zoom)
        self.update()

    # --- MATH ---
    def find_object_at_pos(self, pos):
        for obj in reversed(self.scene.objects):
            if not obj.is_visible or not obj.json_points: continue
            screen_points = [self.transform_to_screen(QPointF(p[0], p[1])) for p in obj.json_points]
            poly = QPolygonF(screen_points)
            if poly.containsPoint(pos, Qt.FillRule.OddEvenFill):
                return obj
        return None

    def point_segment_dist(self, p, v, w):
        l2 = (v.x() - w.x())**2 + (v.y() - w.y())**2
        if l2 == 0: return (p - v).manhattanLength(), v
        t = ((p.x() - v.x()) * (w.x() - v.x()) + (p.y() - v.y()) * (w.y() - v.y())) / l2
        t = max(0, min(1, t))
        projection = QPointF(v.x() + t * (w.x() - v.x()), v.y() + t * (w.y() - v.y()))
        dist = (p - projection).manhattanLength()
        return dist, projection

    def simplify_current_polygon(self):
        if not self.selected_obj: return
        points = np.array(self.selected_obj.json_points, dtype=np.float32)
        if len(points) < 3: return
        self.save_state_for_undo()
        peri = cv2.arcLength(points, True)
        epsilon = 0.005 * peri 
        approx = cv2.approxPolyDP(points, epsilon, True)
        if len(approx) >= 3:
            self.selected_obj.json_points = approx.reshape(-1, 2).tolist()
            self.update()

    def apply_smart_intersection_snap(self, mouse_img_pos, mouse_screen_pos):
        pts = self.selected_obj.json_points
        n = len(pts)
        idx = self.hovered_point_idx
        
        p_prev = QPointF(*pts[(idx - 1) % n])
        p_next = QPointF(*pts[(idx + 1) % n])
        
        ref_vectors = []
        for i in range(n):
            if i == (idx - 1) % n or i == idx: continue
            p1 = QPointF(*pts[i])
            p2 = QPointF(*pts[(i+1)%n])
            vec = p2 - p1
            if vec.manhattanLength() > 0:
                ref_vectors.append(vec)

        best_pos = mouse_img_pos
        min_dist_screen = 15.0
        
        candidates_prev = copy.copy(ref_vectors)
        candidates_next = copy.copy(ref_vectors)

        # Intersection
        intersection_found = False
        for dir1 in candidates_prev:
            for dir2 in candidates_next:
                cross = dir1.x() * dir2.y() - dir1.y() * dir2.x()
                if abs(cross) < 1e-5: continue 
                
                diff = p_next - p_prev
                t = (diff.x() * dir2.y() - diff.y() * dir2.x()) / cross
                intersect_pt = QPointF(p_prev.x() + t * dir1.x(), p_prev.y() + t * dir1.y())
                
                intersect_screen = self.transform_to_screen(intersect_pt)
                dist = (intersect_screen - mouse_screen_pos).manhattanLength()
                
                if dist < min_dist_screen:
                    best_pos = intersect_pt
                    intersection_found = True
                    self.active_guides.append((p_prev, intersect_pt, 1))
                    self.active_guides.append((p_next, intersect_pt, 1))
                    return best_pos 

        # Single Line
        if not intersection_found:
            closest_dist = min_dist_screen
            for ref in candidates_prev:
                proj, dist = self.project_point_on_line(mouse_img_pos, p_prev, ref)
                proj_screen = self.transform_to_screen(proj)
                d_screen = (proj_screen - mouse_screen_pos).manhattanLength()
                if d_screen < closest_dist:
                    closest_dist = d_screen
                    best_pos = proj
                    self.active_guides = [(p_prev, proj, 0)]

            for ref in candidates_next:
                proj, dist = self.project_point_on_line(mouse_img_pos, p_next, ref)
                proj_screen = self.transform_to_screen(proj)
                d_screen = (proj_screen - mouse_screen_pos).manhattanLength()
                if d_screen < closest_dist:
                    closest_dist = d_screen
                    best_pos = proj
                    self.active_guides = [(p_next, proj, 0)]

        return best_pos

    def project_point_on_line(self, point, origin, direction):
        len_sq = direction.x()**2 + direction.y()**2
        if len_sq == 0: return origin, 0
        vec_p = point - origin
        t = (vec_p.x() * direction.x() + vec_p.y() * direction.y()) / len_sq
        proj = QPointF(origin.x() + t * direction.x(), origin.y() + t * direction.y())
        return proj, (point - proj).manhattanLength()


# --- MAIN WINDOW ---
class MaskEditorApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.scenes = [] 
        self.current_idx = 0
        self.global_registry = {} 
        self.all_unique_names = set() 
        self.preserved_selection_name = None

        self.init_ui()
        
        self.undo_action = QAction("Undo", self)
        self.undo_action.setShortcut(QKeySequence("Ctrl+Z"))
        self.undo_action.triggered.connect(self.trigger_undo)
        self.addAction(self.undo_action)
        
        self.redo_action = QAction("Redo", self)
        self.redo_action.setShortcut(QKeySequence("Ctrl+Y"))
        self.redo_action.triggered.connect(self.trigger_redo)
        self.addAction(self.redo_action)

    def init_ui(self):
        self.setWindowTitle("Smart Editor Pro")
        self.resize(1200, 800)
        self.setStyleSheet("background-color: #2b2b2b; color: #ffffff;")
        self.stacked_widget = QStackedWidget()
        self.setCentralWidget(self.stacked_widget)
        self.init_welcome_screen()
        self.init_editor_screen()

    # ГЛОБАЛЬНИЙ ОБРОБНИК КЛАВІШ
    def keyPressEvent(self, event):
        # Якщо ми пишемо текст в інпуті - не крутимо фото
        if isinstance(QApplication.focusWidget(), QLineEdit):
            super().keyPressEvent(event)
            return

        if event.key() == Qt.Key.Key_Left:
            self.prev_image()
        elif event.key() == Qt.Key.Key_Right:
            self.next_image()
        else:
            super().keyPressEvent(event)

    def init_welcome_screen(self):
        widget = QWidget()
        layout = QVBoxLayout()
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl = QLabel("Smart Editor Pro")
        lbl.setStyleSheet("font-size: 24px; font-weight: bold; margin-bottom: 20px;")
        layout.addWidget(lbl)
        btn = QPushButton("📂 Відкрити папку")
        btn.setFixedSize(200, 60)
        btn.setStyleSheet("background-color: #0078d7; font-size: 18px; border-radius: 8px;")
        btn.clicked.connect(self.select_folder)
        layout.addWidget(btn)
        widget.setLayout(layout)
        self.welcome_widget = widget
        self.stacked_widget.addWidget(self.welcome_widget)

    def init_editor_screen(self):
        self.editor_widget = QWidget()
        main_layout = QVBoxLayout(self.editor_widget)
        
        header = QHBoxLayout()
        self.lbl_info = QLabel("File: ...")
        self.lbl_info.setStyleSheet("font-weight: bold; font-size: 14px; margin-right: 15px;")
        header.addWidget(self.lbl_info)

        lbl_hint = QLabel("Колесо: Зум | ЛКМ: Тягати | ПКМ: Видалити | Ctrl+ЛКМ: Додати | Стрілки: Кадри")
        lbl_hint.setStyleSheet("color: #aaa; font-size: 12px; margin-right: 10px;")
        header.addWidget(lbl_hint)

        btn_undo = QPushButton("↩️")
        btn_undo.setToolTip("Undo (Ctrl+Z)")
        btn_undo.setFixedWidth(40)
        btn_undo.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn_undo.clicked.connect(self.trigger_undo)
        header.addWidget(btn_undo)
        
        btn_redo = QPushButton("↪️")
        btn_redo.setToolTip("Redo (Ctrl+Y)")
        btn_redo.setFixedWidth(40)
        btn_redo.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn_redo.clicked.connect(self.trigger_redo)
        header.addWidget(btn_redo)

        self.cb_smart_snap = QCheckBox("🧲 Smart Snap")
        self.cb_smart_snap.setChecked(True)
        self.cb_smart_snap.toggled.connect(self.toggle_smart_snap)
        self.cb_smart_snap.setStyleSheet("margin-left: 10px; margin-right: 10px;")
        self.cb_smart_snap.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        header.addWidget(self.cb_smart_snap)

        btn_simplify = QPushButton("📐 Спростити")
        btn_simplify.clicked.connect(self.simplify_current_shape)
        btn_simplify.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        header.addWidget(btn_simplify)
        
        self.lbl_selected = QLabel("Нічого не вибрано")
        self.lbl_selected.setStyleSheet("color: #00ff00; font-weight: bold; border: 1px solid #444; padding: 4px; border-radius: 4px;")
        header.addWidget(self.lbl_selected)
        
        header.addStretch()
        
        # Кнопка Експорту Проєкту
        btn_export = QPushButton("📦 Експорт проєкту")
        btn_export.setStyleSheet("background-color: #17a2b8; padding: 5px 15px;")
        btn_export.clicked.connect(self.export_project)
        btn_export.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        header.addWidget(btn_export)

        btn_save = QPushButton("💾 Зберегти JSON")
        btn_save.setStyleSheet("background-color: #28a745; padding: 5px 15px;")
        btn_save.clicked.connect(self.save_json)
        btn_save.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        header.addWidget(btn_save)
        
        btn_reset = QPushButton("🔄 Скинути")
        btn_reset.setStyleSheet("background-color: #dc3545; padding: 5px 15px;")
        btn_reset.clicked.connect(self.reset_app)
        btn_reset.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        header.addWidget(btn_reset)
        main_layout.addLayout(header)

        # Work Area
        work_area = QHBoxLayout()
        self.canvas = EditorCanvas(self)
        self.canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.canvas.objectSelected.connect(self.on_object_selected_in_canvas)
        
        canvas_container = QWidget()
        canvas_layout = QVBoxLayout(canvas_container)
        canvas_layout.setContentsMargins(0,0,0,0)
        canvas_layout.addWidget(self.canvas)
        
        nav_layout = QHBoxLayout()
        self.btn_prev = QPushButton("⬅️ Назад")
        self.btn_prev.clicked.connect(self.prev_image)
        self.btn_prev.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_next = QPushButton("Вперед ➡️")
        self.btn_next.clicked.connect(self.next_image)
        self.btn_next.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        nav_layout.addWidget(self.btn_prev)
        self.lbl_counter = QLabel("0 / 0")
        self.lbl_counter.setAlignment(Qt.AlignmentFlag.AlignCenter)
        nav_layout.addWidget(self.lbl_counter)
        nav_layout.addWidget(self.btn_next)
        canvas_layout.addLayout(nav_layout)
        work_area.addWidget(canvas_container, stretch=3)

        right_panel = QWidget()
        right_panel.setFixedWidth(300)
        right_layout = QVBoxLayout(right_panel)
        right_layout.addWidget(QLabel("Список об'єктів:"))
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

    def on_object_selected_in_canvas(self, msg):
        self.lbl_selected.setText(msg)
        if self.canvas.selected_obj:
            self.preserved_selection_name = self.canvas.selected_obj.display_name
        else:
            self.preserved_selection_name = None

    def toggle_smart_snap(self, checked):
        self.canvas.smart_snap_enabled = checked
        
    def simplify_current_shape(self):
        self.canvas.simplify_current_polygon()

    def trigger_undo(self):
        self.canvas.undo()

    def trigger_redo(self):
        self.canvas.redo()

    def sync_visibility(self, name, is_visible):
        if name in self.global_registry:
            self.global_registry[name]['visible'] = is_visible
        for scene in self.scenes:
            for obj in scene.objects:
                if obj.display_name == name:
                    obj.is_visible = is_visible
        self.update_view(update_list=False)

    def sync_color(self, name, color):
        if name in self.global_registry:
            self.global_registry[name]['color'] = color
        for scene in self.scenes:
            for obj in scene.objects:
                if obj.display_name == name:
                    obj.color = color
        self.update_view(update_list=False)

    def sync_name(self, old_name, new_name):
        if self.preserved_selection_name == old_name:
            self.preserved_selection_name = new_name
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
        self.update_view(update_list=True)

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
                self.update_view(update_list=True)
        except Exception as e:
            QMessageBox.critical(self, "Помилка", str(e))
        finally:
            QApplication.restoreOverrideCursor()

    def reset_app(self):
        self.scenes = []
        self.stacked_widget.setCurrentIndex(0)

    def prev_image(self):
        if self.scenes:
            self.current_idx = (self.current_idx - 1 + len(self.scenes)) % len(self.scenes)
            self.update_view(update_list=True)

    def next_image(self):
        if self.scenes:
            self.current_idx = (self.current_idx + 1) % len(self.scenes)
            self.update_view(update_list=True)

    def update_view(self, update_list=True):
        if not self.scenes: return
        scene = self.scenes[self.current_idx]
        self.lbl_info.setText(f"Файл: {os.path.basename(scene.main_path)}")
        self.lbl_counter.setText(f"{self.current_idx + 1} / {len(self.scenes)}")

        self.canvas.set_scene(scene)

        if self.preserved_selection_name:
            target_obj = next((o for o in scene.objects if o.display_name == self.preserved_selection_name), None)
            if target_obj:
                self.canvas.selected_obj = target_obj
                self.lbl_selected.setText(f"Вибрано: {target_obj.display_name}")
                self.canvas.update()
            else:
                self.lbl_selected.setText("Нічого не вибрано")
                self.canvas.selected_obj = None

        if update_list:
            while self.scroll_layout.count():
                child = self.scroll_layout.takeAt(0)
                if child.widget(): child.widget().deleteLater()
            
            sorted_names = sorted(list(self.all_unique_names))
            for name in sorted_names:
                obj_in_scene = next((o for o in scene.objects if o.display_name == name), None)
                if obj_in_scene:
                    obj_in_scene.is_present_in_frame = True
                    item = ObjectListItem(obj_in_scene, self)
                else:
                    settings = self.global_registry.get(name, {'color': Qt.GlobalColor.gray, 'visible': True})
                    ghost_obj = MaskObjectData("", [], [], settings['color'], name, settings['visible'])
                    ghost_obj.is_present_in_frame = False
                    item = ObjectListItem(ghost_obj, self)
                self.scroll_layout.addWidget(item)

    def export_project(self):
        if not self.scenes: return
        
        folder = QFileDialog.getExistingDirectory(self, "Виберіть папку для експорту")
        if not folder: return

        # Створюємо папку images
        images_dir = os.path.join(folder, "images")
        os.makedirs(images_dir, exist_ok=True)

        json_data = []
        
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            for scene in self.scenes:
                # 1. Копіюємо фото
                src_img = scene.main_path
                img_name = os.path.basename(src_img)
                dst_img = os.path.join(images_dir, img_name)
                
                if not os.path.exists(dst_img):
                    shutil.copy2(src_img, dst_img)

                # 2. Формуємо JSON
                entry = {"image_name": img_name, "objects": []}
                for obj in scene.objects:
                    if obj.is_visible:
                        entry["objects"].append({
                            "name": obj.display_name,
                            "original_mask": obj.original_filename,
                            "points": obj.json_points 
                        })
                json_data.append(entry)

            # 3. Зберігаємо JSON
            json_path = os.path.join(folder, "final_data.json")
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(json_data, f, separators=(',', ':'), ensure_ascii=False)
            
            QMessageBox.information(self, "Успіх", f"Проєкт експортовано в:\n{folder}")
            
        except Exception as e:
            QMessageBox.critical(self, "Помилка", f"Не вдалося експортувати: {e}")
        finally:
            QApplication.restoreOverrideCursor()

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
                        "points": obj.json_points 
                    })
            output_data.append(entry)
        try:
            with open(save_path, 'w', encoding='utf-8') as f:
                json.dump(output_data, f, separators=(',', ':'), ensure_ascii=False)
            QMessageBox.information(self, "Успіх", "JSON збережено!")
        except Exception as e:
            QMessageBox.critical(self, "Помилка", str(e))