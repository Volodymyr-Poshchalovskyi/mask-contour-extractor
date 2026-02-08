from PyQt6.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QCheckBox, 
                             QLineEdit, QPushButton, QColorDialog, QComboBox, QLabel)
from PyQt6.QtCore import Qt
from constants import OPTIMIZATION_MODES

class ObjectListItem(QWidget):
    def __init__(self, obj_data, app_reference):
        super().__init__()
        self.obj_data = obj_data
        self.app = app_reference
        self.init_ui()

    def init_ui(self):
        # Використовуємо вертикальний layout, щоб вмістити налаштування
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(5, 5, 5, 10)
        
        # Рядок 1: Чекбокс, Назва, Колір
        row1 = QHBoxLayout()
        
        self.cb_visible = QCheckBox()
        self.cb_visible.setChecked(self.obj_data.is_visible)
        self.cb_visible.clicked.connect(self.on_visibility_change)
        row1.addWidget(self.cb_visible)

        self.le_name = QLineEdit(self.obj_data.display_name)
        self.le_name.editingFinished.connect(self.on_name_change)
        if not self.obj_data.is_present_in_frame:
            self.le_name.setStyleSheet("color: #888; font-style: italic;")
            self.le_name.setToolTip("Немає на поточному кадрі")
        row1.addWidget(self.le_name)

        self.btn_color = QPushButton()
        self.btn_color.setFixedWidth(25)
        self.update_color_btn_style()
        self.btn_color.clicked.connect(self.on_color_pick)
        row1.addWidget(self.btn_color)
        
        main_layout.addLayout(row1)

        # Рядок 2: Вибір режиму ліній
        row2 = QHBoxLayout()
        row2.setContentsMargins(25, 0, 0, 0) # Відступ під назвою
        
        lbl_mode = QLabel("Lines:")
        lbl_mode.setStyleSheet("color: #aaa; font-size: 10px;")
        row2.addWidget(lbl_mode)

        self.combo_mode = QComboBox()
        self.combo_mode.addItems(list(OPTIMIZATION_MODES.keys()))
        self.combo_mode.setCurrentText(self.obj_data.optimization_mode)
        self.combo_mode.setStyleSheet("font-size: 11px; padding: 2px;")
        self.combo_mode.currentTextChanged.connect(self.on_mode_change)
        row2.addWidget(self.combo_mode)
        
        main_layout.addLayout(row2)

        self.setLayout(main_layout)
        
        # Додаємо рамку для відділення об'єктів
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
            
    def on_mode_change(self, mode_text):
        # Викликаємо синхронізацію режиму
        self.app.sync_mode(self.obj_data.display_name, mode_text)