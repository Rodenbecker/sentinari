import re
from pathlib import Path

for fname in ["index.html", "oncology.html", "threats.html"]:
    fpath = Path(r"D:\Sentinari\docs") / fname
    if not fpath.exists():
        continue
    content = fpath.read_text(encoding="utf-8")
    hrefs = sorted(list(set(re.findall(r'href=["\'](.*?)["\']', content))))
    print(f"\n=== {fname} ({len(hrefs)} unique hrefs) ===")
    for h in hrefs:
        if not h.startswith("http") and not h.startswith("#"):
            print(f"  {h}")
