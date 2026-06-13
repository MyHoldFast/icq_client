"""
config.py — сохранение/загрузка конфигурации, истории и незнакомцев;
             ссылка на asyncio event loop; настройки шрифтов.
"""
import os
import json
import asyncio
from typing import Optional

# ── Конфиг ───────────────────────────────────────────────────────────────────
CONFIG_PATH   = os.path.join(os.path.expanduser("~"), ".icq_client.cfg")
ACCOUNTS_PATH = os.path.join(os.path.expanduser("~"), ".icq_accounts.json")
HISTORY_PREVIEW_MESSAGES = 20

def load_config() -> dict:
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_config(cfg: dict):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Ошибка сохранения конфига: {e}")

# ── Список аккаунтов ──────────────────────────────────────────────────────────
# Структура каждого аккаунта:
#   { "uin": str, "password": str, "nick": str,
#     "server": str, "remember": bool, "auto_connect": bool }

def load_accounts() -> list:
    """Возвращает список сохранённых аккаунтов."""
    try:
        with open(ACCOUNTS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
    except Exception:
        pass
    # Миграция: если есть старый конфиг с UIN — переносим его
    cfg = load_config()
    if cfg.get("uin"):
        return [_cfg_to_account(cfg)]
    return []

def save_accounts(accounts: list):
    try:
        with open(ACCOUNTS_PATH, "w", encoding="utf-8") as f:
            json.dump(accounts, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Ошибка сохранения аккаунтов: {e}")

def _cfg_to_account(cfg: dict) -> dict:
    return {
        "uin":          cfg.get("uin", ""),
        "password":     cfg.get("password", ""),
        "nick":         cfg.get("nick", ""),
        "server":       cfg.get("server", "195.66.114.37:5190"),
        "remember":     cfg.get("remember", True),
        "auto_connect": cfg.get("auto_connect", False),
    }

def upsert_account(acc: dict):
    """Добавляет или обновляет аккаунт по UIN."""
    accounts = load_accounts()
    for i, a in enumerate(accounts):
        if a["uin"] == acc["uin"]:
            accounts[i] = acc
            save_accounts(accounts)
            return
    accounts.append(acc)
    save_accounts(accounts)

def delete_account(uin: str):
    accounts = [a for a in load_accounts() if a["uin"] != uin]
    save_accounts(accounts)

def get_auto_connect_account() -> Optional[dict]:
    """Возвращает первый аккаунт с auto_connect=True, иначе None."""
    for a in load_accounts():
        if a.get("auto_connect") and a.get("uin") and a.get("password"):
            return a
    return None

def history_path(uin: str, my_uin: str = "") -> str:
    prefix = f"icq_history_{my_uin}_" if my_uin else "icq_history_"
    return os.path.join(os.path.expanduser("~"), f"{prefix}{uin}.json")

# ── Незнакомцы ────────────────────────────────────────────────────────────────
STRANGERS_GROUP_ID   = -1
STRANGERS_GROUP_NAME = "Не из списка"

def strangers_path(my_uin: str) -> str:
    return os.path.join(os.path.expanduser("~"), f"icq_strangers_{my_uin}.json")

def load_strangers(my_uin: str) -> dict:
    try:
        with open(strangers_path(my_uin), "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}

def save_strangers(my_uin: str, strangers: dict):
    try:
        with open(strangers_path(my_uin), "w", encoding="utf-8") as f:
            json.dump(strangers, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Ошибка сохранения незнакомцев: {e}")

# ── Глобальный event loop ─────────────────────────────────────────────────────
_global_loop: Optional[asyncio.AbstractEventLoop] = None

def set_loop(loop):
    global _global_loop
    _global_loop = loop

def get_loop() -> asyncio.AbstractEventLoop:
    if _global_loop is None:
        raise RuntimeError("Event loop not initialized")
    return _global_loop

# ── Настройки шрифтов ─────────────────────────────────────────────────────────
_CHAT_FONT_FAMILY = "Segoe UI"
_CHAT_FONT_SIZE   = 11
_CHAT_FONT_BOLD   = False
_UI_FONT_FAMILY   = "Segoe UI"
_UI_FONT_SIZE     = 10

def _cf(bold=False, italic=False):
    """Шрифт для переписки (чат-окно)."""
    style = []
    if bold or _CHAT_FONT_BOLD: style.append("bold")
    if italic: style.append("italic")
    return (_CHAT_FONT_FAMILY, _CHAT_FONT_SIZE) + (tuple(style) if style else ())

def _uf(delta=0, bold=False, italic=False):
    """Шрифт для элементов интерфейса (списки, кнопки, метки)."""
    style = []
    if bold: style.append("bold")
    if italic: style.append("italic")
    return (_UI_FONT_FAMILY, _UI_FONT_SIZE + delta) + (tuple(style) if style else ())

def load_font_config():
    """Загружает настройки шрифтов из ~/.icq_client.cfg."""
    global _CHAT_FONT_FAMILY, _CHAT_FONT_SIZE, _CHAT_FONT_BOLD
    global _UI_FONT_FAMILY, _UI_FONT_SIZE
    cfg = load_config()
    _CHAT_FONT_FAMILY = cfg.get("chat_font_family", "Segoe UI")
    _CHAT_FONT_SIZE   = int(cfg.get("chat_font_size", 11))
    _CHAT_FONT_BOLD   = bool(cfg.get("chat_font_bold", False))
    _UI_FONT_FAMILY   = cfg.get("ui_font_family", "Segoe UI")
    _UI_FONT_SIZE     = int(cfg.get("ui_font_size", 10))