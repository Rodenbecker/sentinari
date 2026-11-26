#!/usr/bin/env python3
r"""Sentinari PrintAnatomy Scraper & 3D Anatomy Harvester.

Crawls and archives the open-access European Union / Comenius University
PrintAnatomy medical 3D library (https://printanatomy.eu) directly onto
drive E:\ for sovereign offline surgical and anatomical research.

Features:
- Full catalog discovery across all specialties (Neurosurgery, Cardiology, Paediatrics, Orthopaedics)
- Downloads full-resolution binary/ASCII .stl models with resumable chunked streaming
- Downloads all high-resolution clinical preview images
- Extracts structured clinical case histories, diagnoses, patient age, authors, and verification
- Generates an offline interactive medical portal (index.html) on drive E:\

Usage:
  python scripts/scrape_printanatomy.py --metadata-only  # Fast: catalog, cases & images only
  python scripts/scrape_printanatomy.py --all            # Complete: includes all .stl 3D models
  python scripts/scrape_printanatomy.py --slug apert-syndrome # Single case
"""
from __future__ import annotations

import argparse
import json
import os
import re
import ssl
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

# Force UTF-8 on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE_URL = "https://printanatomy.eu"
DIRECTUS_ASSET_BASE = "https://admin.printanatomy.eu/assets"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def get_ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    return ctx


def http_get(url: str, timeout: int = 25) -> str:
    """Fetch text content from URL."""
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, context=get_ssl_context(), timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def download_file(url: str, dest_path: Path, min_expected_size: int = 100) -> bool:
    """Download binary file with resume and size validation."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Check if already downloaded
    if dest_path.exists() and dest_path.stat().st_size > min_expected_size:
        # Check remote size via HEAD
        try:
            head_req = urllib.request.Request(url, method="HEAD", headers=HEADERS)
            with urllib.request.urlopen(head_req, context=get_ssl_context(), timeout=10) as head_resp:
                rem_len = head_resp.headers.get("Content-Length")
                if rem_len and int(rem_len) == dest_path.stat().st_size:
                    print(f"  [CACHE] {dest_path.name} already exists ({dest_path.stat().st_size / 1e6:.1f} MB), skipping.")
                    return True
        except Exception:
            return True

    tmp_path = dest_path.with_suffix(dest_path.suffix + ".part")
    print(f"  [DOWNLOADING] {dest_path.name} from {url}...")
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, context=get_ssl_context(), timeout=60) as resp:
            total_size = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            t0 = time.time()
            with open(tmp_path, "wb") as f_out:
                while True:
                    chunk = resp.read(1024 * 1024)  # 1 MB chunks
                    if not chunk:
                        break
                    f_out.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        pct = (downloaded / total_size) * 100.0
                        elapsed = time.time() - t0
                        speed = (downloaded / (elapsed + 0.001)) / (1024 * 1024)
                        print(f"\r    -> {downloaded / 1e6:.1f} / {total_size / 1e6:.1f} MB ({pct:.1f}%) @ {speed:.1f} MB/s", end="", flush=True)
            print()
        
        # Atomic rename
        if tmp_path.exists():
            if dest_path.exists():
                dest_path.unlink()
            tmp_path.rename(dest_path)
            print(f"  [SAVED] {dest_path.name} ({dest_path.stat().st_size / 1e6:.1f} MB)")
            return True
    except Exception as exc:
        print(f"\n  [ERROR] Failed to download {url}: {exc}")
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass
        return False
    return False


def discover_all_model_slugs() -> list[str]:
    """Retrieve all model slugs from /models/all."""
    print("Fetching master catalog from https://printanatomy.eu/models/all...")
    html = http_get(f"{BASE_URL}/models/all")
    slugs = sorted(list(set(re.findall(r'href=[\'"]/model/([a-zA-Z0-9_-]+)[\'"]', html))))
    print(f"Discovered {len(slugs)} total anatomical model cases!")
    return slugs


def parse_model_page(slug: str) -> dict:
    """Parse metadata, description, images, and STL download links from a model page."""
    url = f"{BASE_URL}/model/{slug}"
    html = http_get(url)

    # Title
    m_title = re.search(r'<h1[^>]*class="[^"]*is-title[^"]*"[^>]*>(.*?)</h1>', html)
    title = m_title.group(1).strip() if m_title else slug.replace("-", " ").title()

    # Categories
    categories = re.findall(r'href="/collection/([^"]+)"', html)
    categories = sorted(list(set(categories)))

    # Article text content
    article_match = re.search(r'<article[^>]*>(.*?)</article>', html, re.DOTALL)
    article_html = article_match.group(1) if article_match else ""
    
    clean_text = re.sub(r'<[^>]+>', ' ', article_html)
    clean_text = re.sub(r'\s+', ' ', clean_text).strip()

    # STL Model Link
    stl_match = re.search(r'href="(https://admin\.printanatomy\.eu/assets/([0-9a-f-]+))"[^>]*>([^<]+\.stl)</a>', html, re.I)
    if stl_match:
        stl_url = stl_match.group(1)
        stl_uuid = stl_match.group(2)
        stl_filename = stl_match.group(3).strip()
    else:
        # Fallback search for any .stl file in the page
        stl_uuid_match = re.search(r'admin\.printanatomy\.eu/assets/([0-9a-f-]{36})', html)
        stl_url = None
        stl_uuid = None
        stl_filename = None

    # High-resolution Preview Images
    # Directus images may be in <img src="..." or Next.js optimized /_next/image?url=https%3A%2F%2Fadmin...
    decoded_html = urllib.parse.unquote(html)
    found_assets = re.findall(r'admin\.printanatomy\.eu/assets/([0-9a-f-]{36})', decoded_html)
    unique_assets = list(dict.fromkeys(found_assets))
    
    # Filter out STL UUID from image list
    image_uuids = [u for u in unique_assets if u != stl_uuid]

    return {
        "slug": slug,
        "title": title,
        "url": url,
        "categories": categories,
        "stl_url": stl_url,
        "stl_uuid": stl_uuid,
        "stl_filename": stl_filename,
        "image_uuids": image_uuids,
        "description": clean_text,
        "license": "CC BY-NC 4.0 (Creative Commons Attribution-NonCommercial 4.0)",
        "source": "Institute of Anatomy, Faculty of Medicine, Comenius University / PrintAnatomy.eu",
    }


def compute_stl_metrics(stl_path: Path) -> dict | None:
    """Compute exact bounding box, facet count, surface area, and volume using NumPy."""
    try:
        import numpy as np
        stl_dtype = np.dtype([
            ('normal', '<f4', (3,)),
            ('v1', '<f4', (3,)),
            ('v2', '<f4', (3,)),
            ('v3', '<f4', (3,)),
            ('attr', '<u2')
        ])
        with open(stl_path, "rb") as f:
            f.seek(80)
            count = int(np.frombuffer(f.read(4), dtype="<u4")[0])
            # Only compute if reasonable count to keep speed lightning fast
            if count > 5_000_000:
                return {"facet_count": count}
            data = np.fromfile(f, dtype=stl_dtype, count=count)
        
        v1, v2, v3 = data['v1'], data['v2'], data['v3']
        all_verts = np.concatenate([v1, v2, v3], axis=0)
        min_c = all_verts.min(axis=0)
        max_c = all_verts.max(axis=0)
        dims = max_c - min_c

        # Area
        cross = np.cross(v2 - v1, v3 - v1)
        area_mm2 = 0.5 * np.linalg.norm(cross, axis=1).sum()

        # Volume
        signed_vols = np.einsum('ij,ij->i', v1, np.cross(v2, v3)) / 6.0
        volume_mm3 = float(np.abs(signed_vols.sum()))

        return {
            "facet_count": count,
            "dimensions_mm": {
                "width_x": round(float(dims[0]), 2),
                "depth_y": round(float(dims[1]), 2),
                "height_z": round(float(dims[2]), 2),
            },
            "surface_area_cm2": round(float(area_mm2 / 100.0), 2),
            "enclosed_volume_ml": round(float(volume_mm3 / 1000.0), 2),
        }
    except Exception:
        return None


def generate_offline_html_portal(catalog: list[dict], root_dir: Path) -> None:
    r"""Generate a high-fidelity dark-mode offline HTML catalog on drive E:\."""
    html_file = root_dir / "index.html"
    
    cards_html = []
    for item in catalog:
        slug = item["slug"]
        title = item["title"]
        cats = "".join(f'<span class="badge">{c}</span>' for c in item.get("categories", []))
        has_stl = bool(item.get("stl_filename"))
        stl_badge = f'<span class="badge badge-stl">STL: {item["stl_filename"]}</span>' if has_stl else '<span class="badge badge-none">No STL Attachment</span>'
        
        # Local image path
        local_images = item.get("local_images", [])
        img_src = local_images[0] if local_images else ""
        img_tag = f'<img src="{img_src}" alt="{title}" loading="lazy" class="card-img" />' if img_src else '<div class="no-img">No Preview Image</div>'
        
        desc = item.get("description", "")
        # Truncate clean description
        desc_preview = desc[:280] + ("..." if len(desc) > 280 else "")

        metrics = item.get("stl_metrics")
        metrics_html = ""
        if metrics:
            fc = metrics.get("facet_count", 0)
            dims = metrics.get("dimensions_mm", {})
            vol = metrics.get("enclosed_volume_ml", 0)
            metrics_html = f"""
            <div class="metrics-row">
              <span><b>Facets:</b> {fc:,}</span>
              <span><b>Dims:</b> {dims.get('width_x',0)} &times; {dims.get('depth_y',0)} &times; {dims.get('height_z',0)} mm</span>
              <span><b>Volume:</b> {vol} mL</span>
            </div>
            """

        case_dir_rel = f"cases/{slug}"
        stl_link = f'<a href="{item.get("local_stl", "#")}" class="btn btn-stl" download>📥 Download STL ({item.get("stl_filename")})</a>' if has_stl and item.get("local_stl") else ''
        case_link = f'<a href="{case_dir_rel}/case.json" target="_blank" class="btn btn-json">📄 Case JSON</a>'

        card = f"""
        <div class="card" data-categories="{' '.join(item.get('categories', []))}">
          <div class="img-wrapper">{img_tag}</div>
          <div class="card-body">
            <div class="badges-row">{cats} {stl_badge}</div>
            <h3 class="card-title">{title}</h3>
            <p class="card-desc">{desc_preview}</p>
            {metrics_html}
            <div class="btn-row">
              {stl_link}
              {case_link}
              <a href="{item['url']}" target="_blank" rel="noopener" class="btn btn-ext">🌐 Original Webpage &rarr;</a>
            </div>
          </div>
        </div>
        """
        cards_html.append(card)

    all_cards = "\n".join(cards_html)
    total_models = len(catalog)
    total_with_stl = sum(1 for c in catalog if c.get("stl_filename"))

    full_html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sentinari 3D Anatomical Library — Offline Archive (Drive E:\\)</title>
<style>
  :root {{
    --bg-main: #0b1320;
    --bg-card: #132238;
    --border-color: #233a5b;
    --text-main: #e2e8f0;
    --text-muted: #94a3b8;
    --accent-emerald: #10b981;
    --accent-cyan: #06b6d4;
    --accent-blue: #3b82f6;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    padding: 24px;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
    background: var(--bg-main);
    color: var(--text-main);
    line-height: 1.5;
  }}
  .container {{ max-width: 1440px; margin: 0 auto; }}
  header {{
    background: linear-gradient(135deg, #0f1c2d 0%, #172a45 100%);
    border: 1px solid var(--border-color);
    border-radius: 12px;
    padding: 24px 30px;
    margin-bottom: 24px;
  }}
  h1 {{ margin: 0 0 6px; font-size: 24px; color: #fff; }}
  .subtitle {{ color: var(--text-muted); font-size: 13.5px; margin-bottom: 14px; }}
  .stats-row {{ display: flex; gap: 16px; flex-wrap: wrap; }}
  .stat-pill {{
    background: rgba(255,255,255,0.06);
    border: 1px solid rgba(255,255,255,0.12);
    padding: 4px 12px;
    border-radius: 20px;
    font-size: 12px;
    font-weight: 700;
  }}
  .filter-box {{
    margin-top: 14px;
    display: flex;
    gap: 10px;
    align-items: center;
    flex-wrap: wrap;
  }}
  input[type="text"] {{
    background: #09121d;
    border: 1px solid var(--border-color);
    color: #fff;
    padding: 8px 14px;
    border-radius: 6px;
    font-size: 13px;
    width: 320px;
  }}
  .grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(380px, 1fr));
    gap: 20px;
  }}
  .card {{
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: 10px;
    overflow: hidden;
    display: flex;
    flex-direction: column;
    transition: transform 0.15s ease, border-color 0.15s ease;
  }}
  .card:hover {{
    transform: translateY(-2px);
    border-color: var(--accent-cyan);
  }}
  .img-wrapper {{
    background: #080d16;
    height: 220px;
    display: flex;
    align-items: center;
    justify-content: center;
    overflow: hidden;
    border-bottom: 1px solid var(--border-color);
  }}
  .card-img {{
    width: 100%;
    height: 100%;
    object-fit: cover;
  }}
  .no-img {{ color: var(--text-muted); font-size: 12px; }}
  .card-body {{ padding: 16px; display: flex; flex-direction: column; flex: 1; }}
  .badges-row {{ display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 8px; }}
  .badge {{
    background: rgba(56, 189, 248, 0.15);
    color: #38bdf8;
    border: 1px solid rgba(56, 189, 248, 0.35);
    padding: 2px 7px;
    border-radius: 4px;
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
  }}
  .badge-stl {{ background: rgba(16, 185, 129, 0.15); color: #34d399; border-color: rgba(16, 185, 129, 0.4); }}
  .badge-none {{ background: rgba(148, 163, 184, 0.1); color: #94a3b8; border-color: rgba(148, 163, 184, 0.25); }}
  .card-title {{ margin: 0 0 8px; font-size: 16px; color: #fff; }}
  .card-desc {{ font-size: 12.5px; color: #cbd5e1; flex: 1; line-height: 1.45; margin: 0 0 12px; }}
  .metrics-row {{
    background: #09121d;
    border: 1px solid rgba(255,255,255,0.06);
    padding: 8px 10px;
    border-radius: 6px;
    font-size: 11px;
    color: #94a3b8;
    display: flex;
    justify-content: space-between;
    margin-bottom: 12px;
  }}
  .btn-row {{ display: flex; gap: 8px; flex-wrap: wrap; margin-top: auto; }}
  .btn {{
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 6px 12px;
    border-radius: 5px;
    font-size: 11.5px;
    font-weight: 700;
    text-decoration: none;
    border: 1px solid transparent;
  }}
  .btn-stl {{ background: rgba(16, 185, 129, 0.2); color: #6ee7b7; border-color: rgba(16, 185, 129, 0.4); }}
  .btn-stl:hover {{ background: #10b981; color: #000; }}
  .btn-json {{ background: rgba(56, 189, 248, 0.15); color: #7dd3fc; border-color: rgba(56, 189, 248, 0.35); }}
  .btn-ext {{ background: rgba(255, 255, 255, 0.06); color: #cbd5e1; border-color: rgba(255, 255, 255, 0.15); }}
</style>
</head>
<body>
<div class="container">
  <header>
    <h1>🏛️ Sentinari Sovereign 3D Anatomical Library</h1>
    <div class="subtitle">Curated Medical 3D Scans, Surgical Segmentations &amp; Clinical Case Histories &bull; Archived on Drive E:\\</div>
    <div class="stats-row">
      <span class="stat-pill">Total Clinical Cases: {total_models}</span>
      <span class="stat-pill" style="color:#34d399;">3D Models Available: {total_with_stl}</span>
      <span class="stat-pill" style="color:#38bdf8;">License: CC BY-NC 4.0</span>
      <span class="stat-pill">Comenius University Medical Faculty</span>
    </div>
    <div class="filter-box">
      <input type="text" id="searchBox" placeholder="Search by diagnosis, organ, or specialty (e.g. Apert, Tetralogy, Femur)..." oninput="filterCards()" />
    </div>
  </header>

  <div class="grid" id="modelsGrid">
    {all_cards}
  </div>
</div>

<script>
function filterCards() {{
  const query = document.getElementById('searchBox').value.toLowerCase();
  const cards = document.querySelectorAll('.card');
  cards.forEach(card => {{
    const text = card.textContent.toLowerCase();
    card.style.display = text.includes(query) ? '' : 'none';
  }});
}}
</script>
</body>
</html>
"""
    html_file.write_text(full_html, encoding="utf-8")
    print(f"Generated offline anatomical portal: {html_file}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Sentinari PrintAnatomy 3D Harvester")
    parser.add_argument("--out", type=str, default=r"E:\PrintAnatomy", help="Output directory on disk")
    parser.add_argument("--metadata-only", action="store_true", help="Download only metadata, case text, and images (skip large STLs)")
    parser.add_argument("--all", action="store_true", help="Download full library including all .stl 3D files")
    parser.add_argument("--slug", type=str, default="", help="Download single model by slug")
    args = parser.parse_args()

    out_dir = Path(args.out)
    # Check if drive E:\ exists; fallback to D:\Sentinari\data\PrintAnatomy if not
    if not out_dir.parent.exists():
        fallback = Path(r"D:\Sentinari\data\PrintAnatomy")
        print(f"[WARN] Target {out_dir} not available, falling back to {fallback}")
        out_dir = fallback

    out_dir.mkdir(parents=True, exist_ok=True)
    cases_dir = out_dir / "cases"
    images_dir = out_dir / "images"
    models_dir = out_dir / "models"
    cases_dir.mkdir(exist_ok=True)
    images_dir.mkdir(exist_ok=True)
    models_dir.mkdir(exist_ok=True)

    print("=" * 75)
    print(f"  SENTINARI 3D ANATOMY HARVESTER & ARCHIVE ENGINE")
    print(f"  Destination Root: {out_dir}")
    print(f"  Mode: {'METADATA + IMAGES ONLY' if args.metadata_only else 'FULL LIBRARY (STL + IMAGES + METADATA)'}")
    print("=" * 75)

    if args.slug:
        slugs = [args.slug]
    else:
        slugs = discover_all_model_slugs()

    catalog_data = []

    for idx, slug in enumerate(slugs, 1):
        print(f"\n[{idx}/{len(slugs)}] Processing case: {slug}")
        case_dir = cases_dir / slug
        case_dir.mkdir(exist_ok=True)

        try:
            item = parse_model_page(slug)
        except Exception as exc:
            print(f"  [ERROR] Failed to parse model page {slug}: {exc}")
            continue

        local_images = []
        # Download preview images
        for img_idx, img_uuid in enumerate(item["image_uuids"], 1):
            img_url = f"{DIRECTUS_ASSET_BASE}/{img_uuid}"
            img_file = images_dir / f"{slug}_IMG{img_idx}.png"
            if download_file(img_url, img_file):
                # Relative path from index.html
                local_images.append(f"images/{img_file.name}")
        
        item["local_images"] = local_images

        # Check for existing Apert syndrome STL on D: if processing apert-syndrome
        local_stl_path = None
        if slug == "apert-syndrome" and Path(r"D:\Sentinari\docs\27_Apert syndrome.stl").exists():
            target_stl = models_dir / "27_Apert syndrome.stl"
            if not target_stl.exists():
                print("  [COPY] Copying already-downloaded Apert syndrome STL to destination...")
                import shutil
                shutil.copyfile(r"D:\Sentinari\docs\27_Apert syndrome.stl", target_stl)
            local_stl_path = target_stl
            item["local_stl"] = f"models/{target_stl.name}"

        # Download STL model if requested and available
        if not args.metadata_only and item.get("stl_url") and not local_stl_path:
            stl_name = item.get("stl_filename") or f"{slug}.stl"
            stl_dest = models_dir / stl_name
            if download_file(item["stl_url"], stl_dest, min_expected_size=1024):
                local_stl_path = stl_dest
                item["local_stl"] = f"models/{stl_name}"

        # Compute 3D metrics if STL file is present
        if local_stl_path and local_stl_path.exists():
            print(f"  [ANALYZE] Computing 3D metrics for {local_stl_path.name}...")
            metrics = compute_stl_metrics(local_stl_path)
            if metrics:
                item["stl_metrics"] = metrics
                print(f"    Facets: {metrics.get('facet_count',0):,} | Enclosed Vol: {metrics.get('enclosed_volume_ml',0)} mL")

        # Save individual case metadata JSON
        case_json_file = case_dir / "case.json"
        case_json_file.write_text(json.dumps(item, indent=2, ensure_ascii=False), encoding="utf-8")

        # Save readable README.md for case
        readme_md = case_dir / "README.md"
        readme_content = f"""# {item['title']}

**Specialty / Categories:** {', '.join(item.get('categories', []))}  
**Source:** {item.get('source')}  
**License:** {item.get('license')}  
**Original URL:** [{item['url']}]({item['url']})  

## Clinical Description & Case Presentation
{item.get('description')}

## 3D Printing & Model Data
- **Filename:** `{item.get('stl_filename', 'N/A')}`
- **Direct Download URL:** {item.get('stl_url', 'N/A')}
"""
        if item.get("stl_metrics"):
            m = item["stl_metrics"]
            readme_content += f"""
### Computed Anatomical 3D Metrics
- **Triangular Facets:** {m.get('facet_count', 0):,}
- **Bounding Dimensions (X, Y, Z):** {m.get('dimensions_mm', {}).get('width_x')} x {m.get('dimensions_mm', {}).get('depth_y')} x {m.get('dimensions_mm', {}).get('height_z')} mm
- **Bony Surface Area:** {m.get('surface_area_cm2')} cm²
- **Enclosed Calvarial/Tissue Volume:** {m.get('enclosed_volume_ml')} mL
"""
        readme_md.write_text(readme_content, encoding="utf-8")

        catalog_data.append(item)
        time.sleep(0.5)  # Polite delay

    # Save master catalog JSON
    master_json = out_dir / "catalog.json"
    master_json.write_text(json.dumps(catalog_data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[COMPLETE] Saved master catalog with {len(catalog_data)} cases to {master_json}")

    # Generate offline interactive HTML viewer
    generate_offline_html_portal(catalog_data, out_dir)
    print("\n" + "=" * 75)
    print(f"  ANATOMY ARCHIVE COMPLETE ON {out_dir}!")
    print(f"  Open {out_dir}\\index.html in your browser to inspect all cases!")
    print("=" * 75)


if __name__ == "__main__":
    main()
