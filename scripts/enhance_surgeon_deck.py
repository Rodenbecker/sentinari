"""
Enhance Surgeon 3D Deck in templates/vision_workspace.html with:
- Healthy Mode vs Pathological Mode Toggle
- WHO ICD-10 & RadLex ontological telemetry
- Clinical 2D Photography and Radiographic Plate Carousel
"""

import re
from pathlib import Path

WORKSPACE_PATH = Path(r"D:\Sentinari\templates\vision_workspace.html")

def enhance_deck():
    html = WORKSPACE_PATH.read_text(encoding="utf-8")

    # Replace the controls row to include Mode Toggle
    old_controls = """      <!-- Controls Row -->
      <div style="display:grid; grid-template-columns: 1.2fr 1fr auto; gap:12px; margin-bottom:14px; align-items:end;">
        <div>
          <label style="font-size:11.5px; font-weight:700; color:#b0bec5; display:block; margin-bottom:4px;">
            Clinical Case / Specimen Preset
          </label>
          <select id="surgeonCaseSelect" class="control-select" style="width:100%;">
            <option value="apert-syndrome" selected>Apert syndrome (11yo male - 2.93M facets, bicoronal synostosis)</option>
            <option value="apert-syndrome-after-surgery">Apert Syndrome after Surgery (Post-operative reconstruction)</option>
            <option value="craniectomy-at-craniostenosis">Craniectomy at Craniostenosis (Fronto-orbital advancement)</option>
            <option value="anomaly-of-the-embryonic-development-of-the-aortic-arch">Aortic Arch Embryonic Anomaly (Congenital Vascular)</option>
            <option value="double-outlet-right-ventricle-in-tetralogy-of-fallot">Double Outlet Right Ventricle in Tetralogy of Fallot</option>
            <option value="calcaneus">Calcaneus (3D Calcaneal Simplicial Complex)</option>
            <option value="breastbone">Breastbone / Sternum (Thoracic cage)</option>
            <option value="fallen-soldiers-skull-1809">Fallen Soldier's Skull 1809 (Historical cranial ballistics &amp; trauma)</option>
            <option value="clavicle">Clavicle (Orthopedic fracture baseline)</option>
            <option value="mandible-scanned">Mandible Scanned Reconstruction</option>
          </select>
        </div>
        <div>
          <label style="font-size:11.5px; font-weight:700; color:#b0bec5; display:block; margin-bottom:4px;">
            Surgeon SBAR Query / Diagnostic Findings
          </label>
          <input type="text" id="surgeonQueryInput" class="control-input" style="width:100%;" placeholder="e.g. turribrachycephaly, coronal suture synostosis, midface retrusion">
        </div>
        <div>
          <button id="btnSurgeonRecall" class="btn btn-emerald" style="height:38px; white-space:nowrap; padding:0 18px;">
            🧠 Recall 3D Model with Gemma
          </button>
        </div>
      </div>"""

    new_controls = """      <!-- Clinical Evaluation Mode & ICD-10 Bar -->
      <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px; margin-bottom:12px; background:#0b131e; border:1px solid #16263b; border-radius:8px; padding:8px 14px;">
        <div style="display:flex; align-items:center; gap:8px;">
          <span style="font-size:11.5px; font-weight:700; color:#b0bec5;">EVALUATION MODE:</span>
          <button id="btnModePathology" class="btn btn-emerald" style="font-size:11px; padding:3px 10px; height:28px;">
            🩺 Pathological Anomaly Mode
          </button>
          <button id="btnModeHealthy" class="btn btn-outline" style="font-size:11px; padding:3px 10px; height:28px; color:#80d8ff; border-color:#80d8ff;">
            ✨ Healthy Baseline Mode (Ideal Twin)
          </button>
        </div>
        <div style="display:flex; align-items:center; gap:8px;">
          <span id="icd10Pill" class="pill pill-cyan" style="font-size:11px; font-weight:800; letter-spacing:0.5px;">
            WHO ICD-10: Q75.0 &bull; RadLex: RID39049
          </span>
          <span id="genePill" class="pill pill-purple" style="font-size:11px; font-weight:800;">
            Gene: FGFR2
          </span>
        </div>
      </div>

      <!-- Controls Row -->
      <div style="display:grid; grid-template-columns: 1.2fr 1fr auto; gap:12px; margin-bottom:14px; align-items:end;">
        <div>
          <label style="font-size:11.5px; font-weight:700; color:#b0bec5; display:block; margin-bottom:4px;">
            Clinical Case / Specimen Preset
          </label>
          <select id="surgeonCaseSelect" class="control-select" style="width:100%;">
            <option value="apert-syndrome" selected>Apert syndrome (11yo male - 2.93M facets, bicoronal synostosis)</option>
            <option value="apert-syndrome-after-surgery">Apert Syndrome after Surgery (Post-operative reconstruction)</option>
            <option value="craniectomy-at-craniostenosis">Craniectomy at Craniostenosis (Fronto-orbital advancement)</option>
            <option value="anomaly-of-the-embryonic-development-of-the-aortic-arch">Aortic Arch Embryonic Anomaly (Congenital Vascular)</option>
            <option value="double-outlet-right-ventricle-in-tetralogy-of-fallot">Double Outlet Right Ventricle in Tetralogy of Fallot</option>
            <option value="calcaneus">Calcaneus (3D Calcaneal Simplicial Complex)</option>
            <option value="breastbone">Breastbone / Sternum (Thoracic cage)</option>
            <option value="fallen-soldiers-skull-1809">Fallen Soldier's Skull 1809 (Historical cranial ballistics &amp; trauma)</option>
            <option value="clavicle">Clavicle (Orthopedic fracture baseline)</option>
            <option value="mandible-scanned">Mandible Scanned Reconstruction</option>
          </select>
        </div>
        <div>
          <label style="font-size:11.5px; font-weight:700; color:#b0bec5; display:block; margin-bottom:4px;">
            Surgeon SBAR Query / Diagnostic Findings
          </label>
          <input type="text" id="surgeonQueryInput" class="control-input" style="width:100%;" placeholder="e.g. turribrachycephaly, coronal suture synostosis, midface retrusion">
        </div>
        <div>
          <button id="btnSurgeonRecall" class="btn btn-emerald" style="height:38px; white-space:nowrap; padding:0 18px;">
            🧠 Recall 3D Model with Gemma
          </button>
        </div>
      </div>"""

    if old_controls in html:
        html = html.replace(old_controls, new_controls, 1)
        print("Updated controls with Healthy/Pathology mode toggle and ICD-10 pill.")

    # Add 2D Clinical Photography Strip right under the Three.js canvas box
    canvas_box_target = """            <div id="threeOverlayStats" style="position:absolute; bottom:10px; left:12px; pointer-events:none; font-size:11px; color:#90a4ae; background:rgba(7, 13, 20, 0.75); padding:6px 10px; border-radius:6px; border:1px solid #1e334d;">
              <div>Dimensions: <span id="overlayDims" style="color:#00e5ff; font-weight:700;">98.0 &times; 126.6 &times; 123.7 mm</span></div>
              <div>Facets: <span id="overlayFacets" style="color:#69f0ae; font-weight:700;">2,935,132</span> | Volume: <span id="overlayVol" style="color:#b388ff; font-weight:700;">60.9 mL</span></div>
            </div>
          </div>
        </div>"""

    new_canvas_box = """            <div id="threeOverlayStats" style="position:absolute; bottom:10px; left:12px; pointer-events:none; font-size:11px; color:#90a4ae; background:rgba(7, 13, 20, 0.75); padding:6px 10px; border-radius:6px; border:1px solid #1e334d;">
              <div>Dimensions: <span id="overlayDims" style="color:#00e5ff; font-weight:700;">98.0 &times; 126.6 &times; 123.7 mm</span></div>
              <div>Facets: <span id="overlayFacets" style="color:#69f0ae; font-weight:700;">2,935,132</span> | Volume: <span id="overlayVol" style="color:#b388ff; font-weight:700;">60.9 mL</span></div>
            </div>
          </div>

          <!-- Clinical 2D Photography & Radiographic Plate Gallery -->
          <div style="background:#0b131e; border-top:1px solid #16263b; padding:10px 12px;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
              <span style="font-size:11px; font-weight:700; color:#8fa0b5;">📷 Verified Clinical Plates &amp; Radiographic Views:</span>
              <span id="imgGalleryCount" style="font-size:10px; color:#00e5ff;">2 Plates Loaded</span>
            </div>
            <div id="clinicalImageThumbnails" style="display:flex; gap:8px; overflow-x:auto; padding-bottom:4px;">
              <a href="/api/vision/surgeon-recall/stream-image/images/apert-syndrome_IMG1.png" target="_blank" rel="noopener">
                <img src="/api/vision/surgeon-recall/stream-image/images/apert-syndrome_IMG1.png" style="height:60px; border-radius:6px; border:1px solid #1e334d; object-fit:cover; cursor:pointer;" alt="Clinical Plate 1" title="Click to view full resolution">
              </a>
              <a href="/api/vision/surgeon-recall/stream-image/images/apert-syndrome_IMG2.png" target="_blank" rel="noopener">
                <img src="/api/vision/surgeon-recall/stream-image/images/apert-syndrome_IMG2.png" style="height:60px; border-radius:6px; border:1px solid #1e334d; object-fit:cover; cursor:pointer;" alt="Clinical Plate 2" title="Click to view full resolution">
              </a>
            </div>
          </div>
        </div>"""

    if canvas_box_target in html:
        html = html.replace(canvas_box_target, new_canvas_box, 1)
        print("Injected Clinical 2D Photography & Radiographic Plate Gallery.")

    # Update JavaScript to handle mode switching and dynamic gallery loading
    old_js = """    try {
      const res = await fetch('/api/vision/surgeon-recall/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ selected_slug: slug, query_text: query })
      });"""

    new_js = """    let currentClinicalMode = window.activeSurgeonMode || 'pathological';
    try {
      const res = await fetch('/api/vision/surgeon-recall/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ selected_slug: slug, query_text: query, mode: currentClinicalMode })
      });"""

    if old_js in html:
        html = html.replace(old_js, new_js, 1)
        print("Updated JS query to pass current clinical mode.")

    # Update JS gallery loader
    gallery_js_target = """      if (c.stream_url) {
        loadSTLModel(c.stream_url);
      }"""

    gallery_js_repl = """      // Update Ontology Badges
      if (c.ontology) {
        const icdPill = document.getElementById('icd10Pill');
        if (icdPill) icdPill.textContent = `WHO ICD-10: ${c.ontology.icd10 || 'Q75.0'} • RadLex: ${c.ontology.radlex || 'RID39049'}`;
        const genePill = document.getElementById('genePill');
        if (genePill) genePill.textContent = `Gene: ${c.ontology.affected_gene || 'Clinical etiology'}`;
      }

      // Update Clinical Images Gallery
      const gallery = document.getElementById('clinicalImageThumbnails');
      const countLabel = document.getElementById('imgGalleryCount');
      if (gallery && c.images) {
        gallery.innerHTML = '';
        if (countLabel) countLabel.textContent = `${c.images.length} Plates Loaded`;
        c.images.forEach(img => {
          const a = document.createElement('a');
          a.href = img.url;
          a.target = '_blank';
          a.rel = 'noopener';
          a.innerHTML = `<img src="${img.url}" style="height:60px; border-radius:6px; border:1px solid #1e334d; object-fit:cover; cursor:pointer;" alt="${img.filename}" title="${img.filename}">`;
          gallery.appendChild(a);
        });
      }

      if (c.stream_url) {
        loadSTLModel(c.stream_url);
      }"""

    if gallery_js_target in html:
        html = html.replace(gallery_js_target, gallery_js_repl, 1)
        print("Updated JS to dynamically populate image gallery and ICD-10 badges.")

    # Add Mode Toggle Event Listeners
    mode_listeners = """
  // Clinical Mode Toggle
  window.activeSurgeonMode = 'pathological';
  document.getElementById('btnModePathology')?.addEventListener('click', () => {
    window.activeSurgeonMode = 'pathological';
    document.getElementById('btnModePathology').className = 'btn btn-emerald';
    document.getElementById('btnModeHealthy').className = 'btn btn-outline';
    document.getElementById('btnSurgeonRecall')?.click();
  });

  document.getElementById('btnModeHealthy')?.addEventListener('click', () => {
    window.activeSurgeonMode = 'healthy';
    document.getElementById('btnModeHealthy').className = 'btn btn-emerald';
    document.getElementById('btnModePathology').className = 'btn btn-outline';
    document.getElementById('btnSurgeonRecall')?.click();
  });
"""
    if "window.activeSurgeonMode" not in html and "document.getElementById('btnSurgeonRecall')?.addEventListener" in html:
        html = html.replace("document.getElementById('btnSurgeonRecall')?.addEventListener", mode_listeners + "\n  document.getElementById('btnSurgeonRecall')?.addEventListener", 1)
        print("Injected mode toggle event listeners.")

    WORKSPACE_PATH.write_text(html, encoding="utf-8")
    print("Enhanced vision_workspace.html successfully!")

if __name__ == "__main__":
    enhance_deck()
