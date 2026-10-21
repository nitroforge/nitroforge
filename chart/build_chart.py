"""Builds the still 3D commit chart (dark + light) for the profile README.

Reads commits of the repos listed in REPOS from the GitHub API, groups them per day
for the last 10 weeks and renders them with three.js in a headless Chromium.
Usage:  python chart/build_chart.py            (uses GITHUB_TOKEN)
        python chart/build_chart.py --data x.json   (skip the API, use ready cells)
Env:    REPOS   comma list, default nitroforge/NitroLauncher,nitroforge/Nitropack
        OUT_DIR where the .webp files go, default "assets"
"""
import datetime as dt, json, math, os, shutil, sys, threading, functools, http.server, urllib.request, urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPOS = [r.strip() for r in os.environ.get("REPOS", "nitroforge/NitroLauncher,nitroforge/Nitropack").split(",") if r.strip()]
OUT = Path(os.environ.get("OUT_DIR", "assets"))
WEEKS = 10

def window(today=None):
    today = today or dt.datetime.now(dt.timezone.utc).date()
    monday = today - dt.timedelta(days=today.weekday())
    return monday - dt.timedelta(weeks=WEEKS - 1)

def api(url, token):
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "profile-chart", **({"Authorization": f"Bearer {token}"} if token else {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)

def count_commits(repos, start, token, fetch=api):
    counts = {}
    since = dt.datetime.combine(start, dt.time.min).isoformat() + "Z"
    for repo in repos:
        page = 1
        while True:
            q = urllib.parse.urlencode({"since": since, "per_page": 100, "page": page})
            items = fetch(f"https://api.github.com/repos/{repo}/commits?{q}", token)
            for c in items:
                day = c["commit"]["author"]["date"][:10]
                counts[day] = counts.get(day, 0) + 1
            if len(items) < 100:
                break
            page += 1
    return counts

def cells_from(counts, start):
    cells = []
    for w in range(WEEKS):
        for d in range(7):
            day = start + dt.timedelta(days=w * 7 + d)
            cells.append({"w": w, "d": d, "n": counts.get(day.isoformat(), 0), "date": day.isoformat()})
    return cells

def render(cells, frames=1):
    from playwright.sync_api import sync_playwright
    from PIL import Image
    three = HERE / "node_modules" / "three" / "build" / "three.module.js"
    shutil.copy(three, HERE / "three.module.js")
    (HERE / "cal.json").write_text(json.dumps(cells))
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(HERE))
    handler.log_message = lambda *a: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--no-sandbox", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
        for theme in ("dark", "light"):
            pg = b.new_page(viewport={"width": 1200, "height": 560})
            pg.goto(f"http://127.0.0.1:{port}/cal.html?t={theme}")
            pg.wait_for_function("window.__done===true", timeout=60000)
            imgs = []
            tmp = HERE / "_frame.png"
            for i in range(frames):
                pg.evaluate(f"setAngle({-0.25 + 0.22 * math.sin(2 * math.pi * i / frames)})")
                pg.wait_for_timeout(60)
                pg.screenshot(path=str(tmp), omit_background=True)
                imgs.append(Image.open(tmp).convert("RGBA"))
            out = OUT / f"pushes-{theme}.webp"
            imgs[0].save(out, save_all=True, append_images=imgs[1:], duration=80, loop=0, quality=82, method=4)
            print("wrote", out, round(out.stat().st_size / 1e6, 2), "MB")
        b.close()
    for f in ("three.module.js", "cal.json", "_frame.png"):
        (HERE / f).unlink(missing_ok=True)

if __name__ == "__main__":
    start = window()
    if "--data" in sys.argv:
        cells = json.loads(Path(sys.argv[sys.argv.index("--data") + 1]).read_text())
    else:
        cells = cells_from(count_commits(REPOS, start, os.environ.get("GITHUB_TOKEN")), start)
    print("commits in window:", sum(c["n"] for c in cells))
    render(cells)
