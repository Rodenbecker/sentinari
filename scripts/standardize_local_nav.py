"""
Standardize Local Navigation Sidebar across all templates in D:\Sentinari\templates\
Ensures that clicking Dashboard Home always goes to /ui/playground,
and all workspaces (Qualia, Skills, Search, Patterns, Threats, Oncology, Vision) are directly accessible.
"""

from pathlib import Path

TEMPLATES_DIR = Path(r"D:\Sentinari\templates")

STANDARD_NAV = """    <nav class="nav">
      <a href="https://www.patreon.com/Rodenbecker/posts/sentinari-173240973?utm_medium=clipboard_copy&utm_source=copyLink&utm_campaign=postshare_creator&utm_content=join_link" target="_blank" rel="noopener" style="border-color:#FF424D;background:rgba(255,66,77,0.14);color:#ff9da2;font-weight:700;">
        <svg viewBox="0 0 24 24" width="14" height="14" fill="#FF424D" style="vertical-align:middle;margin-right:4px;"><path d="M15.386.002c-4.764 0-8.64 3.876-8.64 8.64 0 4.75 3.876 8.613 8.64 8.613 4.75 0 8.614-3.864 8.614-8.613C24 3.878 20.136.002 15.386.002m-15.386 24h4.488V.002H0z"/></svg>
        Patreon Membership<small>Support sovereign research &amp; models.</small>
      </a>
      <a href="/ui/playground" {active_playground}>&#x1F3E0; Dashboard Home (Playground)<small>Candidate uploads, datasets &amp; domains.</small></a>
      <a href="/ui/qualia" {active_qualia}>&#x2696;&#xFE0F; Qualia Lab<small>Pseudo Dynamics &amp; forensic deception audit.</small></a>
      <a href="/ui/skills" {active_skills}>&#x1F9E0; Skills Manager<small>Candidate pipeline &amp; paper review.</small></a>
      <a href="/ui/search" {active_search}>&#x1F50D; Search Library<small>Scientific library indices &amp; queries.</small></a>
      <a href="/ui/patterns" {active_patterns}>&#x1F52C; New Patterns<small>7-D Gaussian impact matrix.</small></a>
      <a href="/ui/threats" {active_threats} style="border-left:3px solid #ef4444;color:#fca5a5;font-weight:700;">&#x1F30D; Planetary Threat Matrix<small>Exogenous Early-Warning &bull; 14 Open APIs.</small></a>
      <a href="/ui/oncology" {active_oncology} style="border-left:3px solid #10b981;font-weight:700;">&#x1F9EC; Oncology Precision<small>Dedicated Clinical Synthesis &amp; Synergy.</small></a>
      <a href="/ui/vision" {active_vision} style="border-left:3px solid #00e5ff;color:#80d8ff;font-weight:700;">&#x1F441;&#xFE0F; Vision Lab &amp; 3D Anatomy<small>Surgeon 3D Twins &bull; TDA Topology.</small></a>
      <a href="/ui/direct" {active_direct}>&#x1F4AC; Chat Lab<small>Dedicated conversation console.</small></a>
      <a href="/ui/learning" {active_learning}>&#x1F4C8; Learning Index<small>% Learned, exams &amp; calibration.</small></a>
      <a href="/ui/video" {active_video}>&#x1F3A5; Video Studio<small>Autonomous tours &amp; neural narration.</small></a>
      <a href="/ui/ace-step" {active_acestep}>&#x1F3B5; ACE-Step 1.5 Music<small>AI soundscapes &amp; music.</small></a>
      <a href="/ui/wan21" {active_wan21}>&#x1F3AC; Wan 2.1 T2V-14B<small>14B cinematic video diffusion.</small></a>
      <a href="/ui/help" {active_help}>&#x1F4D6; Help Manual<small>Official operating reference &amp; FAQ.</small></a>
      <a href="/reports/the-constitution" target="_blank" rel="noopener" style="border-top:1px solid rgba(255,255,255,0.12);margin-top:8px;padding-top:10px;color:#fbbf24;">&#x1F4DC; 100-Year Constitution<small>Foundational sovereign charter.</small></a>
      <a href="/ui/admin" {active_admin}>⚙️ Admin Console<small>Settings, memory &amp; task board.</small></a>
      <a href="/" target="_blank">&#x1F310; Website Frontpage<small>Exit to Showcase Showroom.</small></a>
    </nav>"""

def update_template_nav(filename, active_key):
    p = TEMPLATES_DIR / filename
    if not p.exists():
        return
    text = p.read_text(encoding="utf-8")
    
    start_tag = '<nav class="nav">'
    end_tag = '</nav>'
    idx_start = text.find(start_tag)
    idx_end = text.find(end_tag, idx_start) + len(end_tag)

    if idx_start == -1 or idx_end == -1:
        print(f"Could not find nav in {filename}")
        return

    # Build nav with active class
    nav_filled = STANDARD_NAV
    keys = ["playground", "qualia", "skills", "search", "patterns", "threats", "oncology", "vision", "direct", "learning", "video", "acestep", "wan21", "help", "admin"]
    for k in keys:
        if k == active_key:
            nav_filled = nav_filled.replace(f"{{active_{k}}}", 'class="active"')
        else:
            nav_filled = nav_filled.replace(f"{{active_{k}}}", "")

    new_text = text[:idx_start] + nav_filled + text[idx_end:]
    p.write_text(new_text, encoding="utf-8")
    print(f"Successfully updated nav in {filename} (Active: {active_key})")

update_template_nav("threats_workspace.html", "threats")
update_template_nav("oncology.html", "oncology")
update_template_nav("vision_workspace.html", "vision")
