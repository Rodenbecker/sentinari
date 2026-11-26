"""
Generate docs/vision.html from templates/vision_workspace.html with relative GitHub Pages links
"""

from pathlib import Path

SRC = Path(r"D:\Sentinari\templates\vision_workspace.html")
DST = Path(r"D:\Sentinari\docs\vision.html")

def generate_vision_doc():
    html = SRC.read_text(encoding="utf-8")

    # Replace sidebar navigation with clean relative links
    old_nav_marker = '<nav class="nav">'
    old_nav_end = '</nav>'

    nav_start = html.find(old_nav_marker)
    nav_finish = html.find(old_nav_end, nav_start) + len(old_nav_end)

    github_nav = """<nav class="nav">
      <a href="https://www.patreon.com/Rodenbecker/posts/sentinari-173240973?utm_medium=clipboard_copy&utm_source=copyLink&utm_campaign=postshare_creator&utm_content=join_link" target="_blank" rel="noopener" style="border-color:#FF424D;background:rgba(255,66,77,0.14);color:#ff9da2;font-weight:700;">
        <svg viewBox="0 0 24 24" width="14" height="14" fill="#FF424D" style="vertical-align:middle;margin-right:4px;"><path d="M15.386.002c-4.764 0-8.64 3.876-8.64 8.64 0 4.75 3.876 8.613 8.64 8.613 4.75 0 8.614-3.864 8.614-8.613C24 3.878 20.136.002 15.386.002m-15.386 24h4.488V.002H0z"/></svg>
        Patreon Membership<small>Support sovereign research &amp; models.</small>
      </a>
      <a href="./vision.html" class="active" style="border-left:3px solid #00e5ff;color:#80d8ff;font-weight:700;">
        👁️ Vision Lab &amp; 3D Anatomy<small>Surgeon 3D Twins &bull; TDA Topology.</small>
      </a>
      <a href="./oncology.html" style="border-left:3px solid #10b981;font-weight:700;">
        🧬 Oncology Precision<small>Dedicated Clinical Synthesis Workspace.</small>
      </a>
      <a href="./threats.html" style="border-left:3px solid #ef4444;color:#fca5a5;font-weight:700;">
        🌍 Planetary Threat Matrix<small>Exogenous Early-Warning &bull; 14 Open APIs.</small>
      </a>
      <a href="./index.html">
        🏠 Dashboard Home<small>Showcase showroom portal.</small>
      </a>
      <a href="./skills.html">
        🧠 Skills Matrix<small>Autonomous competencies.</small>
      </a>
      <a href="./help.html">
        📖 Help Manual<small>Official operating reference &amp; FAQ.</small>
      </a>
      <a href="./Constitution.pdf" target="_blank" rel="noopener" style="border-top:1px solid rgba(255,255,255,0.12);margin-top:8px;padding-top:10px;color:#fbbf24;">
        📜 100-Year Constitution<small>Foundational sovereign charter (PDF).</small>
      </a>
    </nav>"""

    if nav_start != -1 and nav_finish != -1:
        html = html[:nav_start] + github_nav + html[nav_finish:]
        print("Injected GitHub Pages relative navigation into vision.html.")

    # Fix model loading URL for GitHub Pages
    html = html.replace("loadSTLModel('/api/vision/surgeon-recall/stream-model/apert-syndrome');", "loadSTLModel('./27_Apert syndrome.stl');")
    html = html.replace('href="/api/vision/surgeon-recall/stream-model/apert-syndrome"', 'href="./27_Apert syndrome.stl"')
    html = html.replace('/api/vision/surgeon-recall/stream-image/images/apert-syndrome_IMG1.png', './apert_syndrome_render.png')
    html = html.replace('/api/vision/surgeon-recall/stream-image/images/apert-syndrome_IMG2.png', './apert_syndrome_render.png')

    DST.write_text(html, encoding="utf-8")
    print(f"Successfully generated {DST} ({DST.stat().st_size} bytes)!")

if __name__ == "__main__":
    generate_vision_doc()
