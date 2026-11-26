import re
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

FILES = [
    "D:/Sentinari/docs/index.html",
    "D:/Sentinari/index.html",
    "D:/Sentinari/showcase_portal/index.html"
]

for p in FILES:
    print(f"Updating relative links in {p}...")
    with open(p, "r", encoding="utf-8") as f:
        html = f.read()

    # 1. Creative Studios Ribbon
    html = html.replace('href="http://127.0.0.1:8099/ui/ace-step"', 'href="./music.html"')
    html = html.replace('href="http://127.0.0.1:8099/ui/wan21"', 'href="./wan21.html"')
    html = html.replace('href="http://127.0.0.1:8099/ui/video"', 'href="./video.html"')
    html = html.replace('href="http://localhost:8000/ui/ace-step"', 'href="./music.html"')
    html = html.replace('href="http://localhost:8000/ui/wan21"', 'href="./wan21.html"')
    html = html.replace('href="http://localhost:8000/ui/video"', 'href="./video.html"')

    # 2. Qualia Lab & Pseudo Dynamics
    html = html.replace('href="http://127.0.0.1:8099/ui/qualia"', 'href="./qualia.html"')
    html = html.replace('href="http://localhost:8000/ui/qualia"', 'href="./qualia.html"')
    html = html.replace('href="/ui/qualia"', 'href="./qualia.html"')

    # 3. Floating FAB
    html = html.replace('href="http://127.0.0.1:8099/ui/video?workspace=playground"', 'href="./video.html"')
    html = html.replace('href="http://localhost:8000/ui/video?workspace=playground"', 'href="./video.html"')
    html = html.replace('href="/ui/video?workspace=playground"', 'href="./video.html"')

    # 4. Top Navigation Bar: ensure Qualia and Library are clickable directly in nav
    # Look for nav-links div
    old_nav = '<a href="javascript:void(0)" onclick="openPresentationModal(\'topology\')" style="color:#818cf8;font-weight:700;">&#x1F4D0; TDA Video</a>'
    new_nav = '<a href="./qualia.html" style="color:#a5b4fc;font-weight:700;">&#x2696;&#xFE0F; Qualia Lab</a>\n        <a href="./library.html" style="color:#38bdf8;font-weight:700;">&#x1F4DA; Library</a>\n        <a href="javascript:void(0)" onclick="openPresentationModal(\'topology\')" style="color:#818cf8;font-weight:700;">&#x1F4D0; TDA Video</a>'
    if old_nav in html and 'href="./qualia.html"' not in html.split(old_nav)[0]:
        html = html.replace(old_nav, new_nav, 1)

    # 5. Clean up any remaining localhost:8000
    html = html.replace("http://localhost:8000", "http://127.0.0.1:8099")

    with open(p, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  -> Successfully updated {p}")

