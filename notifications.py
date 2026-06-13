"""
notifications.py — всплывающие уведомления:
  DesktopNotification, ConnectionLostNotification.
"""
import tkinter as tk
from theme import PALETTE


class DesktopNotification(tk.Toplevel):
    def __init__(self, master, uin, display_name, msg_snippet, callback,
                 auto_close: bool = True):
        super().__init__(master)
        self.callback = callback
        self.title("ICQ Notify")
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(bg=PALETTE["title_bar"])

        w, h   = 260, 70
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        x, y   = sw - w - 20, sh - h - 50
        self.geometry(f"{w}x{h}+{x}+{y}")

        tk.Frame(self, height=2, bg=PALETTE["accent"]).pack(fill="x", side="top")
        body = tk.Frame(self, bg=PALETTE["title_bar"], padx=10, pady=5)
        body.pack(fill="both", expand=True)
        tk.Label(body, text=f"✉ {display_name}", font=("Segoe UI Symbol", 9, "bold"),
                 bg=PALETTE["title_bar"], fg="white", anchor="w").pack(fill="x")
        tk.Label(body, text=msg_snippet, font=("Segoe UI Symbol", 8),
                 bg=PALETTE["title_bar"], fg="#d0e8ff", anchor="w",
                 wraplength=240, justify="left").pack(fill="x", pady=(2, 0))

        for w in (self, body):
            w.bind("<Button-1>", self._on_click)

        if auto_close:
            self.after(5000, self._safe_destroy)
        else:
            close_lbl = tk.Label(body, text="✕", font=("Segoe UI Symbol", 8),
                                 bg=PALETTE["title_bar"], fg="#ffaaaa", cursor="hand2")
            close_lbl.place(relx=1.0, rely=0.0, anchor="ne", x=-4, y=2)
            close_lbl.bind("<Button-1>", lambda e: self._safe_destroy())

    def _safe_destroy(self):
        try:
            self.destroy()
        except Exception:
            pass

    def _on_click(self, event=None):
        self.destroy()
        if self.callback:
            self.callback()


class ConnectionLostNotification(tk.Toplevel):
    """Красная плашка об обрыве — висит пока пользователь не кликнет."""
    def __init__(self, master, message: str, callback=None):
        super().__init__(master)
        self.callback   = callback
        self.on_dismiss = None
        self.title("ICQ")
        self.overrideredirect(True)
        self.attributes("-topmost", True)

        BG     = "#7a1a1a"
        STRIPE = "#cc2222"
        FG     = "#ffffff"
        FG2    = "#ffcccc"

        self.configure(bg=BG)
        w, h   = 280, 76
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        x      = sw - w - 20
        y      = sh - h - 50
        self.geometry(f"{w}x{h}+{x}+{y}")

        tk.Frame(self, height=3, bg=STRIPE).pack(fill="x", side="top")
        body = tk.Frame(self, bg=BG, padx=10, pady=6)
        body.pack(fill="both", expand=True)

        top_row = tk.Frame(body, bg=BG)
        top_row.pack(fill="x")
        tk.Label(top_row, text="⚠ Обрыв связи", font=("Segoe UI Symbol", 9, "bold"),
                 bg=BG, fg=FG, anchor="w").pack(side="left", fill="x", expand=True)
        close_lbl = tk.Label(top_row, text="✕", font=("Segoe UI Symbol", 8),
                              bg=BG, fg="#ffaaaa", cursor="hand2", padx=4)
        close_lbl.pack(side="right")
        close_lbl.bind("<Button-1>", lambda e: self._dismiss())

        tk.Label(body, text=message, font=("Segoe UI Symbol", 8),
                 bg=BG, fg=FG2, anchor="w", wraplength=256,
                 justify="left").pack(fill="x", pady=(2, 0))

        for widget in (self, body):
            widget.bind("<Button-1>", self._on_click)

    def _on_click(self, event=None):
        self._dismiss()
        if self.callback:
            self.callback()

    def _dismiss(self, event=None):
        if self.on_dismiss:
            try: self.on_dismiss(self)
            except Exception: pass
        try:
            self.destroy()
        except Exception:
            pass
