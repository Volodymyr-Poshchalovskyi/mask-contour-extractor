from PyQt6.QtGui import QColor

# Точність відображення в програмі (не чіпаємо, щоб було гарно)
VISUAL_EPSILON = 0.0005

# Режими оптимізації для JSON
# epsilon_factor: чим більше число, тим грубіша лінія (менше точок)
OPTIMIZATION_MODES = {
    "Detailed":  {"type": "poly", "epsilon": 0.001}, # Точно по масці
    "Balanced":  {"type": "poly", "epsilon": 0.003}, # Стандарт
    "Straight":  {"type": "poly", "epsilon": 0.015}, # Жорсткі прямі лінії (дахи, стіни)
    "Rectangle": {"type": "rect", "epsilon": 0}      # Ідеальний прямокутник (вікна)
}

DEFAULT_PALETTE = [
    QColor(255, 0, 0), QColor(0, 255, 0), QColor(0, 0, 255),
    QColor(255, 255, 0), QColor(255, 0, 255), QColor(0, 255, 255),
    QColor(255, 165, 0), QColor(128, 0, 128), QColor(0, 128, 128)
]

SEMANTIC_COLORS = {
    "roof": QColor(255, 0, 0),
    "basement": QColor(128, 0, 128),
    "floor": QColor(0, 255, 0),
    "window": QColor(0, 255, 255),
    "wall": QColor(255, 165, 0)
}