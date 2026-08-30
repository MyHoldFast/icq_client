import os
import sys
import threading
from typing import Dict, Optional

def get_resource_path(relative_path: str) -> str:
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        exe_path = os.path.join(exe_dir, relative_path)
        if os.path.exists(exe_path):
            return exe_path
        return os.path.join(sys._MEIPASS, relative_path)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(script_dir, relative_path)

TRAY_AVAILABLE = False
try:
    import pystray
    from PIL import Image, ImageDraw, ImageTk, ImageSequence
    TRAY_AVAILABLE = True
except ImportError:
    print("⚠ pystray или Pillow не найдены. Сворачивание в трей будет отключено.")
    print("   Установите: pip install pystray Pillow")

XSTATUS_ICON_W = 16
XSTATUS_ICON_H = 16

_XSTATUS_PHOTO_CACHE: Dict[int, object] = {}
_XSTATUS_SPRITE: Optional[object] = None

def _load_xstatus_sprite():
    global _XSTATUS_SPRITE
    if _XSTATUS_SPRITE is not None:
        return _XSTATUS_SPRITE
    if not TRAY_AVAILABLE:
        return None
    path = get_resource_path(os.path.join("icons", "xstatus.png"))
    if not os.path.exists(path):
        return None
    try:
        _XSTATUS_SPRITE = Image.open(path).convert("RGBA")
    except Exception as e:
        print(f"xStatus: не удалось загрузить спрайт: {e}")
    return _XSTATUS_SPRITE

def get_xstatus_photo(index: int) -> Optional[object]:
    if not TRAY_AVAILABLE:
        return None
    sprite = _load_xstatus_sprite()
    if sprite is None:
        return None
    total = sprite.width // XSTATUS_ICON_W
    if index < 0:
        index = total + index
    if index < 0 or index >= total:
        return None
    if index in _XSTATUS_PHOTO_CACHE:
        return _XSTATUS_PHOTO_CACHE[index]
    x0 = index * XSTATUS_ICON_W
    icon = sprite.crop((x0, 0, x0 + XSTATUS_ICON_W, XSTATUS_ICON_H))
    photo = ImageTk.PhotoImage(icon)
    _XSTATUS_PHOTO_CACHE[index] = photo
    return photo

def get_xstatus_index_by_name(name: str) -> int:
    try:
        from icq_core import XSTATUS_TABLE
        for i, (_, n) in enumerate(XSTATUS_TABLE):
            if n == name:
                return i
    except Exception:
        pass
    return -1

STATUS_ICON_W = 16
STATUS_ICON_H = 16

_STATUS_SPRITE_INDEX: dict = {}

def _init_status_sprite_index():
    try:
        from icq_core import Status as _S
        _STATUS_SPRITE_INDEX[_S.AWAY]    = 0
        _STATUS_SPRITE_INDEX[_S.FREE]    = 1
        _STATUS_SPRITE_INDEX[_S.DND]     = 2
        _STATUS_SPRITE_INDEX[_S.NA]      = 4
        _STATUS_SPRITE_INDEX[_S.OFFLINE] = 6
        _STATUS_SPRITE_INDEX[_S.ONLINE]  = 7
    except Exception:
        pass

_STATUS_SPRITE: Optional[object] = None
_STATUS_PHOTO_CACHE: Dict[int, object] = {}

def _load_status_sprite():
    global _STATUS_SPRITE
    if _STATUS_SPRITE is not None:
        return _STATUS_SPRITE
    if not TRAY_AVAILABLE:
        return None
    path = get_resource_path(os.path.join("icons", "icons.png"))
    if not os.path.exists(path):
        return None
    try:
        _STATUS_SPRITE = Image.open(path).convert("RGBA")
    except Exception as e:
        print(f"Status icons: не удалось загрузить спрайт: {e}")
    return _STATUS_SPRITE

def get_status_photo(status) -> Optional[object]:
    if not TRAY_AVAILABLE:
        return None
    idx = _STATUS_SPRITE_INDEX.get(status)
    if idx is None:
        return None
    if idx in _STATUS_PHOTO_CACHE:
        return _STATUS_PHOTO_CACHE[idx]
    sprite = _load_status_sprite()
    if sprite is None:
        return None
    x0 = idx * STATUS_ICON_W
    if x0 + STATUS_ICON_W > sprite.width:
        return None
    icon = sprite.crop((x0, 0, x0 + STATUS_ICON_W, STATUS_ICON_H))
    photo = ImageTk.PhotoImage(icon)
    _STATUS_PHOTO_CACHE[idx] = photo
    return photo

_ICON_CACHE: Dict[tuple, object] = {}

def _icon_profile(d, s, color):
    d.ellipse([s * 0.32, s * 0.08, s * 0.68, s * 0.44], fill=color)
    d.pieslice([s * 0.08, s * 0.40, s * 0.92, s * 1.15], 180, 360, fill=color)

def _icon_search(d, s, color):
    w = max(1, int(s * 0.12))
    d.ellipse([s * 0.10, s * 0.10, s * 0.62, s * 0.62], outline=color, width=w)
    d.line([s * 0.55, s * 0.55, s * 0.92, s * 0.92], fill=color, width=w)

def _icon_groups(d, s, color):
    color2 = "#5aa0d8"
    d.ellipse([s * 0.06, s * 0.14, s * 0.46, s * 0.54], fill=color2)
    d.pieslice([s * 0.00, s * 0.46, s * 0.52, s * 0.95], 180, 360, fill=color2)
    d.ellipse([s * 0.50, s * 0.06, s * 0.94, s * 0.50], fill=color)
    d.pieslice([s * 0.44, s * 0.42, s * 1.00, s * 0.92], 180, 360, fill=color)

def _icon_settings(d, s, color):
    import math
    cx, cy = s * 0.5, s * 0.5
    r_out, r_in = s * 0.46, s * 0.30
    teeth = 8
    pts = []
    for i in range(teeth * 2):
        ang = math.pi * i / teeth
        r = r_out if i % 2 == 0 else r_out * 0.70
        pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
    d.polygon(pts, fill=color)
    d.ellipse([cx - r_in, cy - r_in, cx + r_in, cy + r_in], fill=(0, 0, 0, 0))

def _icon_logo(d, s, color):
    r = s * 0.24
    cx, cy = s * 0.5, s * 0.42
    for dx, dy in [(-0.24, -0.20), (0.24, -0.20), (-0.24, 0.20), (0.24, 0.20)]:
        d.ellipse([cx + dx * s - r, cy + dy * s - r, cx + dx * s + r, cy + dy * s + r], fill=color)
    w = max(1, int(s * 0.08))
    d.line([cx, cy + s * 0.12, cx, s * 0.96], fill=color, width=w)

def _icon_history(d, s, color):
    w = max(1, int(s * 0.11))
    for y in (0.22, 0.5, 0.78):
        d.line([s * 0.10, s * y, s * 0.90, s * y], fill=color, width=w)

def _icon_close(d, s, color):
    w = max(1, int(s * 0.15))
    d.line([s * 0.18, s * 0.18, s * 0.82, s * 0.82], fill=color, width=w)
    d.line([s * 0.82, s * 0.18, s * 0.18, s * 0.82], fill=color, width=w)

def _icon_smiley(d, s, color):
    w = max(1, int(s * 0.08))
    d.ellipse([s * 0.06, s * 0.06, s * 0.94, s * 0.94], outline=color, width=w)
    er = s * 0.07
    d.ellipse([s * 0.30 - er, s * 0.38 - er, s * 0.30 + er, s * 0.38 + er], fill=color)
    d.ellipse([s * 0.70 - er, s * 0.38 - er, s * 0.70 + er, s * 0.38 + er], fill=color)
    d.arc([s * 0.22, s * 0.28, s * 0.78, s * 0.86], start=20, end=160, fill=color, width=w)

def _icon_send(d, s, color):
    d.polygon([(s * 0.92, s * 0.50), (s * 0.12, s * 0.10), (s * 0.38, s * 0.50), (s * 0.12, s * 0.90)], fill=color)

def _icon_save(d, s, color):
    w = max(1, int(s * 0.06))
    d.rectangle([s * 0.14, s * 0.10, s * 0.86, s * 0.90], outline=color, width=w)
    d.rectangle([s * 0.28, s * 0.10, s * 0.72, s * 0.36], fill=color)
    d.rectangle([s * 0.26, s * 0.55, s * 0.74, s * 0.82], outline=color, width=w)

def _icon_check(d, s, color):
    w = max(1, int(s * 0.15))
    d.line([s * 0.14, s * 0.52, s * 0.40, s * 0.80], fill=color, width=w)
    d.line([s * 0.40, s * 0.80, s * 0.88, s * 0.20], fill=color, width=w)

def _icon_plus(d, s, color):
    w = max(1, int(s * 0.17))
    d.line([s * 0.5, s * 0.12, s * 0.5, s * 0.88], fill=color, width=w)
    d.line([s * 0.12, s * 0.5, s * 0.88, s * 0.5], fill=color, width=w)

def _icon_calendar(d, s, color):
    w = max(1, int(s * 0.07))
    d.rectangle([s * 0.10, s * 0.20, s * 0.90, s * 0.90], outline=color, width=w)
    d.line([s * 0.10, s * 0.40, s * 0.90, s * 0.40], fill=color, width=w)
    d.line([s * 0.30, s * 0.08, s * 0.30, s * 0.28], fill=color, width=w)
    d.line([s * 0.70, s * 0.08, s * 0.70, s * 0.28], fill=color, width=w)

def _icon_lock(d, s, color):
    w = max(1, int(s * 0.09))
    d.arc([s * 0.26, s * 0.08, s * 0.74, s * 0.56], start=180, end=360, fill=color, width=w)
    d.rectangle([s * 0.18, s * 0.42, s * 0.82, s * 0.92], fill=color)

def _icon_info(d, s, color):
    w = max(1, int(s * 0.08))
    d.ellipse([s * 0.08, s * 0.08, s * 0.92, s * 0.92], outline=color, width=w)
    d.ellipse([s * 0.44, s * 0.22, s * 0.56, s * 0.34], fill=color)
    d.rectangle([s * 0.44, s * 0.42, s * 0.56, s * 0.78], fill=color)

def _icon_mail(d, s, color):
    w = max(1, int(s * 0.07))
    d.rectangle([s * 0.08, s * 0.20, s * 0.92, s * 0.80], outline=color, width=w)
    d.line([s * 0.08, s * 0.22, s * 0.5, s * 0.55], fill=color, width=w)
    d.line([s * 0.92, s * 0.22, s * 0.5, s * 0.55], fill=color, width=w)

def _icon_arrow_left(d, s, color):
    d.polygon([(s * 0.68, s * 0.12), (s * 0.68, s * 0.88), (s * 0.22, s * 0.5)], fill=color)

def _icon_arrow_right(d, s, color):
    d.polygon([(s * 0.32, s * 0.12), (s * 0.32, s * 0.88), (s * 0.78, s * 0.5)], fill=color)

def _icon_shield(d, s, color):
    d.polygon([(s * 0.5, s * 0.06), (s * 0.90, s * 0.5), (s * 0.5, s * 0.94), (s * 0.10, s * 0.5)], fill=color)

def _icon_warn(d, s, color):
    d.polygon([(s * 0.5, s * 0.06), (s * 0.94, s * 0.90), (s * 0.06, s * 0.90)], fill=color)
    d.rectangle([s * 0.46, s * 0.40, s * 0.54, s * 0.64], fill=(0, 0, 0, 0))
    d.ellipse([s * 0.44, s * 0.70, s * 0.56, s * 0.80], fill=(0, 0, 0, 0))

def _icon_arrow_down(d, s, color):
    d.polygon([(s * 0.12, s * 0.32), (s * 0.88, s * 0.32), (s * 0.5, s * 0.78)], fill=color)

def _icon_undo(d, s, color):
    w = max(1, int(s * 0.11))
    d.arc([s * 0.14, s * 0.14, s * 0.86, s * 0.86], start=40, end=320, fill=color, width=w)
    d.polygon([(s * 0.30, s * 0.06), (s * 0.30, s * 0.34), (s * 0.06, s * 0.20)], fill=color)

_ICON_DRAWERS = {
    "profile":     _icon_profile,
    "search":      _icon_search,
    "groups":      _icon_groups,
    "settings":    _icon_settings,
    "logo":        _icon_logo,
    "history":     _icon_history,
    "close":       _icon_close,
    "smiley":      _icon_smiley,
    "send":        _icon_send,
    "save":        _icon_save,
    "check":       _icon_check,
    "plus":        _icon_plus,
    "calendar":    _icon_calendar,
    "lock":        _icon_lock,
    "info":        _icon_info,
    "mail":        _icon_mail,
    "arrow_left":  _icon_arrow_left,
    "arrow_right": _icon_arrow_right,
    "arrow_down":  _icon_arrow_down,
    "undo":        _icon_undo,
    "shield":      _icon_shield,
    "warn":        _icon_warn,
}

def get_icon(name: str, size: int = 18, color: str = "#0055aa") -> Optional[object]:
    if not TRAY_AVAILABLE:
        return None
    fn = _ICON_DRAWERS.get(name)
    if fn is None:
        return None
    key = (name, size, color)
    if key in _ICON_CACHE:
        return _ICON_CACHE[key]
    try:
        scale = 4
        big = Image.new("RGBA", (size * scale, size * scale), (0, 0, 0, 0))
        fn(ImageDraw.Draw(big), size * scale, color)
        img = big.resize((size, size), Image.LANCZOS)
        photo = ImageTk.PhotoImage(img)
    except Exception:
        return None
    _ICON_CACHE[key] = photo
    return photo

# Backward-compatible alias
def get_toolbar_icon(name: str, size: int = 18, color: str = "#0055aa") -> Optional[object]:
    return get_icon(name, size, color)

def _create_simple_icon() -> Optional[object]:
    if not TRAY_AVAILABLE:
        return None
    try:
        img = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse([4, 4, 28, 28], fill="#008000")
        draw.ellipse([10, 10, 22, 22], fill="#00cc00")
        return img
    except Exception:
        return None

def _play_sound_file(wav_name: str):
    try:
        wav_path = get_resource_path(os.path.join("sounds", wav_name))
        if sys.platform == "win32":
            import winsound
            if os.path.exists(wav_path):
                winsound.PlaySound(wav_path, winsound.SND_FILENAME | winsound.SND_ASYNC)
            else:
                winsound.MessageBeep(winsound.MB_ICONASTERISK)
        elif sys.platform == "darwin":
            if os.path.exists(wav_path):
                os.system(f"afplay '{wav_path}' &")
            else:
                os.system("afplay /System/Library/Sounds/Tink.aiff &")
        else:
            if os.path.exists(wav_path):
                ret = os.system(f"paplay '{wav_path}' > /dev/null 2>&1")
                if ret != 0:
                    os.system(f"aplay '{wav_path}' > /dev/null 2>&1")
            else:
                ret = os.system("paplay /usr/share/sounds/freedesktop/stereo/message.oga > /dev/null 2>&1")
                if ret != 0:
                    print("\a", end="", flush=True)
    except Exception:
        pass

def _play_msg_sound():
    threading.Thread(target=_play_sound_file, args=("sndMsg.wav",), daemon=True).start()

def _play_online_sound():
    threading.Thread(target=_play_sound_file, args=("sndGlobal.wav",), daemon=True).start()

def _play_error_sound():
    threading.Thread(target=_play_sound_file, args=("sndSrvMsg.wav",), daemon=True).start()
