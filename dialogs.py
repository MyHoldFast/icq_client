import asyncio
import queue as _queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Dict, List, Optional

from reg import ICQRegistration

from icq_core import ICQClient, Status, UserInfo, SearchResult, XSTATUS_TABLE

from config import (load_config, save_config,
                    load_accounts, upsert_account, delete_account)
from theme import PALETTE, STATUS_COLORS, STATUS_LABELS, place_near_parent, icon_button, icon_label
from resources import (
    get_status_photo, get_xstatus_photo, get_xstatus_index_by_name, get_icon,
    STATUS_ICON_W, STATUS_ICON_H, XSTATUS_ICON_W, XSTATUS_ICON_H,
)


_tk_queue: _queue.SimpleQueue = _queue.SimpleQueue()


def _schedule(widget, func):
    _tk_queue.put(func)


class LoginDialog(tk.Toplevel):
    def __init__(self, master, saved_cfg: dict):
        super().__init__(master)
        self.result   = None
        self._cfg     = saved_cfg
        self._accounts: list = load_accounts()
        self._sel_idx: int   = -1

        self.title("Вход в ICQ")
        self.configure(bg=PALETTE["bg_main"])
        self.resizable(False, False)
        self._build()
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.update_idletasks()
        self.minsize(self.winfo_reqwidth(), self.winfo_reqheight())
        place_near_parent(self, master)

    def _build(self):
        hdr = tk.Frame(self, bg=PALETTE["title_bar"], pady=7)
        hdr.pack(fill="x")
        icon_label(hdr, "logo", "ICQ", fallback_symbol="☘",
                   font=("Segoe UI Symbol", 13, "bold"), bg=PALETTE["title_bar"],
                   fg="white", color="white", size=16).pack()
        tk.Label(hdr, text="Выберите аккаунт или введите данные вручную",
                 font=("Segoe UI Symbol", 7), bg=PALETTE["title_bar"], fg="#d0e8ff").pack()

        body = tk.Frame(self, bg=PALETTE["bg_main"])
        body.pack(fill="both", expand=True, padx=0, pady=0)

        left = tk.Frame(body, bg=PALETTE["bg_header"], width=160)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)

        tk.Label(left, text="Аккаунты", font=("Segoe UI Symbol", 8, "bold"),
                 bg=PALETTE["bg_header"], fg=PALETTE["fg_group"]).pack(
                     fill="x", padx=6, pady=(8, 2))

        list_frame = tk.Frame(left, bg=PALETTE["bg_list"], relief="sunken", bd=1)
        list_frame.pack(fill="both", expand=True, padx=6, pady=(0, 4))

        self._listbox = tk.Listbox(
            list_frame, font=("Segoe UI Symbol", 9),
            bg=PALETTE["bg_list"], fg=PALETTE["fg_online"],
            selectbackground=PALETTE["select_bg"], selectforeground="#000000",
            relief="flat", bd=0, activestyle="none", height=7,
        )
        lsb = tk.Scrollbar(list_frame, orient="vertical", command=self._listbox.yview)
        self._listbox.configure(yscrollcommand=lsb.set)
        lsb.pack(side="right", fill="y")
        self._listbox.pack(fill="both", expand=True)
        self._listbox.bind("<<ListboxSelect>>", self._on_list_select)
        self._listbox.bind("<Double-Button-1>", lambda e: self._ok())

        btn_left = tk.Frame(left, bg=PALETTE["bg_header"])
        btn_left.pack(fill="x", padx=6, pady=(0, 6))
        icon_button(btn_left, "plus", "Новый", fallback_symbol="＋",
                    font=("Segoe UI Symbol", 7), bg=PALETTE["toolbar_bg"],
                    relief="groove", bd=1, size=10,
                    command=self._new_account).pack(side="left", padx=(0, 2))
        self._del_btn = icon_button(btn_left, "close", fallback_symbol="✖",
                                     font=("Segoe UI Symbol", 7), bg="#e88080", fg="white",
                                     color="white", relief="groove", bd=1, size=10,
                                     command=self._delete_selected, state="disabled")
        self._del_btn.pack(side="left")

        right = tk.Frame(body, bg=PALETTE["bg_main"])
        right.pack(side="left", fill="both", expand=True, padx=14, pady=8)

        tk.Label(right, text="UIN:", font=("Segoe UI Symbol", 9),
                 bg=PALETTE["bg_main"]).grid(row=0, column=0, sticky="w", pady=4)
        self._uin_entry = tk.Text(right, font=("Segoe UI Symbol", 10),
                                   width=17, height=1, relief="groove", bd=2, wrap="none")
        self._uin_entry.grid(row=0, column=1, pady=4, padx=(6, 0), sticky="ew")
        _style_text_entry(self._uin_entry)

        tk.Label(right, text="Пароль:", font=("Segoe UI Symbol", 9),
                 bg=PALETTE["bg_main"]).grid(row=1, column=0, sticky="w", pady=4)
        self._pwd_entry = tk.Entry(right, font=("Segoe UI Symbol", 10),
                                    width=17, relief="groove", bd=2, show="*")
        self._pwd_entry.grid(row=1, column=1, pady=4, padx=(6, 0), sticky="ew")
        self._pwd_entry.bind("<Return>", lambda e: self._ok())

        tk.Label(right, text="Псевдоним:", font=("Segoe UI Symbol", 9),
                 bg=PALETTE["bg_main"]).grid(row=2, column=0, sticky="w", pady=4)
        self._nick_entry = tk.Entry(right, font=("Segoe UI Symbol", 10),
                                     width=17, relief="groove", bd=2)
        self._nick_entry.grid(row=2, column=1, pady=4, padx=(6, 0), sticky="ew")

        tk.Label(right, text="Сервер:", font=("Segoe UI Symbol", 9),
                 bg=PALETTE["bg_main"]).grid(row=3, column=0, sticky="w", pady=4)
        self._srv_entry = tk.Text(right, font=("Segoe UI Symbol", 9),
                                   width=17, height=1, relief="groove", bd=2, wrap="none")
        self._srv_entry.insert("1.0", "195.66.114.37:5190")
        self._srv_entry.grid(row=3, column=1, pady=4, padx=(6, 0), sticky="ew")
        _style_text_entry(self._srv_entry)

        self._remember_var = tk.BooleanVar(value=True)
        tk.Checkbutton(right, text="Запомнить пароль", variable=self._remember_var,
                       font=("Segoe UI Symbol", 8), bg=PALETTE["bg_main"],
                       activebackground=PALETTE["bg_main"], cursor="hand2").grid(
                           row=4, column=0, columnspan=2, sticky="w", pady=(3, 1))
        self._auto_var = tk.BooleanVar(value=False)
        tk.Checkbutton(right, text="Автоподключение", variable=self._auto_var,
                       font=("Segoe UI Symbol", 8), bg=PALETTE["bg_main"],
                       activebackground=PALETTE["bg_main"], cursor="hand2").grid(
                           row=5, column=0, columnspan=2, sticky="w", pady=(1, 4))

        right.columnconfigure(1, weight=1)

        sep = tk.Frame(self, height=1, bg=PALETTE["border"])
        sep.pack(fill="x")

        btn_bar = tk.Frame(self, bg=PALETTE["bg_main"])
        btn_bar.pack(fill="x", padx=10, pady=8)

        icon_button(btn_bar, "send", "Войти", fallback_symbol="➤",
                    font=("Segoe UI Symbol", 9, "bold"), bg="#3a7abf", fg="white",
                    color="white", relief="groove", bd=2, size=13,
                    padx=14, pady=3,
                    command=self._ok).pack(side="left", padx=(0, 6))
        self._save_btn = icon_button(btn_bar, "save", "Сохранить", fallback_symbol="💾",
                                      font=("Segoe UI Symbol", 9), bg="#5a9a5a", fg="white",
                                      color="white", relief="groove", bd=2, size=14,
                                      padx=10, pady=3,
                                      command=self._save_current)
        self._save_btn.pack(side="left", padx=(0, 6))
        tk.Button(btn_bar, text="Отмена", font=("Segoe UI Symbol", 9),
                  bg="#e0e0e0", relief="groove", bd=2, padx=10, pady=3,
                  cursor="hand2", command=self._cancel).pack(side="left")

        reg_lbl = tk.Label(btn_bar, text="Зарегистрироваться →",
                           font=("Segoe UI Symbol", 8, "underline"),
                           bg=PALETTE["bg_main"], fg=PALETTE["accent"], cursor="hand2")
        reg_lbl.pack(side="right", padx=4)
        reg_lbl.bind("<Button-1>", lambda e: self._open_register())

        self._refresh_listbox()
        if self._accounts:
            last_uin = self._cfg.get("uin", "")
            idx = 0
            for i, a in enumerate(self._accounts):
                if a["uin"] == last_uin:
                    idx = i
                    break
            self._listbox.selection_set(idx)
            self._listbox.activate(idx)
            self._select_account(idx)
        else:
            self._uin_entry.insert("1.0", self._cfg.get("uin", ""))
            self._pwd_entry.insert(0, self._cfg.get("password", ""))
            self._srv_entry.delete("1.0", "end")
            self._srv_entry.insert("1.0", self._cfg.get("server", "195.66.114.37:5190"))
            self._remember_var.set(self._cfg.get("remember", True))
            self._auto_var.set(self._cfg.get("auto_connect", False))
            self._uin_entry.focus_set()

    def _refresh_listbox(self):
        self._listbox.delete(0, "end")
        for acc in self._accounts:
            label = acc.get("nick") or acc["uin"]
            self._listbox.insert("end", f"  {label}")
        for i, acc in enumerate(self._accounts):
            if acc.get("auto_connect"):
                self._listbox.itemconfig(i, fg=PALETTE["fg_online"])
            else:
                self._listbox.itemconfig(i, fg=PALETTE["fg_offline"])

    def _on_list_select(self, event):
        sel = self._listbox.curselection()
        if sel:
            self._select_account(sel[0])

    def _select_account(self, idx: int):
        self._sel_idx = idx
        acc = self._accounts[idx]
        self._del_btn.configure(state="normal")

        self._uin_entry.delete("1.0", "end")
        self._uin_entry.insert("1.0", acc.get("uin", ""))
        self._pwd_entry.delete(0, "end")
        self._pwd_entry.insert(0, acc.get("password", ""))
        self._nick_entry.delete(0, "end")
        self._nick_entry.insert(0, acc.get("nick", ""))
        self._srv_entry.delete("1.0", "end")
        self._srv_entry.insert("1.0", acc.get("server", "195.66.114.37:5190"))
        self._remember_var.set(acc.get("remember", True))
        self._auto_var.set(acc.get("auto_connect", False))

        self._pwd_entry.focus_set()

    def _new_account(self):
        self._listbox.selection_clear(0, "end")
        self._sel_idx = -1
        self._del_btn.configure(state="disabled")
        self._uin_entry.delete("1.0", "end")
        self._pwd_entry.delete(0, "end")
        self._nick_entry.delete(0, "end")
        self._srv_entry.delete("1.0", "end")
        self._srv_entry.insert("1.0", "195.66.114.37:5190")
        self._remember_var.set(True)
        self._auto_var.set(False)
        self._uin_entry.focus_set()

    def _delete_selected(self):
        if self._sel_idx < 0 or self._sel_idx >= len(self._accounts):
            return
        acc  = self._accounts[self._sel_idx]
        name = acc.get("nick") or acc["uin"]
        if not messagebox.askyesno("Удалить аккаунт",
                f"Удалить аккаунт «{name}» из списка?\n(история переписки не затрагивается)",
                icon="warning", parent=self):
            return
        delete_account(acc["uin"])
        self._accounts = load_accounts()
        self._refresh_listbox()
        self._new_account()

    def _save_current(self):
        uin = self._uin_entry.get("1.0", "end-1c").strip()
        pwd = self._pwd_entry.get().strip()
        if not uin:
            messagebox.showwarning("Ошибка", "Введите UIN", parent=self)
            return
        acc = {
            "uin":          uin,
            "password":     pwd if self._remember_var.get() else "",
            "nick":         self._nick_entry.get().strip(),
            "server":       self._srv_entry.get("1.0", "end-1c").strip() or "195.66.114.37:5190",
            "remember":     self._remember_var.get(),
            "auto_connect": self._auto_var.get(),
        }
        upsert_account(acc)
        self._accounts = load_accounts()
        self._refresh_listbox()
        for i, a in enumerate(self._accounts):
            if a["uin"] == uin:
                self._listbox.selection_clear(0, "end")
                self._listbox.selection_set(i)
                self._listbox.activate(i)
                self._listbox.see(i)
                self._select_account(i)
                break

    def _ok(self):
        uin = self._uin_entry.get("1.0", "end-1c").strip()
        pwd = self._pwd_entry.get().strip()
        srv = self._srv_entry.get("1.0", "end-1c").strip() or "195.66.114.37:5190"
        if not uin or not pwd:
            messagebox.showwarning("Ошибка", "Введите UIN и пароль", parent=self)
            return
        acc = {
            "uin":          uin,
            "password":     pwd if self._remember_var.get() else "",
            "nick":         self._nick_entry.get().strip(),
            "server":       srv,
            "remember":     self._remember_var.get(),
            "auto_connect": self._auto_var.get(),
        }
        upsert_account(acc)
        save_config({**acc, "uin": uin})

        host, port = srv, 5190
        if ":" in srv:
            parts = srv.rsplit(":", 1)
            host  = parts[0]
            try: port = int(parts[1])
            except ValueError: pass

        self.result = (uin, pwd, host, port)
        self.destroy()

    def _open_register(self):
        srv = self._srv_entry.get("1.0", "end-1c").strip() or "195.66.114.37:5190"
        dlg = RegisterDialog(self, server_str=srv)
        self.wait_window(dlg)
        if dlg.result:
            uin, pwd = dlg.result
            self._uin_entry.delete("1.0", "end")
            self._uin_entry.insert("1.0", str(uin))
            self._pwd_entry.delete(0, "end")
            self._pwd_entry.insert(0, pwd)

    def _cancel(self):
        self.destroy()


def _style_text_entry(widget):
    widget.bind("<Return>", lambda e: "break")
    widget.bind("<Control-a>", lambda e: (widget.tag_add("sel", "1.0", "end"), "break"))
    widget.bind("<Key>", lambda e: _handle_cpc(e, widget))

def _handle_cpc(event, widget):
    if event.state & 0x4:
        if event.keycode == 67:
            widget.event_generate("<<Copy>>"); return "break"
        elif event.keycode == 86:
            widget.event_generate("<<Paste>>"); return "break"
        elif event.keycode == 88:
            widget.event_generate("<<Cut>>"); return "break"

def _style_entry(widget):
    def _cpc(event):
        if event.state & 0x4:
            if event.keycode == 67:
                widget.event_generate("<<Copy>>"); return "break"
            elif event.keycode == 86:
                widget.event_generate("<<Paste>>"); return "break"
            elif event.keycode == 88:
                widget.event_generate("<<Cut>>"); return "break"
            elif event.keycode == 65:
                widget.select_range(0, "end"); return "break"
    widget.bind("<Key>", _cpc)


class RegisterDialog(tk.Toplevel):
    def __init__(self, master, server_str: str = "195.66.114.37:5190"):
        super().__init__(master)
        self.result = None
        self.title("Регистрация нового UIN")
        self.configure(bg=PALETTE["bg_main"])
        self.resizable(False, False)
        self.grab_set()
        self._server_str  = server_str
        self._own_queue: _queue.SimpleQueue = _queue.SimpleQueue()
        self._build()
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.update_idletasks()
        self.minsize(self.winfo_reqwidth(), self.winfo_reqheight())
        place_near_parent(self, master)
        self._poll_queue()

    def _poll_queue(self):
        try:
            while True:
                func = self._own_queue.get_nowait()
                func()
        except _queue.Empty:
            pass
        except Exception:
            pass
        if self.winfo_exists():
            self.after(50, self._poll_queue)

    def _build(self):
        hdr = tk.Frame(self, bg=PALETTE["title_bar"], pady=8)
        hdr.pack(fill="x")
        icon_label(hdr, "logo", "Регистрация в ICQ", fallback_symbol="☘",
                   font=("Segoe UI Symbol", 13, "bold"),
                   bg=PALETTE["title_bar"], fg="white", color="white", size=16).pack()
        tk.Label(hdr, text="Получить новый UIN через OSCAR",
                 font=("Segoe UI Symbol", 8),
                 bg=PALETTE["title_bar"], fg="#d0e8ff").pack()

        body = tk.Frame(self, bg=PALETTE["bg_main"], padx=20, pady=8)
        body.pack(fill="both", expand=True)

        tk.Label(body, text="Сервер:", font=("Segoe UI Symbol", 9),
                 bg=PALETTE["bg_main"]).grid(row=0, column=0, sticky="w", pady=4)
        self._srv_var = tk.StringVar(value=self._server_str)
        tk.Entry(body, textvariable=self._srv_var, font=("Segoe UI Symbol", 9),
                 width=22, relief="groove", bd=2).grid(
                     row=0, column=1, pady=4, padx=(8, 0), sticky="ew")

        tk.Label(body, text="Пароль:", font=("Segoe UI Symbol", 9),
                 bg=PALETTE["bg_main"]).grid(row=1, column=0, sticky="w", pady=4)
        self._pwd_var = tk.StringVar()
        self._pwd_entry = tk.Entry(body, textvariable=self._pwd_var,
                                   font=("Segoe UI Symbol", 10), width=22,
                                   relief="groove", bd=2, show="*")
        self._pwd_entry.grid(row=1, column=1, pady=4, padx=(8, 0), sticky="ew")
        self._pwd_entry.bind("<Return>", lambda e: self._do_register())

        tk.Label(body, text="Подтверждение:", font=("Segoe UI Symbol", 9),
                 bg=PALETTE["bg_main"]).grid(row=2, column=0, sticky="w", pady=4)
        self._pwd2_var = tk.StringVar()
        pwd2_entry = tk.Entry(body, textvariable=self._pwd2_var,
                              font=("Segoe UI Symbol", 10), width=22,
                              relief="groove", bd=2, show="*")
        pwd2_entry.grid(row=2, column=1, pady=4, padx=(8, 0), sticky="ew")
        pwd2_entry.bind("<Return>", lambda e: self._do_register())

        tk.Label(body, text="• 6–19 символов, только ASCII",
                 font=("Segoe UI Symbol", 7), bg=PALETTE["bg_main"],
                 fg="#666666").grid(row=3, column=0, columnspan=2, sticky="w")

        self._status_lbl = tk.Label(body, text="", font=("Segoe UI Symbol", 8, "italic"),
                                    bg=PALETTE["bg_main"], fg="#0055aa",
                                    wraplength=280, justify="left")
        self._status_lbl.grid(row=4, column=0, columnspan=2, sticky="w", pady=(6, 0))

        self._result_frame = tk.Frame(body, bg=PALETTE["bg_main"])
        self._result_frame.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        self._result_frame.grid_remove()

        res_inner = tk.Frame(self._result_frame, bg="#e8f8e8", relief="groove", bd=1)
        res_inner.pack(fill="x", pady=2)
        icon_label(res_inner, "check", "Регистрация успешна!", fallback_symbol="✔",
                   font=("Segoe UI Symbol", 9, "bold"),
                   bg="#e8f8e8", fg="#006600", color="#006600", size=13).pack(anchor="w", padx=8, pady=(6, 2))
        self._uin_result_lbl = tk.Label(res_inner, text="",
                                        font=("Segoe UI Symbol", 10, "bold"),
                                        bg="#e8f8e8", fg=PALETTE["accent"])
        self._uin_result_lbl.pack(anchor="w", padx=8, pady=(0, 6))

        body.columnconfigure(1, weight=1)

        btn_frame = tk.Frame(self, bg=PALETTE["bg_main"])
        btn_frame.pack(side="bottom", pady=10)
        self._reg_btn = icon_button(
            btn_frame, "send", "Зарегистрировать", fallback_symbol="➤",
            font=("Segoe UI Symbol", 9, "bold"),
            bg="#3a7abf", fg="white", color="white", relief="groove", bd=2,
            padx=14, pady=4, size=14,
            command=self._do_register)
        self._reg_btn.pack(side="left", padx=6)

        self._use_btn = icon_button(
            btn_frame, "smiley", "Войти с этим UIN", fallback_symbol="☺",
            font=("Segoe UI Symbol", 9, "bold"),
            bg="#2e7d32", fg="white", color="white", relief="groove", bd=2,
            padx=12, pady=4, size=15,
            command=self._use_result, state="disabled")
        self._use_btn.pack(side="left", padx=6)

        tk.Button(btn_frame, text="Закрыть",
                  font=("Segoe UI Symbol", 9), bg="#e0e0e0",
                  relief="groove", bd=2, padx=10, pady=4,
                  cursor="hand2", command=self.destroy).pack(side="left", padx=6)

        self._pwd_entry.focus_set()

    def _do_register(self):
        pwd  = self._pwd_var.get()
        pwd2 = self._pwd2_var.get()
        srv  = self._srv_var.get().strip() or "195.66.114.37:5190"

        if not pwd:
            self._set_status("⚠ Введите пароль", "#cc0000"); return
        if pwd != pwd2:
            self._set_status("⚠ Пароли не совпадают", "#cc0000"); return
        if len(pwd) < 6:
            self._set_status("⚠ Пароль слишком короткий (минимум 6 символов)", "#cc0000"); return
        if len(pwd) > 19:
            self._set_status("⚠ Пароль слишком длинный (максимум 19 символов)", "#cc0000"); return
        try:
            pwd.encode("ascii")
        except UnicodeEncodeError:
            self._set_status("⚠ Пароль должен содержать только ASCII символы", "#cc0000"); return

        host, port = srv, 5190
        if ":" in srv:
            parts = srv.rsplit(":", 1)
            host  = parts[0]
            try: port = int(parts[1])
            except ValueError: pass

        self._reg_btn.configure(state="disabled")
        self._result_frame.grid_remove()
        self._set_status(f"⊙ Подключаюсь к {host}:{port}...", "#0055aa")
        self.update()

        self._registered_uin = None
        self._registered_pwd = pwd

        def task():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                reg = ICQRegistration(server=host, port=port)
                uin = loop.run_until_complete(reg.register(pwd, timeout=20.0))
                self._own_queue.put(lambda u=uin: self._on_success(u))
            except RuntimeError as e:
                self._own_queue.put(lambda msg=str(e): self._on_error(msg))
            except ConnectionRefusedError:
                self._own_queue.put(lambda: self._on_error(
                    f"Соединение отклонено ({host}:{port})"))
            except (TimeoutError, asyncio.TimeoutError):
                self._own_queue.put(lambda: self._on_error(
                    "Таймаут — сервер не отвечает (20 с)"))
            except Exception as e:
                self._own_queue.put(lambda msg=str(e): self._on_error(f"Ошибка: {msg}"))
            finally:
                loop.close()

        threading.Thread(target=task, daemon=True).start()

    def _on_success(self, uin: int):
        self._registered_uin = uin
        self._uin_result_lbl.configure(
            text=f"UIN:     {uin}\nПароль:  {self._registered_pwd}")
        self._result_frame.grid()
        self._set_status("", "#006600")
        self._reg_btn.configure(state="disabled")
        self._use_btn.configure(state="normal")
        self.update_idletasks()
        self.minsize(self.winfo_reqwidth(), self.winfo_reqheight())

    def _on_error(self, message: str):
        self._set_status(f"✘ {message}", "#cc0000")
        self._reg_btn.configure(state="normal")

    def _set_status(self, text: str, color: str = "#0055aa"):
        self._status_lbl.configure(text=text, fg=color)

    def _use_result(self):
        if self._registered_uin:
            self.result = (self._registered_uin, self._registered_pwd)
        self.destroy()


class StatusDialog(tk.Toplevel):
    def __init__(self, master, current: Status, current_msg: str):
        super().__init__(master)
        self.result = None
        self.title("Установить статус")
        self.configure(bg=PALETTE["bg_main"])
        self.resizable(False, False)
        statuses = list(Status)
        self.status_var = tk.StringVar(value=current.label)

        btn_f = tk.Frame(self, bg=PALETTE["bg_main"])
        btn_f.pack(side="bottom", pady=8)
        tk.Button(btn_f, text="OK", font=("Segoe UI Symbol", 9, "bold"),
                  bg="#3a7abf", fg="white", relief="groove", padx=14,
                  cursor="hand2", command=self._ok).pack(side="left", padx=6)
        tk.Button(btn_f, text="Отмена", font=("Segoe UI Symbol", 9),
                  bg="#e0e0e0", relief="groove", padx=10,
                  cursor="hand2", command=self.destroy).pack(side="left")

        body = tk.Frame(self, bg=PALETTE["bg_main"], padx=16, pady=10)
        body.pack(fill="x")
        tk.Label(body, text="Выберите статус:", font=("Segoe UI Symbol", 9, "bold"),
                 bg=PALETTE["bg_main"]).pack(anchor="w", pady=(0, 6))
        self._status_photos: list = []
        for s in statuses:
            row = tk.Frame(body, bg=PALETTE["bg_main"], cursor="hand2")
            row.pack(anchor="w", pady=1)
            photo = get_status_photo(s)
            if photo:
                self._status_photos.append(photo)
                tk.Label(row, image=photo, bg=PALETTE["bg_main"],
                         width=STATUS_ICON_W, height=STATUS_ICON_H, bd=0).pack(side="left", padx=(0, 4))
            rb = tk.Radiobutton(row, text=STATUS_LABELS[s], variable=self.status_var,
                                value=s.label, font=("Segoe UI Symbol", 9),
                                bg=PALETTE["bg_main"], fg=STATUS_COLORS[s],
                                cursor="hand2", activebackground=PALETTE["bg_main"])
            rb.pack(side="left")
            row.bind("<Button-1>", lambda e, v=s.label: self.status_var.set(v))

        tk.Frame(self, height=1, bg=PALETTE["border"]).pack(fill="x", padx=8)

        xs_frame = tk.Frame(self, bg=PALETTE["bg_main"], padx=16, pady=8)
        xs_frame.pack(fill="x")
        tk.Label(xs_frame, text="xStatus:", font=("Segoe UI Symbol", 9, "bold"),
                 bg=PALETTE["bg_main"]).pack(anchor="w", pady=(0, 4))

        xs_row = tk.Frame(xs_frame, bg=PALETTE["bg_main"])
        xs_row.pack(anchor="w", fill="x")

        cfg = load_config()
        xs_names     = [""] + [name for _, name in XSTATUS_TABLE]
        self._xs_var = tk.StringVar(value=cfg.get("xstatus_name", ""))

        self._xs_preview = tk.Label(xs_row, bg=PALETTE["bg_main"], image="", bd=0)
        self._xs_preview._xstatus_photo = None
        self._xs_preview.pack(side="left", padx=(0, 4))

        xs_combo = ttk.Combobox(xs_row, textvariable=self._xs_var,
                                values=xs_names, width=16, state="readonly")
        xs_combo.pack(side="left")

        def _update_xs_preview(*_):
            name  = self._xs_var.get()
            idx   = get_xstatus_index_by_name(name)
            photo = get_xstatus_photo(idx) if idx >= 0 else None
            if photo:
                self._xs_preview.configure(image=photo,
                                           width=XSTATUS_ICON_W, height=XSTATUS_ICON_H)
                self._xs_preview._xstatus_photo = photo
                self._xs_preview.pack(side="left", padx=(0, 4))
            else:
                self._xs_preview.pack_forget()
                self._xs_preview.configure(image="", width=1, height=1)
                self._xs_preview._xstatus_photo = None

        xs_combo.bind("<<ComboboxSelected>>", _update_xs_preview)
        _update_xs_preview()

        sub = tk.Frame(xs_frame, bg=PALETTE["bg_main"])
        sub.pack(fill="x", pady=(6, 0))
        sub.columnconfigure(1, weight=1)

        tk.Label(sub, text="Заголовок:", font=("Segoe UI Symbol", 8),
                 bg=PALETTE["bg_main"], anchor="e").grid(row=0, column=0, sticky="e", pady=2, padx=(0, 4))
        self._xs_title_var = tk.StringVar(value=cfg.get("xstatus_title", ""))
        tk.Entry(sub, textvariable=self._xs_title_var, font=("Segoe UI Symbol", 9),
                 relief="groove", bd=2).grid(row=0, column=1, sticky="ew", pady=2)

        tk.Label(sub, text="Описание:", font=("Segoe UI Symbol", 8),
                 bg=PALETTE["bg_main"], anchor="e").grid(row=1, column=0, sticky="e", pady=2, padx=(0, 4))
        self._xs_desc_var = tk.StringVar(value=cfg.get("xstatus_desc", ""))
        tk.Entry(sub, textvariable=self._xs_desc_var, font=("Segoe UI Symbol", 9),
                 relief="groove", bd=2).grid(row=1, column=1, sticky="ew", pady=2)

        self.update_idletasks()
        self.minsize(self.winfo_reqwidth(), self.winfo_reqheight())
        place_near_parent(self, master)

    def _ok(self):
        label = self.status_var.get()
        for s in Status:
            if s.label == label:
                self.result = (s, "",
                               self._xs_var.get(),
                               self._xs_title_var.get().strip(),
                               self._xs_desc_var.get().strip())
                break
        self.destroy()


class UserInfoDialog(tk.Toplevel):
    _FIELDS = [
        ("Никнейм",       "nick",       True),
        ("Имя",           "first_name", True),
        ("Фамилия",       "last_name",  True),
        ("E-mail",        "email",      True),
        ("Город",         "city",       True),
        ("Дата рожд.",    "birthday",   True),
        ("Пол (M/F)",     "gender",     True),
        ("Сайт",          "home_page",  True),
        ("О себе",        "about",      True),
    ]

    def __init__(self, master, uin: str, display_name: str, editable: bool = False):
        super().__init__(master)
        self.uin        = uin
        self.editable   = editable
        self.on_save    = None
        self.on_set_require_auth = None
        self.title(f"{'Моя анкета' if editable else 'Анкета'} — {display_name}  ({uin})")
        self.configure(bg=PALETTE["bg_main"])
        self.resizable(True, True)
        self._vars: Dict[str, tk.StringVar] = {}
        self._require_auth_var = tk.BooleanVar(value=False)
        self._build()
        self.update_idletasks()
        w = max(self.winfo_reqwidth(), 420)
        h = min(self.winfo_reqheight(), 600)
        self.geometry(f"{w}x{h}")
        self.minsize(360, h)
        place_near_parent(self, master)

    def _build(self):
        tk.Label(self, text=f"☘ {'Моя анкета' if self.editable else 'Анкета пользователя'}",
                 font=("Segoe UI Symbol", 11, "bold"), bg=PALETTE["title_bar"], fg="white").pack(fill="x")

        outer  = tk.Frame(self, bg=PALETTE["bg_main"])
        outer.pack(fill="both", expand=True, padx=6, pady=4)
        canvas = tk.Canvas(outer, bg=PALETTE["bg_main"], highlightthickness=0, bd=0,
                           height=300)
        vsb    = tk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        inner  = tk.Frame(canvas, bg=PALETTE["bg_main"])
        cw     = canvas.create_window((0, 0), window=inner, anchor="nw")
        def _on_inner_configure(e):
            canvas.configure(scrollregion=canvas.bbox("all"))
            content_h = inner.winfo_reqheight()
            canvas.configure(height=min(content_h, 300))
        inner.bind("<Configure>", _on_inner_configure)
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(cw, width=e.width))
        canvas.bind("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

        for row_idx, (label, attr, _editable) in enumerate(self._FIELDS):
            tk.Label(inner, text=label + ":", font=("Segoe UI Symbol", 8, "bold"),
                     bg=PALETTE["bg_main"], anchor="e", width=14).grid(
                         row=row_idx, column=0, sticky="e", pady=2, padx=(4, 2))
            var = tk.StringVar()
            self._vars[attr] = var
            if attr == "birthday" and self.editable:
                cell = tk.Frame(inner, bg=PALETTE["bg_main"])
                cell.grid(row=row_idx, column=1, sticky="ew", padx=(2, 4), pady=2)
                cell.columnconfigure(0, weight=1)
                bday_entry = tk.Entry(cell, textvariable=var,
                                     font=("Segoe UI Symbol", 9), relief="groove", bd=2,
                                     width=16)
                bday_entry.grid(row=0, column=0, sticky="ew")
                _style_entry(bday_entry)
                icon_button(cell, "calendar", fallback_symbol="📅",
                            font=("Segoe UI Symbol", 9), bg=PALETTE["toolbar_bg"],
                            relief="groove", bd=1, padx=4, size=13,
                            command=lambda v=var: self._open_date_picker(v)
                            ).grid(row=0, column=1, padx=(2, 0))
            else:
                state = "normal" if (self.editable and _editable) else "readonly"
                e = tk.Entry(inner, textvariable=var, font=("Segoe UI Symbol", 9),
                             relief="groove", bd=2, state=state,
                             readonlybackground=PALETTE["bg_list"], width=28)
                e.grid(row=row_idx, column=1, sticky="ew", padx=(2, 4), pady=2)
                if self.editable and _editable:
                    _style_entry(e)
        inner.columnconfigure(1, weight=1)

        if self.editable:
            auth_frame = tk.Frame(self, bg=PALETTE["bg_main"])
            auth_frame.pack(fill="x", padx=10, pady=(4, 0))
            icon_label(auth_frame, "lock", "Конфиденциальность:", fallback_symbol="🔒",
                       font=("Segoe UI Symbol", 8, "bold"),
                       bg=PALETTE["bg_main"], size=12).pack(anchor="w")
            self._auth_cb = tk.Checkbutton(
                auth_frame,
                text="Требовать авторизацию при добавлении",
                variable=self._require_auth_var,
                font=("Segoe UI Symbol", 8), bg=PALETTE["bg_main"],
                activebackground=PALETTE["bg_main"], cursor="hand2",
                command=self._on_require_auth_toggle)
            self._auth_cb.pack(anchor="w", padx=4)

        self._status_lbl = tk.Label(self, text="", font=("Segoe UI Symbol", 8, "italic"),
                                    bg=PALETTE["bg_main"], fg="#0055aa")
        self._status_lbl.pack(anchor="w", padx=8)

        btn_f = tk.Frame(self, bg=PALETTE["bg_main"])
        btn_f.pack(pady=6)
        if self.editable:
            icon_button(btn_f, "check", "Сохранить", fallback_symbol="✔",
                        font=("Segoe UI Symbol", 9, "bold"),
                        bg="#3a7abf", fg="white", color="white", relief="groove",
                        padx=14, size=13,
                        command=self._do_save).pack(side="left", padx=6)
        tk.Button(btn_f, text="Закрыть", font=("Segoe UI Symbol", 9), bg="#e0e0e0",
                  relief="groove", padx=10, cursor="hand2",
                  command=self.destroy).pack(side="left", padx=4)

    def _open_date_picker(self, var: tk.StringVar):
        import datetime
        picker = tk.Toplevel(self)
        picker.title("Дата рождения")
        picker.configure(bg=PALETTE["bg_main"])
        picker.resizable(False, False)
        picker.grab_set()
        picker.transient(self)

        current = var.get().strip()
        try:
            dt = datetime.datetime.strptime(current, "%d.%m.%Y")
            cy, cm, cd = dt.year, dt.month, dt.day
        except Exception:
            today = datetime.date.today()
            cy, cm, cd = today.year - 25, today.month, today.day

        _state = {"year": cy, "month": cm, "day": cd}
        MONTHS = ["Январь","Февраль","Март","Апрель","Май","Июнь",
                  "Июль","Август","Сентябрь","Октябрь","Ноябрь","Декабрь"]
        DAYS_HEADER = ["Пн","Вт","Ср","Чт","Пт","Сб","Вс"]

        hdr = tk.Frame(picker, bg=PALETTE["title_bar"])
        hdr.pack(fill="x")
        lbl_month = tk.Label(hdr, text="", font=("Segoe UI Symbol", 9, "bold"),
                             bg=PALETTE["title_bar"], fg="white")
        lbl_month.pack(side="left", expand=True, fill="x", padx=6, pady=4)

        nav = tk.Frame(hdr, bg=PALETTE["title_bar"])
        nav.pack(side="right")

        year_frame = tk.Frame(picker, bg=PALETTE["bg_main"])
        year_frame.pack(fill="x", padx=6, pady=(4, 0))
        tk.Label(year_frame, text="Год:", font=("Segoe UI Symbol", 8),
                 bg=PALETTE["bg_main"]).pack(side="left")
        year_var = tk.StringVar(value=str(_state["year"]))
        year_spin = tk.Spinbox(year_frame, from_=1900, to=datetime.date.today().year,
                               textvariable=year_var, width=6,
                               font=("Segoe UI Symbol", 9), relief="groove", bd=2)
        year_spin.pack(side="left", padx=4)

        cal_frame = tk.Frame(picker, bg=PALETTE["bg_main"], padx=6, pady=4)
        cal_frame.pack()
        day_btns: list = []

        def _render():
            for w in day_btns:
                try: w.destroy()
                except Exception: pass
            day_btns.clear()
            try:
                yr = int(year_var.get())
            except ValueError:
                yr = _state["year"]
            _state["year"] = yr
            mo = _state["month"]
            lbl_month.configure(text=f"{MONTHS[mo-1]} {yr}")
            import calendar
            first_wd, ndays = calendar.monthrange(yr, mo)
            for col, d in enumerate(DAYS_HEADER):
                lbl = tk.Label(cal_frame, text=d, font=("Segoe UI Symbol", 7, "bold"),
                               bg=PALETTE["bg_main"], fg=PALETTE["accent"], width=3)
                lbl.grid(row=0, column=col, padx=1, pady=1)
                day_btns.append(lbl)
            row, col = 1, first_wd
            for day in range(1, ndays + 1):
                is_sel = (day == _state["day"] and mo == _state["month"]
                          and yr == _state["year"])
                bg = PALETTE["accent"] if is_sel else PALETTE["bg_list"]
                fg = "white" if is_sel else PALETTE["msg_text"]
                btn = tk.Button(
                    cal_frame, text=str(day), font=("Segoe UI Symbol", 8),
                    bg=bg, fg=fg, relief="flat", width=3, cursor="hand2",
                    command=lambda d=day: _pick(d))
                btn.grid(row=row, column=col, padx=1, pady=1)
                day_btns.append(btn)
                col += 1
                if col > 6:
                    col = 0; row += 1

        def _prev_month():
            if _state["month"] == 1:
                _state["month"] = 12
                _state["year"] -= 1
                year_var.set(str(_state["year"]))
            else:
                _state["month"] -= 1
            _render()

        def _next_month():
            if _state["month"] == 12:
                _state["month"] = 1
                _state["year"] += 1
                year_var.set(str(_state["year"]))
            else:
                _state["month"] += 1
            _render()

        def _pick(day: int):
            try:
                yr = int(year_var.get())
            except ValueError:
                yr = _state["year"]
            _state.update({"day": day, "year": yr})
            import datetime
            try:
                datetime.date(_state["year"], _state["month"], _state["day"])
            except ValueError:
                _state["day"] = 1
            var.set(f"{_state['day']:02d}.{_state['month']:02d}.{_state['year']}")
            picker.destroy()

        icon_button(nav, "arrow_left", fallback_symbol="◀", font=("Segoe UI Symbol", 8),
                    bg=PALETTE["title_bar"], color="white", relief="flat", size=11,
                    command=_prev_month).pack(side="left", padx=2)
        icon_button(nav, "arrow_right", fallback_symbol="▶", font=("Segoe UI Symbol", 8),
                    bg=PALETTE["title_bar"], color="white", relief="flat", size=11,
                    command=_next_month).pack(side="left", padx=2)

        year_spin.bind("<Return>", lambda e: _render())
        year_spin.bind("<FocusOut>", lambda e: _render())

        btn_row = tk.Frame(picker, bg=PALETTE["bg_main"])
        btn_row.pack(pady=4)
        tk.Button(btn_row, text="Очистить", font=("Segoe UI Symbol", 8),
                  bg="#e0e0e0", relief="groove", padx=8, cursor="hand2",
                  command=lambda: [var.set(""), picker.destroy()]).pack(side="left", padx=4)
        tk.Button(btn_row, text="Отмена", font=("Segoe UI Symbol", 8),
                  bg="#e0e0e0", relief="groove", padx=8, cursor="hand2",
                  command=picker.destroy).pack(side="left", padx=4)

        _render()
        place_near_parent(picker, self)

    def _on_require_auth_toggle(self):
        if self.on_set_require_auth:
            self.on_set_require_auth(self._require_auth_var.get())

    def set_require_auth_state(self, require: bool):
        self._require_auth_var.set(require)

    def load_info(self, info: UserInfo):
        for _, attr, _ in self._FIELDS:
            val = getattr(info, attr, "")
            if isinstance(val, int) and val == 0:
                val = ""
            self._vars[attr].set(str(val) if val else "")
        if self.editable and hasattr(info, "auth_required"):
            self._require_auth_var.set(bool(info.auth_required))
        self._status_lbl.configure(text="", fg="#0055aa")

    def set_status(self, text: str, color: str = "#0055aa"):
        self._status_lbl.configure(text=text, fg=color)

    def _do_save(self):
        info = UserInfo(uin=self.uin)
        for _, attr, _ in self._FIELDS:
            val = self._vars[attr].get().strip()
            if attr == "age":
                try: setattr(info, attr, int(val))
                except ValueError: pass
            else:
                setattr(info, attr, val)
        info.auth_required = bool(self._require_auth_var.get())
        if self.on_save:
            self.on_save(info)


class SearchDialog(tk.Toplevel):
    def __init__(self, master, client: ICQClient, loop):
        super().__init__(master)
        self._client  = client
        self._loop    = loop
        self._results: List[SearchResult] = []
        self._timeout_job = None
        self.title("Поиск пользователей")
        self.minsize(480, 420)
        self.configure(bg=PALETTE["bg_main"])
        self._build()
        self.update_idletasks()
        if self.winfo_reqwidth() > 480:
            self.geometry(f"{self.winfo_reqwidth()}x500")
        place_near_parent(self, master)

    def _build(self):
        icon_label(self, "search", "Поиск пользователей ICQ", fallback_symbol="🔍",
                   font=("Segoe UI Symbol", 10, "bold"),
                   bg=PALETTE["title_bar"], fg="white", color="white", size=14).pack(fill="x")

        btn_f = tk.Frame(self, bg=PALETTE["bg_main"])
        btn_f.pack(side="bottom", pady=6)
        icon_button(btn_f, "mail", "Написать", fallback_symbol="✉",
                    font=("Segoe UI Symbol", 9), bg="#3a7abf", fg="white", color="white",
                    relief="groove", padx=10, size=13,
                    command=self._open_selected_chat).pack(side="left", padx=4)
        icon_button(btn_f, "plus", "Добавить в список", fallback_symbol="➕",
                    font=("Segoe UI Symbol", 9), bg="#4a9a4f", fg="white", color="white",
                    relief="groove", padx=10, size=13,
                    command=self._add_selected).pack(side="left", padx=4)
        icon_button(btn_f, "info", "Анкета", fallback_symbol="ℹ",
                    font=("Segoe UI Symbol", 9), bg="#e0e0e0",
                    relief="groove", padx=10, size=13,
                    command=self._view_selected_info).pack(side="left", padx=4)

        form = tk.LabelFrame(self, text="Критерии поиска", font=("Segoe UI Symbol", 8),
                             bg=PALETTE["bg_main"], padx=8, pady=4)
        form.pack(fill="x", padx=8, pady=(6, 2))

        fields_left  = [("UIN:", "uin"), ("Никнейм:", "nick"), ("Имя:", "first_name"), ("Фамилия:", "last_name")]
        fields_right = [("E-mail:", "email"), ("Город:", "city"), ("Ключ. слово:", "keyword")]
        self._svars: Dict[str, tk.StringVar] = {}

        for col, flist in [(0, fields_left), (2, fields_right)]:
            for row, (lbl, key) in enumerate(flist):
                tk.Label(form, text=lbl, font=("Segoe UI Symbol", 8),
                         bg=PALETTE["bg_main"], anchor="e", width=12).grid(
                             row=row, column=col, sticky="e", pady=2, padx=(4, 2))
                var = tk.StringVar()
                self._svars[key] = var
                ent = tk.Entry(form, textvariable=var, font=("Segoe UI Symbol", 9),
                               relief="groove", bd=2, width=18)
                ent.grid(row=row, column=col+1, sticky="ew", padx=(0, 8))
                _style_entry(ent)

        self._only_online_var = tk.BooleanVar()
        tk.Checkbutton(form, text="Только онлайн", variable=self._only_online_var,
                       font=("Segoe UI Symbol", 8), bg=PALETTE["bg_main"],
                       cursor="hand2").grid(row=len(fields_left), column=0,
                                            columnspan=2, sticky="w", pady=2)
        form.columnconfigure(1, weight=1)
        form.columnconfigure(3, weight=1)

        ctrl_f = tk.Frame(self, bg=PALETTE["bg_main"])
        ctrl_f.pack(fill="x", padx=8, pady=(0, 4))
        icon_button(ctrl_f, "search", "Найти", fallback_symbol="🔍",
                    font=("Segoe UI Symbol", 9, "bold"), bg="#3a7abf", fg="white",
                    color="white", relief="groove", padx=14, size=13,
                    command=self._do_search).pack(side="left", padx=4)
        tk.Button(ctrl_f, text="Очистить", font=("Segoe UI Symbol", 9), bg="#e0e0e0",
                  relief="groove", padx=8, cursor="hand2",
                  command=self._clear_results).pack(side="left", padx=4)
        self._search_status = tk.Label(ctrl_f, text="", font=("Segoe UI Symbol", 8, "italic"),
                                       bg=PALETTE["bg_main"], fg="#0055aa")
        self._search_status.pack(side="left", padx=8)

        cols = ("UIN", "Ник", "Имя", "Пол", "Возраст", "Онлайн", "Авт.")
        tree_frame = tk.Frame(self, bg=PALETTE["bg_list"])
        tree_frame.pack(fill="both", expand=True, padx=8, pady=(0, 4))
        vsb = tk.Scrollbar(tree_frame, orient="vertical")
        hsb = tk.Scrollbar(tree_frame, orient="horizontal")
        self._tree = ttk.Treeview(tree_frame, columns=cols, show="headings",
                                   yscrollcommand=vsb.set, xscrollcommand=hsb.set,
                                   selectmode="browse")
        vsb.configure(command=self._tree.yview)
        hsb.configure(command=self._tree.xview)
        vsb.pack(side="right", fill="y")
        hsb.pack(side="bottom", fill="x")
        self._tree.pack(fill="both", expand=True)
        widths = (80, 100, 130, 40, 55, 50, 35)
        for col, w in zip(cols, widths):
            self._tree.heading(col, text=col)
            self._tree.column(col, width=w, minwidth=30, anchor="center")
        self._tree.bind("<Double-1>", self._on_result_double_click)

    def _do_search(self):
        from theme import schedule_in_tk
        kw = {k: self._svars[k].get().strip() for k in self._svars}
        if not any(kw.values()):
            messagebox.showwarning("Поиск", "Укажите хотя бы один критерий.", parent=self)
            return
        if not self._client or not self._loop or not self._loop.is_running():
            messagebox.showwarning("Поиск", "Нет подключения к серверу.", parent=self)
            return
        self._clear_results()
        if self._timeout_job:
            try: self.after_cancel(self._timeout_job)
            except Exception: pass
            self._timeout_job = None
        self._search_status.configure(text="Поиск...", fg="#0055aa")
        only_online = self._only_online_var.get()

        def task():
            try:
                asyncio.run_coroutine_threadsafe(
                    self._client.search_users(
                        uin=kw.get("uin",""), nick=kw.get("nick",""),
                        first_name=kw.get("first_name",""), last_name=kw.get("last_name",""),
                        email=kw.get("email",""), city=kw.get("city",""),
                        keyword=kw.get("keyword",""), only_online=only_online,
                    ), self._loop
                )
            except RuntimeError:
                schedule_in_tk(self.master, lambda: self._search_status.configure(
                    text="Ошибка: нет подключения", fg="#cc0000"))

        threading.Thread(target=task, daemon=True).start()

        def _on_timeout():
            self._timeout_job = None
            if not self.winfo_exists(): return
            self._search_status.configure(
                text=f"Завершено ({len(self._results)} найдено)" if self._results else "Ничего не найдено",
                fg="#006600" if self._results else "#cc0000"
            )
        self._timeout_job = self.after(30000, _on_timeout)

    def search_done(self, results: list):
        if self._timeout_job:
            try: self.after_cancel(self._timeout_job)
            except Exception: pass
            self._timeout_job = None
        count = len(self._results)
        if count:
            self._search_status.configure(text=f"Найдено: {count}", fg="#006600")
        else:
            self._search_status.configure(text="Ничего не найдено", fg="#cc0000")

    def add_result(self, result: SearchResult):
        self._results.append(result)
        self._tree.insert("", "end", iid=result.uin, values=(
            result.uin,
            result.nick or "—",
            f"{result.first_name} {result.last_name}".strip() or "—",
            result.gender or "—",
            result.age if result.age else "—",
            "●" if result.online else "○",
            "Да" if result.auth_req else "Нет",
        ))
        self._search_status.configure(text=f"Найдено: {len(self._results)}", fg="#006600")

    def _clear_results(self):
        for item in self._tree.get_children():
            self._tree.delete(item)
        self._results.clear()
        self._search_status.configure(text="")

    def _selected_result(self) -> Optional[SearchResult]:
        sel = self._tree.selection()
        if not sel: return None
        uin = sel[0]
        return next((r for r in self._results if r.uin == uin), None)

    def _on_result_double_click(self, event):
        self._open_selected_chat()

    def _open_selected_chat(self):
        r = self._selected_result()
        if not r: return
        contact = self._client.contacts.get(r.uin)
        if contact is None:
            contact = type("FC", (), {"uin": r.uin, "display_name": r.nick or r.uin,
                                       "xstatus": "", "xstatus_msg": "", "is_online": r.online})()
        if hasattr(self.master, "_open_chat"):
            self.master._open_chat(contact)

    def _add_selected(self):
        r = self._selected_result()
        if not r: return
        if hasattr(self.master, "_add_contact_dialog"):
            self.master._add_contact_dialog(r.uin, prefill_nick=r.nick or "",
                                            prefill_auth_req=bool(r.auth_req))

    def _view_selected_info(self):
        r = self._selected_result()
        if not r: return
        contact = type("FC", (), {"uin": r.uin, "display_name": r.nick or r.uin})()
        if hasattr(self.master, "_show_contact_info"):
            self.master._show_contact_info(contact)


class AuthRequestDialog(tk.Toplevel):
    def __init__(self, master, uin: str, display_name: str, message: str):
        super().__init__(master)
        self.uin       = uin
        self.on_reply  = None
        self._replied  = False

        self.title("Запрос авторизации")
        self.resizable(False, False)
        self.attributes("-topmost", True)
        self.configure(bg=PALETTE["bg_main"])
        self.geometry("340x210")

        BG_HEAD = "#5a8ab0"
        hdr = tk.Frame(self, bg=BG_HEAD, pady=6, padx=10)
        hdr.pack(fill="x")
        icon_label(hdr, "shield", "Запрос авторизации", fallback_symbol="◈",
                   font=("Segoe UI Symbol", 10, "bold"),
                   bg=BG_HEAD, fg="white", color="white", size=14).pack(side="left")

        body = tk.Frame(self, bg=PALETTE["bg_main"], padx=14, pady=10)
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)

        tk.Label(body, text="От:", font=("Segoe UI Symbol", 9, "bold"),
                 bg=PALETTE["bg_main"], anchor="e").grid(row=0, column=0, sticky="e", pady=3)
        name_text = f"{display_name}  ({uin})" if display_name != uin else uin
        tk.Label(body, text=name_text, font=("Segoe UI Symbol", 9),
                 bg=PALETTE["bg_main"], anchor="w", fg=PALETTE["accent"]).grid(
                     row=0, column=1, sticky="w", padx=8)

        tk.Label(body, text="Сообщение:", font=("Segoe UI Symbol", 9, "bold"),
                 bg=PALETTE["bg_main"], anchor="ne").grid(row=1, column=0, sticky="ne", pady=3)
        msg_frame = tk.Frame(body, bg=PALETTE["bg_main"])
        msg_frame.grid(row=1, column=1, sticky="ew", padx=8)
        msg_text = tk.Text(msg_frame, height=3, width=28, font=("Segoe UI Symbol", 9),
                           bg=PALETTE["input_bg"], relief="groove", bd=1,
                           wrap="word", state="normal")
        msg_text.insert("1.0", message or "(без сообщения)")
        msg_text.configure(state="disabled")
        msg_text.pack(fill="x")

        tk.Label(body, text="Причина\nотклонения:", font=("Segoe UI Symbol", 9),
                 bg=PALETTE["bg_main"], anchor="ne").grid(row=2, column=0, sticky="ne", pady=3)
        self._reason_var   = tk.StringVar()
        self._reason_entry = tk.Entry(body, textvariable=self._reason_var,
                                       font=("Segoe UI Symbol", 9), width=28,
                                       relief="groove", bd=2, bg=PALETTE["input_bg"])
        self._reason_entry.grid(row=2, column=1, sticky="ew", padx=8, pady=3)

        btn_f = tk.Frame(self, bg=PALETTE["bg_main"], pady=6)
        btn_f.pack()
        icon_button(btn_f, "check", "Разрешить", fallback_symbol="✔",
                    font=("Segoe UI Symbol", 9, "bold"), bg="#2e7d32", fg="white",
                    color="white", relief="groove", padx=12, size=13,
                    command=self._grant).pack(side="left", padx=6)
        icon_button(btn_f, "close", "Отклонить", fallback_symbol="✘",
                    font=("Segoe UI Symbol", 9, "bold"), bg="#b71c1c", fg="white",
                    color="white", relief="groove", padx=12, size=12,
                    command=self._deny).pack(side="left", padx=6)
        tk.Button(btn_f, text="Закрыть", font=("Segoe UI Symbol", 9),
                  bg="#e0e0e0", relief="groove", padx=10,
                  cursor="hand2", command=self.destroy).pack(side="left", padx=6)

        self.protocol("WM_DELETE_WINDOW", self.destroy)
        place_near_parent(self, master)
        self.lift()
        self.focus_force()

    def _grant(self):
        if not self._replied:
            self._replied = True
            if self.on_reply:
                self.on_reply(self.uin, True, "")
        self.destroy()

    def _deny(self):
        if not self._replied:
            self._replied = True
            reason = self._reason_var.get().strip()
            if self.on_reply:
                self.on_reply(self.uin, False, reason)
        self.destroy()


class AuthReplyNotification(tk.Toplevel):
    def __init__(self, master, uin: str, display_name: str, granted: bool, message: str):
        super().__init__(master)
        self.title("ICQ")
        self.overrideredirect(True)
        self.attributes("-topmost", True)

        BG     = "#1a5f2e" if granted else "#7a1a1a"
        STRIPE = "#2e8b57" if granted else "#cc2222"
        icon   = "✔" if granted else "✘"
        status = "разрешил авторизацию" if granted else "отклонил авторизацию"

        self.configure(bg=BG)
        w, h   = 280, 72
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{w}x{h}+{sw - w - 20}+{sh - h - 50}")

        tk.Frame(self, height=3, bg=STRIPE).pack(fill="x", side="top")
        body = tk.Frame(self, bg=BG, padx=10, pady=6)
        body.pack(fill="both", expand=True)

        title_str = f"{icon} {display_name} ({uin})"
        tk.Label(body, text=title_str, font=("Segoe UI Symbol", 9, "bold"),
                 bg=BG, fg="white", anchor="w").pack(fill="x")
        detail = status + (f": {message}" if message else "")
        tk.Label(body, text=detail, font=("Segoe UI Symbol", 8),
                 bg=BG, fg="#ccffcc" if granted else "#ffcccc",
                 anchor="w", wraplength=258, justify="left").pack(fill="x", pady=(2, 0))

        for widget in (self, body):
            widget.bind("<Button-1>", lambda e: self.destroy())

        self.after(6000, self._safe_destroy)

    def _safe_destroy(self):
        try:
            self.destroy()
        except Exception:
            pass