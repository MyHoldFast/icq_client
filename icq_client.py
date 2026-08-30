import logging

from config import load_font_config
from resources import _init_status_sprite_index
from main_window import MainWindow

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

if __name__ == "__main__":
    load_font_config()
    _init_status_sprite_index()
    app = MainWindow()
    app.mainloop()
