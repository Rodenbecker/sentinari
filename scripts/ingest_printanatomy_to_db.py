"""
Ingest PrintAnatomy.eu Clinical Cases & 3D Models into Sentinari Knowledge Base (sentinari.db)
==============================================================================================
Maps clinical cases, genetic etiology, radiographic features, and 3D STL spatial metrics
into documents, chunks, and chunk_fts tables so Gemma can perform RAG and recall.
"""

import json
import os
import sqlite3
import hashlib
from pathlib import Path
from datetime import datetime, timezone

DB_PATH = Path(r"D:\Sentinari\data\sentinari.db")
CATALOG_PATH = Path(r"E:\PrintAnatomy\catalog.json")

def ingest_printanatomy():
    if not CATALOG_PATH.exists():
        print(f"Catalog not found at {CATALOG_PATH}")
        return

    with open(CATALOG_PATH, "r", encoding="utf-8") as f:
        cases = json.load(f)

    print(f"Loaded {len(cases)} cases from catalog.")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Ensure sentinel domain and scientific field exist
    cur.execute("""
        INSERT OR IGNORE INTO sentinel_domains (slug, name, description)
        VALUES ('medicine', 'Clinical Medicine & Surgery', 'Medical, radiological, and surgical disciplines')
    """)
    cur.execute("""
        INSERT OR IGNORE INTO sentinel_scientific_fields (domain_slug, field_name, field_slug, detail, taxonomy_path)
        VALUES ('medicine', 'Clinical Anatomy & 3D Bio-Reconstruction', 'anatomy-neurosurgery-cardiology', '3D anatomical ground truth, surgical pathology, and spatial radiology', 'medicine/anatomy-neurosurgery-cardiology')
    """)

    ingested_count = 0
    now_iso = datetime.now(timezone.utc).isoformat()

    for case in cases:
        slug = case.get("slug", "")
        title = case.get("title", "")
        categories = case.get("categories", [])
        desc = case.get("description", "")
        source = case.get("source", "Institute of Anatomy, Faculty of Medicine, Comenius University / PrintAnatomy.eu")
        license_text = case.get("license", "CC BY-NC 4.0")
        stl_filename = case.get("stl_filename") or ""
        local_stl = case.get("local_stl") or ""
        stl_metrics = case.get("stl_metrics") or {}
        local_images = case.get("local_images") or []

        # Check if already ingested
        cur.execute("SELECT id FROM documents WHERE source_id = ?", (f"printanatomy_{slug}",))
        existing = cur.fetchone()
        if existing:
            doc_id = existing[0]
        else:
            meta_json = json.dumps({
                "slug": slug,
                "categories": categories,
                "stl_filename": stl_filename,
                "local_stl": local_stl,
                "stl_metrics": stl_metrics,
                "local_images": local_images,
                "source_url": case.get("url", ""),
                "stl_url": case.get("stl_url", ""),
            })

            cur.execute("""
                INSERT INTO documents (
                    source_id, title, source_type, source_path, source_url,
                    domain, module, topic, language, license, authors, publisher,
                    scientific_field, vocational_discipline, source_collection,
                    document_metadata_json, priority, checksum, raw_char_count, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                f"printanatomy_{slug}",
                f"{title} - 3D Clinical Anatomical Model",
                "3d_anatomy_case",
                str(Path(r"E:\PrintAnatomy\cases") / slug / "case.json"),
                case.get("url", ""),
                "medicine",
                categories[0] if categories else "general_anatomy",
                ", ".join(categories),
                "en",
                license_text,
                "Comenius University Medical Faculty, Bratislava / PrintAnatomy Team",
                "PrintAnatomy.eu / European Union Sponsored",
                "anatomy-neurosurgery-cardiology",
                "Surgical Radiology & 3D Bio-Reconstruction",
                "PrintAnatomy.eu",
                meta_json,
                10,
                hashlib.sha256(desc.encode("utf-8")).hexdigest(),
                len(desc),
                now_iso
            ))
            doc_id = cur.lastrowid
            ingested_count += 1

            local_model_path = f"E:/PrintAnatomy/{local_stl}" if local_stl else (f"E:/PrintAnatomy/models/{stl_filename}" if stl_filename else "E:/PrintAnatomy/models/available_on_portal")
            # Prepare structured knowledge chunk for Gemma
            chunk_content = f"""CLINICAL 3D ANATOMICAL MODEL: {title}
SPECIALTIES & CATEGORIES: {', '.join(categories).upper()}
INSTITUTIONAL SOURCE: {source}
VERIFICATION: Institute of Anatomy, Faculty of Medicine, Comenius University, Bratislava, SK.

ANATOMICAL & PATHOLOGICAL DESCRIPTION:
{desc}

3D SPATIAL & PRINT METRICS:
- STL File: {stl_filename or 'Available on portal'}
- Local Path: {local_model_path}
- Facet Count: {stl_metrics.get('facet_count', 'Standard Simplicial 2-Complex')}
- Calvarial / Anatomical Dimensions: {stl_metrics.get('dimensions_mm', 'Clinical standard 1:1 scale')}
- Surface Area: {stl_metrics.get('surface_area_cm2', 'N/A')} cm2
- Enclosed Volume: {stl_metrics.get('enclosed_volume_ml', 'N/A')} mL

SURGICAL & RADIOLOGICAL INDICATIONS:
Surgeons can reference this true-to-scale 3D geometry when evaluating cranial vault deformities, craniosynostosis (bicoronal/sagittal/metopic), syndactyly, facial dysmorphism, or cardiac anomalies on patient X-ray, CT, and MRI scans.
"""
            chunk_hash = hashlib.sha256(chunk_content.encode("utf-8")).hexdigest()
            cur.execute("""
                INSERT INTO chunks (
                    document_id, chunk_index, content, token_estimate, metadata_json, chunk_hash, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                doc_id,
                0,
                chunk_content,
                len(chunk_content.split()),
                json.dumps({"slug": slug, "title": title, "categories": categories}),
                chunk_hash,
                now_iso
            ))
            chunk_id = cur.lastrowid

            # Insert into Full-Text Search index (chunk_fts)
            cur.execute("""
                INSERT INTO chunk_fts (rowid, content, document_id)
                VALUES (?, ?, ?)
            """, (chunk_id, chunk_content, doc_id))

    conn.commit()
    conn.close()
    print(f"Successfully ingested {ingested_count} PrintAnatomy clinical cases into sentinari.db.")

if __name__ == "__main__":
    ingest_printanatomy()
