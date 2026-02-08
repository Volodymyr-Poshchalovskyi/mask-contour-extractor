class MaskObjectData:
    def __init__(self, original_filename, visual_points, json_points, color, display_name, is_visible=True, optimization_mode="Balanced"):
        self.original_filename = original_filename
        self.visual_points = visual_points # Для малювання в програмі (червоне)
        self.json_points = json_points     # Для збереження в JSON (зелене на сайті)
        self.display_name = display_name
        self.color = color
        self.is_visible = is_visible
        self.optimization_mode = optimization_mode # Запам'ятовуємо режим ("Rectangle", "Straight"...)
        self.is_present_in_frame = True 

class ImageSceneData:
    def __init__(self, main_path):
        self.main_path = main_path
        self.objects = []