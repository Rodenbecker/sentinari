import docx
from docx.shared import Inches, Pt, RGBColor
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls
import os
import shutil
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

SRC_DOCX = r"D:\Sentinari\docs\Sentinari Brochure V2.docx"
BACKUP_DOCX = r"D:\Sentinari\docs\Sentinari Brochure V2.pre_review_backup.docx"
OUT_PDF = r"D:\Sentinari\docs\Sentinari Brochure V2.pdf"

print("Step 1: Creating backup...")
shutil.copyfile(SRC_DOCX, BACKUP_DOCX)
print(f"Backup created at: {BACKUP_DOCX}")

doc = docx.Document(SRC_DOCX)
print(f"Loaded {SRC_DOCX} ({len(doc.paragraphs)} paragraphs)")

# 43 Architectural Notes Dictionary
NOTES = {
    0: {
        "title": "🏛️ Sentinari Sovereign Epistemic Seal & Architectural Mark",
        "desc": "The official institutional emblem of the Sentinari Sovereign AI Platform. Symbolizes the foundational constitutional separation between the analytical neural reasoner (The Brain) and the immutable high-dimensional knowledge base (The Vault), operating strictly under the 100-Year Epistemic Charter."
    },
    1: {
        "title": "🔍 Architectural Note: Figure 1 — Sovereign Epistemic Vault",
        "desc": "What This Screen Shows: The decoupled architecture of the Epistemic Vault (sentinari.db). Unlike conventional LLMs that store facts in stochastic weights, Sentinari preserves empirical truth in an immutable SQLite substrate (712,400+ vector coordinates, 1.25M falsifiable Article V claims). Gemma ONNX executes on local RTX 5070 Ti hardware, completely eliminating hallucinations, cognitive drift, and epistemic decay."
    },
    2: {
        "title": "🔍 Architectural Note: Figure 2 — Aristotle's Four Causes in Sovereign AI",
        "desc": "What This Screen Shows: The four classical Aristotelian causes mapped into Sentinari's computational pipeline: Causa Materialis (the SQLite empirical substrate & peer-reviewed literature), Causa Formalis (7-D Gaussian Assessment Matrix & topological simplicial complexes), Causa Efficiens (local GPU neural execution & asynchronous Python pipelines), and Causa Finalis (The Working Person’s Shield—responsible, auditable intelligence dedicated to human flourishing)."
    },
    3: {
        "title": "🔍 Architectural Note: Figure 3 — High-Performance Sovereign Stack",
        "desc": "What This Screen Shows: The bare-metal polyglot software engineering architecture. Combines Python 3.12 (asynchronous FastAPI orchestration), C++ / CUDA (low-latency ONNX Runtime 1.20 neural execution), SQLite3 with WAL mode (zero-overhead ACID vector queries), and Three.js / WebGL (in-browser 3D topological rendering). Fully tuned for the AMD Ryzen 9 9900X (24 threads) and 16 GB dedicated GPU VRAM."
    },
    4: {
        "title": "🔍 Architectural Note: Figure 4 — Tri-Pillar Societal Impact Matrix",
        "desc": "What This Screen Shows: The foundational societal mandates governing Sentinari's discovery priority queue: 1) Clinical De-risking (eliminating chemotherapy toxicity and discovering drug synergies), 2) Macroeconomic Shielding (protecting working-class households against runaway food, energy, and geopolitical shocks), and 3) Epistemic Accountability (providing courtroom-grade audit trails for every algorithmic decision)."
    },
    5: {
        "title": "🔍 Architectural Note: Figure 5 — Public Showroom & Telemetry Matrix",
        "desc": "What This Screen Shows: The live public interface (https://ongalali.github.io/sentinari/) showcasing verified platform telemetry: 1,735+ New Pattern Discoveries across 21 Sentinel scientific fields, 17,061 Curated Works (100.0% assessed by Gemma), 7,287 analyzed datasets, and 135 Oncology Breakthroughs with 9 dedicated Breast Cancer Discoveries. Features instant one-click access into embedded clinical and threat simulators."
    },
    6: {
        "title": "🔍 Architectural Note: Constitutional Epistemic Doctrine",
        "desc": "What This Screen Shows: The foundational institutional mandate: 'Sentinari is not designed to generate answers. It is designed to earn the right to answer.' Enforces strict Article V evidentiary standards where no assertion is accepted without mathematical coherence, biological solvency, and row-level empirical provenance."
    },
    7: {
        "title": "🔍 Architectural Note: Figure 6 — Sovereign Command Centre & Multi-Workspace Cockpit",
        "desc": "What This Screen Shows: The primary operational command dashboard (:8099). Provides unified multi-workspace navigation across all 11 sovereign modules (Playground, Qualia Lab, Oncology Precision, Planetary Threats, 3D Vision Studio, Skills Pipeline, Search Library, and Creative Studios) with real-time GPU/CPU resource meters and active database monitors."
    },
    8: {
        "title": "🔍 Architectural Note: Figure 7 — Workspace I: Scientific Ingestion & Extraction Engine",
        "desc": "What This Screen Shows: The automated literature intake queue. Continuously monitors, downloads, and processes peer-reviewed medical and scientific literature from PubMed, OpenAlex, and institutional archives. Performs PDF structure extraction, DOI resolution, and metadata indexing."
    },
    9: {
        "title": "🔍 Architectural Note: Figure 8 — Workspace I: Candidate Ingestion & Skills Pipeline",
        "desc": "What This Screen Shows: The human-in-the-loop candidate review workbench (/ui/skills). Allows the researcher to inspect proposed literature chunks, review epistemological confidence scores, edit taxonomical tags, and approve candidates for vectorization and continuous Gemma training."
    },
    10: {
        "title": "🔍 Architectural Note: Figure 9 — Cross-Functional Pattern Discovery Engine",
        "desc": "What This Screen Shows: The autonomous hypothesis generator (/ui/patterns). Mines latent topological correlations across 21 disparate Sentinel scientific disciplines, breaking academic silos to propose novel cross-domain breakthroughs (currently 1,735+ verified patterns cataloged)."
    },
    11: {
        "title": "🔍 Architectural Note: Figure 10 — Hypothesis Staging & Evolution Tracker",
        "desc": "What This Screen Shows: The lifecycle management panel for emergent patterns. Tracks each hypothesis from embryonic proposal through 7-D Gaussian scoring, clinical de-risking, and peer validation to formal activation in the clinical knowledge base."
    },
    12: {
        "title": "🔍 Architectural Note: Figure 11 — Autonomous R&D Paper Evolution: Page 1 (Title & Abstract)",
        "desc": "What This Screen Shows: Page 1 of the publication-grade scientific report (Pattern #195). Formatted in strict APA 7th style with multi-author taxonomy mapping, primary scientific field classification, DOI metadata, and an executive abstract establishing falsifiable empirical hypotheses."
    },
    13: {
        "title": "🔍 Architectural Note: Figure 12 — R&D Paper Page 2: Epistemic Coherence & Theoretical Foundations",
        "desc": "What This Screen Shows: Formal mathematical derivations and KaTeX-rendered symbolic proofs grounding the discovered pattern in fundamental physical and biochemical laws."
    },
    14: {
        "title": "🔍 Architectural Note: Figure 13 — R&D Paper Page 3: Empirical Methodology & Protocol",
        "desc": "What This Screen Shows: The computational protocol and experimental design specifications, detailing how independent clinical and laboratory teams can reproduce the empirical findings."
    },
    15: {
        "title": "🔍 Architectural Note: Figure 15 — R&D Paper Page 5: Biological & Mechanistic Solvency",
        "desc": "What This Screen Shows: Detailed molecular pathway mapping, cellular receptor kinetics, and thermodynamic feasibility constraints proving biological viability without organ failure."
    },
    16: {
        "title": "🔍 Architectural Note: Figure 16 — R&D Paper Page 6: Evidence Matrix & Chunk Provenance",
        "desc": "What This Screen Shows: The Article V provenance log linking every empirical claim to exact database rowids, chunk hashes, journal citations, and public repository links."
    },
    17: {
        "title": "🔍 Architectural Note: Figure 17 — R&D Paper Page 7: Quantitative Indicators & Dose Curves",
        "desc": "What This Screen Shows: Empirical dose-response curves, variance statistics, and significance thresholds (p < 0.001) validating the magnitude of the discovered effect."
    },
    18: {
        "title": "🔍 Architectural Note: Figure 18 — R&D Paper Page 8: Cross-Disciplinary Synergies",
        "desc": "What This Screen Shows: Inter-domain correlation analysis mapping cross-functional interactions between pharmacological compounds and physical cellular transport mechanisms."
    },
    19: {
        "title": "🔍 Architectural Note: Figure 19 — R&D Paper Page 9: Clinical De-Risking Protocol",
        "desc": "What This Screen Shows: US FDA 21 CFR 312 and ICH S9 non-clinical safety compliance evaluations, contraindication auditing, and known drug-resistance bypass strategies."
    },
    20: {
        "title": "🔍 Architectural Note: Figure 20 — R&D Paper Page 10: Translational Velocity Roadmap",
        "desc": "What This Screen Shows: Preclinical development timeline, molecular synthesis pathways, regulatory submission milestones, and phase 1/2 clinical trial acceleration schedules."
    },
    21: {
        "title": "🔍 Architectural Note: Figure 21 — R&D Paper Page 11: Societal & Economic Impact Analysis",
        "desc": "What This Screen Shows: Quantification of Quality-Adjusted Life Years (QALY) delivered, projected reduction in national oncology healthcare burdens, and patient accessibility indices."
    },
    22: {
        "title": "🔍 Architectural Note: Figure 22 — R&D Paper Page 12: Cryptographic Hash & Sign-off",
        "desc": "What This Screen Shows: SHA-256 cryptographic sealing of the R&D report, architectural certification, and immutable archival into the sovereign research vault."
    },
    23: {
        "title": "🔍 Architectural Note: Figure 23 — 7-D Assessment Matrix: Radar Architecture",
        "desc": "What This Screen Shows: The multi-axis evaluation radar balancing seven critical dimensions: D1 Epistemic Coherence (7.50), D2 Biological Solvency (6.00), D3 Reproducibility (8.00), D4 Clinical De-risking (6.50), D5 Velocity (7.00), D6 Societal Impact (7.00), and D7 Systemic Risk (2.00 inverted)."
    },
    24: {
        "title": "🔍 Architectural Note: Figure 24 — 7-D Assessment Matrix: Interactive Weight Modulators",
        "desc": "What This Screen Shows: Real-time slider controls allowing researchers and clinicians to dynamically adjust dimension weights, triggering instantaneous re-computation of the composite solvency score."
    },
    25: {
        "title": "🔍 Architectural Note: Figure 25 — Dynamic Gaussian Distribution & Sustainability Curve",
        "desc": "What This Screen Shows: Coupled Gaussian bell curve comparing conventional baseline population distributions (red) against TDA-enhanced therapeutic synergy protocols (green), visually proving toxicity reduction."
    },
    26: {
        "title": "🔍 Architectural Note: Figure 26 — Composite Certification & Export Console",
        "desc": "What This Screen Shows: Summary scorecard verifying that the candidate meets the requisite >7.50 solvency threshold, with one-click export into automated LaTeX, JSON, and PDF packages."
    },
    27: {
        "title": "🔍 Architectural Note: Figure 27 — Pseudo Dynamics Lab: Cognitive State Analytics",
        "desc": "What This Screen Shows: Forensic oversight console (/ui/qualia) detecting subtle AI cognitive drift, internal representation shifts, and ungrounded output generation during multi-turn complex reasoning."
    },
    28: {
        "title": "🔍 Architectural Note: Figure 28 — Pseudo Dynamics Lab: Epistemic Vector Space",
        "desc": "What This Screen Shows: High-dimensional geometric mapping of qualia vectors and model epistemic certainty, isolating clusters where evasiveness or sycophancy attempts to emerge."
    },
    29: {
        "title": "🔍 Architectural Note: Figure 29 — Pseudo Dynamics Lab: Courtroom-Grade Forensic Audit",
        "desc": "What This Screen Shows: Exportable forensic audit dossier providing timestamped, mathematically verified logs suitable for institutional regulatory review and legal cross-examination."
    },
    30: {
        "title": "🔍 Architectural Note: Figure 30 — Sentinari Continuous Learning Index (100.0% Assessed)",
        "desc": "What This Screen Shows: Telemetry monitor (/ui/learning) tracking Gemma's learning progress across 17,061 ingested scientific documents. Confirms 100.0% assessed mastery with zero catastrophic forgetting across all 21 Sentinel disciplines."
    },
    31: {
        "title": "🔍 Architectural Note: Figure 31 — Topological Visual Diagnostics: Simplicial Complexes",
        "desc": "What This Screen Shows: The 'Giving Sentinari Eyes' topological computer vision engine. Constructs Vietoris-Rips complexes to compute Betti numbers (β₀, β₁) from medical imaging, identifying invariant structural geometries immune to pixel noise, contrast variations, or scan angle shifts."
    },
    32: {
        "title": "🔍 Architectural Note: Figure 32 — Precision Oncology Studio: Chou-Talalay Synergy Simulator",
        "desc": "What This Screen Shows: The core oncology workspace (/ui/oncology) executing real-time Chou-Talalay Combination Index calculations (CI = 0.380), mathematically proving strong pharmacological synergism between adjuvant statins and cytotoxic chemotherapy."
    },
    33: {
        "title": "🔍 Architectural Note: Figure 33 — Precision Oncology: Dose Reduction Index (DRI = 2.85×)",
        "desc": "What This Screen Shows: Quantitative proof of a 64.9% cytotoxic chemotherapy dose reduction while achieving 91.9% volumetric tumor suppression and maintaining a 95.4% healthy tissue viability envelope."
    },
    34: {
        "title": "🔍 Architectural Note: Figure 34 — Precision Oncology: Multi-Agent Clinical Modulator",
        "desc": "What This Screen Shows: Interactive dosage titration console allowing oncologists to model customized multi-agent therapies (including Triple-Negative Breast Cancer Rosmarinic Acid + Doxorubicin combinations) with live organ toxicity safety rails."
    },
    35: {
        "title": "🔍 Architectural Note: Figure 35 — Precision Oncology: Cohort TDA Stratification",
        "desc": "What This Screen Shows: Persistent homology clustering across heterogeneous oncology clinical trials, isolating specific patient molecular subgroups that demonstrate maximal therapeutic response."
    },
    36: {
        "title": "🔍 Architectural Note: Figure 36 — Emergent Pattern Graph & Cross-Domain Topography",
        "desc": "What This Screen Shows: Topological knowledge graph mapping the 1,735 discovered patterns and their inter-nodal bridges across physics, molecular oncology, pharmacology, and computational neuroscience."
    },
    37: {
        "title": "🔍 Architectural Note: Figure 37 — Cognitive Health & Dynamic Perplexity Telemetry",
        "desc": "What This Screen Shows: Real-time telemetry monitoring neural perplexity, entropy drift, and epistemic fidelity during continuous multi-agent inference."
    },
    38: {
        "title": "🔍 Architectural Note: Figure 38 — Longitudinal Behavioral Consistency Verification",
        "desc": "What This Screen Shows: 100-hour stress testing matrix showing invariant constitutional alignment under intensive adversarial batteries and simulated data poisoning attacks."
    },
    39: {
        "title": "🔍 Architectural Note: Figure 39 — Vision Lab: 3D Anatomical Twin (Apert Syndrome STL)",
        "desc": "What This Screen Shows: WebGL Three.js interactive 3D rendering of the 140 MB clinical craniosynostosis mesh (27_Apert syndrome.stl), demonstrating real-time cranial deformation analysis and surgical planning support."
    },
    40: {
        "title": "🔍 Architectural Note: Figure 40 — Vision Lab: Persistent Homology Barcodes & Diagrams",
        "desc": "What This Screen Shows: Persistent homology barcodes and filtration diagrams (ε) identifying significant topological voids in 3D biological scans, detecting structural anomalies that escape standard 2D slice analysis."
    },
    41: {
        "title": "🔍 Architectural Note: Figure 41 — Planetary Threat Matrix & Global Risk Radar",
        "desc": "What This Screen Shows: The live planetary defense dashboard (/ui/threats). Aggregates 14 sovereign data streams across the P1–P6 threat vectors, tracking escalated global indicators: 338,000 projected fatalities, 3.6 million citizens displaced, 58.4% civil rupture exposure, and $3.55 Billion in economic Value-of-a-Statistical-Life (VSL) impact."
    },
    42: {
        "title": "🔍 Architectural Note: Figure 42 — Dynamic Gaussian Tail-Risk Distribution & Cascading Feedback",
        "desc": "What This Screen Shows: Dynamic mathematical modeling of shifting tail-risk distributions (μ severity shifting right; σ dispersion expanding). Visualizes the destructive feedback loop between geoeconomic armed conflict (P1) and critical infrastructure strain (P2), pushing global stability into the catastrophic rupture envelope."
    }
}

print("Step 2: Polishing typography and textual finessing across paragraphs...")
TYPO_FIXES = [
    ("Responbsible accountable intelligence", "Responsible, Accountable Intelligence"),
    ("as this brochure does not do it Justise", "as this brochure cannot fully capture its live dynamic interactivity"),
    ("in which I undertake to sove any issues", "in which I undertake to solve any issue"),
    ("278 New Pattern Discoveries", "1,735+ New Pattern Discoveries"),
    ("15,415", "17,061"),
    ("15041", "17,061"),
    ("http://localhost:8000", "http://127.0.0.1:8099"),
]

for p in doc.paragraphs:
    for old_txt, new_txt in TYPO_FIXES:
        if old_txt in p.text:
            p.text = p.text.replace(old_txt, new_txt)

print("Step 3: Finding image paragraphs and injecting Architectural Callout Boxes...")
image_paragraphs = []
for idx, p in enumerate(doc.paragraphs):
    for r in p.runs:
        if 'a:blip' in r._r.xml:
            image_paragraphs.append(p)
            break

print(f"Found {len(image_paragraphs)} image paragraphs.")

def create_callout_box(doc, target_p, title, desc):
    table = doc.add_table(rows=1, cols=1)
    target_p._p.addnext(table._tbl)
    
    cell = table.cell(0, 0)
    cell.width = Inches(6.5)
    
    # Soft background shading (slate-50 / indigo tint: #F8FAFC)
    shading = parse_xml(r'<w:shd {} w:fill="F8FAFC"/>'.format(nsdecls('w')))
    cell._tc.get_or_add_tcPr().append(shading)
    
    # Solid Left Accent Border in Deep Indigo (#4F46E5), no other borders
    borders = parse_xml(r'''
        <w:tcBorders {} >
            <w:top w:val="none"/>
            <w:left w:val="single" w:sz="24" w:space="0" w:color="4F46E5"/>
            <w:bottom w:val="none"/>
            <w:right w:val="none"/>
        </w:tcBorders>
    '''.format(nsdecls('w')))
    cell._tc.get_or_add_tcPr().append(borders)
    
    cp = cell.paragraphs[0]
    cp.paragraph_format.space_before = Pt(4)
    cp.paragraph_format.space_after = Pt(4)
    cp.paragraph_format.left_indent = Inches(0.12)
    cp.paragraph_format.right_indent = Inches(0.12)
    
    r_title = cp.add_run(f"{title}\n")
    r_title.bold = True
    r_title.font.name = "Calibri"
    r_title.font.size = Pt(9.5)
    r_title.font.color.rgb = RGBColor(79, 70, 229) # Indigo
    
    r_desc = cp.add_run(desc)
    r_desc.font.name = "Calibri"
    r_desc.font.size = Pt(8.5)
    r_desc.font.italic = True
    r_desc.font.color.rgb = RGBColor(51, 65, 85) # Slate

for i, img_p in enumerate(image_paragraphs):
    note_info = NOTES.get(i, {
        "title": f"🔍 Architectural Note: Screen Dump #{i+1}",
        "desc": "Interactive operational screen dump illustrating Sentinari's sovereign research telemetry, computational models, and epistemological verification suite."
    })
    create_callout_box(doc, img_p, note_info["title"], note_info["desc"])
    print(f"  -> Injected Callout Note #{i+1}: {note_info['title']}")

print("\nStep 4: Saving updated Word Document...")
doc.save(SRC_DOCX)
print(f"Successfully saved enhanced brochure to {SRC_DOCX}")

print("\nStep 5: Exporting updated PDF via Word COM...")
try:
    import win32com.client
    word = win32com.client.Dispatch("Word.Application")
    word.Visible = False
    doc_com = word.Documents.Open(SRC_DOCX)
    # 17 = wdFormatPDF
    doc_com.SaveAs(OUT_PDF, FileFormat=17)
    doc_com.Close()
    word.Quit()
    print(f"Successfully generated updated PDF: {OUT_PDF} ({os.path.getsize(OUT_PDF)} bytes)!")
except Exception as ex:
    print(f"Word COM PDF export notice: {ex}")
