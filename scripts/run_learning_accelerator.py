"""Sentinari Learning Accelerator - Local RTX 5070 Ti / CUDA Driver.

Drives the remaining unassessed documents through the Formative Assessment
pipeline using the local Sentinari ONNX server (Port 8100) on NVIDIA Blackwell silicon.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

# Force UTF-8 encoding on standard I/O streams on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from app.learning_index import (
    _candidate_documents,
    _probe_document_with_reason,
    learning_status,
    _set_setting,
)


def main() -> None:
    print("=" * 75)
    print("  SENTINARI LOCAL LEARNING ACCELERATOR (RTX 5070 Ti / RYZEN 9 9900X)")
    print("=" * 75)
    _set_setting("learning_enabled", "on")

    st = learning_status()
    total = st["total"]
    assessed = st["assessed"]
    percent = st["percent"]
    remaining = total - assessed

    print(f"Resuming Status: {assessed}/{total} documents ({percent}%)")
    print(f"Remaining Documents to Process: {remaining}")
    print(f"Engine: {st.get('engine', {})}")
    print("-" * 75)

    if remaining <= 0:
        print("[SUCCESS] All documents are already 100% assessed!")
        return

    processed = 0
    start_time = time.time()
    recent_latencies = []
    failures_per_doc: dict[int, int] = {}

    while True:
        candidates = _candidate_documents()
        if not candidates:
            # Recheck status to be completely certain
            st_now = learning_status()
            if st_now["total"] - st_now["assessed"] <= 0:
                print("\n[SUCCESS] 100% OF ALL INGESTED KNOWLEDGE ASSESSED AND MASTERED!")
                break
            else:
                time.sleep(1.0)
                continue

        doc_id = candidates[0]
        t0 = time.time()
        try:
            record, reason = _probe_document_with_reason(doc_id)
        except Exception as exc:
            print(f"[WARN] Error on Doc {doc_id}: {exc}. Moving forward...", flush=True)
            failures_per_doc[doc_id] = failures_per_doc.get(doc_id, 0) + 1
            if failures_per_doc[doc_id] >= 2:
                from datetime import datetime, timezone
                from app.db import get_connection
                with get_connection() as conn:
                    conn.execute(
                        "INSERT OR REPLACE INTO learning_assessments (document_id, verdict, scientific_field, title, assessed_at) "
                        "VALUES (?, 'skipped', 'skipped', 'Unprocessable or missing document material', ?)",
                        (doc_id, datetime.now(timezone.utc).isoformat(timespec="seconds")),
                    )
                    conn.commit()
                print(f"[SKIP] Document {doc_id} marked skipped after repeated exception", flush=True)
            time.sleep(0.5)
            continue

        if record is None:
            failures_per_doc[doc_id] = failures_per_doc.get(doc_id, 0) + 1
            if failures_per_doc[doc_id] >= 2 or reason == "no-material":
                from datetime import datetime, timezone
                from app.db import get_connection
                with get_connection() as conn:
                    conn.execute(
                        "INSERT OR REPLACE INTO learning_assessments (document_id, verdict, scientific_field, title, assessed_at) "
                        "VALUES (?, 'skipped', 'skipped', 'Unprocessable or missing document material', ?)",
                        (doc_id, datetime.now(timezone.utc).isoformat(timespec="seconds")),
                    )
                    conn.commit()
                print(f"[SKIP] Document {doc_id} marked as skipped ({reason})", flush=True)
            time.sleep(0.1)
            continue

        dt = time.time() - t0

        recent_latencies.append(dt)
        if len(recent_latencies) > 20:
            recent_latencies.pop(0)

        processed += 1

        if processed % 10 == 0 or processed == 1 or processed == remaining:
            st_curr = learning_status()
            cur_assessed = st_curr["assessed"]
            cur_pct = st_curr["percent"]
            rem_now = total - cur_assessed
            avg_speed = sum(recent_latencies) / len(recent_latencies) if recent_latencies else dt
            eta_minutes = (rem_now * avg_speed) / 60.0
            print(
                f"[PROGRESS] {cur_assessed}/{total} ({cur_pct}%) | "
                f"Remaining: {rem_now} | Rate: {avg_speed:.2f}s/doc | "
                f"ETA: {eta_minutes:.1f} min | Last: Doc {doc_id} -> {reason}",
                flush=True
            )

        # 50ms breather for GPU driver queue
        time.sleep(0.05)

    st_final = learning_status()
    elapsed = time.time() - start_time
    print("=" * 75)
    print(f"ACCELERATION COMPLETE in {elapsed/60:.1f} minutes!")
    print(f"Final Status: {st_final['assessed']}/{st_final['total']} ({st_final['percent']}%)")
    print("=" * 75)


if __name__ == "__main__":
    main()
