"""
Ingest 3D Anatomy for the Artist Taxonomy & Spatial Library into sentinari.db
"""

import json
import sqlite3
import hashlib
from pathlib import Path
from datetime import datetime, timezone

DB_PATH = Path(r"D:\Sentinari\data\sentinari.db")
MANIFEST_PATH = Path(r"E:\PrintAnatomy\artist_3d_anatomy\manifest.json")

def ingest_artist_atlas():
    if not MANIFEST_PATH.exists():
        print("Manifest not found")
        return

    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("SELECT id FROM documents WHERE source_id = 'artist_3d_anatomy_atlas'")
    if cur.fetchone():
        print("Artist 3D Anatomy Atlas already ingested.")
        conn.close()
        return

    now_iso = datetime.now(timezone.utc).isoformat()
    meta_json = json.dumps({
        "total_meshes": len(manifest),
        "systems": {
            "skeletal": len([m for m in manifest if m["category"] == "skeletal"]),
            "muscular": len([m for m in manifest if m["category"] == "muscular"]),
            "vascular": len([m for m in manifest if m["category"] == "vascular"]),
            "respiratory": len([m for m in manifest if m["category"] == "respiratory"]),
            "digestive": len([m for m in manifest if m["category"] == "digestive"]),
            "sensory": len([m for m in manifest if m["category"] == "sensory"]),
        },
        "base_path": "E:/PrintAnatomy/artist_3d_anatomy/"
    })

    content = f"""ATLAS OF 3D HUMAN ANATOMY & BIOMECHANICAL GROUND TRUTH (2,373 MESHES)
SYSTEMS & COMPONENT STRUCTURES:
- Skeletal System (1,552 Meshes): Individual cranial bones, vertebral segments (cervical C1-C7, thoracic T1-T12, lumbar L1-L5, sacrum, coccyx), rib cage, pectoral and pelvic girdles, appendicular long bones (femur, tibia, fibula, humerus, radius, ulna), carpal and tarsal articular facets.
- Muscular System (351 Meshes): Superficial and deep striated muscle bellies, origins, insertions, and aponeuroses across cranial, cervical, thoracic, abdominal, and extremity musculature.
- Vascular & Circulatory System (276 Meshes): Great vessels, arterial branches, systemic venous returns, and localized vascular plexuses.
- Respiratory & Visceral Systems (174 Meshes): Tracheobronchial arborization, pulmonary segmentations, visceral organs, and sensory orbital anatomy.

SURGICAL & MULTIMODAL APPLICATION:
Enables Gemma and Sentinari Vision to resolve patient radiographic scans (CT/MRI/X-Ray) against isolated 3D mesh components for reconstructive surgery, orthopedic implant templating, and biomechanical stress analysis.
"""

    cur.execute("""
        INSERT INTO documents (
            source_id, title, source_type, source_path, source_url,
            domain, module, topic, language, license, authors, publisher,
            scientific_field, vocational_discipline, source_collection,
            document_metadata_json, priority, checksum, raw_char_count, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        "artist_3d_anatomy_atlas",
        "Atlas of 3D Human Anatomy & Biomechanical Ground Truth (2,373 Meshes)",
        "3d_anatomy_atlas",
        str(MANIFEST_PATH),
        "local://E:/PrintAnatomy/artist_3d_anatomy",
        "medicine",
        "biomechanics",
        "skeletal, muscular, vascular, respiratory",
        "en",
        "Educational & Clinical Research",
        "Catfish Animation Studio / Inspirari Dissection Team",
        "Sentinari Sovereign Biomedical Library",
        "anatomy-neurosurgery-cardiology",
        "Surgical Biomechanics & 3D Spatial Anatomy",
        "3D Anatomy for the Artist",
        meta_json,
        15,
        hashlib.sha256(content.encode("utf-8")).hexdigest(),
        len(content),
        now_iso
    ))
    doc_id = cur.lastrowid

    cur.execute("""
        INSERT INTO chunks (
            document_id, chunk_index, content, token_estimate, metadata_json, chunk_hash, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        doc_id,
        0,
        content,
        len(content.split()),
        meta_json,
        hashlib.sha256(content.encode("utf-8")).hexdigest(),
        now_iso
    ))
    chunk_id = cur.lastrowid

    cur.execute("""
        INSERT INTO chunk_fts (rowid, content, document_id)
        VALUES (?, ?, ?)
    """, (chunk_id, content, doc_id))

    conn.commit()
    conn.close()
    print("Successfully ingested Artist 3D Anatomy Atlas into sentinari.db.")

if __name__ == "__main__":
    ingest_artist_atlas()
