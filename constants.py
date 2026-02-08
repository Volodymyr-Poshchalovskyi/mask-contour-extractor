from PyQt6.QtGui import QColor

# Налаштування точності
VISUAL_EPSILON = 0.0005  # Деталізація для екрану
JSON_EPSILON = 0.003     # Оптимізація для файлу (Smart JSON)

# Палітра кольорів
DEFAULT_PALETTE = [
    QColor(255, 0, 0), QColor(0, 255, 0), QColor(0, 0, 255),
    QColor(255, 255, 0), QColor(255, 0, 255), QColor(0, 255, 255),
    QColor(255, 165, 0), QColor(128, 0, 128), QColor(0, 128, 128)
]