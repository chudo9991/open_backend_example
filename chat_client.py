#!/usr/bin/env python3
"""Простейший Tkinter-клиент для чата (сервер — FastAPI из этого проекта)."""
import json
import tkinter as tk
from tkinter import messagebox
from urllib import error, request
from urllib.parse import quote

POLL_MS = 3000


class ChatClient:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.messages = {}  # id -> message, порядок = порядок сервера
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        self.root.title("Чат")
        top = tk.Frame(self.root)
        top.pack(fill="x")
        tk.Label(top, text="Сервер:").pack(side="left")
        self.server = tk.Entry(top)
        self.server.insert(0, "http://45.144.30.194:8001")
        self.server.pack(side="left", fill="x", expand=True)
        tk.Label(top, text="Имя:").pack(side="left")
        self.author = tk.Entry(top, width=15)
        self.author.pack(side="left")

        self.listbox = tk.Listbox(self.root, width=80, height=20)
        self.listbox.pack(fill="both", expand=True)

        bottom = tk.Frame(self.root)
        bottom.pack(fill="x")
        self.entry = tk.Entry(bottom)
        self.entry.pack(side="left", fill="x", expand=True)
        self.entry.bind("<Return>", lambda _e: self.send())
        tk.Button(bottom, text="Отправить", command=self.send).pack(side="left")
        tk.Button(bottom, text="Удалить", command=self.delete).pack(side="left")

    def _api(self, method: str, path: str, payload: dict | None = None):
        url = self.server.get().strip().rstrip("/") + path
        data = json.dumps(payload).encode() if payload is not None else None
        req = request.Request(
            url, data=data, method=method, headers={"Content-Type": "application/json"}
        )
        with request.urlopen(req, timeout=5) as resp:
            body = resp.read()
            return json.loads(body) if body else None

    def refresh(self) -> None:
        try:
            data = self._api("GET", "/messages")
        except Exception as exc:  # сеть/сервер недоступны — сообщаем в заголовке и пробуем снова
            self.root.title(f"Чат — нет связи: {exc}")
            self.root.after(POLL_MS, self.refresh)
            return
        self.root.title("Чат")
        if [m["id"] for m in data] != list(self.messages):
            self.messages = {m["id"]: m for m in data}
            self._render()
        self.root.after(POLL_MS, self.refresh)

    def _render(self) -> None:
        self.listbox.delete(0, tk.END)
        me = self.author.get().strip()
        for message in self.messages.values():
            mark = " [моё]" if message["author"] == me else ""
            self.listbox.insert(
                tk.END, f"{message['created_at'][:19]} {message['author']}: {message['text']}{mark}"
            )

    def send(self) -> None:
        text = self.entry.get().strip()
        author = self.author.get().strip()
        if not text or not author:
            messagebox.showwarning("Чат", "Укажите имя и текст сообщения")
            return
        try:
            self._api("POST", "/messages", {"author": author, "text": text})
        except error.HTTPError as exc:
            messagebox.showerror("Чат", exc.read().decode())
            return
        except Exception as exc:
            messagebox.showerror("Чат", str(exc))
            return
        self.entry.delete(0, tk.END)
        self.refresh()

    def delete(self) -> None:
        selection = self.listbox.curselection()
        author = self.author.get().strip()
        if not selection:
            return
        message_id = list(self.messages)[selection[0]]
        if self.messages[message_id]["author"] != author:
            messagebox.showwarning("Чат", "Можно удалять только свои сообщения")
            return
        try:
            self._api("DELETE", f"/messages/{message_id}?author={quote(author)}")
        except Exception as exc:
            messagebox.showerror("Чат", str(exc))
            return
        self.messages.pop(message_id, None)
        self._render()


if __name__ == "__main__":
    root = tk.Tk()
    ChatClient(root)
    root.mainloop()
