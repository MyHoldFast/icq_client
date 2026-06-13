"""
chat_pane.py — ChatPane: панель одного чата (вкладка внутри ChatWindow).
"""
import os
import re
import json
import asyncio
import tkinter as tk
from typing import List, Optional

from icq_core import ICQClient, Message

from config import (
    load_config, save_config, history_path,
    HISTORY_PREVIEW_MESSAGES, _cf, _uf,
)
from theme import PALETTE, schedule_in_tk
from smileys import AnimatedSmiley, parse_smileys, _load_gif_frames, _SMILEY_MAP_RAW
from resources import get_resource_path, TRAY_AVAILABLE


class ChatPane(tk.Frame):
    def __init__(self, master, contact, client: ICQClient, send_mode_var: tk.StringVar):
        super().__init__(master, bg=PALETTE["msg_in_bg"])
        self.contact       = contact
        self.client        = client
        self._send_mode    = send_mode_var
        self._typing_job   = None
        self._is_typing    = False
        self._history_records: List[dict] = []
        self._preview_loaded = False
        self._animated_smileys: List[AnimatedSmiley] = []
        self._smiley_counter = 0
        self._build()
        self._load_history_preview()

    def _build(self):
        hist_bar = tk.Frame(self, bg=PALETTE["bg_header"])
        hist_bar.pack(fill="x", side="top")
        self._hist_btn = tk.Button(
            hist_bar, text="▣ Показать всю историю",
            font=("Segoe UI Symbol", 7), bg=PALETTE["bg_header"],
            fg=PALETTE["accent"], relief="flat", bd=0, cursor="hand2",
            command=self._load_full_history,
        )
        self._hist_btn.pack(side="left", padx=6, pady=1)

        self._clear_btn = tk.Button(
            hist_bar, text="✘ Очистить историю",
            font=("Segoe UI Symbol", 7), bg=PALETTE["bg_header"],
            fg="#aa2200", relief="flat", bd=0, cursor="hand2",
            command=self._clear_history,
        )
        self._clear_btn.pack(side="left", padx=2, pady=1)

        bottom_frame = tk.Frame(self, bg=PALETTE["input_bg"])
        bottom_frame.pack(fill="x", side="bottom")

        tk.Frame(bottom_frame, height=2, bg=PALETTE["border"]).pack(fill="x", side="top")

        service_bar = tk.Frame(bottom_frame, bg=PALETTE["toolbar_bg"], bd=0, relief="flat")
        service_bar.pack(fill="x", side="top")

        self._smiley_btn = tk.Button(
            service_bar, text="☺", font=("Segoe UI Symbol", 11), bg=PALETTE["toolbar_bg"],
            fg="#e8a000", relief="flat", bd=0, cursor="hand2", padx=4,
            command=self._open_smiley_picker,
        )
        self._smiley_btn.pack(side="left", padx=2, pady=1)

        tk.Frame(bottom_frame, height=1, bg=PALETTE["border"]).pack(fill="x", side="top")

        input_area = tk.Frame(bottom_frame, bg=PALETTE["input_bg"], bd=0)
        input_area.pack(fill="x", side="top")

        self.input_text = tk.Text(
            input_area, font=_cf(), bg=PALETTE["input_bg"],
            fg=PALETTE["msg_text"], height=4, wrap="word", relief="flat", bd=0, padx=4, pady=3,
        )
        in_scroll = tk.Scrollbar(input_area, orient="vertical", command=self.input_text.yview)
        self.input_text.configure(yscrollcommand=in_scroll.set)
        in_scroll.pack(side="right", fill="y")
        self.input_text.pack(fill="both", expand=True)

        msg_frame = tk.Frame(self, bg=PALETTE["msg_in_bg"])
        msg_frame.pack(fill="both", expand=True)

        self.msg_text = tk.Text(
            msg_frame, font=_cf(), bg=PALETTE["msg_in_bg"],
            fg=PALETTE["msg_text"], state="disabled", wrap="word",
            relief="flat", bd=0, padx=8, pady=6, cursor="xterm",
        )
        scroll = tk.Scrollbar(msg_frame, orient="vertical", command=self.msg_text.yview)
        self.msg_text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.msg_text.pack(fill="both", expand=True)
        self.msg_text.bind("<Key>", lambda e: self._handle_msg_text_key(e))

        self.msg_text.tag_configure("nick_in",  foreground=PALETTE["msg_nick_in"],  font=_cf(bold=True))
        self.msg_text.tag_configure("nick_out", foreground=PALETTE["msg_nick_out"], font=_cf(bold=True))
        self.msg_text.tag_configure("text_in",  foreground=PALETTE["msg_text"],     font=_cf())
        self.msg_text.tag_configure("text_out", foreground="#1a1a6e",               font=_cf())
        self.msg_text.tag_configure("xstatus_label", foreground="#888888",          font=_uf(delta=-1, italic=True))
        self.msg_text.tag_configure("link", foreground="#0055cc", font=_cf())
        self.msg_text.tag_bind("link", "<Button-1>", self._on_link_click)
        self.msg_text.tag_bind("link", "<Enter>", lambda e: self.msg_text.configure(cursor="hand2"))
        self.msg_text.tag_bind("link", "<Leave>", lambda e: self.msg_text.configure(cursor="xterm"))

        self.input_text.bind("<Return>", self._on_enter)
        self.input_text.bind("<Control-Return>", self._on_ctrl_enter)
        self.input_text.bind("<KeyRelease>", self._on_key_press)
        self.input_text.bind("<Key>", self.handle_copy_paste_cut)

    def handle_copy_paste_cut(self, event):
        if event.state & 0x4:
            if event.keycode == 67:
                self.input_text.event_generate("<<Copy>>")
                return "break"
            elif event.keycode == 86:
                self.input_text.event_generate("<<Paste>>")
                return "break"
            elif event.keycode == 88:
                self.input_text.event_generate("<<Cut>>")
                return "break"

    def _handle_msg_text_key(self, event):
        if event.state & 0x4:
            if event.keycode == 67:
                self.msg_text.event_generate("<<Copy>>")
                return "break"
            elif event.keycode == 65:
                self.msg_text.tag_add("sel", "1.0", "end")
                return "break"
        return None

    def _on_link_click(self, event):
        import webbrowser
        idx = self.msg_text.index(f"@{event.x},{event.y}")
        for tag in self.msg_text.tag_names(idx):
            if tag.startswith("link_url:"):
                url = tag[9:]
                webbrowser.open(url)
                return

    def _insert_text_with_links(self, text: str, text_tag: str):
        self._insert_text_with_smileys(text, text_tag)

    def _insert_text_with_smileys(self, text: str, text_tag: str):
        url_re = re.compile(r'(https?://\S+|ftp://\S+|www\.\S+)', re.IGNORECASE)

        segments = parse_smileys(text)
        for kind, value in segments:
            if kind == "smiley":
                self._insert_smiley(value)
            else:
                last = 0
                for m in url_re.finditer(value):
                    s, e = m.start(), m.end()
                    if s > last:
                        self.msg_text.insert("end", value[last:s], text_tag)
                    url = m.group(0)
                    url_tag = f"link_url:{url}"
                    if url_tag not in self.msg_text.tag_names():
                        self.msg_text.tag_configure(url_tag)
                        self.msg_text.tag_bind(url_tag, "<Button-1>", self._on_link_click)
                        self.msg_text.tag_bind(url_tag, "<Enter>",
                                               lambda e: self.msg_text.configure(cursor="hand2"))
                        self.msg_text.tag_bind(url_tag, "<Leave>",
                                               lambda e: self.msg_text.configure(cursor="xterm"))
                    self.msg_text.insert("end", url, (text_tag, "link", url_tag))
                    last = e
                if last < len(value):
                    self.msg_text.insert("end", value[last:], text_tag)

    def _insert_smiley(self, filename: str):
        if not TRAY_AVAILABLE:
            self.msg_text.insert("end", f"[{filename}]")
            return
        self._smiley_counter += 1
        img_name = f"smiley_{id(self)}_{self._smiley_counter}"
        smiley = AnimatedSmiley(self.msg_text, img_name, filename)
        if smiley._photo_frames:
            self.msg_text.image_create("end", image=smiley._photo_frames[0], name=img_name)
            self._animated_smileys.append(smiley)
        else:
            self.msg_text.insert("end", f"[{filename}]")

    # ── Всплывающий тултип ───────────────────────────────────────────────────
    _tip_win: Optional[tk.Toplevel] = None

    def _show_tip(self, event, text: str):
        self._hide_tip()
        tip = tk.Toplevel(self)
        tip.wm_overrideredirect(True)
        tip.attributes("-topmost", True)
        tip.configure(bg="#ffffcc", relief="solid", bd=1)
        tk.Label(tip, text=text, bg="#ffffcc", fg="#333333",
                 font=("Segoe UI Symbol", 8), padx=4, pady=2).pack()
        tip.geometry(f"+{event.x_root + 10}+{event.y_root + 10}")
        self._tip_win = tip

    def _hide_tip(self):
        if self._tip_win and self._tip_win.winfo_exists():
            self._tip_win.destroy()
        self._tip_win = None

    # ── Выбор смайла ─────────────────────────────────────────────────────────
    def _open_smiley_picker(self):
        if not TRAY_AVAILABLE:
            return

        # Если уже открыта — закрываем
        existing = getattr(self, "_picker_win", None)
        if existing and existing.winfo_exists():
            existing.destroy()
            self._picker_win = None
            return

        btn_x = self._smiley_btn.winfo_rootx()
        btn_y = self._smiley_btn.winfo_rooty()

        win = tk.Toplevel(self)
        win.wm_overrideredirect(True)
        win.configure(bg=PALETTE["bg_main"], relief="solid", bd=1)
        win.attributes("-topmost", True)

        COLS = 10
        PAD  = 4

        canvas = tk.Canvas(win, bg=PALETTE["bg_main"], highlightthickness=0)
        scrollbar = tk.Scrollbar(win, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        inner = tk.Frame(canvas, bg=PALETTE["bg_main"])
        canvas.create_window((0, 0), window=inner, anchor="nw")

        # Кэш PhotoImage-кадров для ячеек пикера (отдельный от AnimatedSmiley)
        _cell_photo_frames: dict = {}

        def _get_photo_frames(filename, frames):
            if filename not in _cell_photo_frames:
                from PIL import ImageTk
                _cell_photo_frames[filename] = [ImageTk.PhotoImage(f) for f in frames]
            return _cell_photo_frames[filename]

        def _make_animator(widget, photo_frames, delays):
            state = [0]
            def _tick():
                if not widget.winfo_exists():
                    return
                state[0] = (state[0] + 1) % len(photo_frames)
                widget.configure(image=photo_frames[state[0]])
                delay = delays[state[0]] if state[0] < len(delays) else 100
                widget.after(delay, _tick)
            return _tick

        for idx, (filename, codes) in enumerate(_SMILEY_MAP_RAW):
            row_i, col_i = divmod(idx, COLS)
            frames, delays = _load_gif_frames(filename)
            if not frames:
                continue

            photo_frames = _get_photo_frames(filename, frames)
            cell = tk.Label(inner, image=photo_frames[0], bg=PALETTE["bg_main"],
                            cursor="hand2", relief="flat", bd=0,
                            padx=PAD, pady=PAD)
            cell.grid(row=row_i, column=col_i, padx=1, pady=1)

            tip_text = codes[0]
            cell.bind("<Enter>", lambda e, t=tip_text: self._show_tip(e, t))
            cell.bind("<Leave>", lambda e: self._hide_tip())

            primary_code = codes[0]
            def _on_cell_click(e, c=primary_code, ww=win):
                self._hide_tip()
                self.input_text.insert("insert", c)
                self.input_text.see("insert")
                self.input_text.focus_set()
                if ww.winfo_exists():
                    ww.destroy()
            cell.bind("<Button-1>", _on_cell_click)

            if len(photo_frames) > 1:
                tick = _make_animator(cell, photo_frames, delays)
                delay0 = delays[0] if delays else 100
                cell.after(delay0, tick)

        win._cell_photo_frames = _cell_photo_frames

        inner.update_idletasks()
        w = inner.winfo_reqwidth() + scrollbar.winfo_reqwidth() + 4
        h = min(inner.winfo_reqheight() + 4, 280)
        canvas.configure(scrollregion=canvas.bbox("all"), width=inner.winfo_reqwidth())

        win.geometry(f"{w}x{h}+{btn_x}+{btn_y - h - 4}")
        self._picker_win = win

        _outside_id: list = []

        def _on_picker_click_outside(event):
            if not win.winfo_exists():
                return
            try:
                wx, wy = win.winfo_rootx(), win.winfo_rooty()
                ww2, wh2 = win.winfo_width(), win.winfo_height()
                ex, ey = event.x_root, event.y_root
                if ex < wx or ex > wx + ww2 or ey < wy or ey > wy + wh2:
                    self._hide_tip()
                    win.destroy()
            except Exception:
                pass

        root = self.winfo_toplevel()
        bind_id = root.bind("<Button-1>", _on_picker_click_outside, add="+")
        _outside_id.append(bind_id)

        def _on_wheel(e):
            canvas.yview_scroll(-1 if e.delta > 0 else 1, "units")
        canvas.bind_all("<MouseWheel>", _on_wheel)

        def _cleanup(e):
            try:
                root.unbind("<Button-1>", _outside_id[0])
            except Exception:
                pass
            canvas.unbind_all("<MouseWheel>")
        win.bind("<Destroy>", _cleanup)

    def _insert_smiley_code(self, code: str, picker_win: tk.Toplevel):
        self.input_text.insert(tk.INSERT, code)
        self.input_text.focus_set()
        picker_win.destroy()

    def _on_enter(self, event):
        if self._send_mode.get() == "enter":
            self._send_message()
            return "break"
        return None

    def _on_ctrl_enter(self, event):
        if self._send_mode.get() == "ctrl_enter":
            self._send_message()
            return "break"
        self.input_text.insert(tk.INSERT, "\n")
        return "break"

    def _on_key_press(self, event):
        if event.keysym in ("Return", "BackSpace", "Delete"):
            return
        if not self._is_typing:
            self._is_typing = True
            self._send_typing(True)
        if self._typing_job:
            self.after_cancel(self._typing_job)
        self._typing_job = self.after(3000, self._stop_typing)

    def _stop_typing(self):
        self._is_typing = False
        self._send_typing(False)

    def _send_typing(self, typing: bool):
        from config import get_loop
        try:
            loop = get_loop()
            asyncio.run_coroutine_threadsafe(
                self.client.send_typing(self.contact.uin, typing), loop)
        except Exception:
            pass

    def focus_input(self):
        self.input_text.focus_set()

    def append_message(self, msg: Message, outgoing_nick: str = "Я"):
        from config import history_path, load_config, _cf, _uf
        from theme import fmt_time, PALETTE

        ts = fmt_time(msg.timestamp)
        if msg.is_outgoing:
            nick = outgoing_nick
            nick_tag = "nick_out"
            text_tag = "text_out"
        else:
            nick = self.contact.display_name
            nick_tag = "nick_in"
            text_tag = "text_in"

        self.msg_text.configure(state="normal")
        self.msg_text.insert("end", f"{nick} ({ts})\n", nick_tag)
        self._insert_text_with_smileys(msg.text, text_tag)
        self.msg_text.insert("end", "\n\n")
        self.msg_text.see("end")
        self.msg_text.configure(state="disabled")

        # Сохраняем в историю
        record = {
            "nick": nick, "time": ts, "text": msg.text,
            "outgoing": msg.is_outgoing,
        }
        self._history_records.append(record)
        path = history_path(self.contact.uin, self.client.uin)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._history_records, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Ошибка сохранения истории: {e}")

    def _send_message(self):
        text = self.input_text.get("1.0", "end-1c").strip()
        if not text:
            return
        self.input_text.delete("1.0", "end")
        self._stop_typing()

        from config import get_loop
        from icq_core import Message
        import time
        loop = get_loop()

        async def _do_send():
            try:
                await self.client.send_message(self.contact.uin, text)
            except Exception as e:
                from tkinter import messagebox
                messagebox.showerror("Ошибка", str(e))

        asyncio.run_coroutine_threadsafe(_do_send(), loop)

        msg = Message(
            sender_uin=self.client.uin,
            text=text,
            timestamp=__import__("time").time(),
            is_outgoing=True,
        )
        my_nick = getattr(self.client, "my_nick", "") or "Я"
        self.append_message(msg, outgoing_nick=my_nick)

    def stop_animations(self):
        for s in self._animated_smileys:
            s.stop()
        self._animated_smileys.clear()

    def _load_history_preview(self):
        path = history_path(self.contact.uin, self.client.uin)
        if not os.path.exists(path):
            self._hist_btn.configure(state="disabled", fg="#aaaaaa", text="▣ История недоступна")
            self._clear_btn.pack_forget()
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                records = json.load(f)
        except Exception:
            return

        if not isinstance(records, list): return
        self._history_records = records[:]
        preview = records[-HISTORY_PREVIEW_MESSAGES:]
        separator = "─" * 40

        self.msg_text.configure(state="normal")
        if not self._preview_loaded:
            if len(records) > HISTORY_PREVIEW_MESSAGES:
                self.msg_text.insert("end", f"[ Показаны последние {HISTORY_PREVIEW_MESSAGES} сообщений. Нажмите кнопку выше для полной истории. ]\n{separator}\n", "xstatus_label")
            else:
                self.msg_text.insert("end", f"[ История переписки ]\n{separator}\n", "xstatus_label")
            self._preview_loaded = True

        for rec in preview:
            nick, ts_str, text, is_out = rec.get("nick",""), rec.get("time",""), rec.get("text",""), rec.get("outgoing",False)
            nick_tag = "nick_out" if is_out else "nick_in"
            text_tag = "text_out" if is_out else "text_in"
            self.msg_text.insert("end", f"{nick} ({ts_str})\n", nick_tag)
            self._insert_text_with_smileys(text, text_tag)
            self.msg_text.insert("end", "\n\n")

        if self._preview_loaded:
            self.msg_text.insert("end", f"{separator}\n\n", "xstatus_label")
        self.msg_text.see("end")
        self.msg_text.configure(state="disabled")

    def _load_full_history(self):
        path = history_path(self.contact.uin, self.client.uin)
        if not os.path.exists(path):
            from tkinter import messagebox
            messagebox.showinfo("История", "Файл истории не найден.")
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                records = json.load(f)
        except Exception as e:
            from tkinter import messagebox
            messagebox.showerror("Ошибка", str(e))
            return
        if not isinstance(records, list): return

        win = tk.Toplevel(self)
        win.title(f"Полная история — {self.contact.display_name}")
        win.geometry("600x480")
        win.configure(bg=PALETTE["bg_main"])

        tk.Label(win, text=f"▣ История с {self.contact.display_name}", font=("Segoe UI Symbol", 10, "bold"), bg=PALETTE["title_bar"], fg="white").pack(fill="x", pady=0)
        frame = tk.Frame(win, bg=PALETTE["msg_in_bg"])
        frame.pack(fill="both", expand=True, padx=4, pady=4)

        txt = tk.Text(frame, font=_cf(), bg=PALETTE["msg_in_bg"], fg=PALETTE["msg_text"], wrap="word", relief="flat", bd=0, padx=6, pady=4)
        sb = tk.Scrollbar(frame, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        txt.pack(fill="both", expand=True)

        txt.tag_configure("nick_in", foreground=PALETTE["msg_nick_in"], font=_cf(bold=True))
        txt.tag_configure("nick_out", foreground=PALETTE["msg_nick_out"], font=_cf(bold=True))
        txt.tag_configure("text_in", foreground=PALETTE["msg_text"], font=_cf())
        txt.tag_configure("text_out", foreground="#1a1a6e", font=_cf())
        txt.tag_configure("xstatus_label", foreground="#888888", font=_uf(delta=-1, italic=True))

        txt.insert("end", "[ Полная история переписки ]\n" + "─"*40 + "\n", "xstatus_label")
        for rec in records:
            nick, ts_str, text, is_out = rec.get("nick",""), rec.get("time",""), rec.get("text",""), rec.get("outgoing",False)
            txt.insert("end", f"{nick} ({ts_str})\n", "nick_out" if is_out else "nick_in")
            txt.insert("end", text + "\n", "text_out" if is_out else "text_in")
            txt.insert("end", "\n")
        txt.configure(state="disabled")
        txt.see("end")

    def apply_fonts(self):
        self.msg_text.configure(font=_cf())
        self.input_text.configure(font=_cf())
        self.msg_text.tag_configure("nick_in",       font=_cf(bold=True))
        self.msg_text.tag_configure("nick_out",      font=_cf(bold=True))
        self.msg_text.tag_configure("text_in",       font=_cf())
        self.msg_text.tag_configure("text_out",      font=_cf())
        self.msg_text.tag_configure("xstatus_label", font=_uf(delta=-1, italic=True))
        self.msg_text.tag_configure("link",          font=_cf())

    def _clear_history(self):
        from tkinter import messagebox
        if not messagebox.askyesno("Очистить историю",
                f"Удалить всю историю переписки с {self.contact.display_name}?\nФайл: {history_path(self.contact.uin, self.client.uin)}",
                icon="warning"):
            return
        path = history_path(self.contact.uin, self.client.uin)
        try:
            if os.path.exists(path): os.remove(path)
        except Exception as e:
            from tkinter import messagebox
            messagebox.showerror("Ошибка", f"Не удалось удалить файл:\n{e}")
            return
        self.msg_text.configure(state="normal")
        self.msg_text.delete("1.0", "end")
        self.msg_text.configure(state="disabled")
        self._hist_btn.configure(state="disabled", fg="#aaaaaa", text="▣ История недоступна")
        self._clear_btn.pack_forget()
        self._preview_loaded = False
        self._history_records.clear()