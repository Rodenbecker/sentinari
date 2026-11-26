"""
Add route aliases for /ui/threats.html, /threats, etc. in app/main.py
"""

from pathlib import Path

MAIN_PY = Path(r"D:\Sentinari\app\main.py")

def patch_routes():
    text = MAIN_PY.read_text(encoding="utf-8")

    # 1. Threats
    target_threats = '@app.get("/ui/threats", response_class=HTMLResponse)'
    repl_threats = """@app.get("/ui/threats", response_class=HTMLResponse)
@app.get("/ui/threats.html", response_class=HTMLResponse, include_in_schema=False)
@app.get("/ui/threats-workspace", response_class=HTMLResponse, include_in_schema=False)
@app.get("/ui/planetary-risk", response_class=HTMLResponse, include_in_schema=False)
@app.get("/threats", response_class=HTMLResponse, include_in_schema=False)"""

    if target_threats in text and '@app.get("/ui/threats.html"' not in text:
        text = text.replace(target_threats, repl_threats, 1)
        print("Patched threats routes.")

    # 2. Vision
    target_vision = '@app.get("/ui/vision", response_class=HTMLResponse)'
    repl_vision = """@app.get("/ui/vision", response_class=HTMLResponse)
@app.get("/ui/vision.html", response_class=HTMLResponse, include_in_schema=False)
@app.get("/vision", response_class=HTMLResponse, include_in_schema=False)"""

    if target_vision in text and '@app.get("/ui/vision.html"' not in text:
        text = text.replace(target_vision, repl_vision, 1)
        print("Patched vision routes.")

    # 3. Oncology
    target_oncology = '@app.get("/ui/oncology", response_class=HTMLResponse)'
    repl_oncology = """@app.get("/ui/oncology", response_class=HTMLResponse)
@app.get("/ui/oncology.html", response_class=HTMLResponse, include_in_schema=False)
@app.get("/oncology", response_class=HTMLResponse, include_in_schema=False)"""

    if target_oncology in text and '@app.get("/ui/oncology.html"' not in text:
        text = text.replace(target_oncology, repl_oncology, 1)
        print("Patched oncology routes.")

    MAIN_PY.write_text(text, encoding="utf-8")
    print("Successfully patched main.py!")

if __name__ == "__main__":
    patch_routes()
