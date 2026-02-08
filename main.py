import sys
from PyQt6.QtWidgets import QApplication
from main_window import MaskEditorApp

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MaskEditorApp()
    window.show()
    sys.exit(app.exec())