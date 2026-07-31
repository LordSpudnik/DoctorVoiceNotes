import customtkinter as ctk

from src.ui.main_window import MainWindow
from src.utils.config_manager import ConfigManager

if __name__ == "__main__":
    config = ConfigManager()
    config.load()

    root = ctk.CTk()
    app = MainWindow(root, config)
    root.mainloop()