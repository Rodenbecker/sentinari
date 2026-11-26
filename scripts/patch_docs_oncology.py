"""
Patch navigation links in docs/oncology.html to ensure 100% working relative links for GitHub Pages
"""

from pathlib import Path

ONCOLOGY_DOC = Path(r"D:\Sentinari\docs\oncology.html")

def patch_oncology():
    text = ONCOLOGY_DOC.read_text(encoding="utf-8")

    # Fix sidebar navigation
    old_nav = """    <nav class="nav">
      <a href="https://www.patreon.com/Rodenbecker/posts/sentinari-173240973?utm_medium=clipboard_copy&utm_source=copyLink&utm_campaign=postshare_creator&utm_content=join_link" target="_blank" rel="noopener" style="border-color:#FF424D;background:rgba(255,66,77,0.14);color:#ff9da2;font-weight:700;">
        <svg viewBox="0 0 24 24" width="14" height="14" fill="#FF424D" style="vertical-align:middle;margin-right:4px;"><path d="M15.386.002c-4.764 0-8.64 3.876-8.64 8.64 0 4.75 3.876 8.613 8.64 8.613 4.75 0 8.614-3.864 8.614-8.613C24 3.878 20.136.002 15.386.002m-15.386 24h4.488V.002H0z"/></svg>
        Patreon Membership<small>Support sovereign cancer research.</small>
      </a>
      <a href="/ui/oncology" class="active">&#x1F9EC; Oncology Precision<small>Dedicated Clinical Synthesis Workspace.</small></a>
      <a href="./threats.html" style="border-left:3px solid #ef4444;color:#fca5a5;font-weight:700;">&#x1F30D; Planetary Threat Matrix<small>Exogenous Early-Warning &bull; 14 Open APIs.</small></a>
      <a href="/ui/patterns">&#x1F52C; New Patterns<small>7-D Gaussian impact matrix.</small></a>
      <a href="/ui/playground">&#x1F3E0; Dashboard Home<small>Summary, domains &amp; downloads.</small></a>
      <a href="/ui/qualia">&#x2696;&#xFE0F; Qualia Lab<small>Courtroom forensic deception audit.</small></a>
      <a href="/ui/direct">&#x1F4AC; Chat Lab<small>Dedicated conversation console.</small></a>
      <a href="/ui/learning">&#x1F4C8; Learning Index<small>% Learned, exams &amp; calibration.</small></a>
      <a href="/ui/video">&#x1F3A5; Video Studio<small>Autonomous tours &amp; neural narration.</small></a>
      <a href="/ui/ace-step">&#x1F3B5; ACE-Step 1.5 Music<small>AI soundscapes &amp; music.</small></a>
      <a href="/ui/wan21">&#x1F3AC; Wan 2.1 T2V-14B<small>14B cinematic video diffusion.</small></a>
      <a href="/ui/search">&#x1F50D; Search Library<small>Ingested scientific archives.</small></a>
      <a href="/ui/help">&#x1F4D6; Help Manual<small>Official operating reference &amp; FAQ.</small></a>
      <a href="/reports/the-constitution" target="_blank" rel="noopener" style="border-top:1px solid rgba(255,255,255,0.12);margin-top:8px;padding-top:10px;color:#fbbf24;">&#x1F4DC; 100-Year Constitution<small>Foundational sovereign charter.</small></a>
      <a href="./index.html">&#x1F310; Website Frontpage<small>Showcase showroom portal.</small></a>
    </nav>"""

    new_nav = """    <nav class="nav">
      <a href="https://www.patreon.com/Rodenbecker/posts/sentinari-173240973?utm_medium=clipboard_copy&utm_source=copyLink&utm_campaign=postshare_creator&utm_content=join_link" target="_blank" rel="noopener" style="border-color:#FF424D;background:rgba(255,66,77,0.14);color:#ff9da2;font-weight:700;">
        <svg viewBox="0 0 24 24" width="14" height="14" fill="#FF424D" style="vertical-align:middle;margin-right:4px;"><path d="M15.386.002c-4.764 0-8.64 3.876-8.64 8.64 0 4.75 3.876 8.613 8.64 8.613 4.75 0 8.614-3.864 8.614-8.613C24 3.878 20.136.002 15.386.002m-15.386 24h4.488V.002H0z"/></svg>
        Patreon Membership<small>Support sovereign cancer research.</small>
      </a>
      <a href="./oncology.html" class="active" style="border-left:3px solid #10b981;font-weight:700;">&#x1F9EC; Oncology Precision<small>Dedicated Clinical Synthesis Workspace.</small></a>
      <a href="./threats.html" style="border-left:3px solid #ef4444;color:#fca5a5;font-weight:700;">&#x1F30D; Planetary Threat Matrix<small>Exogenous Early-Warning &bull; 14 Open APIs.</small></a>
      <a href="./vision.html" style="border-left:3px solid #00e5ff;color:#80d8ff;font-weight:700;">&#x1F441;&#xFE0F; Vision Lab &amp; 3D Anatomy<small>Surgeon 3D Twins &bull; TDA Topology.</small></a>
      <a href="./index.html">&#x1F3E0; Dashboard Home<small>Showcase showroom portal.</small></a>
      <a href="./skills.html">&#x1F9E0; Skills Matrix<small>Autonomous competencies.</small></a>
      <a href="./help.html">&#x1F4D6; Help Manual<small>Official operating reference &amp; FAQ.</small></a>
      <a href="./Constitution.pdf" target="_blank" rel="noopener" style="border-top:1px solid rgba(255,255,255,0.12);margin-top:8px;padding-top:10px;color:#fbbf24;">&#x1F4DC; 100-Year Constitution<small>Foundational sovereign charter (PDF).</small></a>
      <a href="./Sentinari_Cancer_Breakthrough_Pattern_24_Dossier.pdf" target="_blank" rel="noopener" style="color:#6ee7b7;">&#x1F4D1; Breakthrough Dossier<small>Pattern #24 Clinical Paper (PDF).</small></a>
    </nav>"""

    if old_nav in text:
        text = text.replace(old_nav, new_nav, 1)
        print("Replaced old nav in docs/oncology.html.")
    else:
        # Fallback regex/replace
        text = text.replace('href="/ui/oncology"', 'href="./oncology.html"')
        text = text.replace('href="/reports/the-constitution"', 'href="./Constitution.pdf"')
        text = text.replace('href="/reports/cancer-breakthrough"', 'href="./Sentinari_Cancer_Breakthrough_Pattern_24_Dossier.pdf"')
        text = text.replace('href="/reports/cancer-breakthrough?download=1"', 'href="./Sentinari_Cancer_Breakthrough_Pattern_24_Dossier.pdf"')
        text = text.replace('href="/ui/help"', 'href="./help.html"')
        text = text.replace('href="/ui/playground"', 'href="./index.html"')
        print("Fallback replaced root links in docs/oncology.html.")

    # Also replace any other /reports/ or /ui/ links
    text = text.replace('href="/reports/the-constitution"', 'href="./Constitution.pdf"')
    text = text.replace('href="/reports/cancer-breakthrough"', 'href="./Sentinari_Cancer_Breakthrough_Pattern_24_Dossier.pdf"')
    text = text.replace('href="/reports/cancer-breakthrough?download=1"', 'href="./Sentinari_Cancer_Breakthrough_Pattern_24_Dossier.pdf"')

    ONCOLOGY_DOC.write_text(text, encoding="utf-8")
    print("Successfully patched docs/oncology.html!")

if __name__ == "__main__":
    patch_oncology()
