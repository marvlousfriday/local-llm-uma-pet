# -*- coding: utf-8 -*-
"""
Generate MarvelousSunday's Japanese voice wav files for DesktopGremlin.

Source of the voice:
  hf-mirror.com/gouhuo/Umamusume_Vits_models/tree/main/MarvelousSunday
    G_latest.pth  158897385 bytes
    config.json       2139 bytes
  Put both in:  <UMAVITS_DIR>/models/MarvelousSunday/

The action -> wav mapping is HARD-CODED in DesktopGremlin's C# source
(MediaManager.PlaySound calls), not a translation table:
  intro.wav   startup                MainWindow.xaml.cs:63
  outro.wav   tray "Stylish Close"   ConfigManager.cs:310
  emote1-4.wav  hotspot / random emotes (EmoteHelper)
  grab.wav    left-button drag       MainWindow.xaml.cs:440
  hover.wav   mouse hover (5s throttle) MainWindow.xaml.cs:411
  run.wav     running                MainWindow.xaml.cs:452,611
  sleep.wav   falling asleep         MainWindow.xaml.cs:493,686
  mambo.wav   random dance           MainWindow.xaml.cs:242,401,596
  food.wav    food spawn             MainWindow.xaml.cs:392
  eat.wav     GLOBAL Sounds/Misc/, not per character -> do not generate here

wake.wav / pat.wav / click.wav / spawn.wav exist in some character folders
but are NEVER referenced by the v4.0 source - they are dead files.
wake.wav is still generated below because the placeholder copy is Doto's
voice; overwriting it keeps the folder free of the wrong character.

Usage:
  python make_voice.py --dry-run     # print the plan, generate nothing
  python make_voice.py              # generate all wavs

It starts a SEPARATE TTS server on port 9881 with --char MarvelousSunday,
so the pet's own 9880 service is untouched.
Japanese text only - this VITS model goes silent on Chinese input.
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

# ---- Local paths: edit these, or set the same-name env vars ----
UMAVITS = Path(os.environ.get("UMAVITS_DIR", r"C://path//to//umavits"))
SOUNDS = Path(os.environ.get("PET_SOUNDS_DIR", r"C://path//to//pet//Sounds//MarvelousSunday"))
# ---------------------------------------------------------------
VENV_PY = UMAVITS / "venv" / "Scripts" / "python.exe"
MODEL_DIR = UMAVITS / "models" / "MarvelousSunday"
PORT = 9881
BASE_URL = "http://127.0.0.1:%d" % PORT

LINES = [
    ("intro.wav",  "マーベラス、登場だよー"),
    ("outro.wav",  "またね、今日もマーベラスだったよ"),
    ("grab.wav",   "わっ、びっくりしたー"),
    ("hover.wav",  "ん、なになに、マーベラスな予感"),
    ("emote1.wav", "マーベラス、すごいでしょ"),
    ("emote2.wav", "これって、奇跡だね"),
    ("emote3.wav", "アタシ、がんばっちゃうよー"),
    ("emote4.wav", "ふふっ、星がキラキラしてる"),
    ("sleep.wav",  "ちょっとだけ、おやすみー"),
    ("run.wav",    "はしるよー、マーベラススピードで"),
    ("mambo.wav",  "マーベラス、ダンスタイムだよ"),
    ("food.wav",   "わーい、ごはんだー"),
    ("wake.wav",   "おはよー、マーベラスな朝だよ"),
]

# Bypass the system Clash proxy for localhost requests.
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def check_model():
    missing = [n for n in ("G_latest.pth", "config.json")
               if not (MODEL_DIR / n).is_file()]
    if missing:
        print("Missing model files in %s: %s" % (MODEL_DIR, ", ".join(missing)))
        print("Download them first:")
        print("  https://hf-mirror.com/gouhuo/Umamusume_Vits_models/resolve/main/"
              "MarvelousSunday/G_latest.pth")
        print("  https://hf-mirror.com/gouhuo/Umamusume_Vits_models/resolve/main/"
              "MarvelousSunday/config.json")
        return False
    return True


def start_server():
    if not VENV_PY.is_file():
        sys.exit("venv python not found: " + str(VENV_PY))
    cmd = [str(VENV_PY), str(UMAVITS / "tts_server.py"),
           "--port", str(PORT), "--char", "MarvelousSunday", "--idle", "0",
           "--parent-pid", str(os.getpid())]
    proc = subprocess.Popen(cmd, cwd=str(UMAVITS),
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    for _ in range(60):
        try:
            with OPENER.open(BASE_URL + "/health", timeout=1) as r:
                if r.status == 200:
                    return proc
        except Exception:
            time.sleep(0.5)
    proc.terminate()
    sys.exit("TTS server on port %d did not become ready" % PORT)


def synth(text):
    data = json.dumps({"text": text, "speed": 1.0}).encode("utf-8")
    req = urllib.request.Request(BASE_URL + "/tts", data=data,
                                 headers={"Content-Type": "application/json"})
    with OPENER.open(req, timeout=120) as r:
        return r.read()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    print("Target : %s" % SOUNDS)
    print("Voice  : MarvelousSunday (local VITS)")
    for name, text in LINES:
        print("  %-12s %s" % (name, text))
    if args.dry_run:
        print("\n--dry-run: nothing generated.")
        return
    if not check_model():
        sys.exit(1)

    SOUNDS.mkdir(parents=True, exist_ok=True)
    proc = start_server()
    try:
        for name, text in LINES:
            try:
                wav = synth(text)
                (SOUNDS / name).write_bytes(wav)
                print("[ok] %-12s %7.1f KB" % (name, len(wav) / 1024.0))
            except Exception as e:
                print("[FAIL] %-12s %s" % (name, e))
    finally:
        # terminate + kill fallback, plus tts_server's own --parent-pid watchdog
        # as a third safety net so no orphan survives a re-run.
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except Exception:
            proc.kill()
            try:
                proc.wait(timeout=3)
            except Exception:
                pass
    print("\nDone. Restart the pet to pick up the new wavs.")
    print("NOTE: chat read-aloud (port 9880) still uses MeishoDoto. Changing that")
    print("requires adding --char to TtsLauncher.cs and rebuilding the exe.")


if __name__ == "__main__":
    main()
