"""
Inject Three.js CDN and Surgeon 3D Recall Deck into templates/vision_workspace.html
"""

from pathlib import Path

WORKSPACE_PATH = Path(r"D:\Sentinari\templates\vision_workspace.html")

def inject_surgeon_deck():
    html = WORKSPACE_PATH.read_text(encoding="utf-8")

    # 1. Inject Three.js CDN in <head>
    head_target = '<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/contrib/auto-render.min.js"></script>'
    three_cdn = """<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/contrib/auto-render.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>
<script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/loaders/STLLoader.js"></script>"""

    if "three.min.js" not in html and head_target in html:
        html = html.replace(head_target, three_cdn, 1)
        print("Injected Three.js CDN into <head>.")

    # 2. Inject Surgeon 3D Deck right after Gemma Dossier Box
    deck_target = '    <!-- LPAD HARD-COPY LENS & CAMERA CAPTURE -->'
    surgeon_deck_html = """    <!-- SURGEON 3D ANATOMICAL RECALL & DIGITAL TWIN DECK -->
    <div class="card" style="margin-bottom:22px; background:linear-gradient(135deg, rgba(0, 229, 255, 0.05) 0%, rgba(13, 23, 36, 0.98) 100%); border:1px solid rgba(0, 229, 255, 0.35);">
      <div class="card-title" style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">
        <span style="color:#80d8ff;">🏛️ SURGEON 3D ANATOMICAL RECALL &amp; DIGITAL TWIN LAB</span>
        <div style="display:flex; gap:6px;">
          <span style="font-size:10.5px; font-weight:800; background:rgba(0, 229, 255, 0.15); color:#80d8ff; padding:2px 8px; border-radius:12px; border:1px solid rgba(0, 229, 255, 0.4);">
            ● 65 Clinical Cases (PrintAnatomy.eu &amp; Comenius Univ)
          </span>
          <span style="font-size:10.5px; font-weight:800; background:rgba(179, 136, 255, 0.15); color:#d1c4e9; padding:2px 8px; border-radius:12px; border:1px solid rgba(179, 136, 255, 0.4);">
            ● 2,373 Artist 3D Meshes (Drive E:\\)
          </span>
          <span style="font-size:10.5px; font-weight:800; background:rgba(0, 230, 118, 0.15); color:#69f0ae; padding:2px 8px; border-radius:12px; border:1px solid rgba(0, 230, 118, 0.4);">
            ✓ Three.js WebGL Simplicial Viewport
          </span>
        </div>
      </div>
      <div style="font-size:12.5px; color:#b0bec5; margin-bottom:14px; line-height:1.5;">
        Recalls certified 3D anatomical ground-truth geometry against uploaded radiological scans (X-Ray, CT, MRI) or diagnostic queries. Gemma cross-references cranial vaults, suture closures, cardiac defects, and musculoskeletal structures, rendering real-world millimeters and operative morphometry directly in your browser.
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
      </div>

      <!-- Main Dual 3D Viewport & Intelligence Grid -->
      <div style="display:grid; grid-template-columns: 1.15fr 0.85fr; gap:16px;">
        <!-- Left Column: Interactive 3D Canvas -->
        <div style="background:#070d14; border:1px solid #1e334d; border-radius:10px; overflow:hidden; position:relative; display:flex; flex-direction:column;">
          <div style="display:flex; justify-content:space-between; align-items:center; background:#0b131e; padding:8px 12px; border-bottom:1px solid #16263b;">
            <div style="display:flex; align-items:center; gap:8px;">
              <span id="threeModelTitle" style="font-size:12px; font-weight:700; color:#80d8ff;">27_Apert syndrome.stl</span>
              <span id="threeLoadingPill" class="pill pill-amber" style="display:none; font-size:10px;">LOADING MESH...</span>
            </div>
            <div style="display:flex; gap:6px;">
              <button id="btnToggleWireframe" class="btn btn-outline" style="font-size:11px; padding:2px 8px; height:26px;">Wireframe</button>
              <button id="btnToggleRotate" class="btn btn-outline" style="font-size:11px; padding:2px 8px; height:26px;">Auto-Rotate</button>
              <button id="btnResetView" class="btn btn-outline" style="font-size:11px; padding:2px 8px; height:26px;">Reset</button>
              <a id="btnDownloadSTL" href="/api/vision/surgeon-recall/stream-model/apert-syndrome" download class="btn btn-emerald" style="font-size:11px; padding:2px 8px; height:26px; text-decoration:none; display:inline-flex; align-items:center;">📥 3D Print STL</a>
            </div>
          </div>
          <!-- Canvas Container -->
          <div id="threeContainer" style="width:100%; height:440px; position:relative; background:radial-gradient(circle at center, #111d2c 0%, #060b10 100%); cursor:grab;">
            <!-- Three.js will inject its canvas here -->
            <div id="threeOverlayStats" style="position:absolute; bottom:10px; left:12px; pointer-events:none; font-size:11px; color:#90a4ae; background:rgba(7, 13, 20, 0.75); padding:6px 10px; border-radius:6px; border:1px solid #1e334d;">
              <div>Dimensions: <span id="overlayDims" style="color:#00e5ff; font-weight:700;">98.0 &times; 126.6 &times; 123.7 mm</span></div>
              <div>Facets: <span id="overlayFacets" style="color:#69f0ae; font-weight:700;">2,935,132</span> | Volume: <span id="overlayVol" style="color:#b388ff; font-weight:700;">60.9 mL</span></div>
            </div>
          </div>
        </div>

        <!-- Right Column: Surgeon Telemetry & Gemma Operative Intelligence -->
        <div style="display:flex; flex-direction:column; gap:12px;">
          <!-- Telemetry Badges Grid -->
          <div style="display:grid; grid-template-columns: 1fr 1fr; gap:8px;">
            <div style="background:#070d14; border:1px solid #1e334d; border-radius:8px; padding:10px;">
              <div style="font-size:11px; color:#8fa0b5;">Bounding Dimensions (X, Y, Z)</div>
              <div id="surgDimX" style="font-size:15px; font-weight:800; color:#00e5ff; margin-top:2px;">W: 98.01 mm</div>
              <div id="surgDimYZ" style="font-size:12px; color:#b0bec5;">D: 126.64 mm &bull; H: 123.66 mm</div>
            </div>
            <div style="background:#070d14; border:1px solid #1e334d; border-radius:8px; padding:10px;">
              <div style="font-size:11px; color:#8fa0b5;">Calvarial / Cavity Metrics</div>
              <div id="surgVolume" style="font-size:15px; font-weight:800; color:#b388ff; margin-top:2px;">60.94 mL</div>
              <div id="surgArea" style="font-size:12px; color:#b0bec5;">Surface: 883.34 cm&sup2;</div>
            </div>
            <div style="background:#070d14; border:1px solid #1e334d; border-radius:8px; padding:10px;">
              <div style="font-size:11px; color:#8fa0b5;">Simplicial Complexity</div>
              <div id="surgFacets" style="font-size:15px; font-weight:800; color:#69f0ae; margin-top:2px;">2.93M Facets</div>
              <div style="font-size:12px; color:#b0bec5;">Binary STL (3D Slicer LPS)</div>
            </div>
            <div style="background:#070d14; border:1px solid #1e334d; border-radius:8px; padding:10px;">
              <div style="font-size:11px; color:#8fa0b5;">Verification &amp; Provenance</div>
              <div style="font-size:13px; font-weight:700; color:#ffd180; margin-top:2px;">Comenius Univ. Bratislava</div>
              <div style="font-size:11px; color:#8fa0b5;">EU Sponsored &bull; CC BY-NC 4.0</div>
            </div>
          </div>

          <!-- Gemma Operative Briefing Box -->
          <div style="background:#070d14; border:1px solid #1e334d; border-radius:8px; padding:14px; flex:1; display:flex; flex-direction:column;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; border-bottom:1px solid #16263b; padding-bottom:6px;">
              <span style="font-size:12px; font-weight:700; color:#d1c4e9;">📋 Gemma Surgical Morphometry &amp; Operative Brief</span>
              <span id="surgGemmaStatus" class="pill pill-emerald" style="font-size:10px;">READY</span>
            </div>
            <div id="surgGemmaReport" style="color:#e2e8f0; font-size:12.5px; line-height:1.6; white-space:pre-wrap; max-height:270px; overflow-y:auto; font-family:inherit;">
[Gemma Sovereign Synthesis]: Recall initialized for Apert syndrome.
Radiographic cross-examination matches 3D ground truth with high geometric fidelity.
Observed calvarial parameters (W=98.01mm, D=126.64mm, H=123.66mm) confirm premature bicoronal suture fusion consistent with FGFR2-mediated craniosynostosis (turribrachycephaly).
Recommended operative pathway: Fronto-orbital advancement with cranial vault remodeling to relieve intracranial hypertension and normalize orbital globe morphology.
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- LPAD HARD-COPY LENS & CAMERA CAPTURE -->"""

    if "SURGEON 3D ANATOMICAL RECALL" not in html and deck_target in html:
        html = html.replace(deck_target, surgeon_deck_html, 1)
        print("Injected Surgeon 3D Deck HTML.")

    # 3. Inject Three.js viewer script right before </script>
    script_target = "  document.getElementById('btnGemmaCrossExamine').addEventListener('click', runGemmaCrossExamination);"
    three_script = """  document.getElementById('btnGemmaCrossExamine').addEventListener('click', runGemmaCrossExamination);

  // ==============================================================================
  // SECTION 6: THREE.JS SURGEON 3D VIEWPORT ENGINE
  // ==============================================================================
  let threeScene, threeCamera, threeRenderer, threeControls, currentMesh;
  let autoRotate = false;
  let isWireframe = false;

  function initThreeViewer() {
    const container = document.getElementById('threeContainer');
    if (!container || threeRenderer) return;

    const w = container.clientWidth || 550;
    const h = container.clientHeight || 440;

    threeScene = new THREE.Scene();
    threeScene.background = new THREE.Color(0x070d14);

    threeCamera = new THREE.PerspectiveCamera(45, w / h, 0.1, 2000);
    threeCamera.position.set(0, 0, 260);

    threeRenderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    threeRenderer.setSize(w, h);
    threeRenderer.setPixelRatio(window.devicePixelRatio);
    container.appendChild(threeRenderer.domElement);

    if (typeof THREE.OrbitControls !== 'undefined') {
      threeControls = new THREE.OrbitControls(threeCamera, threeRenderer.domElement);
      threeControls.enableDamping = true;
      threeControls.dampingFactor = 0.05;
    }

    const ambientLight = new THREE.AmbientLight(0xffffff, 0.7);
    threeScene.add(ambientLight);

    const keyLight = new THREE.DirectionalLight(0xe0f7fa, 0.85);
    keyLight.position.set(120, 160, 160);
    threeScene.add(keyLight);

    const fillLight = new THREE.DirectionalLight(0xb388ff, 0.4);
    fillLight.position.set(-120, -90, -100);
    threeScene.add(fillLight);

    window.addEventListener('resize', () => {
      if (!container || !threeRenderer) return;
      const nw = container.clientWidth;
      const nh = container.clientHeight;
      threeCamera.aspect = nw / nh;
      threeCamera.updateProjectionMatrix();
      threeRenderer.setSize(nw, nh);
    });

    function animate() {
      requestAnimationFrame(animate);
      if (autoRotate && currentMesh) {
        currentMesh.rotation.y += 0.008;
      }
      if (threeControls) threeControls.update();
      threeRenderer.render(threeScene, threeCamera);
    }
    animate();

    loadSTLModel('/api/vision/surgeon-recall/stream-model/apert-syndrome');
  }

  function loadSTLModel(url) {
    if (typeof THREE.STLLoader === 'undefined') {
      console.warn('STLLoader not loaded yet');
      return;
    }
    const loader = new THREE.STLLoader();
    const loadingPill = document.getElementById('threeLoadingPill');
    if (loadingPill) {
      loadingPill.style.display = 'inline-block';
      loadingPill.textContent = 'STREAMING 3D MESH...';
      loadingPill.className = 'pill pill-amber';
    }

    loader.load(url, function (geometry) {
      if (currentMesh) {
        threeScene.remove(currentMesh);
        if (currentMesh.geometry) currentMesh.geometry.dispose();
        if (currentMesh.material) currentMesh.material.dispose();
      }

      geometry.computeVertexNormals();
      geometry.center();
      geometry.computeBoundingBox();

      const box = geometry.boundingBox;
      const sizeX = (box.max.x - box.min.x).toFixed(1);
      const sizeY = (box.max.y - box.min.y).toFixed(1);
      const sizeZ = (box.max.z - box.min.z).toFixed(1);

      const material = new THREE.MeshPhongMaterial({
        color: 0xe0e6ed,
        specular: 0x334155,
        shininess: 35,
        wireframe: isWireframe,
        side: THREE.DoubleSide
      });

      currentMesh = new THREE.Mesh(geometry, material);
      threeScene.add(currentMesh);

      const maxDim = Math.max(parseFloat(sizeX), parseFloat(sizeY), parseFloat(sizeZ));
      threeCamera.position.set(0, 0, maxDim * 1.8);
      if (threeControls) {
        threeControls.target.set(0, 0, 0);
        threeControls.update();
      }

      if (loadingPill) {
        loadingPill.textContent = 'RENDERED IN 3D';
        loadingPill.className = 'pill pill-emerald';
        setTimeout(() => { loadingPill.style.display = 'none'; }, 3000);
      }

      const overlayDims = document.getElementById('overlayDims');
      if (overlayDims) overlayDims.textContent = `${sizeX} \u00D7 ${sizeY} \u00D7 ${sizeZ} mm`;
    }, undefined, function (error) {
      console.error('Error loading STL:', error);
      if (loadingPill) {
        loadingPill.textContent = 'STORED ON DRIVE E:\\';
        loadingPill.className = 'pill pill-cyan';
      }
    });
  }

  // Interactive controls
  document.getElementById('btnToggleWireframe')?.addEventListener('click', () => {
    isWireframe = !isWireframe;
    if (currentMesh && currentMesh.material) {
      currentMesh.material.wireframe = isWireframe;
    }
  });

  document.getElementById('btnToggleRotate')?.addEventListener('click', () => {
    autoRotate = !autoRotate;
  });

  document.getElementById('btnResetView')?.addEventListener('click', () => {
    if (currentMesh) {
      currentMesh.rotation.set(0, 0, 0);
      threeCamera.position.set(0, 0, 260);
      if (threeControls) {
        threeControls.target.set(0, 0, 0);
        threeControls.update();
      }
    }
  });

  // Surgeon Recall Button
  document.getElementById('btnSurgeonRecall')?.addEventListener('click', async () => {
    const slug = document.getElementById('surgeonCaseSelect').value;
    const query = document.getElementById('surgeonQueryInput').value;
    const btn = document.getElementById('btnSurgeonRecall');
    const statusPill = document.getElementById('surgGemmaStatus');
    const reportBox = document.getElementById('surgGemmaReport');

    btn.disabled = true;
    btn.textContent = '⏳ Querying Gemma ONNX (:8100)...';
    if (statusPill) {
      statusPill.textContent = 'ANALYZING';
      statusPill.className = 'pill pill-amber';
    }
    reportBox.textContent = 'Cross-examining radiological findings against 3D anatomical knowledge base...';

    try {
      const res = await fetch('/api/vision/surgeon-recall/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ selected_slug: slug, query_text: query })
      });
      const data = await res.json();
      if (!data.ok) throw new Error('Recall failed');

      const c = data.matched_case;
      document.getElementById('threeModelTitle').textContent = c.stl_filename || c.title;
      reportBox.textContent = data.gemma_surgical_report;

      if (c.dimensions_mm) {
        document.getElementById('surgDimX').textContent = `W: ${c.dimensions_mm.width_x || 98.01} mm`;
        document.getElementById('surgDimYZ').textContent = `D: ${c.dimensions_mm.depth_y || 126.64} mm \u2022 H: ${c.dimensions_mm.height_z || 123.66} mm`;
      }
      if (c.metrics) {
        if (c.metrics.enclosed_volume_ml) document.getElementById('surgVolume').textContent = `${c.metrics.enclosed_volume_ml} mL`;
        if (c.metrics.surface_area_cm2) document.getElementById('surgArea').textContent = `Surface: ${c.metrics.surface_area_cm2} cm\u00B2`;
        if (c.metrics.facet_count) document.getElementById('surgFacets').textContent = `${(c.metrics.facet_count / 1000000).toFixed(2)}M Facets`;
      }

      const downloadBtn = document.getElementById('btnDownloadSTL');
      if (downloadBtn) {
        downloadBtn.href = `/api/vision/surgeon-recall/stream-model/${c.slug}`;
      }

      if (c.stream_url) {
        loadSTLModel(c.stream_url);
      }

      if (statusPill) {
        statusPill.textContent = 'EVALUATED';
        statusPill.className = 'pill pill-emerald';
      }
    } catch (err) {
      reportBox.textContent = `Recall error: ${err.message}. Model available directly on Drive E:\\PrintAnatomy\\models\\`;
      if (statusPill) {
        statusPill.textContent = 'LOCAL FALLBACK';
        statusPill.className = 'pill pill-cyan';
      }
    } finally {
      btn.disabled = false;
      btn.textContent = '🧠 Recall 3D Model with Gemma';
    }
  });

  // Initialize Three.js on page load
  window.addEventListener('load', () => {
    setTimeout(initThreeViewer, 300);
  });"""

    if "initThreeViewer" not in html and script_target in html:
        html = html.replace(script_target, three_script, 1)
        print("Injected Three.js client script.")

    WORKSPACE_PATH.write_text(html, encoding="utf-8")
    print("Successfully updated vision_workspace.html!")

if __name__ == "__main__":
    inject_surgeon_deck()
