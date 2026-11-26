"""
Extract all 2,373 3D Meshes from 3D Anatomy for the Artist onto Drive E:\
========================================================================
Categorizes models into Skeletal, Muscular, Vascular, Respiratory, Digestive, Sensory.
Exports Wavefront .OBJ files with vertex normals and faces.
"""

import os
import sys
import json
from pathlib import Path
import UnityPy

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

SOURCE_ASSETS = r"C:\Program Files\WindowsApps\CatfishAnimationStudio.3DAnatomyfortheArtist_7.1.3.0_x64__5w37ds3rm089g\3D Anatomy for the Artist_Data\resources.assets"
OUT_BASE = Path(r"E:\PrintAnatomy\artist_3d_anatomy")
OUT_BASE.mkdir(parents=True, exist_ok=True)

CATEGORY_MAP = {
    "Ske": "skeletal",
    "Mus": "muscular",
    "Vei": "vascular",
    "Res": "respiratory",
    "Dig": "digestive",
    "Eye": "sensory",
    "Int": "integumentary",
}

def export_all():
    print(f"Loading Unity assets from {SOURCE_ASSETS}...")
    env = UnityPy.load(SOURCE_ASSETS)
    
    for sub in CATEGORY_MAP.values():
        (OUT_BASE / sub).mkdir(parents=True, exist_ok=True)
    (OUT_BASE / "other").mkdir(parents=True, exist_ok=True)

    manifest = []
    exported = 0
    errors = 0

    for obj in env.objects:
        if obj.type.name != "Mesh":
            continue
        try:
            data = obj.read()
            name = getattr(data, "m_Name", getattr(data, "name", "unnamed"))
            prefix = name.split("_")[0] if "_" in name else "Other"
            cat_dir = CATEGORY_MAP.get(prefix, "other")
            out_file = OUT_BASE / cat_dir / f"{name}.obj"

            # Check if export method is available
            obj_content = None
            if hasattr(data, "export"):
                obj_content = data.export()
            elif hasattr(data, "export_obj"):
                obj_content = data.export_obj()

            if obj_content:
                if isinstance(obj_content, str):
                    out_file.write_text(obj_content, encoding="utf-8")
                else:
                    out_file.write_bytes(obj_content)
                
                size_bytes = out_file.stat().st_size
                manifest.append({
                    "mesh_name": name,
                    "category": cat_dir,
                    "prefix": prefix,
                    "file_path": str(out_file),
                    "relative_path": f"artist_3d_anatomy/{cat_dir}/{name}.obj",
                    "size_bytes": size_bytes,
                })
                exported += 1
                if exported % 100 == 0:
                    print(f"Exported {exported} meshes...")
        except Exception as ex:
            errors += 1

    manifest_path = OUT_BASE / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"Extraction complete! Successfully exported {exported} meshes (errors: {errors}).")
    print(f"Manifest written to {manifest_path}")

if __name__ == "__main__":
    export_all()
