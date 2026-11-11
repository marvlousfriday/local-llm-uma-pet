# -*- coding: utf-8 -*-
"""
UmaViewer GIF/PNG -> DesktopGremlin sprite sheet converter.

Usage:
    python gif_to_sheet.py <input_dir> <character_dir> [--cell 325] [--col 10]

Put UmaViewer recordings in <input_dir>, named after the action, e.g.
    idle.gif  walkDown.gif  runRight.gif  emote1.gif  intro.png ...

Or use PNG-sequence FOLDERS named after the action (recommended):
    input/idle/0001.png input/idle/0002.png ...
    UmaViewer > Screenshot > "Record PNG Sequence" > rename the timestamped
    output folder to the action name (idle, walkDown, ...).

Recommended recording settings: 1024 x 1024, Transparent ON, Sequence fps 30
(the pet plays at 30 fps; 120 fps quadruples the frames for no benefit).
Frames are streamed, so 1024px / long clips will not exhaust memory.

Supported action names (case/underscore insensitive):
    Actions : idle intro outro click grab hover sleep runIdle pat
    Run     : runUp runDown runLeft runRight upLeft upRight downLeft downRight
    Walk    : walkUp walkDown walkLeft walkRight
    Emotes  : emote1 emote2 emote3 emote4

Rules:
  * GIF frames are laid out left-to-right, top-to-bottom, COLUMN frames per row.
  * White / flat-color screenshot backgrounds are turned into alpha.
    If UmaViewer saved a transparent PNG, the existing alpha is kept.
  * Each frame is cropped to its alpha bounding box, scaled to fit the cell,
    bottom-aligned (feet on the ground) and centered horizontally.
  * A single still image becomes a 12-frame gentle breathing loop.
  * Mirrored actions are auto-generated: if runRight exists but runLeft does not,
    runLeft is produced by flipping runRight (same for the other left/right pairs).
  * Actions without source material keep their existing placeholder sheet.
  * config.txt frame counts are updated only for actions that were rebuilt.

Requires Pillow. Run with the system Python 3.11:
    python.exe  (with Pillow, numpy and opencv-python installed)
"""

import argparse
import math
import re
import sys
import time
from pathlib import Path

try:
    from PIL import Image, ImageFilter, ImageSequence
except ImportError:
    sys.exit("Pillow is missing. Install it with: pip install -i https://pypi.org/simple Pillow")

try:
    import numpy as np
    import cv2
    HAVE_CV = True
except ImportError:
    HAVE_CV = False

# action key -> (sub folder, output file name, config key)
ACTIONS = {
    # "idle":      ("Actions", "idle.png",      "IDLE"),
    # "intro":     ("Actions", "intro.png",     "INTRO"),
    # "outro":     ("Actions", "outro.png",     "OUTRO"),
    # "click":     ("Actions", "click.png",     "CLICK"),
    # "grab":      ("Actions", "grab.png",      "GRAB"),
    # "hover":     ("Actions", "hover.png",     "HOVER"),
    "sleep":     ("Actions", "sleep.png",     "SLEEP"),
    # "runidle":   ("Actions", "runIdle.png",   "RUNIDLE"),
    # "pat":       ("Actions", "pat.png",       "PAT"),
    # "runup":     ("Run",     "runUp.png",     "RUNUP"),
    # "rundown":   ("Run",     "runDown.png",   "RUNDOWN"),
    # "runleft":   ("Run",     "runLeft.png",   "RUNLEFT"),
    # "runright":  ("Run",     "runRight.png",  "RUNRIGHT"),
    # "upleft":    ("Run",     "upLeft.png",    "UPLEFT"),
    # "upright":   ("Run",     "upRight.png",   "UPRIGHT"),
    # "downleft":  ("Run",     "downLeft.png",  "DOWNLEFT"),
    # "downright": ("Run",     "downRight.png", "DOWNRIGHT"),
    # "walkup":    ("Walk",    "walkUp.png",    "WALKUP"),
    # "walkdown":  ("Walk",    "walkDown.png",  "WALKDOWN"),
    # "walkleft":  ("Walk",    "walkLeft.png",  "WALKLEFT"),
    # "walkright": ("Walk",    "walkRight.png", "WALKRIGHT"),
    # "emote1":    ("Emotes",  "emote1.png",    "EMOTE1"),
    # "emote2":    ("Emotes",  "emote2.png",    "EMOTE2"),
    # "emote3":    ("Emotes",  "emote3.png",    "EMOTE3"),
    # "emote4":    ("Emotes",  "emote4.png",    "EMOTE4"),
}

MIRROR_PAIRS = [
    ("runleft", "runright"),
    ("upleft", "upright"),
    ("downleft", "downright"),
    ("walkleft", "walkright"),
]

MAX_FRAMES = 340          # keep the sheet within the game's practical limits
STILL_LOOP_FRAMES = 12    # breathing animation generated from a single still
FILL = 0.88               # character occupies 88% of the cell
BOTTOM_MARGIN = 0.04      # feet sit 4% above the cell bottom
IMG_EXTS = (".gif", ".png", ".webp", ".apng", ".jpg", ".jpeg")


def normalize(name):
    return re.sub(r"[^a-z0-9]", "", name.lower())


def load_frames(path, crop=None):
    """Return a list of RGBA frames from a GIF/APNG/PNG/WEBP."""
    im = Image.open(path)
    frames = [f.convert("RGBA").copy() for f in ImageSequence.Iterator(im)]
    if crop:
        x, y, w, h = crop
        frames = [f.crop((x, y, x + w, y + h)) for f in frames]
    if not frames:
        raise RuntimeError("no frames in " + str(path))
    # Pillow already returns fully composited GIF frames. Accumulating them
    # again would leave ghost trails on transparent recordings.
    return frames


def iter_frames(path, crop=None):
    """Yield RGBA frames one at a time.

    A 1024x1024, 369-frame recording is ~1.5 GB if loaded all at once, so both
    GIFs and PNG-sequence folders are streamed instead.
    """
    path = Path(path)

    def prep(im):
        fr = im.convert("RGBA").copy()
        if crop:
            x, y, w, h = crop
            fr = fr.crop((x, y, x + w, y + h))
        return fr

    if path.is_dir():
        files = sorted(p for p in path.iterdir() if p.suffix.lower() in IMG_EXTS)
        if not files:
            raise RuntimeError("no images in sequence folder " + str(path))
        for p in files:
            with Image.open(p) as im:
                yield prep(im)
    else:
        with Image.open(path) as im:
            for f in ImageSequence.Iterator(im):
                yield prep(f)


def corner_color(img):
    """Average colour of the four corners; None when the image is already transparent."""
    w, h = img.size
    pts = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]
    samples = [img.getpixel(p) for p in pts]
    if sum(s[3] for s in samples) < 40:
        return None
    return tuple(sum(s[i] for s in samples) // 4 for i in range(3))


def remove_background(img, bg):
    """Turn a flat background colour into alpha, WITHOUT punching holes in
    white clothing inside the character.

    Only background-coloured pixels connected to the image border are removed
    (connected-component flood). White areas enclosed by outlines stay opaque.
    Uses OpenCV when available; falls back to a plain colour threshold.
    """
    if bg is None:
        return img
    rgb = img.convert("RGB")
    if HAVE_CV:
        arr = np.asarray(rgb, dtype=np.float32)
        delta = arr - np.array(bg, dtype=np.float32)
        dist = np.sqrt((delta * delta).sum(axis=2))
        soft = np.clip((dist - 18.0) / 42.0 * 255.0, 0, 255).astype(np.uint8)
        candidate = (dist < 60).astype(np.uint8)
        n, labels, stats, _ = cv2.connectedComponentsWithStats(candidate, connectivity=4)
        if n > 1:
            border = set(np.unique(np.concatenate((
                labels[0, :], labels[-1, :], labels[:, 0], labels[:, -1]
            ))).tolist())
            border.discard(0)
            outside = np.isin(labels, list(border))
            alpha = np.full(dist.shape, 255, dtype=np.uint8)
            alpha[outside] = soft[outside]
            out = img.copy()
            out.putalpha(Image.fromarray(alpha, mode="L"))
            return out
    # fallback: plain threshold
    px = rgb.load()
    alpha = Image.new("L", rgb.size, 255)
    ap = alpha.load()
    w, h = rgb.size
    for y in range(h):
        for x in range(w):
            r, g, b = px[x, y]
            dist = math.sqrt((r - bg[0]) ** 2 + (g - bg[1]) ** 2 + (b - bg[2]) ** 2)
            ap[x, y] = 0 if dist <= 18 else (int(255 * (dist - 18) / 42) if dist < 60 else 255)
    out = img.copy()
    out.putalpha(alpha)
    return out


def bleed_edges(img, radius=3):
    """Give transparent pixels just outside the character a sensible RGB.

    Palette GIFs store pure black in fully transparent pixels. Any later
    resampling (our converter or WPF at display time) blends that black into
    the visible edge, producing a grey haze. Inpainting a thin outer band
    removes the halo without inflating the PNG much.
    """
    if not HAVE_CV:
        return img
    a = np.asarray(img.convert("RGBA"))
    rgb, al = a[:, :, :3], a[:, :, 3]
    opaque = (al > 0).astype(np.uint8)
    band = cv2.dilate(opaque, np.ones((radius * 2 + 1, radius * 2 + 1), np.uint8))
    mask = ((band > 0) & (al == 0)).astype(np.uint8) * 255
    if not mask.any():
        return img
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    bled = cv2.cvtColor(cv2.inpaint(bgr, mask, 3, cv2.INPAINT_TELEA), cv2.COLOR_BGR2RGB)
    return Image.fromarray(np.dstack([bled, al]))


def fit_to_cell(img, cell, bbox=None, sharpen=True):
    """Crop, bottom-align, center. Skip resampling entirely when the character
    already fits - that LANCZOS pass was the main source of softness.

    A shared bbox keeps every frame on the same coordinate system so the
    character does not pulse in size between frames.
    """
    if bbox is None:
        bbox = img.getchannel("A").point(lambda v: 255 if v > 12 else 0).getbbox()
    if not bbox:
        return Image.new("RGBA", (cell, cell), (0, 0, 0, 0))
    bbox = (max(0, bbox[0]), max(0, bbox[1]), min(img.width, bbox[2]), min(img.height, bbox[3]))
    crop = bleed_edges(img.crop(bbox))
    cw, ch = crop.size
    if cw <= 0 or ch <= 0:
        return Image.new("RGBA", (cell, cell), (0, 0, 0, 0))
    maxw = int(cell * FILL)
    maxh = cell - int(cell * BOTTOM_MARGIN)
    if cw > maxw or ch > maxh:
        scale = min(maxw / cw, maxh / ch)
        nw, nh = max(1, int(cw * scale)), max(1, int(ch * scale))
        crop = crop.resize((nw, nh), Image.LANCZOS)
    else:
        nw, nh = cw, ch
    if sharpen:
        alpha = crop.getchannel("A")
        rgb = crop.convert("RGB").filter(
            ImageFilter.UnsharpMask(radius=0.7, percent=110, threshold=2))
        crop = rgb.convert("RGBA")
        crop.putalpha(alpha)
    canvas = Image.new("RGBA", (cell, cell), (0, 0, 0, 0))
    x = (cell - nw) // 2
    y = cell - int(cell * BOTTOM_MARGIN) - nh
    canvas.alpha_composite(crop, (max(0, x), max(0, y)))
    return canvas


def breathing_frames(still, cell, count=STILL_LOOP_FRAMES, bbox=None, sharpen=True):
    """Create a subtle loop from one still image."""
    base = fit_to_cell(still, cell, bbox, sharpen)
    frames = []
    for i in range(count):
        t = i / count * 2 * math.pi
        s = 1.0 + 0.012 * math.sin(t)
        dy = int(round(2 * math.sin(t)))
        w = int(cell * s)
        h = int(cell * s)
        scaled = base.resize((w, h), Image.LANCZOS)
        f = Image.new("RGBA", (cell, cell), (0, 0, 0, 0))
        f.alpha_composite(scaled, ((cell - w) // 2, (cell - h) // 2 + dy))
        frames.append(f)
    return frames


def thin_frames(frames, limit=MAX_FRAMES):
    if len(frames) <= limit:
        return frames
    step = len(frames) / limit
    return [frames[min(len(frames) - 1, int(i * step))] for i in range(limit)]


def save_sheet(img, path, retries=8):
    """Windows antivirus / indexer can briefly lock a freshly written PNG."""
    for i in range(retries):
        try:
            img.save(path)
            return
        except OSError as e:
            if i == retries - 1:
                raise
            print("[retry] %s locked (%s), retry %d" % (path.name, e.errno, i + 1))
            time.sleep(0.4 * (i + 1))


def build_sheet(frames, cell, col):
    n = len(frames)
    rows = math.ceil(n / col)
    sheet = Image.new("RGBA", (cell * col, cell * rows), (0, 0, 0, 0))
    for i, f in enumerate(frames):
        sheet.alpha_composite(f, ((i % col) * cell, (i // col) * cell))
    return sheet


def update_config(char_dir, counts):
    path = char_dir / "config.txt"
    if not path.exists():
        print("[warn] config.txt missing, skipped frame-count update")
        return
    text = path.read_text(encoding="utf-8-sig")
    lines = text.splitlines()
    seen = set()
    for i, line in enumerate(lines):
        if "=" not in line or line.lstrip().startswith("//") or line.lstrip().startswith("#"):
            continue
        key = line.split("=")[0].strip().upper()
        if key in counts:
            lines[i] = "%s=%d" % (key, counts[key])
            seen.add(key)
    missing = [k for k in counts if k not in seen]
    if missing:
        lines.append("")
        lines.append("//Auto generated by gif_to_sheet.py")
        for k in missing:
            lines.append("%s=%d" % (k, counts[k]))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def fill_remaining(char_dir, built_paths, base_cells, cell):
    """Replace every sheet without a recording with the NEW character's base
    frames, keeping the original sheet size so existing frame counts stay valid.
    Prevents leftover art from the placeholder character showing up mid-game."""
    if not base_cells:
        return []
    filled = []
    for p in sorted(char_dir.rglob("*.png")):
        # Never touch icon sources or screenshots that happen to sit in Misc/.
        if p.parent.name not in ("Actions", "Run", "Walk", "Emotes"):
            continue
        if p.resolve() in built_paths:
            continue
        try:
            w, h = Image.open(p).size
        except Exception:
            continue
        cols = max(1, w // cell)
        rows = max(1, h // cell)
        total = cols * rows
        sheet = Image.new("RGBA", (cols * cell, rows * cell), (0, 0, 0, 0))
        for i in range(total):
            f = base_cells[i % len(base_cells)]
            sheet.alpha_composite(f, ((i % cols) * cell, (i // cols) * cell))
        save_sheet(sheet, p)
        filled.append(str(p.relative_to(char_dir)))
    return filled


ALIASES = {
    "however": "hover",     # common typo for hover.gif
    "hove": "hover",
    "runupaction": "runup",
}


def discover(input_dir):
    """Accept action-named files (idle.gif) or action-named folders holding a
    PNG sequence (idle/0001.png ...). Rename UmaViewer's timestamped sequence
    folders to the action name first."""
    found = {}
    skipped = []
    for p in sorted(input_dir.iterdir()):
        raw = normalize(p.name if p.is_dir() else p.stem)
        key = ALIASES.get(raw, raw)
        if p.is_dir():
            has_img = any(q.suffix.lower() in IMG_EXTS for q in p.iterdir())
            if key in ACTIONS and has_img:
                found[key] = p
                print("[sequence] %s/ -> %s" % (p.name, key))
            else:
                skipped.append(p.name + "/")
            continue
        if p.suffix.lower() not in IMG_EXTS:
            continue
        if key in ACTIONS:
            if key != raw:
                print("[alias] %s -> %s" % (p.name, key))
            found[key] = p
        else:
            skipped.append(p.name)
    if skipped:
        print("[skip] %d unrecognized item(s) ignored (e.g. %s)" % (len(skipped), skipped[0]))
    return found


def global_bbox(sources, crop=None, pad=6, sample_every=5):
    """Shared crop box across every recording so size stays constant in all
    animations. Streamed + sampled, so 1024px long clips stay low-memory."""
    boxes = []
    sizes = set()
    for src in sources.values():
        path = src[0] if isinstance(src, tuple) else src
        try:
            for idx, f in enumerate(iter_frames(path, crop)):
                if idx == 0:
                    sizes.add(f.size)
                if idx % sample_every:
                    continue
                b = f.getchannel("A").point(lambda v: 255 if v > 12 else 0).getbbox()
                if b:
                    boxes.append(b)
        except Exception as e:
            print("[warn] bbox scan failed for %s: %s" % (path.name, e))
    if len(sizes) > 1:
        print("[warn] mixed source sizes %s -> the shared crop box will be WRONG "
              "for some actions. Re-record everything at one resolution." % sorted(sizes))
    if not boxes:
        return None
    box = (min(b[0] for b in boxes) - pad,
           min(b[1] for b in boxes) - pad,
           max(b[2] for b in boxes) + pad,
           max(b[3] for b in boxes) + pad)
    print("[bbox] shared crop box: %s (from %d sampled frames)" % (str(box), len(boxes)))
    return box


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input_dir")
    ap.add_argument("character_dir")
    ap.add_argument("--cell", type=int, default=325)
    ap.add_argument("--col", type=int, default=10)
    ap.add_argument("--no-mirror", action="store_true")
    ap.add_argument("--no-fill", action="store_true",
                    help="keep placeholder sheets for actions without recordings")
    ap.add_argument("--no-sharpen", action="store_true",
                    help="disable the light unsharp mask applied to each frame")
    ap.add_argument("--crop", default="",
                    help="crop source frames before processing: X,Y,W,H (e.g. 300,0,680,576)")
    args = ap.parse_args()
    crop = None
    if args.crop:
        try:
            crop = tuple(int(v) for v in args.crop.split(","))
            if len(crop) != 4:
                raise ValueError
        except ValueError:
            sys.exit("--crop needs four integers: X,Y,W,H")

    input_dir = Path(args.input_dir)
    char_dir = Path(args.character_dir)
    if not input_dir.is_dir():
        sys.exit("input dir not found: " + str(input_dir))
    if not char_dir.is_dir():
        sys.exit("character dir not found: " + str(char_dir))

    sources = discover(input_dir)
    if not sources:
        print("No GIF/PNG found in %s" % input_dir)
        print("Name files after actions, e.g. idle.gif, walkDown.gif, emote1.png")
        return

    # auto mirror left/right
    if not args.no_mirror:
        for left, right in MIRROR_PAIRS:
            if left not in sources and right in sources:
                sources[left] = (sources[right], "mirror")
            elif right not in sources and left in sources:
                sources[right] = (sources[left], "mirror")

    shared_box = global_bbox(sources, crop)

    counts = {}
    report = []
    built_paths = set()
    base_cells = None
    for key, src in sorted(sources.items()):
        mirrored = isinstance(src, tuple)
        path = src[0] if mirrored else src
        frames = []
        bg = None
        first_raw = None
        n_source = 0
        try:
            for f in iter_frames(path, crop):
                if mirrored:
                    f = f.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
                if bg is None:
                    bg = corner_color(f)
                if first_raw is None:
                    first_raw = f.copy()
                frames.append(fit_to_cell(remove_background(f, bg), args.cell, shared_box,
                                          not args.no_sharpen))
                n_source += 1
        except Exception as e:
            print("[error] %s: %s" % (path.name, e))
            continue
        if not frames:
            continue

        if len(frames) == 1:
            frames = breathing_frames(remove_background(first_raw, bg), args.cell,
                                      bbox=shared_box, sharpen=not args.no_sharpen)
            note = "still -> %d-frame breathing loop" % len(frames)
        else:
            frames = thin_frames(frames)
            note = "%d source frames" % n_source
        if mirrored:
            note += ", mirrored"

        sub, filename, cfgkey = ACTIONS[key]
        outdir = char_dir / sub
        outdir.mkdir(parents=True, exist_ok=True)
        sheet = build_sheet(frames, args.cell, args.col)
        outpath = outdir / filename
        save_sheet(sheet, outpath)
        built_paths.add(outpath.resolve())
        if key == "idle" or base_cells is None:
            base_cells = frames
        counts[cfgkey] = len(frames)
        report.append((sub + "/" + filename, len(frames), note))

    if counts:
        update_config(char_dir, counts)

    filled = []
    if not args.no_fill:
        filled = fill_remaining(char_dir, built_paths, base_cells, args.cell)

    print("\n=== built from your recordings: %d sheets ===" % len(report))
    for name, n, note in report:
        print("  %-24s %3d frames  (%s)" % (name, n, note))
    if filled:
        print("\n=== auto-filled from the new character's idle frames: %d sheets ===" % len(filled))
        print("  " + ", ".join(filled))
        print("  These are static loops from the same character; record more GIFs to replace them.")
    covered = {k for k in sources}
    rest = [ACTIONS[k][0] + "/" + ACTIONS[k][1] for k in ACTIONS if k not in covered]
    if rest and args.no_fill:
        print("\n=== left as placeholder (%d) ===" % len(rest))
        print("  " + ", ".join(sorted(rest)))
    print("\nconfig.txt frame counts updated. Restart the pet (or pick the character in Options.exe) to apply.")


if __name__ == "__main__":
    main()
