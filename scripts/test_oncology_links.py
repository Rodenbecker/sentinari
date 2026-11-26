import re
import urllib.request
from pathlib import Path

onc_text = Path(r"D:\Sentinari\docs\oncology.html").read_text(encoding="utf-8")
hrefs = sorted(list(set(re.findall(r'href=["\'](.*?)["\']', onc_text))))

print(f"Testing {len(hrefs)} links from oncology.html against GitHub Pages:")
base = "https://ongalali.github.io/sentinari/"

for h in hrefs:
    if h.startswith("http") or h.startswith("#") or h.startswith("javascript") or h.startswith("mailto") or "${" in h:
        continue
    if h.startswith("/"):
        target_url = "https://ongalali.github.io" + h
    else:
        clean_h = h.lstrip("./")
        target_url = base + clean_h
    try:
        req = urllib.request.Request(target_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            print(f"  [OK {resp.status}] {h}")
    except urllib.error.HTTPError as ex:
        print(f"  [FAIL {ex.code}] {h} -> {target_url}")
    except Exception as ex:
        print(f"  [ERR] {h} -> {ex}")
