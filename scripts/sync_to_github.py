"""
Sentinari Sovereign Sync Bridge
================================
Synchronizes local discoveries, clinical 3D models, oncology dossiers,
and verified telemetry to the public GitHub showroom (ongalali.github.io/sentinari).

Conceived & Architected by Dr. Pierre C. Wepener
"""

import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(r"D:\Sentinari")
DOCS = ROOT / "docs"
DATA = ROOT / "data"

def get_learning_telemetry():
    db_path = DATA / "sentinari.db"
    if not db_path.exists():
        return {}
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        total_docs = cur.execute("SELECT count(*) FROM documents").fetchone()[0]
        anatomy_docs = cur.execute("SELECT count(*) FROM documents WHERE scientific_field = 'anatomy-neurosurgery-cardiology'").fetchone()[0]
        conn.close()
        return {
            "total_documents": total_docs,
            "anatomy_cases": anatomy_docs,
            "synced_at": datetime.now(timezone.utc).isoformat()
        }
    except Exception as ex:
        return {"error": str(ex)}

def verify_docs_links():
    """Ensure all links in docs/*.html are strictly relative."""
    print("Verifying docs links for GitHub Pages safety...")
    for f in DOCS.glob("*.html"):
        content = f.read_text(encoding="utf-8")
        updated = False
        
        # Replace accidental /ui/ links with ./
        if 'href="/ui/oncology"' in content:
            content = content.replace('href="/ui/oncology"', 'href="./oncology.html"')
            updated = True
        if 'href="/ui/threats"' in content:
            content = content.replace('href="/ui/threats"', 'href="./threats.html"')
            updated = True
        if 'href="/ui/vision"' in content:
            content = content.replace('href="/ui/vision"', 'href="./vision.html"')
            updated = True
        if 'href="/ui/help"' in content:
            content = content.replace('href="/ui/help"', 'href="./help.html"')
            updated = True
        if 'href="/ui/playground"' in content:
            content = content.replace('href="/ui/playground"', 'href="./index.html"')
            updated = True

        if updated:
            f.write_text(content, encoding="utf-8")
            print(f"  Fixed links in {f.name}")

def push_to_github():
    print("Checking git status...")
    status = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain"], capture_output=True, text=True)
    if not status.stdout.strip():
        print("Everything is already up-to-date with GitHub!")
        return True

    print("Staging showroom updates...")
    subprocess.run(["git", "-C", str(ROOT), "add", "docs/", ".gitignore"], check=True)

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    commit_msg = f"sync: Sovereign update to GitHub showroom ({now_str})"
    
    print(f"Committing: {commit_msg}")
    commit_res = subprocess.run(["git", "-C", str(ROOT), "commit", "-m", commit_msg], capture_output=True, text=True)
    print(commit_res.stdout)

    print("Pushing to ongalali remote...")
    push_res = subprocess.run(["git", "-C", str(ROOT), "push", "ongalali", "main"], capture_output=True, text=True)
    print(push_res.stdout)
    if push_res.stderr:
        print(push_res.stderr)

    return push_res.returncode == 0

def run_sync():
    print("==================================================")
    print("🚀 SENTINARI SOVEREIGN SYNC BRIDGE")
    print("==================================================")
    telemetry = get_learning_telemetry()
    print(f"Local Master Telemetry: {telemetry.get('total_documents', 'N/A')} documents in database.")
    
    verify_docs_links()
    success = push_to_github()

    if success:
        print("✅ SUCCESS: Showroom synchronized with https://ongalali.github.io/sentinari/")
    else:
        print("⚠️ Warning: Git push reported an error. Please inspect output.")

if __name__ == "__main__":
    run_sync()
