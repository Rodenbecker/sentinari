import re
from pathlib import Path

docs_dir = Path(r"D:\Sentinari\docs")
for f in docs_dir.glob("*.html"):
    text = f.read_text(encoding="utf-8")
    matches = set(re.findall(r'href=["\'](/[^"\']*)["\']', text))
    if matches:
        print(f"File {f.name} has {len(matches)} root-relative links:")
        for m in sorted(matches):
            print(f"  {m}")
