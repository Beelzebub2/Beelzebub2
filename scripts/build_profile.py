#!/usr/bin/env python3
"""Build the profile README and its SVG panels from profile.config.json.

    python scripts/build_profile.py

Everything shown on a card (name, description, language, stars, topics) comes
from the GitHub API, so featuring a repo only takes adding its link to
"featured" in profile.config.json. Standard library only.

Set GITHUB_TOKEN to raise the API rate limit (the workflow does this).
"""
import base64
import functools
import html
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "profile"
CONFIG = json.loads((ROOT / "profile.config.json").read_text(encoding="utf-8"))
USER = CONFIG["user"]
TOKEN = os.environ.get("GITHUB_TOKEN")

ACCENT = CONFIG.get("colors", {}).get("accent", "#FF2E5B")
SIGNAL = CONFIG.get("colors", {}).get("signal", "#FFB000")
BG, RAISED, TRACK = "#08070B", "#100D14", "#1A151F"
LINE, LINE2 = "#2B2431", "#43384A"
BONE, MUTED, GREY = "#EFE8E4", "#A0949C", "#6E6470"

# role -> (Google Fonts family, fallback stack). Glyphs are subset per SVG and
# embedded, because an SVG shown through <img> cannot load external fonts.
FONTS = {
    "disp": ("Tektur", "'Segoe UI', sans-serif"),
    "mono": ("JetBrains Mono", "Consolas, monospace"),
    "kana": ("Dela Gothic One", "'Yu Gothic UI', Meiryo, sans-serif"),
}
DISP_EM = 0.66  # Tektur's average advance, on the wide side so text never overflows

BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

DEFS = (
    '<pattern id="hz" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
    f'<rect width="3" height="6" fill="{SIGNAL}"/></pattern>'
    '<pattern id="hatch" width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
    f'<rect width="3" height="7" fill="{ACCENT}"/></pattern>'
    '<pattern id="dots" width="18" height="18" patternUnits="userSpaceOnUse">'
    f'<circle cx="9" cy="9" r="1" fill="{BONE}" fill-opacity=".07"/></pattern>'
    '<pattern id="scan" width="4" height="4" patternUnits="userSpaceOnUse">'
    '<rect width="4" height="1" fill="#FFF" fill-opacity=".035"/></pattern>'
    '<pattern id="bars" width="10" height="16" patternUnits="userSpaceOnUse">'
    f'<rect width="2" height="16" fill="{MUTED}"/><rect x="5" width="1" height="16" fill="{MUTED}"/></pattern>'
)

ANIM = (
    "@keyframes blink{50%{opacity:.25}}"
    ".blink{animation:blink 1.4s steps(1,end) infinite}"
    "@keyframes sweep{to{transform:translateY(326px)}}"
    ".sweep{animation:sweep 6s linear infinite}"
    "@keyframes ga{0%,91%,96%,100%{transform:translate(0,0)}92%{transform:translate(-9px,2px)}94%{transform:translate(12px,-1px)}}"
    ".ga{animation:ga 5s steps(1,end) infinite}"
    "@keyframes gc{0%,91%,96%,100%{opacity:0}92%{opacity:1;transform:translate(-40px,0)}94%{opacity:1;transform:translate(18px,0)}}"
    ".gc{opacity:0;animation:gc 5s steps(1,end) infinite}"
    "@keyframes spin{to{transform:rotate(360deg)}}"
    ".spin{transform-box:fill-box;transform-origin:center;animation:spin 90s linear infinite}"
    "@media (prefers-reduced-motion:reduce){.blink,.sweep,.ga,.gc,.spin{animation:none}}"
)

ICONS = {
    "repo": "M4 3h12v14H4zM8 3v14",
    "people": "M10 4a3 3 0 1 0 0 6a3 3 0 0 0 0-6zM4 17c0-3.3 2.7-5 6-5s6 1.7 6 5",
    "cup": "M4 6h10v5a4 4 0 0 1-4 4H8a4 4 0 0 1-4-4zM14 7h1.5a2 2 0 0 1 0 4H14",
    "arrow": "M3 10h13M11 5l5 5-5 5",
}
STAR = "M10 2.5l2.3 4.7 5.2.8-3.8 3.6.9 5.2L10 14.3l-4.6 2.5.9-5.2L2.5 8l5.2-.8z"


# ---------------------------------------------------------------- network

def fetch(url, headers=None, data=None, tries=3):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": BROWSER_UA, **(headers or {})})
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=30) as res:
                return res.read()
        except urllib.error.HTTPError as err:
            if err.code < 500 or attempt == tries - 1:
                raise
        except OSError:
            if attempt == tries - 1:
                raise
        time.sleep(2 ** attempt)


def api(path, body=None):
    headers = {"Accept": "application/vnd.github+json", "Content-Type": "application/json"}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    data = json.dumps(body).encode() if body else None
    return json.loads(fetch("https://api.github.com" + path, headers, data))


@functools.lru_cache(maxsize=None)
def font_face(family, weight, chars):
    """@font-face CSS for just `chars`, with the font file inlined as base64."""
    query = urllib.parse.urlencode({"family": f"{family}:wght@{weight}", "text": chars})
    css = fetch("https://fonts.googleapis.com/css2?" + query).decode()

    def inline(match):
        return "url(data:font/woff2;base64," + base64.b64encode(fetch(match.group(1))).decode() + ")"

    return re.sub(r"\s+", " ", re.sub(r"url\((https://[^)]+)\)", inline, css)).strip()


def contributions():
    """Contributions in the last year, or None when it can't be read without a token."""
    if TOKEN:
        query = '{user(login:"%s"){contributionsCollection{contributionCalendar{totalContributions}}}}' % USER
        result = api("/graphql", {"query": query})
        return result["data"]["user"]["contributionsCollection"]["contributionCalendar"]["totalContributions"]
    try:
        page = fetch(f"https://github.com/users/{USER}/contributions").decode()
    except OSError:
        return None
    found = re.search(r"([\d,]+)\s+contributions?\s+in the last year", page)
    return int(found.group(1).replace(",", "")) if found else None


def load_data():
    profile = api(f"/users/{USER}")
    repos, page = [], 1
    while True:
        batch = api(f"/users/{USER}/repos?type=owner&per_page=100&page={page}")
        repos += batch
        if len(batch) < 100:
            break
        page += 1
    by_name = {r["full_name"].lower(): r for r in repos}

    featured = []
    for link in CONFIG["featured"]:
        found = re.search(r"(?:github\.com/)?([\w.-]+)/([\w.-]+?)(?:\.git)?/?$", link.strip())
        if not found:
            raise SystemExit(f"profile.config.json: not a repo link: {link!r}")
        slug = f"{found.group(1)}/{found.group(2)}"
        featured.append(by_name.get(slug.lower()) or api(f"/repos/{slug}"))

    # Forks and the profile repo itself never count as "my work" below.
    own = [r for r in repos if not r["fork"] and r["name"].lower() != USER.lower()]
    now = max(own, key=lambda r: r["pushed_at"], default=None)
    shown = {r["full_name"] for r in featured} | ({now["full_name"]} if now else set())
    archive = sorted((r for r in own if r["full_name"] not in shown and r["stargazers_count"]),
                     key=lambda r: -r["stargazers_count"])[:3]

    languages = {}
    for r in own:
        if r["language"]:
            languages[r["language"]] = languages.get(r["language"], 0) + 1

    return {
        "uid": profile["id"],
        "repos": profile["public_repos"],
        "followers": profile["followers"],
        "stars": sum(r["stargazers_count"] for r in repos),
        "contributions": contributions(),
        "featured": featured,
        "now": now,
        "archive": archive,
        "languages": sorted(languages.items(), key=lambda kv: (-kv[1], kv[0])),
        "sources": len(own),
    }


# ---------------------------------------------------------------- drawing

def esc(value):
    return html.escape(str(value), quote=True)


def num(value):
    return f"{value:.1f}".rstrip("0").rstrip(".")


def mono_w(text, size, ls=0.0):
    """Width of JetBrains Mono text: every glyph advances 0.6em."""
    return len(text) * size * (0.6 + ls)


def fit(text, size, room):
    """Largest display size up to `size` that keeps `text` within `room` px."""
    return min(size, room / (max(len(text), 1) * DISP_EM))


def wrap(text, width, lines):
    out, cur = [], ""
    for word in (text or "").split():
        if cur and len(cur) + 1 + len(word) > width:
            out.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}".strip()
    if cur:
        out.append(cur)
    if len(out) > lines:
        out = out[:lines]
        out[-1] = out[-1][:width - 1].rstrip(" ,.;:-—") + "…"
    return [line if len(line) <= width else line[:width - 1] + "…" for line in out]


def chamfer(x, y, w, h, c):
    """Points of a rectangle with its top-left and bottom-right corners cut."""
    pts = [(x + c, y), (x + w, y), (x + w, y + h - c), (x + w - c, y + h), (x, y + h), (x, y + c)]
    return " ".join(f"{num(px)},{num(py)}" for px, py in pts)


def panel(w, h, c, y=0, stroke=LINE, fill=BG):
    return f'<polygon points="{chamfer(0.5, y + 0.5, w - 1, h - 1, c)}" fill="{fill}" stroke="{stroke}"/>'


def icon(name, x, y, color):
    return (f'<path d="{ICONS[name]}" fill="none" stroke="{color}" stroke-width="1.8" '
            f'transform="translate({num(x)} {num(y)}) scale(.9)"/>')


def star(x, y):
    return f'<path d="{STAR}" fill="{SIGNAL}" transform="translate({num(x)} {num(y)}) scale(.65)"/>'


def date(stamp):
    return stamp[:10].replace("-", ".")


class Svg:
    def __init__(self, w, h, label):
        self.w, self.h, self.label = w, h, label
        self.body, self.glyphs = [], {}

    def add(self, markup):
        self.body.append(markup)

    def text(self, x, y, runs, size, font="mono", weight=400, fill=MUTED, ls=0.0, anchor=None, cls=None):
        """Draw text at baseline (x, y). `runs` is a string or [(string, fill), ...]."""
        if isinstance(runs, str):
            runs = [(runs, fill)]
        self.glyphs.setdefault((font, weight), set()).update("".join(r[0] for r in runs))
        family, fallback = FONTS[font]
        attrs = (f'x="{num(x)}" y="{num(y)}" font-family="{family}, {fallback}" '
                 f'font-size="{num(size)}" font-weight="{weight}"')
        if ls:
            attrs += f' letter-spacing="{size * ls:.2f}"'
        if anchor:
            attrs += f' text-anchor="{anchor}"'
        if cls:
            attrs += f' class="{cls}"'
        if len(runs) == 1:
            self.add(f'<text {attrs} fill="{runs[0][1]}">{esc(runs[0][0])}</text>')
        else:
            spans = "".join(f'<tspan fill="{color}">{esc(part)}</tspan>' for part, color in runs)
            self.add(f'<text {attrs} xml:space="preserve">{spans}</text>')

    def render(self):
        body = "".join(self.body)
        style = "".join(font_face(FONTS[font][0], weight, "".join(sorted(chars)))
                        for (font, weight), chars in sorted(self.glyphs.items()))
        if 'class="' in body:
            style += ANIM
        return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{self.h}" '
                f'viewBox="0 0 {self.w} {self.h}" role="img" aria-label="{esc(self.label)}">'
                f"<style>{style}</style><defs>{DEFS}</defs>{body}</svg>\n")


def heading(svg, number, title, caption):
    """The 40px section bar at the top of an SVG."""
    svg.add(panel(svg.w, 40, 10))
    svg.add(f'<polygon points="20,8 48,8 48,32 14,32 14,14" fill="{ACCENT}"/>')
    svg.text(31, 24.5, number, 13, "disp", 700, BG, anchor="middle")
    svg.text(62, 27, title, 20, "disp", 700, BONE, ls=0.08)
    svg.text(832, 24, caption, 11, ls=0.16, anchor="end")
    stripes = 832 - mono_w(caption, 11, 0.16) - 14 - 56
    svg.add(f'<rect x="{num(stripes)}" y="16" width="56" height="8" fill="url(#hz)"/>')
    rule = 62 + len(title) * 20 * (DISP_EM + 0.08) + 12
    if rule < stripes - 14:
        svg.add(f'<path d="M{num(rule)} 20.5H{num(stripes - 14)}" stroke="{LINE}"/>')


def eye(cx, cy):
    def ring(r, attrs):
        return f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" {attrs}/>'

    return "".join([
        ring(190, f'stroke="{ACCENT}" stroke-opacity=".45"'),
        ring(170, f'stroke="{ACCENT}" stroke-dasharray="2 10"'),
        ring(148, f'stroke="{ACCENT}" stroke-opacity=".16" stroke-width="18" stroke-dasharray="58 8"'),
        ring(124, f'stroke="{ACCENT}" stroke-width="1.5"'),
        f'<circle class="spin" cx="{cx}" cy="{cy}" r="108" fill="none" stroke="{SIGNAL}" '
        'stroke-width="7" stroke-dasharray="1.5 12.637"/>',
        ring(86, f'stroke="{ACCENT}" stroke-width="3" stroke-dasharray="150 120"'),
        f'<path d="M{cx - 200} {cy}h112M{cx + 88} {cy}h112" stroke="{ACCENT}" stroke-opacity=".45"/>',
        f'<circle cx="{cx}" cy="{cy}" r="56" fill="{ACCENT}"/>',
        ring(44, f'stroke="{BG}" stroke-width="2" stroke-dasharray="3 6"'),
        ring(33, f'stroke="{BG}"'),
        f'<path d="M{cx} {cy - 50}Q{cx + 24} {cy} {cx} {cy + 50}Q{cx - 24} {cy} {cx} {cy - 50}Z" fill="{BG}"/>',
        f'<rect x="{cx + 14}" y="{cy - 28}" width="8" height="8" fill="{BONE}"/>',
    ])


# ---------------------------------------------------------------- panels

def hero(data):
    word = CONFIG["wordmark"]
    svg = Svg(848, 448, f'{word} - {CONFIG["tagline"]}. {CONFIG["about"]}')
    outline = chamfer(0.5, 0.5, 847, 447, 24)
    svg.add(f'<clipPath id="panel"><polygon points="{outline}"/></clipPath>'
            '<clipPath id="main"><rect x="1" y="41" width="846" height="327"/></clipPath>'
            f'<polygon points="{outline}" fill="{BG}"/><g clip-path="url(#panel)">')

    # status strip
    svg.add(f'<rect class="blink" x="36" y="16" width="8" height="8" fill="{ACCENT}"/>')
    svg.text(54, 24, [("SESSION START", BONE), (" // ", ACCENT), (f"{USER.upper()}@GITHUB", MUTED)], 11, ls=0.16)
    svg.text(760, 24, CONFIG["strapline"], 11, ls=0.16, anchor="end")
    svg.add(f'<rect x="772" y="16" width="44" height="8" fill="url(#hz)"/><path d="M0 40.5H848" stroke="{LINE}"/>')

    # eye and wordmark
    svg.add('<g clip-path="url(#main)"><rect x="1" y="41" width="846" height="327" fill="url(#dots)"/>'
            + eye(690, 124)
            + f'<rect class="sweep" x="1" y="41" width="846" height="1" fill="{ACCENT}" fill-opacity=".45"/></g>')
    svg.text(36, 77, [("> ", SIGNAL), (CONFIG["caption"], MUTED)], 11, ls=0.16)

    kana = CONFIG.get("kana", "")
    uid_x = 36
    if kana:
        svg.text(36, 158, kana, 24, "kana", 400, ACCENT)
        rule = 36 + len(kana) * 24 + 14
        svg.add(f'<path d="M{rule} 149.5h40" stroke="{ACCENT}" stroke-opacity=".45"/>')
        uid_x = rule + 54
    svg.text(uid_x, 153, f'UID {data["uid"]}', 11, ls=0.16)

    # Two thin cuts through the letters; the torn band only shows while the glitch plays.
    size = fit(word, 112, 776)
    width = len(word) * size * DISP_EM
    left, right = 36 + width * 0.3, 36 + width * 0.58
    svg.add('<clipPath id="keep"><rect y="140" width="848" height="74"/>'
            f'<rect x="{num(left)}" y="214" width="848" height="3"/><rect y="217" width="848" height="28"/>'
            f'<rect y="245" width="{num(right)}" height="3"/><rect y="248" width="848" height="70"/></clipPath>'
            '<clipPath id="tear"><rect y="222" width="848" height="12"/></clipPath>'
            '<clipPath id="low"><rect y="239" width="848" height="20"/></clipPath>')
    svg.text(31, 265, word, size, "disp", 900, ACCENT, ls=0.01, cls="ga")
    svg.add('<g clip-path="url(#low)">')
    svg.text(41, 265, word, size, "disp", 900, SIGNAL, ls=0.01)
    svg.add('</g><g clip-path="url(#keep)">')
    svg.text(36, 265, word, size, "disp", 900, BONE, ls=0.01)
    svg.add('</g><g clip-path="url(#tear)">')
    svg.text(36, 265, word, size, "disp", 900, ACCENT, ls=0.01, cls="gc")
    svg.add("</g>")

    svg.text(36, 303, CONFIG["tagline"], 15, fill=SIGNAL, ls=0.04)
    svg.text(36, 332, CONFIG["about"], 13.5)

    # stat strip
    cells = [(data["repos"], "PUBLIC REPOS", BONE), (data["stars"], "STARS EARNED", BONE),
             (data["followers"], "FOLLOWERS", BONE)]
    if data["contributions"] is not None:
        cells.append((data["contributions"], "CONTRIBUTIONS · 12 MO", SIGNAL))
    svg.add(f'<path d="M0 368.5H848" stroke="{LINE}"/>')
    width = 846 / len(cells)
    for i, (value, label, color) in enumerate(cells):
        x = 1 + i * width
        if i:
            svg.add(f'<path d="M{num(x)} 369V448" stroke="{LINE}"/>')
        x += 22 if i else 36
        svg.text(x, 407, f"{value:,}", 30, "disp", 700, color)
        svg.text(x, 428, label, 10.5, ls=0.14)

    svg.add(f'<rect width="848" height="448" fill="url(#scan)"/></g>'
            f'<polygon points="{outline}" fill="none" stroke="{LINE2}"/>')
    return svg


def link_button(label, right, icon_name, kind):
    fill, stroke, color, dim = {
        "solid": (ACCENT, ACCENT, BG, BG),
        "plain": (BG, LINE2, BONE, MUTED),
        "signal": (BG, SIGNAL, SIGNAL, SIGNAL),
    }[kind]
    svg = Svg(272, 56, label.title())
    svg.add(panel(272, 56, 12, stroke=stroke, fill=fill) + icon(icon_name, 20, 19, color))
    svg.text(50, 33, label, 15, "disp", 700, color, ls=0.1)
    svg.text(222, 32, str(right), 12, fill=dim, ls=0.08, anchor="end")
    svg.add(icon("arrow", 234, 19, color))
    return svg


def now_building(repo):
    svg = Svg(848, 232, f'Now building: {repo["name"]} - {repo["description"] or ""}')
    heading(svg, "01", "NOW BUILDING", "LATEST PUSH")
    svg.add(panel(848, 184, 16, y=48, stroke=LINE2))

    tags = [t.upper() for t in repo["topics"]][:3] or [(repo["language"] or "repository").upper()]
    while len(tags) > 1 and len(" // ".join(tags)) > 44:
        tags.pop()
    svg.add(f'<rect class="blink" x="32" y="73" width="8" height="8" fill="{SIGNAL}"/>')
    svg.text(50, 81, " // ".join(tags), 11, fill=SIGNAL, ls=0.16)
    svg.add(icon("arrow", 498, 70, ACCENT))
    svg.text(32, 135, repo["name"], fit(repo["name"], 46, 480), "disp", 700, BONE)
    for i, line in enumerate(wrap(repo["description"], 57, 3)):
        svg.text(32, 160 + i * 20, line, 13)

    rows = [("LANGUAGE", repo["language"] or "—"), ("CREATED", date(repo["created_at"])),
            ("LAST PUSH", date(repo["pushed_at"])), ("STARS", repo["stargazers_count"])]
    svg.add(f'<path d="M548.5 49V231" stroke="{LINE}"/>')
    for i, (label, value) in enumerate(rows):
        y = 68 + i * 36
        if i:
            svg.add(f'<path d="M576 {y}.5H816" stroke="{LINE}"/>')
        svg.text(576, y + 22, label, 10.5, ls=0.14)
        svg.text(816, y + 22, str(value), 12, fill=BONE, anchor="end")
    return svg


def section_heading(number, title, caption):
    svg = Svg(848, 40, title.title())
    heading(svg, number, title, caption)
    return svg


def featured_card(index, repo):
    """One featured project. Every field comes from the GitHub API."""
    color = ACCENT if index % 4 in (0, 3) else SIGNAL
    svg = Svg(416, 172, f'{repo["name"]} - {repo["description"] or repo["language"] or "repository"}')
    svg.add(panel(416, 172, 14) + f'<rect x="22" width="44" height="3" fill="{color}"/>')

    kicker = [(f"{index + 1:02d}", color)]
    if repo["language"]:
        kicker.append((f"  {repo['language'].upper()}", MUTED))
    if repo["fork"]:
        kicker.append(("  // FORK", MUTED))
    if repo["owner"]["login"].lower() != USER.lower():
        kicker.append((f"  // {repo['owner']['login'].upper()}", MUTED))
    svg.text(22, 32, kicker, 10.5, ls=0.14)
    if repo["stargazers_count"]:
        count = f'{repo["stargazers_count"]:,}'
        svg.text(394, 32, count, 12, fill=BONE, anchor="end")
        svg.add(star(394 - mono_w(count, 12) - 18, 21))

    svg.text(22, 71, repo["name"], fit(repo["name"], 24, 372), "disp", 700, BONE)
    for i, line in enumerate(wrap(repo["description"], 47, 2)):
        svg.text(22, 98 + i * 19, line, 13)

    x = 22
    for tag in [t.upper() for t in repo["topics"]]:
        width = mono_w(tag, 10.5, 0.1) + 16
        if x + width > 360:
            break
        svg.add(f'<rect x="{num(x + 0.5)}" y="132.5" width="{num(width - 1)}" height="21" fill="none" stroke="{LINE2}"/>')
        svg.text(x + 8, 147, tag, 10.5, fill=BONE, ls=0.1)
        x += width + 6
    svg.add(icon("arrow", 376, 134, color))
    return svg


def archive_row(repo):
    svg = Svg(848, 68, f'{repo["name"]} - {repo["description"] or ""}')
    svg.add(panel(848, 68, 12))
    name_y = 31 if repo["description"] else 41
    svg.text(32, name_y, repo["name"], fit(repo["name"], 19, 560), "disp", 700, BONE)
    for line in wrap(repo["description"], 84, 1):
        svg.text(32, 51, line, 12.5)
    count = f'{repo["stargazers_count"]:,}'
    svg.text(816, 39, count, 13, fill=SIGNAL, anchor="end")
    star_x = 816 - mono_w(count, 13) - 19
    svg.add(star(star_x, 28))
    if repo["language"]:
        svg.text(star_x - 18, 38, repo["language"].upper(), 10.5, ls=0.14, anchor="end")
    return svg


def archive_all(total):
    label = f"VIEW ALL {total} REPOSITORIES"
    svg = Svg(848, 52, label.title())
    svg.add(panel(848, 52, 12))
    svg.text(32, 31, label, 14, "disp", 700, ACCENT, ls=0.12)
    svg.add(icon("arrow", 798, 17, ACCENT))
    return svg


def stack(data):
    names = CONFIG["stack"]
    rows = -(-len(names) // 5)
    height = 132 + rows * 60 + (rows - 1) * 12 + 28
    svg = Svg(848, 48 + height, "Stack: " + ", ".join(names))
    heading(svg, "04", "STACK", "LANGUAGES // TOOLS")
    svg.add(panel(848, height, 16, y=48))

    langs = data["languages"]
    shown = langs if len(langs) <= 5 else langs[:4] + [("Other", sum(n for _, n in langs[4:]))]
    total = sum(n for _, n in shown) or 1
    svg.text(32, 88, "PRIMARY LANGUAGE BY REPO", 11, ls=0.16)
    svg.text(816, 88, f'{data["sources"]} REPOS // FORKS EXCLUDED', 11, ls=0.16, anchor="end")
    fills = [ACCENT, SIGNAL, BONE, "url(#hatch)", GREY]
    room, x, legend = 784 - 3 * (len(shown) - 1), 32.0, 32.0
    for (name, count), fill in zip(shown, fills):
        width = room * count / total
        outline = f' stroke="{ACCENT}"' if fill.startswith("url") else ""
        svg.add(f'<rect x="{num(x + 0.5)}" y="104.5" width="{num(width - 1)}" height="21" fill="{fill}"{outline}/>'
                f'<rect x="{num(legend + 0.5)}" y="138.5" width="8" height="8" fill="{fill}"{outline}/>')
        x += width + 3
        label = [(name.upper(), BONE), (f" {count:02d}", MUTED)]
        svg.text(legend + 15, 147, label, 11, ls=0.08)
        legend += 15 + mono_w(name + f" {count:02d}", 11, 0.08) + 24

    tile = (784 - 4 * 12) / 5
    for i, name in enumerate(names):
        tx, ty = 32 + (i % 5) * (tile + 12), 180 + (i // 5) * 72
        svg.add(f'<rect x="{num(tx + 0.5)}" y="{ty}.5" width="{num(tile - 1)}" height="59" fill="{RAISED}" stroke="{LINE}"/>')
        svg.text(tx + 14, ty + 22, f"{i + 1:02d}", 10.5, ls=0.14)
        svg.text(tx + 14, ty + 45, name.upper(), fit(name, 16, tile - 26), "disp", 700, BONE)
    return svg


def footer():
    lines = CONFIG["signoff"]
    svg = Svg(848, 252, " ".join(lines))
    outline = chamfer(0.5, 0.5, 847, 251, 24)
    svg.add(f'<clipPath id="panel"><polygon points="{outline}"/></clipPath><polygon points="{outline}" fill="{BG}"/>')
    for i, (label, percent) in enumerate(CONFIG["meters"][:2]):
        x, color = 36 + i * 404, (ACCENT, SIGNAL)[i]
        svg.text(x, 40, label, 11, ls=0.16)
        svg.text(x + 372, 40, f"{percent}%", 11, fill=color, ls=0.16, anchor="end")
        svg.add(f'<rect x="{x}" y="52" width="372" height="8" fill="{TRACK}"/>'
                f'<rect x="{x}" y="52" width="{num(372 * min(percent, 100) / 100)}" height="8" fill="{color}"/>')
    size = min(fit(line, 36, 776) for line in lines)
    for i, line in enumerate(lines[:2]):
        svg.text(36, 124 + i * 42, line, size, "disp", 700, ACCENT if i else BONE, ls=0.01)
    svg.text(36, 222, CONFIG["footnote"], 11, ls=0.16)
    svg.add('<rect x="680" y="208" width="120" height="16" fill="url(#bars)"/>'
            '<rect width="848" height="252" fill="url(#scan)" clip-path="url(#panel)"/>'
            f'<polygon points="{outline}" fill="none" stroke="{LINE2}"/>')
    return svg


# ---------------------------------------------------------------- README

START, END = "<!-- profile:start -->", "<!-- profile:end -->"


def build():
    data = load_data()
    files, blocks = {}, []

    def img(name, svg, width, href=None):
        files[name] = svg.render()
        tag = f'<img src="assets/profile/{name}" width="{width}" alt="{esc(svg.label)}">'
        return f'<a href="{esc(href)}">{tag}</a>' if href else tag

    def block(*images):
        blocks.append('<p align="center">\n  ' + "\n  ".join(images) + "\n</p>")

    home = f"https://github.com/{USER}"
    block(img("hero.svg", hero(data), "100%"))
    links = [img("link-repositories.svg", link_button("REPOSITORIES", data["repos"], "repo", "solid"),
                 "32%", home + "?tab=repositories"),
             img("link-followers.svg", link_button("FOLLOWERS", data["followers"], "people", "plain"),
                 "32%", home + "?tab=followers")]
    if CONFIG.get("kofi"):
        links.append(img("link-kofi.svg", link_button("KO-FI", "SUPPORT", "cup", "signal"), "32%", CONFIG["kofi"]))
    block(*links)

    if data["now"]:
        block(img("now-building.svg", now_building(data["now"]), "100%", data["now"]["html_url"]))

    featured = data["featured"]
    if featured:
        caption = f"{len(featured):02d} SELECTED"
        block(img("heading-featured.svg", section_heading("02", "FEATURED PROJECTS", caption), "100%"),
              *(img(f"featured-{i + 1}.svg", featured_card(i, repo), "49%", repo["html_url"])
                for i, repo in enumerate(featured)))

    if data["archive"]:
        block(img("heading-archive.svg", section_heading("03", "FROM THE ARCHIVE", "BY STARS"), "100%"),
              *(img(f"archive-{i + 1}.svg", archive_row(repo), "100%", repo["html_url"])
                for i, repo in enumerate(data["archive"])),
              img("archive-all.svg", archive_all(data["repos"]), "100%", home + "?tab=repositories"))

    block(img("stack.svg", stack(data), "100%"))
    block(img("footer.svg", footer(), "100%"))

    OUT.mkdir(parents=True, exist_ok=True)
    for stale in OUT.glob("*.svg"):
        if stale.name not in files:
            stale.unlink()
    for name, content in files.items():
        (OUT / name).write_text(content, encoding="utf-8", newline="\n")

    generated = (f"{START}\n<!-- Generated by scripts/build_profile.py. Edit profile.config.json, not this block. -->\n"
                 + "\n\n".join(blocks) + f"\n{END}")
    readme = ROOT / "README.md"
    current = readme.read_text(encoding="utf-8") if readme.exists() else ""
    if START in current and END in current:
        generated = current[:current.index(START)] + generated + current[current.index(END) + len(END):]
    else:
        generated += "\n"
    readme.write_text(generated, encoding="utf-8", newline="\n")
    print(f"Built {len(files)} panels for {USER}: {len(featured)} featured, "
          f'now building {data["now"]["name"] if data["now"] else "nothing"}.')


if __name__ == "__main__":
    build()
