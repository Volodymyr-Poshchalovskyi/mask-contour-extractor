class MaskObjectData:
    """Дані про один конкретний об'єкт (маску)"""
    def __init__(self, original_filename, visual_points, json_points, color, display_name, is_visible=True):
        self.original_filename = original_filename
        self.visual_points = visual_points
        self.json_points = json_points
        self.display_name = display_name
        self.color = color
        self.is_visible = is_visible
        self.is_present_in_frame = True 

class ImageSceneData:
    """Дані про одну сцену (основне фото + список об'єктів)"""
    def __init__(self, main_path):
        self.main_path = main_path
        self.objects = []