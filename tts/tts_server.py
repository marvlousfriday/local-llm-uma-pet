# -*- coding: utf-8 -*-
"""
本地 TTS 服务 —— 把 UmaChat 的 VITS 模型包成一个 HTTP 接口，给桌宠调用。

    POST /tts    {"text": "こんにちは", "speed": 1.0}
                 -> audio/wav 字节流
    GET  /health -> {"ok": true, "model": "MeishoDoto"}

启动:
    venv\Scripts\python.exe tts_server.py [--port 9880] [--char MeishoDoto]

注意:
    推理走 CPU（RTF 约 0.33，比实时快 3 倍），不占显存，可与 qwen 同时跑。
"""
import gc
import io
import json
import os
import sys
import threading
import time
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = os.path.dirname(os.path.abspath(__file__))

# pythonw 启动时 sys.stdout / sys.stderr 是 None，任何 print 都会抛异常直接崩掉。
# 重定向到日志文件，顺便留个可查的痕迹。
if sys.stdout is None or sys.stderr is None:
    try:
        _f = open(os.path.join(BASE, "tts_server.log"), "a", encoding="utf-8", buffering=1)
        if sys.stdout is None:
            sys.stdout = _f
        if sys.stderr is None:
            sys.stderr = _f
    except Exception:
        pass

SRC_ROOT = os.path.join(BASE, "src")
_subs = [d for d in os.listdir(SRC_ROOT) if os.path.isdir(os.path.join(SRC_ROOT, d))]
SRC = os.path.join(SRC_ROOT, _subs[0])
sys.path.insert(0, SRC)

import numpy as np
import torch

from models import SynthesizerTrn
from text import text_to_sequence
from text.japanese import japanese_to_romaji_with_accent
import commons
import utils

DEVICE = "cpu"
_LOCK = threading.Lock()      # torch 推理串行化，避免并发互相踩
_MODEL_DIR = None
_NET = None
_HPS = None
_CHAR = "MeishoDoto"
_IDLE_TIMEOUT = 600           # 秒；0 表示不自动卸载
_PARENT_PID = 0               # 由桌宠传入，父进程消失就自动退出
_LAST_USE = time.time()


def pid_alive(pid):
    """父进程是否还活着（Windows）"""
    try:
        import ctypes
        k32 = ctypes.WinDLL("kernel32")
        h = k32.OpenProcess(0x1000, False, pid)      # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        ok = k32.GetExitCodeProcess(h, ctypes.byref(code))
        k32.CloseHandle(h)
        return bool(ok) and code.value == 259        # STILL_ACTIVE
    except Exception:
        return True                                   # 查不到就当作还活着，别误杀


def load_model(char):
    global _MODEL_DIR, _NET, _HPS, _CHAR
    _CHAR = char
    _MODEL_DIR = os.path.join(BASE, "models", char)
    cfg = os.path.join(_MODEL_DIR, "config.json")
    if not os.path.isfile(cfg):
        raise SystemExit("找不到模型: %s" % cfg)

    hps = utils.get_hparams_from_file(cfg)
    net = SynthesizerTrn(
        len(hps.symbols),
        hps.data.filter_length // 2 + 1,
        hps.train.segment_size // hps.data.hop_length,
        n_speakers=hps.data.n_speakers,
        **hps.model,
    ).to(DEVICE)
    net.eval()

    ckpt = torch.load(os.path.join(_MODEL_DIR, "G_latest.pth"),
                      map_location=DEVICE, weights_only=False)
    state = ckpt.get("model", ckpt) if isinstance(ckpt, dict) else ckpt
    net.load_state_dict(state)

    _NET, _HPS = net, hps
    return hps


def ensure_model():
    """模型被卸载过就重新加载，并刷新最后使用时间"""
    global _LAST_USE
    if _NET is None:
        t0 = time.time()
        load_model(_CHAR)
        print("[tts] 重新加载模型 %s（%.1fs）" % (_CHAR, time.time() - t0), flush=True)
    _LAST_USE = time.time()


def unload_model():
    global _NET, _HPS
    _NET = None
    _HPS = None
    gc.collect()

    # gc 只回收 Python 对象，torch 的 C++ 内存池不会还给系统。
    # 用 EmptyWorkingSet 把工作集刷到页面文件，RSS 才会真的降下来。
    # 注意：GetCurrentProcess 返回 -1 伪句柄，必须声明 restype=c_void_p，否则句柄被截断、调用静默失败。
    try:
        import ctypes
        k32 = ctypes.WinDLL("kernel32")
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        psapi = ctypes.WinDLL("psapi")
        psapi.EmptyWorkingSet.argtypes = [ctypes.c_void_p]
        psapi.EmptyWorkingSet.restype = ctypes.c_bool
        ok = psapi.EmptyWorkingSet(k32.GetCurrentProcess())
        print("[tts] EmptyWorkingSet -> %s" % bool(ok), flush=True)
    except Exception as e:
        print("[tts] 刷工作集失败: %s" % e, flush=True)


def idle_watchdog():
    """父进程守护 + 空闲释放模型"""
    while True:
        time.sleep(5)

        # 桌宠被强杀或崩溃时不会走 Exit 事件，这里兜底
        if _PARENT_PID and not pid_alive(_PARENT_PID):
            print("[tts] 父进程已退出，服务关闭", flush=True)
            os._exit(0)

        if _IDLE_TIMEOUT <= 0 or _NET is None:
            continue
        if time.time() - _LAST_USE <= _IDLE_TIMEOUT:
            continue
        if _LOCK.locked():
            continue
        with _LOCK:
            unload_model()
        print("[tts] 空闲超时，已释放模型（下次请求自动重载）", flush=True)


def synth_wav_bytes(text, speed=1.0):
    """日语文本 -> wav 字节"""
    ensure_model()

    romaji = japanese_to_romaji_with_accent(text)
    romaji = romaji.replace("ts", "ʦ").replace("u", "ɯ").replace("...", "…")

    seq = text_to_sequence(romaji, _HPS.symbols, [])
    if _HPS.data.add_blank:
        seq = commons.intersperse(seq, 0)

    x = torch.LongTensor(seq).unsqueeze(0)
    x_len = torch.LongTensor([len(seq)])
    speakers = getattr(_HPS, "speakers", None) or {0: 0}
    sid_val = int(list(speakers.values())[0]) if isinstance(speakers, dict) else 0
    sid = torch.LongTensor([sid_val])

    with _LOCK:
        with torch.no_grad():
            audio = _NET.infer(
                x, x_len, sid=sid,
                noise_scale=0.667, noise_scale_w=0.8,
                length_scale=1.0 / max(0.1, float(speed)),
            )[0][0, 0].cpu().float().numpy()

    sr = _HPS.data.sampling_rate
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return buf.getvalue(), sr, len(pcm) / float(sr)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        sys.stderr.write("[tts] %s - %s\n" % (self.address_string(), fmt % args))

    def _send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/health"):
            self._send_json({
                "ok": True,
                "model": _CHAR,
                "loaded": _NET is not None,
                "idle_timeout": _IDLE_TIMEOUT,
                "idle_seconds": round(time.time() - _LAST_USE, 1),
                "sampling_rate": _HPS.data.sampling_rate if _HPS else None,
            })
        else:
            self._send_json({"error": "not found"}, 404)

    def do_POST(self):
        if not self.path.startswith("/tts"):
            self._send_json({"error": "not found"}, 404)
            return

        try:
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            text = (payload.get("text") or "").strip()
            speed = float(payload.get("speed", 1.0))
            if not text:
                self._send_json({"error": "empty text"}, 400)
                return

            t0 = time.time()
            data, sr, dur = synth_wav_bytes(text, speed)
            cost = time.time() - t0
            sys.stderr.write("[tts] %d字 %.2fs音频 耗时%.2fs\n" % (len(text), dur, cost))

            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Sample-Rate", str(sr))
            self.send_header("X-Duration", "%.3f" % dur)
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:
            self._send_json({"error": str(e)}, 500)


def main():
    global _IDLE_TIMEOUT, _CHAR, _PARENT_PID
    char = "MeishoDoto"
    port = 9880
    args = sys.argv[1:]
    for i, a in enumerate(args):
        if a == "--char" and i + 1 < len(args):
            char = args[i + 1]
        if a == "--port" and i + 1 < len(args):
            port = int(args[i + 1])
        if a == "--idle" and i + 1 < len(args):
            _IDLE_TIMEOUT = int(args[i + 1])
        if a == "--parent-pid" and i + 1 < len(args):
            _PARENT_PID = int(args[i + 1])

    if "--preload" in args:
        print("[1] 预加载模型:", char)
        t0 = time.time()
        hps = load_model(char)
        print("    完成 %.1fs | 采样率 %d" % (time.time() - t0, hps.data.sampling_rate))

        print("[2] 预热...")
        t0 = time.time()
        try:
            synth_wav_bytes("こんにちは")
            print("    预热完成 %.1fs" % (time.time() - t0))
        except Exception as e:
            print("    预热失败（不影响服务）:", e)
    else:
        _CHAR = char
        print("[1] 模型 %s 将在首次请求时加载（省内存，首次多等约 0.5 秒）" % char)

    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print("[3] 监听 http://127.0.0.1:%d  (Ctrl+C 退出)" % port)
    threading.Thread(target=idle_watchdog, daemon=True).start()
    if _IDLE_TIMEOUT > 0:
        print("[4] 空闲 %d 秒后自动释放模型" % _IDLE_TIMEOUT)
    if _PARENT_PID:
        print("[5] 守护父进程 PID %d" % _PARENT_PID)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n退出")
        srv.shutdown()


if __name__ == "__main__":
    main()
