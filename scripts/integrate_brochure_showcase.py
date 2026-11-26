import os
import shutil
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

DOCS_DIR = r"D:\Sentinari\docs"
src_pdf = os.path.join(DOCS_DIR, "Sentinari Brochure V2.pdf")
src_docx = os.path.join(DOCS_DIR, "Sentinari Brochure V2.docx")

dst_pdf_safename = os.path.join(DOCS_DIR, "Sentinari_Brochure_V2.pdf")
dst_docx_safename = os.path.join(DOCS_DIR, "Sentinari_Brochure_V2.docx")
dst_pdf_master = os.path.join(DOCS_DIR, "Sentinari_Master_Brochure.pdf")

print("Step 1: Creating space-free web safe copies...")
shutil.copyfile(src_pdf, dst_pdf_safename)
shutil.copyfile(src_docx, dst_docx_safename)
shutil.copyfile(src_pdf, dst_pdf_master)
print(f"Created: {dst_pdf_safename} ({os.path.getsize(dst_pdf_safename):,} bytes)")
print(f"Created: {dst_docx_safename} ({os.path.getsize(dst_docx_safename):,} bytes)")
print(f"Created: {dst_pdf_master} ({os.path.getsize(dst_pdf_master):,} bytes)")

TARGET_FILES = [
    r"D:\Sentinari\docs\index.html",
    r"D:\Sentinari\index.html",
    r"D:\Sentinari\showcase_portal\index.html",
    r"D:\Sentinari\templates\portal_landing.html"
]

BROCHURE_CARD_HTML = """
          <!-- 0) Sentinari Master Architectural Brochure V2 (Flagship Report) -->
          <div class="report-card" style="border-color: rgba(99, 102, 241, 0.55); background: linear-gradient(180deg, rgba(30, 27, 75, 0.5) 0%, rgba(15, 23, 42, 0.95) 100%); grid-column: 1 / -1; box-shadow: 0 8px 32px rgba(99, 102, 241, 0.2);">
            <div>
              <span class="report-badge" style="background: rgba(99, 102, 241, 0.25); color: #c7d2fe; border-color: rgba(99, 102, 241, 0.55);">&#x1F4D8; Flagship Publication &bull; PDF (14.1 MB) &bull; DOCX (13.9 MB) &bull; 43 Annotated Figures</span>
              <h3 style="color: #ffffff; font-size: 1.45rem; margin-top: 8px;">Sentinari Master Architectural Brochure V2</h3>
              <div class="report-sub" style="color: #818cf8; font-weight: 700;">Conceived &amp; Architected by Dr. Pierre C. Wepener &bull; Full Operational &amp; Epistemic Telemetry</div>
              <p class="report-desc" style="font-size: 0.95rem; line-height: 1.6; color: #cbd5e1;">
                The authoritative 88-page master architectural monograph detailing Sentinari's sovereign cognitive architecture. Includes <b>43 fully annotated high-resolution screen dumps</b> with dedicated architectural notes explaining the decoupled Epistemic Vault, Aristotle's four causes, 7-D Gaussian Assessment Matrix, Chou-Talalay oncology synergy simulator (Pattern #24), Pseudo Dynamics deception auditing, and the 3D Apert syndrome anatomical twin engine.
              </p>
              <ul class="report-highlights" style="display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 10px; margin-top: 14px;">
                <li><span>&#x25B8;</span><span><b>43 Annotated Screen Dumps:</b> Comprehensive notes under every figure explaining UI operations, telemetry meters, and mathematical proofs.</span></li>
                <li><span>&#x25B8;</span><span><b>Decoupled Epistemic Vault:</b> SQLite empirical substrate (17,061 works, 1.25M Article V claims) divorced from local Gemma ONNX inference.</span></li>
                <li><span>&#x25B8;</span><span><b>Oncology &amp; Breast Cancer:</b> Full documentation of 135 Oncology Breakthroughs and 9 dedicated Breast Cancer discoveries (TNBC synergy CI=0.380).</span></li>
                <li><span>&#x25B8;</span><span><b>Zero-Cloud Hardware Tuning:</b> Bare-metal optimization for AMD Ryzen 9 9900X and NVIDIA RTX 5070 Ti (16 GB VRAM).</span></li>
              </ul>
            </div>
            <div class="report-actions" style="margin-top: 20px; display: flex; flex-wrap: wrap; gap: 12px; align-items: center;">
              <a href="./Sentinari_Brochure_V2.pdf" target="_blank" rel="noopener" class="btn-report-primary" style="background: linear-gradient(135deg, #4f46e5, #4338ca); border-color: #6366f1; font-weight: 800; padding: 10px 22px; font-size: 0.95rem; display: inline-flex; align-items: center; gap: 8px;">
                <span>&#x1F4D6;</span> <span>Open Master Brochure V2 (PDF)</span>
              </a>
              <a href="./Sentinari_Brochure_V2.pdf" download="Sentinari_Master_Architectural_Brochure_V2.pdf" class="btn-report-secondary" style="border-color: #818cf8; color: #c7d2fe; font-weight: 700; padding: 10px 18px; display: inline-flex; align-items: center; gap: 6px;">
                <span>&#x2B07;</span> <span>Download PDF (14.1 MB)</span>
              </a>
              <a href="./Sentinari_Brochure_V2.docx" download="Sentinari_Master_Architectural_Brochure_V2.docx" class="btn-report-secondary" style="border-color: #38bdf8; color: #7dd3fc; font-weight: 700; padding: 10px 18px; display: inline-flex; align-items: center; gap: 6px;">
                <span>&#x1F4C4;</span> <span>Download Word (.docx 13.9 MB)</span>
              </a>
            </div>
          </div>
"""

for p in TARGET_FILES:
    if not os.path.exists(p):
        continue
    print(f"\nProcessing {p}...")
    with open(p, "r", encoding="utf-8") as f:
        html = f.read()

    # 1. Add to Navigation bar
    if 'href="./Sentinari_Brochure_V2.pdf"' not in html:
        # Insert in nav-links right after Constitution
        const_link = '<a href="./Constitution.pdf" target="_blank" rel="noopener" target="_blank" rel="noopener" style="color:#fbbf24;font-weight:700;">&#x1F4DC; Constitution</a>'
        if const_link not in html:
            const_link = '<a href="./Constitution.pdf" target="_blank" rel="noopener" style="color:#fbbf24;font-weight:700;">&#x1F4DC; Constitution</a>'
        
        new_nav_item = f'{const_link}\n        <a href="./Sentinari_Brochure_V2.pdf" target="_blank" rel="noopener" style="color:#38bdf8;font-weight:700;">&#x1F4D8; Brochure V2</a>'
        if const_link in html:
            html = html.replace(const_link, new_nav_item, 1)

    # 2. Add to Sub-ribbon (Featured Publications)
    if '<span>📘</span> <strong>Master Brochure V2</strong>' not in html:
        old_pub_tag = '<span class="nav-sub-badge">Featured Publications</span>'
        new_pub_tag = f"""<span class="nav-sub-badge">Featured Publications</span>
          <a href="./Sentinari_Brochure_V2.pdf" target="_blank" rel="noopener" class="nav-sub-link">
            <span>📘</span> <strong>Master Brochure V2</strong>
          </a>
          <span class="nav-sub-divider">&bull;</span>"""
        if old_pub_tag in html:
            html = html.replace(old_pub_tag, new_pub_tag, 1)

    # 3. Add to Hero CTA Group
    if 'Open Research Console' in html and 'Sentinari_Brochure_V2.pdf' not in html.split('Open Research Console')[0]:
        cta_target = '<a href="./oncology.html" target="_blank" rel="noopener" class="btn-primary">Open Research Console</a>'
        brochure_hero_btn = '<a href="./Sentinari_Brochure_V2.pdf" target="_blank" rel="noopener" class="btn-secondary" style="border-color:#818cf8;color:#c7d2fe;background:rgba(99,102,241,0.14);"><span>📘</span> <span>Master Brochure V2 (PDF)</span></a>\n          '
        if cta_target in html:
            html = html.replace(cta_target, brochure_hero_btn + cta_target, 1)

    # 4. Add Flagship Brochure Card to Reports Grid
    if 'Sentinari Master Architectural Brochure V2' not in html:
        grid_target = '<div class="reports-grid">'
        if grid_target in html:
            html = html.replace(grid_target, f"{grid_target}\n{BROCHURE_CARD_HTML}", 1)

    # 5. Add to Footer
    if 'Brochure V2' not in html.split('</footer>')[0] if '</footer>' in html else '':
        footer_admin = '<a href="./qualia.html"'
        if '<a href="https://github.com/Rodenbecker/sentinari"' in html:
            html = html.replace(
                '<a href="https://github.com/Rodenbecker/sentinari"',
                '<a href="./Sentinari_Brochure_V2.pdf" target="_blank" rel="noopener" style="color:#818cf8;font-weight:700;">📘 Master Brochure V2 (PDF)</a>\n        <a href="https://github.com/Rodenbecker/sentinari"',
                1
            )

    with open(p, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Successfully integrated Brochure V2 showcase features into {p}")

print("\nDone integrating brochure into all landing page files!")
