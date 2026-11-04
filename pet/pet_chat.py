# -*- coding: utf-8 -*-
"""
桌宠对话外挂 — 点击 DesktopGremlin 桌宠，弹出对话气泡，走本地 Ollama。

用法:
    python pet_chat.py            # 正常启动（无控制台窗口时用 pythonw）
    python pet_chat.py --test     # 不发界面，直接测一次 API

配置在下方常量区，改完重启即可。
"""
import ctypes
import ctypes.wintypes as wt
import json
import os
import sys
import threading
import time
import urllib.request
import datetime

# ---------------- 配置 ----------------
OLLAMA = "http://127.0.0.1:11434"
MODEL = "qwen9b"                 # 换成 qwen9b32k 也行（显存更紧）
PET_EXE = "desktopgremlin.exe"   # 目标进程名，小写
THINK = False                    # 关思考，响应快
NUM_PREDICT = 512
POLL_MS = 60                     # 鼠标轮询间隔
SYSTEM_PROMPT = (
    "你是特雷森学园的一名马娘，正趴在用户的桌面上陪他。"
    "说话简短口语化，一次不超过三句，偶尔带点小傲娇。"
    "不要自称 AI、不要提模型、不要输出列表和标题。"
)
# -------------------------------------

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # 物理像素，坐标才对得上
except Exception:
    pass

EnumWindowsProc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)


def _pid_of(hwnd):
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def _exe_of(pid):
    PROCESS_QUERY_LIMITED = 0x1000
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED, False, pid)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wt.DWORD(1024)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value).lower()
        return ""
    finally:
        kernel32.CloseHandle(h)


def pet_rects():
    """返回桌宠所有可见窗口的矩形 [(l,t,r,b), ...]"""
    out = []
    cache = {}

    def cb(hwnd, lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        pid = _pid_of(hwnd)
        if pid not in cache:
            cache[pid] = _exe_of(pid)
        if cache[pid] != PET_EXE:
            return True
        r = wt.RECT()
        if user32.GetWindowRect(hwnd, ctypes.byref(r)):
            if r.right - r.left > 10 and r.bottom - r.top > 10:
                out.append((r.left, r.top, r.right, r.bottom))
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return out


def cursor_pos():
    p = wt.POINT()
    user32.GetCursorPos(ctypes.byref(p))
    return p.x, p.y


def left_down():
    return bool(user32.GetAsyncKeyState(0x01) & 0x8000)


# 本地请求必须绕过系统代理（Clash 之类会把 127.0.0.1 也代理掉 → 502）
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _open(req, timeout):
    return _OPENER.open(req, timeout=timeout)


def chat_stream(messages, on_delta, on_done, on_error):
    """流式调用 Ollama"""
    body = json.dumps({
        "model": MODEL,
        "messages": messages,
        "stream": True,
        "think": THINK,
        "options": {"num_predict": NUM_PREDICT},
    }).encode("utf-8")

    def worker():
        try:
            req = urllib.request.Request(
                OLLAMA + "/api/chat", data=body,
                headers={"Content-Type": "application/json"})
            with _open(req, 300) as resp:
                for line in resp:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue
                    piece = (obj.get("message") or {}).get("content") or ""
                    if piece:
                        on_delta(piece)
                    if obj.get("done"):
                        break
            on_done()
        except Exception as e:
            on_error(str(e))

    threading.Thread(target=worker, daemon=True).start()


class ChatBubble:
    def __init__(self, root):
        self.root = root
        self.history = []
        self.busy = False
        self._build()
        self.top.withdraw()

    def _build(self):
        self.top = tk.Toplevel(self.root)
        self.top.overrideredirect(True)
        self.top.attributes("-topmost", True)
        self.top.configure(bg="#1f1f23")

        wrap = tk.Frame(self.top, bg="#2a2a31", bd=0, highlightthickness=1,
                        highlightbackground="#4a4a55")
        wrap.pack(fill="both", expand=True, padx=1, pady=1)

        head = tk.Frame(wrap, bg="#2a2a31")
        head.pack(fill="x", padx=10, pady=(8, 0))
        tk.Label(head, text="和她说点什么", bg="#2a2a31", fg="#9a9aa8",
                 font=("Microsoft YaHei UI", 9)).pack(side="left")
        close = tk.Label(head, text="×", bg="#2a2a31", fg="#7a7a88",
                         font=("Consolas", 12), cursor="hand2")
        close.pack(side="right")
        close.bind("<Button-1>", lambda e: self.hide())

        self.out = tk.Text(wrap, height=8, width=36, bg="#1b1b20", fg="#e8e8ee",
                           insertbackground="#e8e8ee", bd=0, wrap="word",
                           font=("Microsoft YaHei UI", 10), padx=10, pady=8,
                           state="disabled")
        self.out.pack(fill="both", expand=True, padx=10, pady=(8, 6))

        row = tk.Frame(wrap, bg="#2a2a31")
        row.pack(fill="x", padx=10, pady=(0, 10))
        self.entry = tk.Entry(row, bg="#1b1b20", fg="#e8e8ee", bd=0,
                              insertbackground="#e8e8ee",
                              font=("Microsoft YaHei UI", 10))
        self.entry.pack(side="left", fill="x", expand=True, ipady=6, padx=(0, 6))
        self.entry.bind("<Return>", lambda e: self.send())
        self.entry.bind("<Escape>", lambda e: self.hide())
        tk.Button(row, text="发送", bg="#4a4a55", fg="#e8e8ee", bd=0,
                  activebackground="#5a5a66", activeforeground="#fff",
                  font=("Microsoft YaHei UI", 9), padx=10, cursor="hand2",
                  command=self.send).pack(side="right")

        for w in (self.top, wrap, head, self.out):
            w.bind("<Button-1>", self._drag_start)
            w.bind("<B1-Motion>", self._drag_move)

        self.top.update_idletasks()
        self._w = max(320, self.top.winfo_reqwidth())
        self._h = max(280, self.top.winfo_reqheight())

    def _drag_start(self, e):
        self._dx, self._dy = e.x_root - self.top.winfo_x(), e.y_root - self.top.winfo_y()

    def _drag_move(self, e):
        self.top.geometry(f"+{e.x_root - self._dx}+{e.y_root - self._dy}")

    def _append(self, text):
        self.out.configure(state="normal")
        self.out.insert("end", text)
        self.out.see("end")
        self.out.configure(state="disabled")

    def show_near(self, rect):
        if self.top.winfo_viewable():
            self.top.lift()
            self.entry.focus_force()
            return
        l, t, r, b = rect
        w, h = self._w, self._h
        sw, sh = self.top.winfo_screenwidth(), self.top.winfo_screenheight()
        x = min(max(l + (r - l) // 2 - w // 2, 0), sw - w)
        y = t - h - 8
        if y < 0:
            y = min(b + 8, sh - h)
        self.top.geometry(f"{w}x{h}+{x}+{y}")
        self.top.deiconify()
        self.top.attributes("-topmost", True)
        self.entry.focus_force()
        self.entry.delete(0, "end")

    def hide(self):
        self.top.withdraw()

    def send(self):
        if self.busy:
            return
        q = self.entry.get().strip()
        if not q:
            return
        self.entry.delete(0, "end")
        self._append(f"你：{q}\n")
        self._append("她：")
        self.busy = True

        today = datetime.datetime.now().strftime("%Y-%m-%d %A")
        msgs = [{"role": "system", "content": SYSTEM_PROMPT + f"（今天是 {today}）"}]
        msgs += self.history[-8:]
        msgs.append({"role": "user", "content": q})

        answer = []

        def on_delta(piece):
            answer.append(piece)
            self.root.after(0, lambda: self._append(piece))

        def on_done():
            self.history.append({"role": "user", "content": q})
            self.history.append({"role": "assistant", "content": "".join(answer)})
            self.busy = False
            self.root.after(0, lambda: self._append("\n\n"))

        def on_error(msg):
            self.busy = False
            self.root.after(0, lambda: self._append(f"\n[出错] {msg}\n\n"))

        chat_stream(msgs, on_delta, on_done, on_error)


def main():
    global tk
    import tkinter as _tk
    globals()["tk"] = _tk

    root = _tk.Tk()
    root.withdraw()
    bubble = ChatBubble(root)

    was_down = False
    armed = True

    def tick():
        nonlocal was_down, armed
        down = left_down()
        if down and not was_down:
            x, y = cursor_pos()
            for rect in pet_rects():
                l, t, r, b = rect
                if l <= x <= r and t <= y <= b:
                    bubble.show_near(rect)
                    break
        was_down = down
        root.after(POLL_MS, tick)

    root.after(POLL_MS, tick)
    root.mainloop()


def test():
    today = datetime.datetime.now().strftime("%Y-%m-%d %A")
    msgs = [{"role": "system", "content": SYSTEM_PROMPT + f"（今天是 {today}）"},
            {"role": "user", "content": "你好呀，今天过得怎么样？"}]
    print(f"[1] 检测桌宠窗口: {len(pet_rects())} 个")
    for r in pet_rects():
        print("    ", r)
    print(f"[2] 请求 {MODEL} ...")
    buf = []
    done = threading.Event()

    def d(p):
        buf.append(p)
        print(p, end="", flush=True)

    def e(m):
        print("\n[错误]", m)
        done.set()

    chat_stream(msgs, d, lambda: done.set(), e)
    done.wait(120)
    print("\n[3] 完成，共", len("".join(buf)), "字")


if __name__ == "__main__":
    if "--test" in sys.argv:
        test()
    else:
        main()
