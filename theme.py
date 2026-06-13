"""
theme.py — цветовая палитра, маппинги статусов и общие UI-утилиты.
"""
import tkinter as tk
from datetime import datetime
from typing import Optional

from icq_core import Status

# ── Цветовая палитра ──────────────────────────────────────────────────────────
PALETTE = {
    "bg_main":        "#d4e8f0",
    "bg_header":      "#b8d4e8",
    "bg_list":        "#eaf4fb",
    "bg_online":      "#ffffff",
    "bg_offline":     "#f0f0f0",
    "fg_online":      "#008000",
    "fg_offline":     "#808080",
    "fg_away":        "#0000cc",
    "fg_dnd":         "#cc0000",
    "fg_free":        "#008000",
    "fg_na":          "#888800",
    "fg_group":       "#000080",
    "accent":         "#0055aa",
    "msg_in_bg":      "#ffffff",
    "msg_out_bg":     "#dff0d8",
    "msg_nick_in":    "#cc0000",
    "msg_nick_out":   "#0000cc",
    "msg_time":       "#808080",
    "msg_text":       "#000000",
    "toolbar_bg":     "#c8dce8",
    "status_bar_bg":  "#b0c8dc",
    "input_bg":       "#ffffff",
    "border":         "#8aabcc",
    "title_bar":      "#6a9ec4",
    "select_bg":      "#b3d4f0",
    "tab_active":     "#ffffff",
    "tab_inactive":   "#c8dce8",
    "tab_unread":     "#ff6600",
    "tab_unread_fg":  "#ffffff",
    "unread_badge":   "#ff4400",
    "typing_fg":      "#006600",
    "separator":      "#9bbfd8",
}

STATUS_COLORS = {
    Status.ONLINE:  PALETTE["fg_online"],
    Status.AWAY:    PALETTE["fg_away"],
    Status.DND:     PALETTE["fg_dnd"],
    Status.NA:      PALETTE["fg_na"],
    Status.FREE:    PALETTE["fg_free"],
    Status.OFFLINE: PALETTE["fg_offline"],
}

STATUS_ICONS = {
    Status.ONLINE:  "●",
    Status.AWAY:    "◑",
    Status.DND:     "⊗",
    Status.NA:      "⊘",
    Status.FREE:    "✿",
    Status.OFFLINE: "○",
}

STATUS_LABELS = {
    Status.ONLINE:  "В сети",
    Status.AWAY:    "Отошёл",
    Status.DND:     "Не беспокоить",
    Status.NA:      "Недоступен",
    Status.FREE:    "Свободен",
    Status.OFFLINE: "Не в сети",
}

# ── Утилиты ───────────────────────────────────────────────────────────────────
def fmt_time(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%H:%M:%S %d/%m/%Y")

def schedule_in_tk(root: tk.Tk, fn, *args):
    root.after(0, fn, *args)

def place_near_parent(win: tk.Toplevel, parent: tk.Misc):
    """Открывает win рядом с parent, не вылезая за края экрана."""
    win.withdraw()
    win.update_idletasks()
    px, py = parent.winfo_rootx(), parent.winfo_rooty()
    pw, ph = parent.winfo_width(), parent.winfo_height()
    ww, wh = win.winfo_reqwidth(), win.winfo_reqheight()
    sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
    x = px + pw + 4
    if x + ww > sw:
        x = px - ww - 4
    if x < 0:
        x = max(0, px + (pw - ww) // 2)
    y = py
    if y + wh > sh:
        y = max(0, sh - wh)
    win.geometry(f"+{x}+{y}")
    win.deiconify()
