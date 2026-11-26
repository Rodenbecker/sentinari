import os
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

DOCS_UI = r"D:\Sentinari\docs\ui"

forwarders = {
    "qualia": "../../qualia.html",
    "library": "../../library.html",
    "search": "../../library.html",
    "video": "../../video.html",
    "music": "../../music.html",
    "ace-step": "../../music.html",
    "wan21": "../../wan21.html",
    "playground": "../../playground.html",
}

for folder, target in forwarders.items():
    fdir = os.path.join(DOCS_UI, folder)
    os.makedirs(fdir, exist_ok=True)
    html = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta http-equiv="refresh" content="0; url={target}">
  <title>Redirecting to {target}...</title>
  <script>window.location.replace('{target}');</script>
</head>
<body>
  <p>Redirecting to <a href="{target}">{target}</a>...</p>
</body>
</html>"""
    fpath = os.path.join(fdir, "index.html")
    with open(fpath, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Created forwarder {fpath} -> {target}")
