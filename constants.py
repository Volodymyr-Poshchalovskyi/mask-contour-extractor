from PyQt6.QtGui import QColor

# Візуальні налаштування редактора
POINT_RADIUS = 6        # Розмір точки на екрані
LINE_WIDTH = 2          # Товщина лінії
HOVER_DIST = 10         # Відстань, на якій курсор "прилипає" до точки

# Палітра
DEFAULT_PALETTE = [
    QColor(255, 0, 0), QColor(0, 255, 0), QColor(0, 0, 255),
    QColor(255, 255, 0), QColor(255, 0, 255), QColor(0, 255, 255),
    QColor(255, 165, 0), QColor(128, 0, 128), QColor(0, 128, 128)
]

# Семантика (авто-колір)
SEMANTIC_COLORS = {
    "roof": QColor(255, 0, 0),
    "basement": QColor(128, 0, 128),
    "floor": QColor(0, 255, 0),
    "window": QColor(0, 255, 255),
    "wall": QColor(255, 165, 0)
}