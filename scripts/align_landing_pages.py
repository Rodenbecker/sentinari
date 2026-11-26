import re
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

FILES = [
    "D:/Sentinari/docs/index.html",
    "D:/Sentinari/index.html",
    "D:/Sentinari/showcase_portal/index.html",
    "D:/Sentinari/templates/portal_landing.html",
]

NEW_CSS = """
  /* ======================================================== */
  /* NOVEL KNOWLEDGE DISCOVERY & ONCOLOGY / BREAST CANCER TAGS */
  /* ======================================================== */
  .novel-knowledge-tag {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    background: rgba(129, 140, 248, 0.16);
    border: 1px solid rgba(129, 140, 248, 0.45);
    color: #c7d2fe;
    font-size: 0.74rem;
    font-weight: 700;
    padding: 3px 10px;
    border-radius: 9999px;
    cursor: pointer;
    transition: all 0.2s ease;
    margin-top: 6px;
    text-transform: none;
    letter-spacing: 0.2px;
  }
  .novel-knowledge-tag:hover {
    background: rgba(129, 140, 248, 0.32);
    border-color: #818cf8;
    color: #ffffff;
    transform: translateY(-1px);
    box-shadow: 0 0 14px rgba(129, 140, 248, 0.45);
  }
  .onco-nav-tag {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    background: linear-gradient(135deg, rgba(236, 72, 153, 0.22) 0%, rgba(16, 185, 129, 0.22) 100%);
    border: 1px solid rgba(236, 72, 153, 0.55);
    color: #fbcfe8;
    font-size: 0.72rem;
    font-weight: 700;
    padding: 2px 8px;
    border-radius: 9999px;
    margin-left: 6px;
    cursor: pointer;
    transition: all 0.2s ease;
    vertical-align: middle;
    text-transform: none;
  }
  .onco-nav-tag:hover {
    background: linear-gradient(135deg, rgba(236, 72, 153, 0.4) 0%, rgba(16, 185, 129, 0.4) 100%);
    border-color: #f472b6;
    color: #ffffff;
    box-shadow: 0 0 12px rgba(236, 72, 153, 0.5);
  }
  .onco-breakthrough-pill {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    background: linear-gradient(135deg, rgba(16, 185, 129, 0.15) 0%, rgba(6, 182, 212, 0.15) 100%);
    border: 1px solid rgba(16, 185, 129, 0.45);
    color: #6ee7b7;
    font-size: 0.78rem;
    font-weight: 700;
    padding: 5px 12px;
    border-radius: 8px;
    cursor: pointer;
    transition: all 0.2s ease;
  }
  .onco-breakthrough-pill:hover {
    border-color: #34d399;
    box-shadow: 0 0 14px rgba(16, 185, 129, 0.4);
    transform: translateY(-1px);
  }
  .breast-cancer-pill {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    background: linear-gradient(135deg, rgba(236, 72, 153, 0.2) 0%, rgba(244, 114, 182, 0.15) 100%);
    border: 1px solid rgba(236, 72, 153, 0.55);
    color: #fbcfe8;
    font-size: 0.78rem;
    font-weight: 700;
    padding: 5px 12px;
    border-radius: 8px;
    cursor: pointer;
    transition: all 0.2s ease;
  }
  .breast-cancer-pill:hover {
    border-color: #f472b6;
    box-shadow: 0 0 14px rgba(236, 72, 153, 0.45);
    transform: translateY(-1px);
  }
"""

for path in FILES:
    print(f"Processing {path}...")
    with open(path, "r", encoding="utf-8") as f:
        html = f.read()

    # 1. Add CSS if not present
    if ".novel-knowledge-tag" not in html:
        target_css = ".onco-tooltip-close:hover { color: #f43f5e; }\n</style>"
        replacement_css = f".onco-tooltip-close:hover {{ color: #f43f5e; }}\n{NEW_CSS}\n</style>"
        if target_css in html:
            html = html.replace(target_css, replacement_css, 1)
        else:
            html = html.replace("</style>", f"{NEW_CSS}\n</style>", 1)

    # 2. Update Navigation Patterns Count & Oncology tag
    nav_old = re.search(r'<a href="(?:\./)?#deliverables"[^>]*>New Patterns \(<span id="navPatternsCount">[^<]*</span>\)</a>', html)
    if nav_old:
        nav_new = '<a href="./#deliverables" target="_blank" rel="noopener">New Patterns (<span id="navPatternsCount">1,735</span>)</a>'
        html = html.replace(nav_old.group(0), nav_new, 1)

    # Add Oncology nav tag if not present
    onco_nav_old = '<a href="#oncology-workspace" style="color:#6ee7b7;font-weight:700;">&#x1F9EC; Oncology Workspace</a>'
    onco_nav_new = '<a href="#oncology-workspace" style="color:#6ee7b7;font-weight:700;">&#x1F9EC; Oncology Workspace <span class="onco-nav-tag" title="135 Oncology Breakthroughs &bull; 9 Breast Cancer Discoveries" data-tooltip="Oncology &amp; Breast Cancer Portfolio: 135 verified Oncology Breakthroughs and 9 dedicated Breast Cancer Discoveries cataloged (including Rosmarinic Acid + Doxorubicin TNBC chemosensitization CI=0.380, BCAT1 metabolic reprogramming, and DTI Fractional Anisotropy predictive biomarkers) backed by 256 oncology papers." onclick="showOncoTooltip(event, this, \'Oncology &amp; Breast Cancer Discoveries\')">135 Breakthroughs &bull; 9 Breast Cancer <span class="info-pill" style="margin-left:2px;">?</span></span></a>'
    if onco_nav_old in html:
        html = html.replace(onco_nav_old, onco_nav_new, 1)

    # 3. Update CTA buttons
    cta_pat_old = re.search(r'<a href="(?:\./)?#deliverables"[^>]*class="btn-secondary">New Pattern Discoveries \(<span id="ctaPatternsCount">[^<]*</span>\)</a>', html)
    if cta_pat_old:
        cta_pat_new = '<a href="./#deliverables" target="_blank" rel="noopener" class="btn-secondary">New Pattern Discoveries (<span id="ctaPatternsCount">1,735</span>)</a>'
        html = html.replace(cta_pat_old.group(0), cta_pat_new, 1)

    cta_onco_old = '<a href="#global-reports" class="btn-secondary">Oncology Breakthrough &amp; Global Reports (4)</a>'
    cta_onco_new = '<a href="#global-reports" class="btn-secondary">&#x1F9EC; Oncology Breakthroughs (135) &bull; Breast Cancer (9)</a>'
    if cta_onco_old in html:
        html = html.replace(cta_onco_old, cta_onco_new, 1)

    # 4. Update Telemetry Cards: New Pattern Discoveries card & Curated Works
    # Replace portalPatternsCount
    html = re.sub(
        r'<div class="stat-value" id="portalPatternsCount">(?:278|{{PATTERNS_COUNT}})</div>\s*<div class="stat-sub" id="portalPatternsSub">[^<]*</div>',
        '<div class="stat-value" id="portalPatternsCount">1,735</div>\n          <div class="stat-sub" id="portalPatternsSub">7,287 datasets analyzed &bull; 15-Indicator R&amp;D Papers &bull; 7-D Gaussian Matrix</div>\n          <div class="novel-knowledge-tag" title="Emergent cross-domain discovery" data-tooltip="Emergent Cross-Domain Discovery: 1,735 verified patterns synthesizing novel relationships between previously isolated scientific domains—establishing new scientific knowledge that did not exist before in any single scientific domain." onclick="showOncoTooltip(event, this, \'Novel Scientific Knowledge\')">&#x2728; (New knowledge that did exist before in an scientific domain) <span class="info-pill" style="margin-left:2px;">?</span></div>',
        html
    )

    # Also update Curated Works to 17,061
    html = re.sub(
        r'<div class="stat-value" id="portalDocsCount">(?:15,415|{{DOCS_COUNT}})</div>\s*<div class="stat-sub">[^<]*</div>',
        '<div class="stat-value" id="portalDocsCount">17,061</div>\n          <div class="stat-sub">100.0% Peer-reviewed papers assessed by Gemma</div>',
        html
    )

    # 5. Update Oncology Workspace Header pill strip
    onco_pill_old = '<span class="pill" style="background:rgba(16,185,129,0.15);border-color:rgba(16,185,129,0.4);color:#6ee7b7;font-weight:700;">&#x1F9EC; Sovereign Clinical Engine</span>'
    onco_pill_new = """<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:12px 0 18px 0;">
            <span class="pill" style="background:rgba(16,185,129,0.15);border-color:rgba(16,185,129,0.4);color:#6ee7b7;font-weight:700;">&#x1F9EC; Sovereign Clinical Engine</span>
            <span class="onco-breakthrough-pill" data-tooltip="Verified Oncology Portfolio: 135 total Oncology Breakthroughs cataloged across chemotherapy synergism, oncolytic virotherapy, immunotherapeutic kinetics, and radiomic precision. Includes 256 peer-reviewed clinical oncology papers in the sovereign library." onclick="showOncoTooltip(event, this, '135 Oncology Breakthroughs')">&#x1FA78; 135 Oncology Breakthroughs <span class="info-pill">?</span></span>
            <span class="breast-cancer-pill" data-tooltip="Breast Cancer Breakthrough Portfolio: 9 distinct discoveries cataloged, including Rosmarinic Acid + Doxorubicin TNBC chemosensitization (CI=0.380), BCAT1 BCAA metabolic reprogramming, DTI Fractional Anisotropy predictive biomarkers, CHEK1/TOP2A diagnostics, and IMRT cardiac risk reduction. Backed by 77 dedicated breast cancer clinical datasets." onclick="showOncoTooltip(event, this, '9 Breast Cancer Discoveries')">&#x1F397;&#xFE0F; 9 Breast Cancer Discoveries <span class="info-pill">?</span></span>
            <span class="novel-knowledge-tag" data-tooltip="Sovereign AI Oncology Synthesis: Novel cross-disciplinary knowledge synthesizing oncology, physics, pharmacology, and bioinformatics that did not previously exist in isolated single-domain literature." onclick="showOncoTooltip(event, this, 'New Oncology Knowledge')">&#x2728; (New knowledge that did exist before in an scientific domain) <span class="info-pill">?</span></span>
          </div>"""
    if onco_pill_old in html and "onco-breakthrough-pill" not in html:
        html = html.replace(onco_pill_old, onco_pill_new, 1)

    # 6. Update Concertina Part 1 pill (if 21 Sentinel Disciplines)
    html = re.sub(
        r'<span class="pill" style="background:rgba\(56,189,248,0\.15\);border-color:rgba\(56,189,248,0\.4\);color:#38bdf8;">21 Sentinel Disciplines &bull; [^<]*</span>',
        '<span class="pill" style="background:rgba(56,189,248,0.15);border-color:rgba(56,189,248,0.4);color:#38bdf8;">21 Sentinel Disciplines &bull; 1,735 Discoveries</span>',
        html
    )

    # 7. Update any localhost:8000 links to 127.0.0.1:8099
    html = html.replace("http://localhost:8000", "http://127.0.0.1:8099")

    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Successfully updated {path}")
