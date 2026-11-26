"""
Download all remaining 3D STL files from PrintAnatomy.eu directly to E:\PrintAnatomy\models\
"""

import json
import os
import sys
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

CATALOG_PATH = Path(r"E:\PrintAnatomy\catalog.json")
MODELS_DIR = Path(r"E:\PrintAnatomy\models")
MODELS_DIR.mkdir(parents=True, exist_ok=True)

def download_stls():
    with open(CATALOG_PATH, "r", encoding="utf-8") as f:
        cases = json.load(f)

    downloaded = 0
    skipped = 0
    failed = 0

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://printanatomy.eu/"
    }

    for case in cases:
        stl_url = case.get("stl_url")
        stl_filename = case.get("stl_filename")
        if not stl_url or not stl_filename:
            continue

        clean_filename = stl_filename.replace("/", "_").replace("\\", "_")
        target_path = MODELS_DIR / clean_filename

        if target_path.exists() and target_path.stat().st_size > 1000:
            case["local_stl"] = f"models/{clean_filename}"
            skipped += 1
            continue

        print(f"Downloading {clean_filename} from {stl_url}...")
        try:
            req = urllib.request.Request(stl_url, headers=headers)
            with urllib.request.urlopen(req, timeout=45) as resp:
                data = resp.read()
                target_path.write_bytes(data)
                case["local_stl"] = f"models/{clean_filename}"
                downloaded += 1
                print(f" -> Saved {clean_filename} ({len(data)} bytes)")
        except Exception as ex:
            print(f" -> Failed {clean_filename}: {ex}")
            failed += 1

    # Save updated catalog
    with open(CATALOG_PATH, "w", encoding="utf-8") as f:
        json.dump(cases, f, indent=2, ensure_ascii=False)

    print(f"Download complete: {downloaded} downloaded, {skipped} already existed, {failed} failed.")

if __name__ == "__main__":
    download_stls()
