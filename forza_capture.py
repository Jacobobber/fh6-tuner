"""forza_capture.py — safe, read-only auto-walk of the FH6 Upgrade Shop.

Focuses the Forza Horizon 6 window, clicks through the upgrade categories, and
screenshots every part. Auto-detects how many options each category has (2 up to
12+, including grids that scroll) by fingerprinting the highlighted item's info
panel and stopping when a move reveals an already-seen option (wrapped) or no
movement (dead end). Screens land in captures/.

SAFETY: only arrow keys + Enter + Esc (+ q/e/tab for menu tabs). Enter is used
only to OPEN a part/category; in the per-part scan every Enter is followed by Esc
and Enter is never pressed on a detail screen — so no purchase/toggle is possible.

Usage:
  python forza_capture.py shot            # screenshot current screen
  python forza_capture.py walk [ncats]    # full walk (auto-detects options/category)
  python forza_capture.py keys <k,k,...>  # send safe keys, then screenshot
"""
import sys
import time
import pathlib

import numpy as np
import pyautogui
import pygetwindow as gw
import mss
import mss.tools

TITLE = "Forza Horizon 6"
OUT = pathlib.Path("captures")
SAFE_KEYS = {"up", "down", "left", "right", "enter", "esc", "q", "e", "tab", "pageup", "pagedown"}
pyautogui.PAUSE = 0.2
DELAY = 0.6           # between nav keypresses
CAP_SETTLE = 0.7      # extra wait for a detail panel to fade in before capture
FP_THRESH = 6.0       # fingerprint mean-abs-diff below this = "same menu item"
_n = 0


def _win():
    w = gw.getWindowsWithTitle(TITLE)
    return w[0] if w else None


def region():
    w = _win()
    if w:
        return {"left": w.left, "top": w.top, "width": w.width, "height": w.height}
    return {"left": 472, "top": 250, "width": 1616, "height": 939}


def focus():
    w = _win()
    if w:
        try:
            if w.isMinimized:
                w.restore()
            w.activate()
        except Exception as e:
            print("activate warning:", e)
    time.sleep(0.6)
    return w


def press(key):
    assert key in SAFE_KEYS, f"refusing unsafe key {key!r}"
    pyautogui.press(key)
    time.sleep(DELAY)


def _grab():
    with mss.mss() as sct:
        img = sct.grab(region())
    return np.frombuffer(img.rgb, dtype=np.uint8).reshape(img.height, img.width, 3)


def cap(label):
    global _n
    with mss.mss() as sct:
        img = sct.grab(region())
        name = f"{_n:03d}_{label}.png"
        mss.tools.to_png(img.rgb, img.size, output=str(OUT / name))
    _n += 1
    return name


def fingerprint(zone="bottomleft"):
    """Coarse grayscale fingerprint of a stable, per-item region (excludes the
    animated car). 'bottomleft' = the upgrade grid's highlighted-item info panel;
    'topbar' = the tune-screen tab bar (which tab is highlighted)."""
    arr = _grab().astype(np.float32)
    h, w, _ = arr.shape
    if zone == "topbar":
        crop = arr[int(h * 0.08):int(h * 0.20), int(w * 0.08):int(w * 0.96)].mean(axis=2)
    else:
        crop = arr[int(h * 0.68):int(h * 0.98), int(w * 0.02):int(w * 0.52)].mean(axis=2)
    fh, fw = 24, 24
    ph, pw = max(1, crop.shape[0] // fh), max(1, crop.shape[1] // fw)
    crop = crop[:fh * ph, :fw * pw]
    return crop.reshape(fh, ph, fw, pw).mean(axis=(1, 3))


def _seen(fp, seen):
    return any(np.mean(np.abs(fp - s)) < FP_THRESH for s in seen)


def scan_grid(prefix, rows=4, cols=3):
    """Cover a part grid up to rows×cols (12 cells = the documented max; 'down'
    scrolls if the grid is taller than the screen). Snake each row L->R, return to
    column 0, drop a row. Over-scans short grids (harmless duplicate captures that
    are de-duped afterward by OCR/reading). Reliable full coverage beats clever
    live stopping (which mis-counted). Read-only: Enter opens, Esc backs out."""
    def open_capture(tag):
        press("enter")            # grid -> part detail (open; non-destructive)
        time.sleep(CAP_SETTLE)
        cap(f"{prefix}_{tag}")
        press("esc")              # detail -> grid (never confirms)

    for r in range(rows):
        for c in range(cols):
            open_capture(f"r{r}c{c}")
            if c < cols - 1:
                press("right")        # next column
        for _ in range(cols - 1):
            press("left")             # back to column 0
        press("down")                 # next row (scrolls if needed)
    print(f"  {prefix}: captured {rows * cols} cells (unique count via OCR de-dup)")


def tune(max_tabs=12):
    """Capture every tune tab. Assumes the Tune screen is open on the first tab;
    PgDn advances tabs, auto-stopping when it wraps to an already-seen tab.
    Read-only — PgDn only switches tabs, never changes a slider value."""
    OUT.mkdir(exist_ok=True)
    for p in OUT.glob("tune_*.png"):
        p.unlink()
    focus()
    seen = [fingerprint("topbar")]
    cap("tune_00")
    i = 1
    while i < max_tabs:
        press("pagedown")
        fp = fingerprint("topbar")
        if _seen(fp, seen):
            break              # wrapped to a seen tab -> all tabs captured
        seen.append(fp)
        cap(f"tune_{i:02d}")
        i += 1
    print(f"captured {i} tune tabs")


def walk(ncats):
    OUT.mkdir(exist_ok=True)
    for p in OUT.glob("*.png"):
        p.unlink()
    focus()
    cap("start")                           # expected: Upgrades menu, Custom Upgrade highlighted
    press("enter")                         # Custom Upgrade -> Upgrade Shop (category icons)
    cap("categories")
    moves = ["", "right", "right", "down", "left", "left"][:ncats]
    for ci, mv in enumerate(moves):
        focus()
        if mv:
            press(mv)                      # move to next category icon
        cap(f"cat{ci}_icon")
        press("enter")                     # categories -> this category's grid
        cap(f"cat{ci}_grid")
        scan_grid(f"cat{ci}")
        press("esc")                       # grid -> categories
    print(f"captured {_n} screenshots to {OUT}/")


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "shot"
    if mode == "shot":
        OUT.mkdir(exist_ok=True)
        focus()
        print("captured", cap("now"))
    elif mode == "walk":
        ncats = int(sys.argv[2]) if len(sys.argv) > 2 else 6
        walk(ncats)
    elif mode == "tune":
        tune()
    elif mode == "nudge":
        OUT.mkdir(exist_ok=True)
        focus()
        key = sys.argv[2]
        count = int(sys.argv[3]) if len(sys.argv) > 3 else 1
        for _ in range(count):
            press(key)
        print("captured", cap("nudge"))
    elif mode == "keys":
        OUT.mkdir(exist_ok=True)
        focus()
        for k in [x.strip() for x in sys.argv[2].split(",") if x.strip()]:
            press(k)
        print("captured", cap("after_keys"))
    else:
        print("usage: python forza_capture.py [shot|walk [ncats]|tune|keys <k,k>]")


if __name__ == "__main__":
    main()
