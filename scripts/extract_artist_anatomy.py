#!/usr/bin/env python3
"""Sentinari Unity Anatomy Mesh Extractor (Aristotelian Causa Efficiens).

Extracts all 2,373 anatomical 3D meshes (bones & muscles) and textures from
Catfish Animation Studio's '3D Anatomy for the Artist' directly onto drive E:\.

Usage:
  python scripts/extract_artist_anatomy.py [--limit N]
"""
import sys
import time
from pathlib import Path

# Force UTF-8 on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

try:
    import UnityPy
except ImportError:
    print("[ERROR] UnityPy not installed. Run: pip install UnityPy")
    sys.exit(1)

APP_DIR = Path(r"C:\Program Files\WindowsApps\CatfishAnimationStudio.3DAnatomyfortheArtist_7.1.3.0_x64__5w37ds3rm089g")
DATA_DIR = APP_DIR / "3D Anatomy for the Artist_Data"
RESOURCES_ASSETS = DATA_DIR / "resources.assets"

DEST_DIR = Path(r"E:\PrintAnatomy\artist_3d_anatomy")
BONES_DIR = DEST_DIR / "skeletal_bones"
MUSCLES_DIR = DEST_DIR / "muscular_system"
OTHER_DIR = DEST_DIR / "other_structures"

for d in [BONES_DIR, MUSCLES_DIR, OTHER_DIR]:
    d.mkdir(parents=True, exist_ok=True)


def extract_all_meshes(limit: int = 0) -> None:
    print("=" * 75)
    print("  SENTINARI ARISTOTELIAN ANATOMY EXTRACTOR (CAUSA EFFICIENS)")
    print(f"  Source: {RESOURCES_ASSETS}")
    print(f"  Target: {DEST_DIR}")
    print("=" * 75)

    if not RESOURCES_ASSETS.exists():
        print(f"[ERROR] Cannot find resources.assets at {RESOURCES_ASSETS}")
        return

    print("Loading Unity asset environment (reading ~263 MB index)...")
    t0 = time.time()
    env = UnityPy.load(str(RESOURCES_ASSETS))
    print(f"Index loaded in {time.time() - t0:.2f}s!")

    extracted_bones = 0
    extracted_muscles = 0
    extracted_other = 0
    total_found = 0

    print("Extracting 3D Wavefront (.obj) meshes...")
    for obj in env.objects:
        if obj.type.name != "Mesh":
            continue

        total_found += 1
        data = obj.read()
        name = getattr(data, "m_Name", getattr(data, "name", "unnamed_mesh"))

        # Sort into bones vs muscles
        if name.startswith("Ske_"):
            target_file = BONES_DIR / f"{name}.obj"
            extracted_bones += 1
        elif name.startswith("Mus_"):
            target_file = MUSCLES_DIR / f"{name}.obj"
            extracted_muscles += 1
        else:
            target_file = OTHER_DIR / f"{name}.obj"
            extracted_other += 1

        # Skip if already exists
        if target_file.exists() and target_file.stat().st_size > 100:
            continue

        try:
            if hasattr(data, "export"):
                obj_text = data.export()
                target_file.write_text(obj_text, encoding="utf-8")
            else:
                # Manual export
                verts = data.vertices
                indices = data.indices
                with open(target_file, "w", encoding="utf-8") as f:
                    f.write(f"# Sentinari Sovereign 3D Anatomy: {name}\n")
                    f.write(f"o {name}\n")
                    for v in verts:
                        f.write(f"v {v.x} {v.y} {v.z}\n")
                    for i in range(0, len(indices), 3):
                        f.write(f"f {indices[i]+1} {indices[i+1]+1} {indices[i+2]+1}\n")
        except Exception as exc:
            print(f"  [WARN] Failed to export {name}: {exc}")

        total_saved = extracted_bones + extracted_muscles + extracted_other
        if total_saved % 50 == 0:
            print(f"  -> Extracted {total_saved} meshes (Bones: {extracted_bones}, Muscles: {extracted_muscles})...", flush=True)

        if limit > 0 and total_saved >= limit:
            print(f"Reached limit of {limit} meshes.")
            break

    print("\n" + "=" * 75)
    print(f"EXTRACTION COMPLETE!")
    print(f"Total Meshes Processed: {total_found}")
    print(f"Skeletal Bones Saved:   {extracted_bones} in {BONES_DIR}")
    print(f"Muscles Saved:          {extracted_muscles} in {MUSCLES_DIR}")
    print(f"Other Structures Saved: {extracted_other} in {OTHER_DIR}")
    print("=" * 75)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="Limit number of meshes to extract (0 = all)")
    args = parser.parse_args()
    extract_all_meshes(limit=args.limit)
