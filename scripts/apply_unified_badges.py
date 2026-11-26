import re
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

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

TARGET_FILES = [
    "D:/Sentinari/templates/portal_landing.html",
    "D:/Sentinari/docs/index.html",
    "D:/Sentinari/index.html",
    "D:/Sentinari/showcase_portal/index.html"
]

for p in TARGET_FILES:
    with open(p, "r", encoding="utf-8") as f:
        content = f.read()

    # CSS injection
    if ".novel-knowledge-tag" not in content:
        content = content.replace("</style>", f"{NEW_CSS}\n</style>", 1)

    # Navigation Oncology tag
    # Check for oncology link in nav
    nav_onco_match = re.search(r'(<a href="[^"]*oncology[^"]*"[^>]*style="[^"]*font-weight:700;[^"]*">[^<]*&#x1F9EC;[^<]*</a>)', content)
    if nav_onco_match and "onco-nav-tag" not in nav_onco_match.group(0):
        matched = nav_onco_match.group(0)
        # extract href
        href_match = re.search(r'href="([^"]*)"', matched)
        href = href_match.group(1) if href_match else "#oncology-workspace"
        replacement = f'<a href="{href}" style="color:#6ee7b7;font-weight:700;">&#x1F9EC; Oncology Workspace <span class="onco-nav-tag" title="135 Oncology Breakthroughs &bull; 9 Breast Cancer Discoveries" data-tooltip="Oncology &amp; Breast Cancer Portfolio: 135 verified Oncology Breakthroughs and 9 dedicated Breast Cancer Discoveries cataloged (including Rosmarinic Acid + Doxorubicin TNBC chemosensitization CI=0.380, BCAT1 metabolic reprogramming, and DTI Fractional Anisotropy predictive biomarkers) backed by 256 oncology papers." onclick="showOncoTooltip(event, this, \'Oncology &amp; Breast Cancer Discoveries\')">135 Breakthroughs &bull; 9 Breast Cancer <span class="info-pill" style="margin-left:2px;">?</span></span></a>'
        content = content.replace(matched, replacement, 1)

    # Oncology Workspace Section Pill Strip
    # Look for Sovereign Oncology Workspace or Sovereign Clinical Engine
    onco_section_match = re.search(r'(<span class="pill"[^>]*>&#x1F9EC;[^<]*</span>)', content)
    if onco_section_match and "onco-breakthrough-pill" not in content:
        orig_pill = onco_section_match.group(0)
        pill_strip = f"""<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:12px 0 18px 0;">
            {orig_pill}
            <span class="onco-breakthrough-pill" data-tooltip="Verified Oncology Portfolio: 135 total Oncology Breakthroughs cataloged across chemotherapy synergism, oncolytic virotherapy, immunotherapeutic kinetics, and radiomic precision. Includes 256 peer-reviewed clinical oncology papers in the sovereign library." onclick="showOncoTooltip(event, this, '135 Oncology Breakthroughs')">&#x1FA78; 135 Oncology Breakthroughs <span class="info-pill">?</span></span>
            <span class="breast-cancer-pill" data-tooltip="Breast Cancer Breakthrough Portfolio: 9 distinct discoveries cataloged, including Rosmarinic Acid + Doxorubicin TNBC chemosensitization (CI=0.380), BCAT1 BCAA metabolic reprogramming, DTI Fractional Anisotropy predictive biomarkers, CHEK1/TOP2A diagnostics, and IMRT cardiac risk reduction. Backed by 77 dedicated breast cancer clinical datasets." onclick="showOncoTooltip(event, this, '9 Breast Cancer Discoveries')">&#x1F397;&#xFE0F; 9 Breast Cancer Discoveries <span class="info-pill">?</span></span>
            <span class="novel-knowledge-tag" data-tooltip="Sovereign AI Oncology Synthesis: Novel cross-disciplinary knowledge synthesizing oncology, physics, pharmacology, and bioinformatics that did not previously exist in isolated single-domain literature." onclick="showOncoTooltip(event, this, 'New Oncology Knowledge')">&#x2728; (New knowledge that did exist before in an scientific domain) <span class="info-pill">?</span></span>
          </div>"""
        content = content.replace(orig_pill, pill_strip, 1)

    # Telemetry card: ensure New knowledge tag is present under portalPatternsCount
    if "novel-knowledge-tag" not in content:
        pat_card_match = re.search(r'(<div class="stat-value" id="portalPatternsCount">[^<]*</div>\s*<div class="stat-sub" id="portalPatternsSub">[^<]*</div>)', content)
        if pat_card_match:
            orig_stat = pat_card_match.group(0)
            new_stat = f"""{orig_stat}
          <div class="novel-knowledge-tag" title="Emergent cross-domain discovery" data-tooltip="Emergent Cross-Domain Discovery: 1,735 verified patterns synthesizing novel relationships between previously isolated scientific domains—establishing new scientific knowledge that did not exist before in any single scientific domain." onclick="showOncoTooltip(event, this, 'Novel Scientific Knowledge')">&#x2728; (New knowledge that did exist before in an scientific domain) <span class="info-pill" style="margin-left:2px;">?</span></div>"""
            content = content.replace(orig_stat, new_stat, 1)

    with open(p, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"Applied unified badges to {p}")
