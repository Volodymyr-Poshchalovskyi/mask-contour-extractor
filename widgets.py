from PyQt6.QtWidgets import (QWidget, QHBoxLayout, QCheckBox, 
                             QLineEdit, QPushButton, QColorDialog)
from PyQt6.QtCore import Qt

class ObjectListItem(QWidget):
    def __init__(self, obj_data, app_reference):
        super().__init__()
        self.obj_data = obj_data
        self.app = app_reference
        self.init_ui()

    def init_ui(self):
        layout = QHBoxLayout()
        layout.setContentsMargins(5, 5, 5, 5)

        # 1. Чекбокс
        self.cb_visible = QCheckBox()
        self.cb_visible.setChecked(self.obj_data.is_visible)
        self.cb_visible.clicked.connect(self.on_visibility_change)
        layout.addWidget(self.cb_visible)

        # 2. Поле вводу
        self.le_name = QLineEdit(self.obj_data.display_name)
        self.le_name.editingFinished.connect(self.on_name_change)
        if not self.obj_data.is_present_in_frame:
            self.le_name.setStyleSheet("color: #888; font-style: italic;")
            self.le_name.setToolTip("Немає на поточному кадрі")
        layout.addWidget(self.le_name)

        # 3. Кнопка кольору
        self.btn_color = QPushButton()
        self.btn_color.setFixedWidth(25)
        self.update_color_btn_style()
        self.btn_color.clicked.connect(self.on_color_pick)
        layout.addWidget(self.btn_color)

        self.setLayout(layout)
        # Рамка знизу
        self.setStyleSheet("border-bottom: 1px solid #444;")

    def update_color_btn_style(self):
        c = self.obj_data.color
        border = "1px solid #555" if self.obj_data.is_present_in_frame else "1px dashed #666"
        self.btn_color.setStyleSheet(f"background-color: {c.name()}; border: {border};")

    def on_visibility_change(self):
        self.app.sync_visibility(self.obj_data.display_name, self.cb_visible.isChecked())

    def on_name_change(self):
        new_name = self.le_name.text()
        old_name = self.obj_data.display_name
        if new_name != old_name:
            self.app.sync_name(old_name, new_name)

    def on_color_pick(self):
        color = QColorDialog.getColor(self.obj_data.color, self, "Оберіть колір")
        if color.isValid():
            self.app.sync_color(self.obj_data.display_name, color)
            self.update_color_btn_style()