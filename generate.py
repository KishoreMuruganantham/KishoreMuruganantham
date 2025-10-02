#!/usr/bin/env python3
"""
Regenerates dark_mode.svg and light_mode.svg for the profile README.

Layout is a fake `neofetch` readout: ASCII portrait on the left,
key/value stats block on the right.  Everything numeric is computed
live from the GitHub API so the card never goes stale.

Usage:  python generate.py            (uses $GITHUB_TOKEN or `gh auth token`)
"""
import datetime as dt
import html
import io
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

from PIL import Image, ImageEnhance, ImageOps

# ---------------------------------------------------------------- config ----
USERNAME = "KishoreMuruganantham"
HEADER = "@KishoreMuruganantham"
DOB = dt.date(2004, 6, 17)
ACCOUNT_CREATED = dt.date(2023, 5, 12)

CARD_W, CARD_H = 985, 550
ART_X, ART_Y = 15, 30
PANEL_X = 390
LINE_H = 20
FONT_SIZE = 16
CHAR_W = FONT_SIZE * 0.5993         # rendered advance (Consolas + size-adjust 109%)
COLS, ROWS = 39, 26
VALUE_COL = 26                      # column where values start
MAX_LINE = 60                       # keep every line inside the card
LANG_SHORT = {"Jupyter Notebook": "Jupyter", "TypeScript": "TS",
              "JavaScript": "JS", "C#": "C#"}

THEMES = {
    "dark": dict(bg="#161b22", text="#c9d1d9", key="#ffa657",
                 value="#a5d6ff", cc="#616e7f", add="#3fb950", dele="#f85149"),
    "light": dict(bg="#f6f8fa", text="#24292f", key="#953800",
                  value="#0a3069", cc="#c2cfde", add="#1a7f37", dele="#cf222e"),
}

# Ramp: index 0 = darkest pixel.  We map *dark pixels to dense glyphs*, so the
# subject reads as ink and the background falls back to the card colour.
RAMP = "@%#*+=-:. "

# Non-personal panel content.  Dates/ages are derived, not hard-coded.
FIELDS = [
    "__HEADER__",
    ("OS", "Windows 11, Android 14, Linux"),
    ("__UPTIME__", ""),
    ("__MEMBER__", ""),
    ("Shell", "PowerShell, Bash"),
    ("IDE", "IntelliJ IDEA, VS Code"),
    "__BLANK__",
    ("Lang.Programming", "Python, Java, C++, SQL, TypeScript"),
    ("Lang.Computer", "HTML, CSS, JSON, YAML"),
    ("Lang.Spoken", "English, Tamil, Hindi"),
    "__BLANK__",
    ("Hobbies", "Hackathons, Competitive Coding, ML"),
    "__BLANK__",
    "__SECTION__:Notable Awards",
    ("SIH 2024", "1st Place, Ministry of Education"),
    ("Kaggle HeatCode", "1st Place"),
    "__BLANK__",
    "__SECTION__:Contact",
    ("Email", "kishore.muruganantham@gmail.com"),
    ("LinkedIn", "kishore-m-13a7402a7"),
    "__BLANK__",
    "__SECTION__:GitHub Stats",
    "__STATS_REPOS__",
    "__STATS_COMMITS__",
    "__STATS_LOC__",
    "__STATS_LANG__",
]


# ------------------------------------------------------------------ api -----
def _token():
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if tok:
        return tok
    try:
        return subprocess.run(["gh", "auth", "token"], capture_output=True,
                              text=True, timeout=30).stdout.strip()
    except Exception:
        return ""


TOKEN = _token()


def api_get(path, retries=4):
    for attempt in range(retries):
        req = urllib.request.Request(
            "https://api.github.com" + path,
            headers={"Authorization": "Bearer " + TOKEN,
                     "Accept": "application/vnd.github+json",
                     "User-Agent": "profile-readme"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                body = r.read()
            if body.strip():
                return json.loads(body)
        except urllib.error.HTTPError as e:
            if e.code not in (202, 409, 503):
                return None
        except Exception:
            pass
        time.sleep(2.5 * (attempt + 1))
    return None


def graphql(query):
    data = json.dumps({"query": query}).encode()
    req = urllib.request.Request(
        "https://api.github.com/graphql", data=data,
        headers={"Authorization": "Bearer " + TOKEN,
                 "Accept": "application/vnd.github+json",
                 "User-Agent": "profile-readme"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def _split_months(birth, today):
    y = today.year - birth.year
    m = today.month - birth.month
    d = today.day - birth.day
    if d < 0:
        prev = today.replace(day=1) - dt.timedelta(days=1)
        d += prev.day
        m -= 1
    if m < 0:
        m += 12
        y -= 1
    parts = []
    for n, word in ((y, "year"), (m, "month"), (d, "day")):
        if n or not parts:
            parts.append(f"{n} {word}{'s' if n != 1 else ''}")
    return ", ".join(parts)


def fetch_stats():
    today = dt.date.today()
    q = ('{ user(login: "%s") { '
         '  repositories(first: 100, ownerAffiliations: OWNER, privacy: PUBLIC) '
         '  { totalCount nodes { stargazerCount '
         '      languages(first: 6, orderBy: {field: SIZE, direction: DESC}) '
         '      { edges { size node { name color } } } } } '
         '  contributionsCollection(from: "%s", to: "%s") '
         '  { totalCommitContributions contributionCalendar { totalContributions } } '
         '} }' % (USERNAME, (today - dt.timedelta(days=365)).isoformat() + "T00:00:00Z",
                  today.isoformat() + "T23:59:59Z"))
    user = graphql(q)["data"]["user"]
    repos = user["repositories"]
    stats = {
        "repos": repos["totalCount"],
        "stars": sum(n["stargazerCount"] for n in repos["nodes"]),
        "uptime": _split_months(DOB, today),
        "member_since": ACCOUNT_CREATED.strftime("%d %b %Y"),
    }

    # aggregate bytes-per-language across every public repo -> top 3
    agg = {}
    for n in repos["nodes"]:
        for e in (n.get("languages") or {}).get("edges") or []:
            name = e["node"]["name"]
            size, color = agg.get(name, (0, e["node"]["color"]))
            agg[name] = (size + e["size"], color)
    total = sum(v[0] for v in agg.values()) or 1
    stats["languages"] = [
        {"name": k, "pct": round(v[0] / total * 100), "color": v[1]}
        for k, v in sorted(agg.items(), key=lambda kv: -kv[1][0])[:3]
    ]

    # lifetime totals: walk non-overlapping <= 1yr windows back to account creation
    total_contrib = total_commits = 0
    start = ACCOUNT_CREATED
    while start < today:
        end = min(start + dt.timedelta(days=364), today)
        wq = ('{ user(login: "%s") { contributionsCollection(from: "%s", to: "%s") '
              '{ totalCommitContributions '
              '  contributionCalendar { totalContributions } } } }'
              % (USERNAME, start.isoformat() + "T00:00:00Z",
                 end.isoformat() + "T23:59:59Z"))
        try:
            c = graphql(wq)["data"]["user"]["contributionsCollection"]
            total_contrib += c["contributionCalendar"]["totalContributions"]
            total_commits += c["totalCommitContributions"]
        except Exception:
            pass
        start = end + dt.timedelta(days=1)
    stats["contributions"] = total_contrib
    stats["commits"] = total_commits

    # followers
    u = api_get(f"/users/{USERNAME}") or {}
    stats["followers"] = u.get("followers", 0)

    # lines of code: stats/code_frequency is computed lazily (HTTP 202), retry
    add = dele = 0
    for repo in repos["nodes"]:
        pass
    names = api_get(f"/users/{USERNAME}/repos?per_page=100&type=owner") or []
    for r in names:
        freq = api_get(f"/repos/{USERNAME}/{r['name']}/stats/code_frequency")
        if not isinstance(freq, list):
            continue
        for row in freq:
            if isinstance(row, list) and len(row) == 3:
                add += row[1]
                dele += abs(row[2])
    stats["additions"] = add
    stats["deletions"] = dele
    stats["net"] = add - dele
    return stats


def avatar_image():
    u = api_get(f"/users/{USERNAME}") or {}
    url = u.get("avatar_url") or f"https://avatars.githubusercontent.com/u/133372253?v=4"
    req = urllib.request.Request(url, headers={"User-Agent": "profile-readme"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return Image.open(io.BytesIO(r.read()))


# ------------------------------------------------------------------ art -----
def _aspect_crop(im, aspect):
    """Centre-crop so the box matches the panel's visual aspect."""
    w, h = im.size
    if w / h > aspect:
        nw, nh = int(round(h * aspect)), h
        return im.crop(((w - nw) // 2, 0, (w - nw) // 2 + nw, nh))
    nw, nh = w, int(round(w / aspect))
    return im.crop((0, (h - nh) // 2, nw, (h - nh) // 2 + nh))


def ascii_art(img, cols=COLS, rows=ROWS):
    """Crop the portrait to the panel aspect, then sample to a character grid.

    The wall behind the subject is a flat mid-grey, so its luminance is
    measured from the top edge of the photo and anything within tolerance
    of it is left blank -- the subject is drawn, the background is not.

    The crop window is then panned down to the top of the head so there is
    no dead band of empty rows above him.
    """
    aspect = (cols * CHAR_W) / (rows * LINE_H)
    w, h = img.size

    lum = img.convert("L")
    sp = lum.load()

    x0, x1 = int(w * 0.16), int(w * 0.86)
    edge = sorted(sp[x, 0] for x in range(x0, x1))
    bg = edge[len(edge) // 2]
    spread = sorted(abs(sp[x, 0] - bg) for x in range(x0, x1))
    tol = max(24, spread[len(spread) // 2] * 3)

    # first row of the head -- pan the window so he starts flush at row 0
    top = 0
    step = max(1, (x1 - x0) // 100)
    for yy in range(h):
        hits = sum(1 for x in range(x0, x1, step) if abs(sp[x, yy] - bg) > tol)
        if hits >= 4:
            top = yy
            break

    box_h = int(h * 0.74)
    y0, y1 = top, top + box_h
    if y1 > h:
        y1 = h
        y0 = max(0, y1 - box_h)

    im = _aspect_crop(img.crop((x0, y0, x1, y1)), aspect)
    g = ImageEnhance.Contrast(im.convert("L")).enhance(1.15)
    g = g.resize((cols, rows), Image.LANCZOS)
    px = g.load()

    n = len(RAMP)
    lines = []
    for y in range(rows):
        row = []
        for x in range(cols):
            d = abs(px[x, y] - bg)
            if d <= tol:
                row.append(" ")
                continue
            s = min(1.0, (d - tol) / 85.0)   # 0 = faint, 1 = solid
            row.append(RAMP[int(round((1 - s) * (n - 1)))])
        lines.append("".join(row))
    return _centre(lines, cols)


def _centre(lines, cols):
    """Shift the portrait horizontally so the ink sits in the middle of the
    panel instead of hugging the left edge."""
    ink = [x for x in range(cols)
           if any(len(l) > x and l[x].strip() for l in lines)]
    if not ink:
        return lines
    shift = ((cols - 1) - (min(ink) + max(ink))) // 2
    if not shift:
        return lines
    out = []
    for l in lines:
        l = l.ljust(cols)
        if shift > 0:
            out.append(" " * shift + l[:cols - shift])
        else:
            out.append(l[-shift:] + " " * -shift)
    return out


# --------------------------------------------------------------- panel ------
def dashes(prefix, total=MAX_LINE):
    """A dashed rule that finishes the header/section line."""
    n = max(0, total - len(prefix))
    if n < 4:
        return ""
    return "-" + "—" * (n - 4) + "-—-"


def field(key, value):
    prefix = ". " + key + ":"
    n = max(0, VALUE_COL - len(prefix) - 2)
    filler = " " + "." * n + " "
    assert len(prefix) + len(filler) <= VALUE_COL, key
    return [(". ", "cc"), (key, "key"), (":", None),
            (filler, "cc"), (value, "value")]


def build_rows(s):
    out = []
    for item in FIELDS:
        if item == "__BLANK__":
            out.append([(". ", "cc")])
        elif item == "__HEADER__":
            out.append([(HEADER, None), (dashes(HEADER), None)])
        elif isinstance(item, str) and item.startswith("__SECTION__:"):
            t = "- " + item.split(":", 1)[1]
            out.append([(t, None), (dashes(t), None)])
        elif isinstance(item, tuple) and item[0] == "__UPTIME__":
            out.append(field("Uptime", s["uptime"]))
        elif isinstance(item, tuple) and item[0] == "__MEMBER__":
            out.append(field("Member Since", s["member_since"]))
        elif item == "__STATS_REPOS__":
            out.append([
                (". ", "cc"), ("Repos", "key"), (":", None),
                (" " + "." * (VALUE_COL - 8 - 2) + " ", "cc"),
                (str(s["repos"]), "value"), (" | ", "cc"),
                ("Stars", "key"), (":", None), (" ", "cc"),
                (str(s["stars"]), "value"), (" | ", None),
                ("Followers", "key"), (":", None), (" ", "cc"),
                (str(s["followers"]), "value"),
            ])
        elif item == "__STATS_COMMITS__":
            out.append([
                (". ", "cc"), ("Commits", "key"), (":", None),
                (" " + "." * (VALUE_COL - 10 - 2) + " ", "cc"),
                (f"{s['commits']:,}", "value"), (" | ", None),
                ("Contributions", "key"), (":", None), (" ", "cc"),
                (f"{s['contributions']:,}", "value"),
            ])
        elif item == "__STATS_LOC__":
            out.append([
                (". ", "cc"), ("Lines of Code", "key"), (":", None),
                (" " + "." * (VALUE_COL - 16 - 2) + " ", "cc"),
                (f"{s['net']:,}", "value"), (" (", None),
                (f"{s['additions']/1e6:.1f}M", "add"), ("++", "add"),
                (", ", None),
                (f"{s['deletions']/1e6:.1f}M", "dele"), ("--", "dele"),
                (")", None),
            ])
        elif item == "__STATS_LANG__":
            pre = 2 + len("Languages") + 1          # ". Languages:"
            spans = [(". ", "cc"), ("Languages", "key"), (":", None),
                     (" " + "." * (VALUE_COL - pre - 2) + " ", "cc")]
            langs = s.get("languages") or []
            if not langs:
                spans.append(("\u2014", "value"))
            for i, L in enumerate(langs):
                if i:
                    spans.append((" | ", "cc"))
                nm = LANG_SHORT.get(L["name"], L["name"])
                spans.append((f"{nm} {L['pct']}%", L["color"]))
            out.append(spans)
        else:
            out.append(field(*item))

    assert len(out) == ROWS, f"expected {ROWS} rows, got {len(out)}"
    return out


def xml(s):
    return html.escape(s, quote=False)


def render(mode, art, rows):
    t = THEMES[mode]
    p = []
    p.append("<?xml version='1.0' encoding='UTF-8'?>")
    p.append(f'<svg xmlns="http://www.w3.org/2000/svg" '
             f'font-family="ConsolasFallback,Consolas,monospace" '
             f'width="{CARD_W}px" height="{CARD_H}px" font-size="{FONT_SIZE}px">')
    p.append("<style>")
    p.append("@font-face {src: local('Consolas'), local('Consolas Bold');"
             "font-family: 'ConsolasFallback';font-display: swap;"
             "-webkit-size-adjust: 109%;size-adjust: 109%;}")
    p.append(f".key {{fill: {t['key']};}}")
    p.append(f".value {{fill: {t['value']};}}")
    p.append(f".addColor {{fill: {t['add']};}}")
    p.append(f".delColor {{fill: {t['dele']};}}")
    p.append(f".cc {{fill: {t['cc']};}}")
    p.append("text, tspan {white-space: pre;}")
    p.append("</style>")
    p.append(f'<rect width="{CARD_W}px" height="{CARD_H}px" fill="{t["bg"]}" rx="15"/>')

    # ASCII portrait
    p.append(f'<text x="{ART_X}" y="{ART_Y}" fill="{t["text"]}" class="ascii">')
    for i, line in enumerate(art):
        y = ART_Y + i * LINE_H
        p.append(f'<tspan x="{ART_X}" y="{y}">{xml(line.rstrip())}</tspan>')
    p.append("</text>")

    # stat block
    p.append(f'<text x="{PANEL_X}" y="{ART_Y}" fill="{t["text"]}">')
    for i, spans in enumerate(rows):
        y = ART_Y + i * LINE_H
        chunk = [f'<tspan x="{PANEL_X}" y="{y}">']
        first = True
        for text, cls in spans:
            if not text:
                continue
            esc = xml(text)
            if first:
                chunk.append(esc)
                first = False
            elif cls:
                if cls.startswith("#"):
                    chunk.append(f'<tspan fill="{cls}">{esc}</tspan>')
                    continue
                css = {"add": "addColor", "dele": "delColor"}.get(cls, cls)
                chunk.append(f'<tspan class="{css}">{esc}</tspan>')
            else:
                chunk.append(esc)
        chunk.append("</tspan>")
        p.append("".join(chunk))
    p.append("</text>")
    p.append("</svg>")
    return "\n".join(p) + "\n"


def main():
    cache = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stats.json")
    if "--cached" in sys.argv and os.path.exists(cache):
        with open(cache, encoding="utf-8") as f:
            stats = json.load(f)
    else:
        stats = fetch_stats()
        with open(cache, "w", encoding="utf-8") as f:
            json.dump(stats, f, indent=2)
    art = ascii_art(avatar_image())
    for mode in ("dark", "light"):
        svg = render(mode, art, build_rows(stats))
        with open(f"{mode}_mode.svg", "w", encoding="utf-8", newline="\n") as f:
            f.write(svg)
        print(f"wrote {mode}_mode.svg", file=sys.stderr)
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
