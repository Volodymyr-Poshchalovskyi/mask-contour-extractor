import os
import json
import math
import copy
import cv2
import shutil
import numpy as np
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QLabel, QFileDialog, QMessageBox, 
                             QScrollArea, QStackedWidget, QSizePolicy, QApplication, 
                             QCheckBox, QLineEdit, QFrame)
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
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus) # Canvas не краде фокус у вікна
        
        self.scene = None
        self.current_image = None
        self.original_pixmap = None 
        
        self.zoom_level = 1.0
        self.offset = QPointF(0, 0)
        
        # --- CROP STATE ---
        self.global_crop_rect = None 
        self.is_cropping_mode = False
        self.temp_crop_rect = QRectF()
        self.crop_handle_size = 10
        self.active_crop_handle = None 
        self.crop_aspect_ratio = None 

        # Editor State
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
        
        if scene:
            cv_img = read_image_safe(scene.main_path, cv2.IMREAD_COLOR)
            if cv_img is not None:
                cv_img = cv2.cvtColor(cv_img, cv2.COLOR_BGR2RGB)
                h, w, ch = cv_img.shape
                bytes_per_line = ch * w
                q_img = QImage(cv_img.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
                self.original_pixmap = QPixmap.fromImage(q_img)
                
                # Ініціалізація кропу або підгонка під розмір
                if self.global_crop_rect is None:
                    self.global_crop_rect = QRectF(0, 0, w, h)
                else:
                    # Захист: якщо нове фото менше за попередній кроп
                    img_rect = QRectF(0, 0, w, h)
                    self.global_crop_rect = self.global_crop_rect.intersected(img_rect)
                    
                self.update_current_image_view()
            else:
                self.current_image = None
        else:
            self.current_image = None
        self.update()

    def update_current_image_view(self):
        """Вирізає шматок з original_pixmap для відображення"""
        if self.original_pixmap and self.global_crop_rect:
            # toRect() округлює, intersected гарантує межі
            safe_rect = self.global_crop_rect.toRect().intersected(self.original_pixmap.rect())
            self.current_image = self.original_pixmap.copy(safe_rect)
        else:
            self.current_image = self.original_pixmap

    # --- CROP LOGIC ---
    def start_crop_mode(self):
        self.is_cropping_mode = True
        if self.global_crop_rect:
            self.temp_crop_rect = self.global_crop_rect
        elif self.original_pixmap:
            self.temp_crop_rect = QRectF(0, 0, self.original_pixmap.width(), self.original_pixmap.height())
        self.update()

    def apply_crop(self):
        self.is_cropping_mode = False
        self.global_crop_rect = self.temp_crop_rect
        self.update_current_image_view()
        self.offset = QPointF(0, 0)
        self.zoom_level = 1.0 
        self.update()

    def cancel_crop(self):
        self.is_cropping_mode = False
        self.update()

    def set_aspect_ratio(self, ratio):
        self.crop_aspect_ratio = ratio
        if self.original_pixmap:
            img_w, img_h = self.original_pixmap.width(), self.original_pixmap.height()
            
            if ratio is None: # Free
                self.temp_crop_rect = QRectF(10, 10, img_w - 20, img_h - 20)
            else:
                target_w = img_w * 0.8
                target_h = target_w / ratio
                if target_h > img_h * 0.8:
                    target_h = img_h * 0.8
                    target_w = target_h * ratio
                
                x = (img_w - target_w) / 2
                y = (img_h - target_h) / 2
                self.temp_crop_rect = QRectF(x, y, target_w, target_h)
            self.update()

    # --- COORDINATES ---
    def transform_to_img_absolute(self, screen_pos):
        local_pos = (screen_pos - self.offset) / self.zoom_level
        if self.is_cropping_mode:
            return local_pos
        else:
            crop_offset = self.global_crop_rect.topLeft() if self.global_crop_rect else QPointF(0,0)
            return local_pos + crop_offset

    def transform_to_screen(self, absolute_img_pos):
        if self.is_cropping_mode:
            return (absolute_img_pos * self.zoom_level) + self.offset
        else:
            crop_offset = self.global_crop_rect.topLeft() if self.global_crop_rect else QPointF(0,0)
            return ((absolute_img_pos - crop_offset) * self.zoom_level) + self.offset

    # --- PAINTING ---
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#222"))

        if not self.scene or not self.original_pixmap:
            painter.setPen(Qt.GlobalColor.white)
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No Image Loaded")
            return

        # ЛОГІКА ВІДОБРАЖЕННЯ
        if self.is_cropping_mode:
            # 1. Малюємо ПОВНЕ фото
            img_rect = QRectF(self.offset.x(), self.offset.y(), 
                              self.original_pixmap.width() * self.zoom_level, 
                              self.original_pixmap.height() * self.zoom_level)
            painter.drawPixmap(img_rect.toRect(), self.original_pixmap)

            # 2. Затемнення
            overlay_color = QColor(0, 0, 0, 150)
            painter.setBrush(overlay_color)
            painter.setPen(Qt.PenStyle.NoPen)
            
            tl = self.transform_to_screen(self.temp_crop_rect.topLeft())
            br = self.transform_to_screen(self.temp_crop_rect.bottomRight())
            screen_crop_rect = QRectF(tl, br)
            
            # Малюємо 4 прямокутники навколо кропу (замість QPainterPath)
            painter.drawRect(QRectF(0, 0, self.width(), screen_crop_rect.top())) # Верх
            painter.drawRect(QRectF(0, screen_crop_rect.bottom(), self.width(), self.height() - screen_crop_rect.bottom())) # Низ
            painter.drawRect(QRectF(0, screen_crop_rect.top(), screen_crop_rect.left(), screen_crop_rect.height())) # Ліво
            painter.drawRect(QRectF(screen_crop_rect.right(), screen_crop_rect.top(), self.width() - screen_crop_rect.right(), screen_crop_rect.height())) # Право

            # 3. Рамка кропу
            pen = QPen(Qt.GlobalColor.white, 2, Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(screen_crop_rect)

            # 4. Ручки
            painter.setBrush(Qt.GlobalColor.white)
            painter.setPen(Qt.GlobalColor.black)
            handles = self.get_crop_handles(screen_crop_rect)
            for h_rect in handles.values():
                painter.drawRect(h_rect)
                
            # Сітка третин
            pen.setColor(QColor(255, 255, 255, 80))
            pen.setStyle(Qt.PenStyle.SolidLine)
            pen.setWidth(1)
            painter.setPen(pen)
            w3 = screen_crop_rect.width() / 3
            h3 = screen_crop_rect.height() / 3
            painter.drawLine(QPointF(screen_crop_rect.left() + w3, screen_crop_rect.top()), QPointF(screen_crop_rect.left() + w3, screen_crop_rect.bottom()))
            painter.drawLine(QPointF(screen_crop_rect.left() + 2*w3, screen_crop_rect.top()), QPointF(screen_crop_rect.left() + 2*w3, screen_crop_rect.bottom()))
            painter.drawLine(QPointF(screen_crop_rect.left(), screen_crop_rect.top() + h3), QPointF(screen_crop_rect.right(), screen_crop_rect.top() + h3))
            painter.drawLine(QPointF(screen_crop_rect.left(), screen_crop_rect.top() + 2*h3), QPointF(screen_crop_rect.right(), screen_crop_rect.top() + 2*h3))

        else:
            # ЗВИЧАЙНИЙ РЕЖИМ
            if self.current_image:
                img_rect = QRectF(self.offset.x(), self.offset.y(), 
                                  self.current_image.width() * self.zoom_level, 
                                  self.current_image.height() * self.zoom_level)
                painter.drawPixmap(img_rect.toRect(), self.current_image)

            # Малюємо об'єкти
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
                
                if obj == self.selected_obj and self.active_guides:
                   for p1_img, p2_img, g_type in self.active_guides:
                        s1 = self.transform_to_screen(p1_img)
                        s2 = self.transform_to_screen(p2_img)
                        guide_pen = QPen(QColor("#FFD700") if g_type == 1 else QColor("#00FFFF"))
                        guide_pen.setWidth(2 if g_type == 1 else 1)
                        if g_type == 0: guide_pen.setStyle(Qt.PenStyle.DashLine)
                        painter.setPen(guide_pen)
                        painter.drawLine(s1, s2)

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

    def get_crop_handles(self, rect):
        s = self.crop_handle_size
        return {
            'tl': QRectF(rect.left(), rect.top(), s, s),
            'tr': QRectF(rect.right()-s, rect.top(), s, s),
            'bl': QRectF(rect.left(), rect.bottom()-s, s, s),
            'br': QRectF(rect.right()-s, rect.bottom()-s, s, s),
        }

    # --- MOUSE LOGIC ---
    def mousePressEvent(self, event):
        pos = event.position()
        
        if self.is_cropping_mode:
            tl = self.transform_to_screen(self.temp_crop_rect.topLeft())
            br = self.transform_to_screen(self.temp_crop_rect.bottomRight())
            screen_rect = QRectF(tl, br)
            
            handles = self.get_crop_handles(screen_rect)
            clicked_handle = None
            for name, h_rect in handles.items():
                if h_rect.contains(pos):
                    clicked_handle = name
                    break
            
            if clicked_handle:
                self.active_crop_handle = clicked_handle
                self.last_mouse_pos = pos
            elif screen_rect.contains(pos):
                self.active_crop_handle = 'move'
                self.last_mouse_pos = pos
            else:
                self.drag_active = True
                self.last_mouse_pos = pos
            return

        self.parent_app.setFocus() # Повертаємо фокус головному вікну для стрілок
        
        if event.button() == Qt.MouseButton.LeftButton:
            if self.selected_obj:
                if self.hovered_point_idx != -1:
                    self.save_state_for_undo()
                    self.dragging_point = True
                    return
                if self.hovered_segment_idx != -1 and (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
                    self.save_state_for_undo()
                    img_pt = self.transform_to_img_absolute(event.position())
                    self.selected_obj.json_points.insert(self.hovered_segment_idx + 1, [img_pt.x(), img_pt.y()])
                    self.hovered_point_idx = self.hovered_segment_idx + 1
                    self.dragging_point = True
                    self.hovered_segment_point = None
                    self.update()
                    return

            clicked_obj = self.find_object_at_pos(pos)
            if clicked_obj:
                self.selected_obj = clicked_obj
                self.objectSelected.emit(f"Вибрано: {clicked_obj.display_name}")
                self.update()
            else:
                self.drag_active = True
                self.last_mouse_pos = pos
                self.update()
        elif event.button() == Qt.MouseButton.RightButton:
            if self.selected_obj and self.hovered_point_idx != -1:
                if len(self.selected_obj.json_points) > 3:
                    self.save_state_for_undo()
                    del self.selected_obj.json_points[self.hovered_point_idx]
                    self.hovered_point_idx = -1
                    self.update()

    def mouseMoveEvent(self, event):
        pos = event.position()
        
        if self.is_cropping_mode:
            if self.active_crop_handle:
                delta_screen = pos - self.last_mouse_pos
                delta_img = delta_screen / self.zoom_level
                
                rect = self.temp_crop_rect
                
                if self.active_crop_handle == 'move':
                    rect.translate(delta_img.x(), delta_img.y())
                else:
                    new_rect = QRectF(rect)
                    if 'l' in self.active_crop_handle: new_rect.setLeft(new_rect.left() + delta_img.x())
                    if 'r' in self.active_crop_handle: new_rect.setRight(new_rect.right() + delta_img.x())
                    if 't' in self.active_crop_handle: new_rect.setTop(new_rect.top() + delta_img.y())
                    if 'b' in self.active_crop_handle: new_rect.setBottom(new_rect.bottom() + delta_img.y())
                    
                    new_rect = new_rect.normalized()

                    if self.crop_aspect_ratio:
                        if self.active_crop_handle in ['br', 'tr', 'bl', 'tl']:
                             current_ratio = new_rect.width() / new_rect.height() if new_rect.height() > 0 else 1
                             if current_ratio > self.crop_aspect_ratio:
                                 new_rect.setHeight(new_rect.width() / self.crop_aspect_ratio)
                             else:
                                 new_rect.setWidth(new_rect.height() * self.crop_aspect_ratio)
                    self.temp_crop_rect = new_rect

                self.last_mouse_pos = pos
                self.update()
            elif self.drag_active:
                delta = pos - self.last_mouse_pos
                self.offset += delta
                self.last_mouse_pos = pos
                self.update()
            return

        self.active_guides = []
        if self.dragging_point and self.selected_obj:
            raw_img_pos = self.transform_to_img_absolute(pos)
            final_pos = raw_img_pos
            
            snap_dist_screen = 15
            snapped_to_vertex = False
            for obj in self.scene.objects:
                if obj == self.selected_obj or not obj.is_visible: continue
                for pt in obj.json_points:
                    pt_screen = self.transform_to_screen(QPointF(pt[0], pt[1]))
                    if (pt_screen - pos).manhattanLength() < snap_dist_screen:
                        final_pos = QPointF(pt[0], pt[1])
                        snapped_to_vertex = True
                        break
                if snapped_to_vertex: break
            
            if not snapped_to_vertex and self.smart_snap_enabled:
                final_pos = self.apply_smart_intersection_snap(raw_img_pos, pos)

            self.selected_obj.json_points[self.hovered_point_idx] = [final_pos.x(), final_pos.y()]
            self.update()
            return

        if self.drag_active:
            delta = pos - self.last_mouse_pos
            self.offset += delta
            self.last_mouse_pos = pos
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
                if (pt - pos).manhattanLength() < min_dist:
                    self.hovered_point_idx = i
                    self.update()
                    return
            if (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
                for i in range(len(screen_points)):
                    p1 = screen_points[i]
                    p2 = screen_points[(i + 1) % len(screen_points)]
                    dist, projection = self.point_segment_dist(pos, p1, p2)
                    if dist < min_dist:
                        self.hovered_segment_idx = i
                        self.hovered_segment_point = projection
                        self.update()
                        return
        self.update()

    def mouseReleaseEvent(self, event):
        self.drag_active = False
        self.dragging_point = False
        self.active_crop_handle = None
        self.active_guides = []
        self.update()

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta == 0: delta = event.pixelDelta().y() * 10
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

    # --- HELPERS AND MATH ---
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
        proj = QPointF(v.x() + t * (w.x() - v.x()), v.y() + t * (w.y() - v.y()))
        dist = (p - proj).manhattanLength()
        return dist, proj

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
            if vec.manhattanLength() > 0: ref_vectors.append(vec)
        best_pos = mouse_img_pos
        min_dist_screen = 15.0
        candidates_prev = copy.copy(ref_vectors)
        candidates_next = copy.copy(ref_vectors)
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
        if not intersection_found:
            closest_dist = min_dist_screen
            for ref in candidates_prev:
                proj, dist_val = self.project_point_on_line(mouse_img_pos, p_prev, ref)
                proj_screen = self.transform_to_screen(proj)
                d_screen = (proj_screen - mouse_screen_pos).manhattanLength()
                if d_screen < closest_dist:
                    closest_dist = d_screen
                    best_pos = proj
                    self.active_guides = [(p_prev, proj, 0)]
            for ref in candidates_next:
                proj, dist_val = self.project_point_on_line(mouse_img_pos, p_next, ref)
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
        self.resize(1300, 850)
        self.setStyleSheet("background-color: #2b2b2b; color: #ffffff;")
        self.stacked_widget = QStackedWidget()
        self.setCentralWidget(self.stacked_widget)
        self.init_welcome_screen()
        self.init_editor_screen()

    def keyPressEvent(self, event):
        if isinstance(QApplication.focusWidget(), QLineEdit):
            super().keyPressEvent(event)
            return
        if event.key() == Qt.Key.Key_Left: self.prev_image()
        elif event.key() == Qt.Key.Key_Right: self.next_image()
        else: super().keyPressEvent(event)

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
        
        toolbar = QFrame()
        toolbar.setStyleSheet("background-color: #333; border-bottom: 1px solid #444;")
        tb_layout = QHBoxLayout(toolbar)
        tb_layout.setContentsMargins(10, 5, 10, 5)

        self.lbl_info = QLabel("File: ...")
        self.lbl_info.setStyleSheet("font-weight: bold; font-size: 14px; margin-right: 15px;")
        tb_layout.addWidget(self.lbl_info)

        lbl_hint = QLabel("Зум: Колесо | ЛКМ: Тягати | Ctrl+ЛКМ: Додати | ПКМ: Видалити | Стрілки: Кадри")
        lbl_hint.setStyleSheet("color: #aaa; font-size: 11px; margin-right: 10px;")
        tb_layout.addWidget(lbl_hint)

        btn_undo = QPushButton("↩️")
        btn_undo.setFixedWidth(30)
        btn_undo.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn_undo.clicked.connect(self.trigger_undo)
        tb_layout.addWidget(btn_undo)
        
        btn_redo = QPushButton("↪️")
        btn_redo.setFixedWidth(30)
        btn_redo.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn_redo.clicked.connect(self.trigger_redo)
        tb_layout.addWidget(btn_redo)

        self.cb_smart_snap = QCheckBox("🧲 Snap")
        self.cb_smart_snap.setChecked(True)
        self.cb_smart_snap.toggled.connect(self.toggle_smart_snap)
        self.cb_smart_snap.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        tb_layout.addWidget(self.cb_smart_snap)

        btn_simplify = QPushButton("📐 Спростити")
        btn_simplify.clicked.connect(self.simplify_current_shape)
        btn_simplify.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        tb_layout.addWidget(btn_simplify)
        
        tb_layout.addSpacing(20)
        lbl_crop = QLabel("✂️")
        tb_layout.addWidget(lbl_crop)
        
        btn_crop_mode = QPushButton("Обрізати")
        btn_crop_mode.setCheckable(True)
        btn_crop_mode.clicked.connect(self.toggle_crop_mode)
        btn_crop_mode.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_crop_mode = btn_crop_mode
        tb_layout.addWidget(btn_crop_mode)

        self.crop_panel = QWidget()
        crop_layout = QHBoxLayout(self.crop_panel)
        crop_layout.setContentsMargins(0,0,0,0)
        
        btn_16_9 = QPushButton("16:9")
        btn_16_9.clicked.connect(lambda: self.canvas.set_aspect_ratio(16/9))
        btn_16_9.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        crop_layout.addWidget(btn_16_9)

        btn_4_3 = QPushButton("4:3")
        btn_4_3.clicked.connect(lambda: self.canvas.set_aspect_ratio(4/3))
        btn_4_3.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        crop_layout.addWidget(btn_4_3)
        
        btn_1_1 = QPushButton("1:1")
        btn_1_1.clicked.connect(lambda: self.canvas.set_aspect_ratio(1.0))
        btn_1_1.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        crop_layout.addWidget(btn_1_1)
        
        btn_free = QPushButton("Free")
        btn_free.clicked.connect(lambda: self.canvas.set_aspect_ratio(None))
        btn_free.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        crop_layout.addWidget(btn_free)
        
        btn_apply_crop = QPushButton("✅ Apply")
        btn_apply_crop.clicked.connect(self.apply_crop)
        btn_apply_crop.setStyleSheet("background-color: #28a745;")
        btn_apply_crop.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        crop_layout.addWidget(btn_apply_crop)

        self.crop_panel.setVisible(False)
        tb_layout.addWidget(self.crop_panel)

        tb_layout.addStretch()
        
        self.lbl_selected = QLabel("Нічого")
        self.lbl_selected.setStyleSheet("color: #00ff00; font-weight: bold;")
        tb_layout.addWidget(self.lbl_selected)

        btn_export = QPushButton("📦 Експорт")
        btn_export.setStyleSheet("background-color: #17a2b8;")
        btn_export.clicked.connect(self.export_project)
        btn_export.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        tb_layout.addWidget(btn_export)

        btn_save = QPushButton("💾 JSON")
        btn_save.clicked.connect(self.save_json)
        btn_save.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        tb_layout.addWidget(btn_save)
        
        main_layout.addWidget(toolbar)

        work_area = QHBoxLayout()
        self.canvas = EditorCanvas(self)
        self.canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.canvas.objectSelected.connect(self.on_object_selected_in_canvas)
        
        canvas_container = QWidget()
        canvas_layout = QVBoxLayout(canvas_container)
        canvas_layout.setContentsMargins(0,0,0,0)
        canvas_layout.addWidget(self.canvas)
        
        nav_layout = QHBoxLayout()
        self.btn_prev = QPushButton("⬅️")
        self.btn_prev.clicked.connect(self.prev_image)
        self.btn_prev.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_next = QPushButton("➡️")
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

    def toggle_crop_mode(self):
        if self.btn_crop_mode.isChecked():
            self.canvas.start_crop_mode()
            self.crop_panel.setVisible(True)
        else:
            self.canvas.cancel_crop()
            self.crop_panel.setVisible(False)
            
    def apply_crop(self):
        self.canvas.apply_crop()
        self.btn_crop_mode.setChecked(False)
        self.crop_panel.setVisible(False)

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

    def trigger_undo(self): self.canvas.undo()
    def trigger_redo(self): self.canvas.redo()

    def sync_visibility(self, name, is_visible):
        if name in self.global_registry: self.global_registry[name]['visible'] = is_visible
        for scene in self.scenes:
            for obj in scene.objects:
                if obj.display_name == name: obj.is_visible = is_visible
        self.update_view(update_list=False)

    def sync_color(self, name, color):
        if name in self.global_registry: self.global_registry[name]['color'] = color
        for scene in self.scenes:
            for obj in scene.objects:
                if obj.display_name == name: obj.color = color
        self.update_view(update_list=False)

    def sync_name(self, old_name, new_name):
        if self.preserved_selection_name == old_name: self.preserved_selection_name = new_name
        if old_name in self.global_registry:
            data = self.global_registry.pop(old_name)
            self.global_registry[new_name] = data
        if old_name in self.all_unique_names:
            self.all_unique_names.remove(old_name)
            self.all_unique_names.add(new_name)
        for scene in self.scenes:
            for obj in scene.objects:
                if obj.display_name == old_name: obj.display_name = new_name
        self.update_view(update_list=True)

    def select_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Виберіть папку")
        if folder: self.process_folder(folder)

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
        self.lbl_info.setText(f"File: {os.path.basename(scene.main_path)}")
        self.lbl_counter.setText(f"{self.current_idx + 1} / {len(self.scenes)}")

        self.canvas.set_scene(scene)

        if self.preserved_selection_name:
            target_obj = next((o for o in scene.objects if o.display_name == self.preserved_selection_name), None)
            if target_obj:
                self.canvas.selected_obj = target_obj
                self.lbl_selected.setText(f"Вибрано: {target_obj.display_name}")
                self.canvas.update()
            else:
                self.lbl_selected.setText("Нічого")
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

        images_dir = os.path.join(folder, "images")
        os.makedirs(images_dir, exist_ok=True)
        json_data = []
        
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            crop_rect = self.canvas.global_crop_rect
            
            for scene in self.scenes:
                src_img = scene.main_path
                img_name = os.path.basename(src_img)
                dst_img = os.path.join(images_dir, img_name)
                
                # --- CROP IMAGE EXPORT ---
                if crop_rect:
                    # ВАЖЛИВО: Використовуємо read_image_safe для читання (Unicode шляхи)
                    img_cv = read_image_safe(src_img, cv2.IMREAD_COLOR) 
                    
                    if img_cv is not None:
                        x, y, w, h = int(crop_rect.x()), int(crop_rect.y()), int(crop_rect.width()), int(crop_rect.height())
                        h_src, w_src = img_cv.shape[:2]
                        x = max(0, x); y = max(0, y)
                        w = min(w, w_src - x); h = min(h, h_src - y)
                        
                        cropped_img = img_cv[y:y+h, x:x+w]
                        
                        # Для збереження також треба обережно (imencode + tofile) для Unicode
                        is_success, buffer = cv2.imencode(".jpg", cropped_img)
                        if is_success:
                            with open(dst_img, "wb") as f:
                                f.write(buffer)
                    else:
                        shutil.copy2(src_img, dst_img)
                else:
                    shutil.copy2(src_img, dst_img)

                # --- JSON ---
                entry = {"image_name": img_name, "objects": []}
                offset_x = crop_rect.x() if crop_rect else 0
                offset_y = crop_rect.y() if crop_rect else 0
                
                for obj in scene.objects:
                    if obj.is_visible:
                        shifted_points = [[p[0] - offset_x, p[1] - offset_y] for p in obj.json_points]
                        entry["objects"].append({
                            "name": obj.display_name,
                            "original_mask": obj.original_filename,
                            "points": shifted_points 
                        })
                json_data.append(entry)

            json_path = os.path.join(folder, "final_data.json")
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(json_data, f, separators=(',', ':'), ensure_ascii=False)
            
            QMessageBox.information(self, "Успіх", f"Проєкт експортовано!\nФото обрізано і збережено в images/.")
            
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