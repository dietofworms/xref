"""Render the xref README banner as a dithered ASCII image.

Usage: python docs/banner.py docs/banner.png (needs Pillow and the
JetBrains Mono and Inter fonts at the paths below).
"""

import random
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageStat

COLS, ROWS = 164, 44
FS = 26  # font size at 2x
CW, CH = FS * 0.6, 28
W, H = round(COLS * CW), ROWS * CH

MONO = "/usr/share/fonts/truetype/jetbrains-mono/JetBrainsMono-Regular.ttf"
MONO_B = "/usr/share/fonts/truetype/jetbrains-mono/JetBrainsMono-Bold.ttf"
TITLE = "/usr/share/fonts/opentype/inter/Inter-ExtraBold.otf"

BG = (10, 13, 20)
DIM = (34, 41, 56)
FRAME = (52, 62, 82)
EDGE = (92, 101, 118)
TEXT = (201, 209, 221)
MUTED = (110, 120, 138)
ORANGE = (255, 105, 74)
VIOLET = (167, 139, 250)
BLUE = (88, 166, 255)
PEACH = (255, 214, 204)
LILAC = (221, 214, 254)

BAYER = [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]
RAMP = " .:-=+*#%@"

Cell = tuple[str, tuple[int, int, int], bool]
grid: list[list[Cell]] = [[(" ", BG, False)] * COLS for _ in range(ROWS)]


def lerp(a: tuple[int, int, int], b: tuple[int, int, int], t: float):
    t = max(0.0, min(1.0, t))
    return (
        round(a[0] + (b[0] - a[0]) * t),
        round(a[1] + (b[1] - a[1]) * t),
        round(a[2] + (b[2] - a[2]) * t),
    )


def put(c: int, r: int, s: str, color: tuple[int, int, int], bold: bool = False):
    for i, ch in enumerate(s):
        if 0 <= c + i < COLS and 0 <= r < ROWS:
            grid[r][c + i] = (ch, color, bold)


def centre(r: int, s: str, color: tuple[int, int, int], c: float = COLS / 2):
    put(round(c - len(s) / 2), r, s, color)


def thresh(c: int, r: int) -> float:
    return (BAYER[r % 4][c % 4] + 0.5) / 16


# --- background: sparse ordered-dither vignette -----------------------------
rng = random.Random(7)
for r in range(ROWS):
    for c in range(COLS):
        dx, dy = (c - COLS / 2) / (COLS / 2), (r - ROWS / 2) / (ROWS / 2)
        v = 0.16 * min(1.0, (dx * dx + dy * dy) ** 0.5) + 0.03 * rng.random()
        if v > thresh(c, r) * 0.9:
            put(c, r, "." if v < 0.13 else ":", DIM)

# --- title: "xref" sampled into cells, shaded and dithered ------------------
mask = Image.new("L", (W, H), 0)
font = ImageFont.truetype(TITLE, 440)
md = ImageDraw.Draw(mask)
box = md.textbbox((0, 0), "xref", font=font)
tw, th = box[2] - box[0], box[3] - box[1]
top = CH
md.text(((W - tw) / 2 - box[0], top - box[1]), "xref", font=font, fill=255)
glow = mask.filter(ImageFilter.GaussianBlur(26))
title_rows = range(0, 15)
y0, y1 = top / CH, (top + th) / CH
x0, x1 = (W - tw) / 2 / CW, (W + tw) / 2 / CW


def sample(img: Image.Image, c: int, r: int) -> float:
    if not 0 <= c < COLS:
        return 0.0
    cell = (round(c * CW), r * CH, round((c + 1) * CW), (r + 1) * CH)
    return ImageStat.Stat(img.crop(cell)).mean[0] / 255


cov_map = {(c, r): sample(mask, c, r) for r in title_rows for c in range(COLS)}
glow_map = {(c, r): sample(glow, c, r) for r in title_rows for c in range(COLS)}

# glitch: some rows slip sideways, a red and a cyan copy sit either side of
# the letters, and a few noise bars cut across.
CYAN, MAGENTA = (0, 229, 255), (255, 46, 136)
shift = {4: 2, 5: 2, 9: -2, 12: 1}
glitch_rng = random.Random(11)


def cov_at(c: int, r: int) -> float:
    return cov_map.get((c - shift.get(r, 0), r), 0.0)


for r in title_rows:
    for c in range(COLS):
        cov = cov_at(c, r)
        g = glow_map.get((c - shift.get(r, 0), r), 0.0)
        tx = (c - x0) / (x1 - x0)
        ty = (r - y0) / (y1 - y0)
        if cov > 0.04:
            shade = cov * (1.15 - 0.3 * ty) + 0.25 * (thresh(c, r) - 0.5)
            i = max(1, min(len(RAMP) - 1, round(shade * (len(RAMP) - 1))))
            col = lerp(ORANGE, VIOLET, tx)
            col = lerp(lerp(BG, col, 0.55), col, shade + 0.25)
            if r in shift and glitch_rng.random() < 0.03:
                put(c, r, glitch_rng.choice("░▒"), lerp(col, (255, 255, 255), 0.35))
            else:
                put(c, r, RAMP[i], col, bold=True)
        elif (k := cov_at(c + 2, r)) > 0.5 and cov_at(c - 2, r) < 0.04:
            put(c, r, RAMP[max(1, round(k * 4))], lerp(BG, CYAN, 0.6))
        elif (k := cov_at(c - 2, r)) > 0.5 and cov_at(c + 2, r) < 0.04:
            put(c, r, RAMP[max(1, round(k * 4))], lerp(BG, MAGENTA, 0.6))
        elif g > 0.05 and g * 0.9 > thresh(c, r):
            put(c, r, "." if g < 0.2 else ":", lerp(BG, lerp(ORANGE, VIOLET, tx), 0.45))

for r, c, n, col in [
    (4, 36, 12, CYAN),
    (9, 117, 16, MAGENTA),
    (12, 40, 8, MAGENTA),
    (2, 92, 6, CYAN),
]:
    for i in range(n):
        if glitch_rng.random() < 0.75:
            put(
                c + i, r, glitch_rng.choice("░░▒▓"), lerp(BG, col, 0.35 + 0.4 * glitch_rng.random())
            )

centre(15, "cross-project ref() for dbt v2 · no platform plan required", MUTED)


# --- DAG --------------------------------------------------------------------
def frame(c: int, r: int, w: int, h: int, color, dashed: bool = False):
    hz, vt = ("┄", "┆") if dashed else ("─", "│")
    put(c, r, "╭" + hz * (w - 2) + "╮", color)
    for y in range(r + 1, r + h - 1):
        put(c, y, vt, color)
        put(c + w - 1, y, vt, color)
    put(c, r + h - 1, "╰" + hz * (w - 2) + "╯", color)


def node(c: int, r: int, label: str, color=EDGE, text=TEXT, dashed=False, w=19):
    frame(c, r, w, 3, color, dashed)
    put(c + 1, r + 1, " " * (w - 2), BG)
    put(c + (w - len(label)) // 2, r + 1, label, text)


def merge(c: int, top: int, bottom: int, mid: int, end: int, color=EDGE):
    put(c, top, "──", color)
    put(c + 2, top, "╮", color)
    put(c, bottom, "──", color)
    put(c + 2, bottom, "╯", color)
    for y in range(top + 1, bottom):
        put(c + 2, y, "│", color)
    put(c + 2, mid, "├", color)
    put(c + 3, mid, "─" * (end - c - 4), color)
    put(end - 1, mid, "▶", color)


def panel(c: int, name: str, role: str, dot):
    frame(c, 18, 56, 17, FRAME)
    for y in range(19, 34):
        put(c + 1, y, " " * 54, BG)
    put(c + 3, 19, "●", dot)
    put(c + 5, 19, name, TEXT, bold=True)
    put(c + 53 - len(role), 19, role, MUTED)


panel(3, "product_a", "producer", ORANGE)
node(6, 21, "stg_orders")
node(6, 28, "stg_customers")
merge(25, 22, 29, 26, 35)
node(35, 25, "dim_customers", ORANGE, PEACH)
put(41, 25, " public ", ORANGE, bold=True)

panel(105, "product_b", "consumer", VIOLET)
node(108, 21, "dim_customers", VIOLET, LILAC, dashed=True)
put(110, 24, "ephemeral stub", (125, 111, 179))
node(108, 28, "stg_payments")
merge(127, 22, 29, 26, 137)
node(137, 25, "fct_revenue")

# the cross-project ref: dashed, coloured orange -> violet along its length
for c in range(54, 81):
    put(c, 26, "╌", lerp(ORANGE, VIOLET, (c - 54) / 53))
put(81, 26, "╯", lerp(ORANGE, VIOLET, 27 / 53))
for y in range(23, 26):
    put(81, y, "╎", lerp(ORANGE, VIOLET, 27 / 53))
put(81, 22, "╭", lerp(ORANGE, VIOLET, 27 / 53))
for c in range(82, 107):
    put(c, 22, "╌", lerp(ORANGE, VIOLET, (c - 54) / 53))
put(107, 22, "▶", VIOLET)

ref = [
    ("{{ ", MUTED),
    ("ref", VIOLET),
    ("(", MUTED),
    ("'product_a'", (255, 143, 117)),
    (", ", MUTED),
    ("'dim_customers'", PEACH),
    (") }}", MUTED),
]
c = round(81 - sum(len(s) for s, _ in ref) / 2)
put(c - 2, 20, " " * (sum(len(s) for s, _ in ref) + 4), BG)
for s, col in ref:
    put(c, 20, s, col)
    c += len(s)

# --- manifest store ---------------------------------------------------------
store = [
    "╭───────────────────────╮",
    "│╰─────────────────────╯│",
    "│                       │",
    "│     manifest.json     │",
    "│                       │",
    "╰───────────────────────╯",
]
sc = 81 - len(store[0]) // 2
for i, line in enumerate(store):
    put(sc, 35 + i, " " * len(line), BG)
    put(sc, 35 + i, line, BLUE)
put(sc + 6, 38, "manifest.json", (156, 203, 255))
centre(42, "s3 · gcs · azure · local", MUTED, 81)

for y in range(35, 38):
    put(44, y, "│", BLUE)
put(44, 38, "╰" + "─" * (sc - 47), BLUE)
put(sc - 2, 38, "▶", BLUE)
put(36, 40, "$ xref publish", (156, 203, 255), bold=True)

sx = sc + len(store[0])
put(sx + 1, 38, "─" * (117 - sx - 2), BLUE)
put(116, 38, "╯", BLUE)
for y in range(36, 38):
    put(116, y, "│", BLUE)
put(116, 35, "▲", BLUE)
put(120, 40, "$ xref sync", (156, 203, 255), bold=True)

# --- render -----------------------------------------------------------------
img = Image.new("RGB", (W, H), BG)
d = ImageDraw.Draw(img)
reg, bold = ImageFont.truetype(MONO, FS), ImageFont.truetype(MONO_B, FS)
for r, row in enumerate(grid):
    for c, (ch, col, b) in enumerate(row):
        if ch != " ":
            d.text((c * CW, r * CH + (CH - FS) / 2 - 2), ch, font=bold if b else reg, fill=col)
img.save(sys.argv[1], optimize=True)
