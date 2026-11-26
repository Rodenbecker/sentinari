import re
import urllib.request
from pathlib import Path

index_text = Path(r"D:\Sentinari\docs\index.html").read_text(encoding="utf-8")
hrefs = sorted(list(set(re.findall(r'href=["\'](.*?)["\']', index_text))))

print(f"Testing {len(hrefs)} links from index.html against GitHub Pages:")
base = "https://ongalali.github.io/sentinari/"

for h in hrefs:
    if h.startswith("http") or h.startswith("#") or h.startswith("javascript") or h.startswith("mailto"):
        continue
    # resolve relative
    clean_h = h.lstrip("./")
    target_url = base + clean_h
    try:
        req = urllib.request.Request(target_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            print(f"  [OK {resp.status}] {clean_h}")
    except urllib.error.HTTPError as ex:
        print(f"  [FAIL {ex.code}] {clean_h} -> {target_url}")
    except Exception as ex:
        print(f"  [ERR] {clean_h} -> {ex}")
