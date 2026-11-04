# -*- coding: utf-8 -*-
"""
UmaChat VITS 模型最小推理脚本 —— 只做「日语文本 → wav」，不碰原项目的 OpenAI / 百度翻译 / 情感识别。

用法:
    venv\Scripts\python.exe tts_test.py "こんにちは" out.wav
"""
import os
import sys
import wave

BASE = os.path.dirname(os.path.abspath(__file__))
SRC_ROOT = os.path.join(BASE, "src")
subs = [d for d in os.listdir(SRC_ROOT) if os.path.isdir(os.path.join(SRC_ROOT, d))]
SRC = os.path.join(SRC_ROOT, subs[0])
sys.path.insert(0, SRC)

import numpy as np
import torch

from models import SynthesizerTrn
from text import text_to_sequence
from text.japanese import japanese_to_romaji_with_accent
import commons
import utils

DEVICE = "cpu"
MODEL_DIR = os.path.join(BASE, "models", "MeishoDoto")


def load_model(model_dir=MODEL_DIR):
    cfg = os.path.join(model_dir, "config.json")
    ckpt_path = os.path.join(model_dir, "G_latest.pth")
    hps = utils.get_hparams_from_file(cfg)

    net = SynthesizerTrn(
        len(hps.symbols),
        hps.data.filter_length // 2 + 1,
        hps.train.segment_size // hps.data.hop_length,
        n_speakers=hps.data.n_speakers,
        **hps.model,
    ).to(DEVICE)
    net.eval()

    ckpt = torch.load(ckpt_path, map_location=DEVICE, weights_only=False)
    state = ckpt.get("model", ckpt) if isinstance(ckpt, dict) else ckpt
    net.load_state_dict(state)
    return net, hps


def synth(net, hps, text, out_path, speed=1.0):
    # 关键：先转成带声调的罗马音。
    # 直接用 zh_ja_mixture_cleaners 会把纯日语全部丢掉（它只处理 [JA] 标记内的内容）。
    romaji = japanese_to_romaji_with_accent(text)
    romaji = romaji.replace("ts", "ʦ").replace("u", "ɯ").replace("...", "…")

    seq = text_to_sequence(romaji, hps.symbols, [])
    if hps.data.add_blank:
        seq = commons.intersperse(seq, 0)

    x = torch.LongTensor(seq).unsqueeze(0).to(DEVICE)
    x_len = torch.LongTensor([len(seq)]).to(DEVICE)

    speaker_ids = getattr(hps, "speakers", None) or {0: 0}
    first_sid = list(speaker_ids.values())[0] if isinstance(speaker_ids, dict) else 0
    sid = torch.LongTensor([int(first_sid)]).to(DEVICE)

    with torch.no_grad():
        audio = net.infer(
            x, x_len, sid=sid,
            noise_scale=0.667, noise_scale_w=0.8,
            length_scale=1.0 / speed,
        )[0][0, 0].cpu().float().numpy()

    sr = hps.data.sampling_rate
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
    with wave.open(out_path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return sr, len(pcm) / float(sr)


if __name__ == "__main__":
    text = sys.argv[1] if len(sys.argv) > 1 else "こんにちは、トレーナーさん。今日も一緒に頑張ろうね！"
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(BASE, "test.wav")

    print("[1] 加载模型:", MODEL_DIR)
    net, hps = load_model()
    print("    采样率:", hps.data.sampling_rate, "| speakers:", getattr(hps, "speakers", None))

    print("[2] 合成:", text)
    sr, dur = synth(net, hps, text, out)
    print("[3] 完成 ->", out)
    print("    %.0f Hz, %.2f 秒" % (sr, dur))
