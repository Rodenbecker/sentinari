import os
import re
import shutil
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

TEMPLATES_DIR = r"D:\Sentinari\templates"
DOCS_DIR = r"D:\Sentinari\docs"

def adapt_template_for_docs(src_path, dst_path, module_name, local_port_route):
    print(f"Adapting {src_path} -> {dst_path} ({module_name})...")
    with open(src_path, "r", encoding="utf-8", errors="ignore") as f:
        html = f.read()

    # Replace localhost:8000 with 127.0.0.1:8099
    html = html.replace("http://localhost:8000", "http://127.0.0.1:8099")
    html = html.replace("localhost:8000", "http://127.0.0.1:8099")

    # Adapt common navigation links to relative showcase files
    link_replacements = [
        ('href="/ui/oncology"', 'href="./oncology.html"'),
        ('href="/ui/threats"', 'href="./threats.html"'),
        ('href="/ui/vision"', 'href="./vision.html"'),
        ('href="/ui/qualia"', 'href="./qualia.html"'),
        ('href="/ui/search"', 'href="./library.html"'),
        ('href="/ui/library"', 'href="./library.html"'),
        ('href="/ui/video"', 'href="./video.html"'),
        ('href="/ui/music"', 'href="./music.html"'),
        ('href="/ui/ace-step"', 'href="./music.html"'),
        ('href="/ui/wan21"', 'href="./wan21.html"'),
        ('href="/ui/skills"', 'href="./skills.html"'),
        ('href="/ui/help"', 'href="./help.html"'),
        ('href="/ui/playground"', 'href="./playground.html"'),
        ('href="/"', 'href="./index.html"'),
        ('href="/portal"', 'href="./index.html"'),
        ('href="/index.html"', 'href="./index.html"'),
    ]
    for old_ref, new_ref in link_replacements:
        html = html.replace(old_ref, new_ref)

    # Sovereign Showroom Top Banner
    showroom_banner = f"""
    <div id="sentinariShowroomBanner" style="background:linear-gradient(90deg, rgba(15,23,42,0.95) 0%, rgba(30,41,59,0.95) 100%);border-bottom:1px solid rgba(99,102,241,0.35);padding:10px 18px;display:flex;align-items:center;justify-content:space-between;font-size:12.5px;color:#cbd5e1;flex-wrap:wrap;gap:10px;position:relative;z-index:99999;box-shadow:0 4px 16px rgba(0,0,0,0.4);">
      <div style="display:flex;align-items:center;gap:10px;">
        <span style="display:inline-block;width:9px;height:9px;border-radius:50%;background:#10b981;box-shadow:0 0 8px #10b981;"></span>
        <span style="font-weight:700;color:#ffffff;letter-spacing:0.3px;">Sentinari Showroom &bull; {module_name}</span>
        <span style="background:rgba(99,102,241,0.22);color:#a5b4fc;border:1px solid rgba(99,102,241,0.45);padding:2px 8px;border-radius:12px;font-size:11px;font-weight:700;">Interactive Demonstration</span>
      </div>
      <div style="display:flex;align-items:center;gap:14px;">
        <a href="./index.html" style="color:#38bdf8;text-decoration:none;font-weight:700;display:inline-flex;align-items:center;gap:4px;">&larr; Frontpage Showroom</a>
        <a href="./oncology.html" style="color:#6ee7b7;text-decoration:none;font-weight:700;">Oncology Studio</a>
        <a href="./threats.html" style="color:#f87171;text-decoration:none;font-weight:700;">Threat Matrix</a>
        <a href="http://127.0.0.1:8099{local_port_route}" id="btnLocalSovereignConnect" target="_blank" rel="noopener" style="color:#6ee7b7;text-decoration:none;font-weight:700;background:rgba(16,185,129,0.18);padding:4px 12px;border-radius:14px;border:1px solid rgba(16,185,129,0.5);display:inline-flex;align-items:center;gap:6px;">
          <span>&#x26A1;</span> <span>Connect Local Engine (:8099)</span>
        </a>
      </div>
    </div>
    """

    # Inject banner right after <body>
    if "<body" in html:
        html = re.sub(r'(<body[^>]*>)', r'\1' + showroom_banner, html, count=1)

    # API Base definition injection before closing </head> or at start of <script>
    api_base_script = """
    <script>
      window.API_BASE = (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') ? 'http://127.0.0.1:8099' : '';
    </script>
    """
    if "</head>" in html:
        html = html.replace("</head>", f"{api_base_script}\n</head>", 1)

    with open(dst_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  -> Generated {dst_path} ({len(html)} bytes)")

# 1. Qualia Lab & Pseudo Dynamics
adapt_template_for_docs(
    os.path.join(TEMPLATES_DIR, "qualia_console.html"),
    os.path.join(DOCS_DIR, "qualia.html"),
    "Qualia Lab & Pseudo Dynamics",
    "/ui/qualia"
)

# 2. Search Library
adapt_template_for_docs(
    os.path.join(TEMPLATES_DIR, "search_workspace.html"),
    os.path.join(DOCS_DIR, "library.html"),
    "Sovereign Knowledge Search Library",
    "/ui/search"
)
shutil.copyfile(os.path.join(DOCS_DIR, "library.html"), os.path.join(DOCS_DIR, "search.html"))

# 3. Compact Video Editor & Workspace Tour Generator
adapt_template_for_docs(
    os.path.join(TEMPLATES_DIR, "wan_console.html"),
    os.path.join(DOCS_DIR, "video.html"),
    "Text-to-Video Editor & Tour Generator",
    "/ui/video"
)

# 4. ACE-Step 1.5 Music Studio
adapt_template_for_docs(
    os.path.join(TEMPLATES_DIR, "ace_step_workspace.html"),
    os.path.join(DOCS_DIR, "music.html"),
    "ACE-Step 1.5 Sovereign AI Music Studio",
    "/ui/ace-step"
)
shutil.copyfile(os.path.join(DOCS_DIR, "music.html"), os.path.join(DOCS_DIR, "ace-step.html"))

# 5. Wan 2.1 T2V-14B Cinematic Video Studio
adapt_template_for_docs(
    os.path.join(TEMPLATES_DIR, "wan21_workspace.html"),
    os.path.join(DOCS_DIR, "wan21.html"),
    "Wan 2.1 T2V-14B Cinematic Video Studio",
    "/ui/wan21"
)

# 6. Playground Workbench
adapt_template_for_docs(
    os.path.join(TEMPLATES_DIR, "playground_workbench.html"),
    os.path.join(DOCS_DIR, "playground.html"),
    "Playground & Candidate Ingestion Workbench",
    "/ui/playground"
)

print("\nAll 6 showcase HTML files created in docs/!")
