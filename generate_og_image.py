"""
TopEpisode.com — Open Graph image generator.

Produces a 1200×630 PNG (site/og-image.png) featuring the site title,
subtitle, and a ranked list of top episodes from the dataset.
Run after the scraper so CSV data is available.
"""

import csv
import math
import os
import sys

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("Pillow not installed — skipping OG image generation.")
    sys.exit(0)


# ── Config ──────────────────────────────────────────────────────────────
WIDTH, HEIGHT = 1200, 630
BG_COLOR = (14, 15, 17)        # --bg: #0e0f11
PANEL_COLOR = (23, 24, 27)     # --panel: #17181b
ACCENT = (245, 197, 24)        # --accent: #f5c518
TEXT_COLOR = (234, 234, 234)   # --text: #eaeaea
MUTED = (154, 154, 154)       # --muted: #9a9a9a
BORDER = (42, 43, 46)         # --border: #2a2b2e
OUTPUT = os.path.join("site", "og-image.png")
NUM_EPISODES = 7


# ── Font helpers ────────────────────────────────────────────────────────
def _try_fonts(names, size):
    """Try to load a TrueType font from common system paths."""
    search_dirs = [
        "/System/Library/Fonts",
        "/System/Library/Fonts/Supplemental",
        "/Library/Fonts",
        "/usr/share/fonts/truetype",
        "/usr/share/fonts",
    ]
    for name in names:
        # Direct name (Pillow searches system paths)
        try:
            return ImageFont.truetype(name, size)
        except (OSError, IOError):
            pass
        # Search in common directories
        for d in search_dirs:
            path = os.path.join(d, name)
            if os.path.isfile(path):
                try:
                    return ImageFont.truetype(path, size)
                except (OSError, IOError):
                    pass
    return ImageFont.load_default()


def get_fonts():
    bold_names = [
        "SF-Pro-Display-Bold.otf", "SFProDisplay-Bold.otf",
        "HelveticaNeue-Bold.ttf", "Helvetica-Bold.ttf",
        "Arial Bold.ttf", "arialbd.ttf",
        "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf",
    ]
    regular_names = [
        "SF-Pro-Display-Regular.otf", "SFProDisplay-Regular.otf",
        "HelveticaNeue.ttf", "Helvetica.ttf",
        "Arial.ttf", "arial.ttf",
        "DejaVuSans.ttf", "LiberationSans-Regular.ttf",
    ]
    italic_names = [
        "SF-Pro-Display-RegularItalic.otf", "SFProDisplay-RegularItalic.otf",
        "HelveticaNeue-Italic.ttf", "Helvetica-Oblique.ttf",
        "Arial Italic.ttf", "ariali.ttf",
        "DejaVuSans-Oblique.ttf", "LiberationSans-Italic.ttf",
    ]
    return {
        "title": _try_fonts(bold_names, 56),
        "subtitle": _try_fonts(regular_names, 22),
        "catchphrase": _try_fonts(italic_names, 22),
        "rank": _try_fonts(bold_names, 24),
        "episode": _try_fonts(bold_names, 22),
        "series": _try_fonts(regular_names, 22),
        "se": _try_fonts(bold_names, 18),
        "rating_label": _try_fonts(bold_names, 24),
    }


# ── Load top episodes from CSV ──────────────────────────────────────────
def load_top_episodes():
    """Read the top episodes CSV and return the highest-rated with 1000+ votes."""
    csv_path = os.path.join("data", "top_episodes.csv")
    if not os.path.isfile(csv_path):
        # Try chunk files
        for chunk in ["90_1000", "90_100", "85_1000"]:
            p = os.path.join("data", f"top_episodes_{chunk}.csv")
            if os.path.isfile(p):
                csv_path = p
                break

    episodes = []
    try:
        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    rating = float(row.get("rating", 0))
                    votes = int(row.get("votes", 0))
                except (ValueError, TypeError):
                    continue
                if votes >= 1000:
                    episodes.append({
                        "episode_title": row.get("episode_title", ""),
                        "series_title": row.get("series_title", ""),
                        "season_number": row.get("season_number", ""),
                        "episode_number": row.get("episode_number", ""),
                        "rating": rating,
                        "votes": votes,
                    })
    except FileNotFoundError:
        print(f"Warning: CSV not found at {csv_path}, using placeholder data.")
        return []

    episodes.sort(key=lambda e: (-e["rating"], -e["votes"]))
    return episodes[:NUM_EPISODES]


# ── Draw ────────────────────────────────────────────────────────────────
def draw_image():
    fonts = get_fonts()
    episodes = load_top_episodes()

    img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # ── Top accent bar ──
    draw.rectangle([0, 0, WIDTH, 4], fill=ACCENT)

    # ── Title: "TopEpisode.com" ──
    x_left = 50
    y_title = 34

    parts = [
        ("Top", TEXT_COLOR),
        ("Episode", ACCENT),
        (".com", TEXT_COLOR),
    ]
    x = x_left
    for text, color in parts:
        draw.text((x, y_title), text, fill=color, font=fonts["title"])
        bbox = fonts["title"].getbbox(text)
        x += bbox[2] - bbox[0]

    # ── Subtitle ──
    y_sub = y_title + 66
    subtitle_text = "Top episodes of TV based on IMDb rankings — sortable, filterable, auto-updated daily."
    draw.text((x_left, y_sub), subtitle_text, fill=MUTED, font=fonts["subtitle"])

    # "Absolute cinema." in italics on next line or same line
    sub_bbox = fonts["subtitle"].getbbox(subtitle_text)
    sub_w = sub_bbox[2] - sub_bbox[0]
    # Check if it fits on the same line
    catch_bbox = fonts["catchphrase"].getbbox("Absolute cinema.")
    catch_w = catch_bbox[2] - catch_bbox[0]
    if x_left + sub_w + 8 + catch_w < WIDTH - 50:
        draw.text((x_left + sub_w + 8, y_sub), "Absolute cinema.", fill=ACCENT, font=fonts["catchphrase"])
        y_after_sub = y_sub + 34
    else:
        y_after_sub = y_sub + 30
        draw.text((x_left, y_after_sub), "Absolute cinema.", fill=ACCENT, font=fonts["catchphrase"])
        y_after_sub += 34

    # ── Divider ──
    y_div = y_after_sub + 4
    draw.line([(x_left, y_div), (WIDTH - 50, y_div)], fill=BORDER, width=1)

    # ── Episode list — single-line horizontal layout ──
    y_start = y_div + 14
    row_h = 56

    if not episodes:
        draw.text((x_left, y_start + 20), "Top-rated episodes will appear here",
                   fill=MUTED, font=fonts["episode"])
    else:
        for i, ep in enumerate(episodes):
            y = y_start + i * row_h
            y_text = y + (row_h - 28) // 2  # vertically center text in row

            # Row background (alternating)
            if i % 2 == 0:
                draw.rectangle(
                    [x_left - 10, y + 2, WIDTH - 40, y + row_h - 2],
                    fill=PANEL_COLOR,
                )

            x_cursor = x_left

            # Rank number (e.g. "1.")
            rank_text = f"{i + 1}."
            draw.text((x_cursor, y_text), rank_text, fill=MUTED, font=fonts["rank"])
            x_cursor += 38

            # Rating — draw a star polygon + "9.9"

            star_cx = x_cursor + 12
            star_cy = y_text + 14
            star_r_outer = 11
            star_r_inner = 5
            star_pts = []
            for k in range(10):
                angle = math.pi / 2 + k * math.pi / 5
                r = star_r_outer if k % 2 == 0 else star_r_inner
                star_pts.append((star_cx + r * math.cos(angle), star_cy - r * math.sin(angle)))
            draw.polygon(star_pts, fill=ACCENT)
            rating_text = f"{ep['rating']:.1f}"
            draw.text((x_cursor + 28, y_text), rating_text, fill=ACCENT, font=fonts["rating_label"])
            x_cursor += 90

            # S/E badge (e.g. "S6E9")
            sn = ep.get("season_number", "")
            en = ep.get("episode_number", "")
            se_text = f"S{sn}E{en}" if sn and en else ""
            if se_text:
                # Draw S/E in a subtle badge
                se_bbox = fonts["se"].getbbox(se_text)
                se_w = se_bbox[2] - se_bbox[0]
                badge_pad = 6
                badge_x = x_cursor
                badge_y = y_text + 2
                badge_h = 24
                # Badge background
                draw.rounded_rectangle(
                    [badge_x, badge_y, badge_x + se_w + badge_pad * 2, badge_y + badge_h],
                    radius=4,
                    fill=BORDER,
                )
                draw.text((badge_x + badge_pad, badge_y + 2), se_text, fill=TEXT_COLOR, font=fonts["se"])
                x_cursor += se_w + badge_pad * 2 + 12
            else:
                x_cursor += 4

            # Episode title (bold white)
            ep_title = ep["episode_title"]
            # Calculate remaining space for episode + series
            remaining = WIDTH - 50 - x_cursor
            ep_bbox = fonts["episode"].getbbox(ep_title)
            ep_w = ep_bbox[2] - ep_bbox[0]

            # Build the " — Series" suffix
            series_suffix = f" — {ep['series_title']}" if ep["series_title"] else ""

            if series_suffix:
                suf_bbox = fonts["series"].getbbox(series_suffix)
                suf_w = suf_bbox[2] - suf_bbox[0]
            else:
                suf_w = 0

            # Truncate episode title if needed to leave room for series
            max_ep_w = remaining - suf_w - 10
            if ep_w > max_ep_w and max_ep_w > 50:
                # Truncate
                while ep_w > max_ep_w and len(ep_title) > 5:
                    ep_title = ep_title[:-1]
                    ep_bbox = fonts["episode"].getbbox(ep_title + "…")
                    ep_w = ep_bbox[2] - ep_bbox[0]
                ep_title += "…"
                ep_bbox = fonts["episode"].getbbox(ep_title)
                ep_w = ep_bbox[2] - ep_bbox[0]

            draw.text((x_cursor, y_text), ep_title, fill=TEXT_COLOR, font=fonts["episode"])
            x_cursor += ep_w

            # Series title (regular, muted) with em dash
            if series_suffix:
                # Truncate series if needed
                avail = WIDTH - 50 - x_cursor - 4
                if suf_w > avail and avail > 40:
                    s = series_suffix
                    while suf_w > avail and len(s) > 5:
                        s = s[:-1]
                        suf_bbox = fonts["series"].getbbox(s + "…")
                        suf_w = suf_bbox[2] - suf_bbox[0]
                    series_suffix = s + "…"
                draw.text((x_cursor, y_text), series_suffix, fill=MUTED, font=fonts["series"])

    # ── Bottom accent bar ──
    draw.rectangle([0, HEIGHT - 4, WIDTH, HEIGHT], fill=ACCENT)

    os.makedirs("site", exist_ok=True)
    img.save(OUTPUT, "PNG", optimize=True)
    print(f"OG image saved to {OUTPUT}")


if __name__ == "__main__":
    draw_image()

