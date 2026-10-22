#!/usr/bin/env python3
"""Generate high-resolution Master Functional Schematic Diagram for Sentinari.

Conceived, Architected & Engineered by Dr. Pierre C. Wepener.
Renders both high-resolution PNG (2400x1400) and scalable SVG blueprints.
"""

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import os

def get_font(size: int, bold: bool = False):
    font_names = (
        ["C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/arialbd.ttf"]
        if bold
        else ["C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf"]
    )
    for p in font_names:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()

def draw_box(draw, box, fill, outline, width=2, radius=12):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)

def draw_arrow(draw, start, end, fill, width=3):
    draw.line([start, end], fill=fill, width=width)
    x1, y1 = start
    x2, y2 = end
    # Downward arrow
    if y2 > y1 and abs(x2 - x1) < 10:
        draw.polygon([(x2, y2), (x2 - 7, y2 - 14), (x2 + 7, y2 - 14)], fill=fill)
    # Rightward arrow
    elif x2 > x1 and abs(y2 - y1) < 10:
        draw.polygon([(x2, y2), (x2 - 14, y2 - 7), (x2 - 14, y2 + 7)], fill=fill)

def render_png(out_path: Path):
    w, h = 2400, 1400
    im = Image.new("RGB", (w, h), (10, 14, 23))
    draw = ImageDraw.Draw(im)

    # Ambient glows
    draw.ellipse([w//2 - 600, -200, w//2 + 600, 400], fill=(18, 24, 45))
    draw.ellipse([-200, h//2 - 400, 500, h//2 + 400], fill=(14, 30, 40))
    draw.ellipse([w - 500, h - 500, w + 300, h + 300], fill=(22, 18, 44))

    # Fonts
    f_title = get_font(42, bold=True)
    f_subtitle = get_font(20, bold=False)
    f_badge = get_font(18, bold=True)
    f_sec_hdr = get_font(22, bold=True)
    f_box_hdr = get_font(19, bold=True)
    f_box_sub = get_font(15, bold=False)
    f_foot = get_font(16, bold=False)

    # 1. Header
    draw.text((100, 45), "SENTINARI: MASTER FUNCTIONAL ARCHITECTURE & DATAFLOW SCHEMATIC", font=f_title, fill=(255, 255, 255))
    draw.text((100, 100), "The Sovereign Discipline of Responsible Intelligence • Decoupled Analytical Reasoner & High-Dimensional Memory Matrix", font=f_subtitle, fill=(148, 163, 184))
    
    # Header Badge
    badge_text = "DR. PIERRE C. WEPENER • CHIEF ARCHITECT"
    draw.rounded_rectangle([w - 520, 50, w - 100, 92], radius=10, fill=(26, 32, 54), outline=(99, 102, 241), width=2)
    draw.text((w - 500, 60), badge_text, font=f_badge, fill=(165, 180, 252))

    draw.line([100, 135, w - 100, 135], fill=(30, 41, 59), width=2)
    draw.line([100, 135, 450, 135], fill=(99, 102, 241), width=4)

    # 2. TOP LAYER: THE 100-YEAR CONSTITUTION & ETHICAL GOVERNANCE ENVELOPE (Y: 155 - 280)
    draw_box(draw, [100, 155, w - 100, 280], fill=(16, 22, 38), outline=(245, 158, 11), width=2, radius=14)
    # Header bar
    draw.rounded_rectangle([100, 155, w - 100, 195], radius=14, fill=(35, 26, 16))
    draw.rectangle([100, 180, w - 100, 195], fill=(35, 26, 16))
    draw.text((125, 163), "FOUNDATIONAL GOVERNANCE: THE 100-YEAR CONSTITUTION (/constitution • D:/Constitution.pdf)", font=f_sec_hdr, fill=(251, 191, 36))

    # Constitutional Pillars inside Box
    pillars = [
        ("Article I: Material Reality", "Empirical truth & physical telemetry unconditionally supersede institutional narratives."),
        ("Article II: Neutral Illuminator", "Zero corporate enemies, zero ideological loyalties; only verifiable hypotheses."),
        ("Article III: Systematic Humility", "Confidence degrades immediately upon emergence of superior counter-evidence."),
        ("Article IV: Inadequacy Declaration", "Mandatory refusal to hallucinate or speculate when primary corpus is incomplete."),
    ]
    pw = (w - 200 - 3 * 20) // 4
    for i, (p_title, p_desc) in enumerate(pillars):
        px = 120 + i * (pw + 20)
        py = 205
        draw_box(draw, [px, py, px + pw, py + 62], fill=(22, 28, 44), outline=(45, 55, 78), width=1, radius=8)
        draw.text((px + 12, py + 8), p_title, font=f_box_hdr, fill=(255, 255, 255))
        draw.text((px + 12, py + 34), p_desc, font=f_box_sub, fill=(148, 163, 184))

    # Flow arrows from Constitution down to Core Engines
    for ax in [380, 980, 1580, 2180]:
        draw_arrow(draw, (ax, 280), (ax, 320), fill=(245, 158, 11), width=2)

    # 3. MIDDLE LAYER: THE 4 CORE WORKSPACES (Y: 320 - 980)
    col_w = (w - 200 - 3 * 25) // 4  # ~520px each
    
    # COL 1: PLAYGROUND & REINDEXING ENGINE (/ui/playground)
    c1_x = 100
    draw_box(draw, [c1_x, 320, c1_x + col_w, 980], fill=(14, 20, 32), outline=(16, 185, 129), width=2, radius=14)
    draw.rounded_rectangle([c1_x, 320, c1_x + col_w, 365], radius=14, fill=(16, 38, 30))
    draw.rectangle([c1_x, 350, c1_x + col_w, 365], fill=(16, 38, 30))
    draw.text((c1_x + 20, 330), "WORKSPACE 1: PLAYGROUND", font=f_sec_hdr, fill=(52, 211, 153))

    c1_boxes = [
        ("Curated Multi-Disciplinary Corpus", "15,041+ Indexed Primary Scientific Works\n21 Sovereign Sentinel Disciplines\n(Medicine, Geopolitics, Physics, Micro-Macro)"),
        ("Synchronous Database Reindexing", "Active 'Refresh Database' Pipeline\nRecalibrates document counts across fields\nAudits ingestion background workers\nValidates FTS5 full-text shadow tables"),
        ("Dual Database Engine Architecture", "Local: SQLite 3.45 in WAL Mode (Lock-Armored)\nCloud: Cloud SQL PostgreSQL 16 + pgvector\nZero cross-database latency & fail-closed"),
        ("Divorced Memory Matrix", "Reasoning Core (Brain) decoupled from\nPersistent High-Dimensional Vectors (Memory)\nEliminates catastrophic forgetting forever"),
    ]
    by = 380
    for bh, bd in c1_boxes:
        draw_box(draw, [c1_x + 18, by, c1_x + col_w - 18, by + 128], fill=(18, 26, 42), outline=(24, 52, 45), width=1, radius=10)
        draw.text((c1_x + 32, by + 12), bh, font=f_box_hdr, fill=(255, 255, 255))
        draw.line([c1_x + 32, by + 40, c1_x + col_w - 32, by + 40], fill=(24, 45, 38), width=1)
        for li, line in enumerate(bd.split("\n")):
            draw.text((c1_x + 32, by + 48 + li * 22), line, font=f_box_sub, fill=(203, 213, 225))
        by += 144

    # COL 2: NEW PATTERN DISCOVERY & R&D PAPERS (/ui/patterns)
    c2_x = 100 + col_w + 25
    draw_box(draw, [c2_x, 320, c2_x + col_w, 980], fill=(14, 20, 32), outline=(99, 102, 241), width=2, radius=14)
    draw.rounded_rectangle([c2_x, 320, c2_x + col_w, 365], radius=14, fill=(26, 28, 54))
    draw.rectangle([c2_x, 350, c2_x + col_w, 365], fill=(26, 28, 54))
    draw.text((c2_x + 20, 330), "WORKSPACE 2: PATTERN DISCOVERY", font=f_sec_hdr, fill=(165, 180, 252))

    c2_boxes = [
        ("Autonomous Interdisciplinary Daemon", "Cross-correlates findings across all 21 fields\nSurfaces hidden emergent macro-correlations\n233 Candidate Discoveries generated"),
        ("Concertina Discovery Interface", "8 collapsible cards per page (high-perf)\n5-Stage Maturity Indicator (Embryo -> Valid)\nOverall Confidence % + primary quote links"),
        ("7-D Assessment Matrix Simulator", "Closed-Form Gaussian Bell Curves:\nS_i(x_i) = A_i * exp(-(x_i - mu_i)^2 / (2*sigma_i^2))\nKnowledge, Intel, Decision, Agency, Society, Ethics, Risk\nCoupled Interdependence Rules & NSIS Score"),
        ("15-Indicator R&D Paper & Fig 6.4", "Autonomous 5-section publication paper\nKaTeX proofs, APA 7th citations, solutions\nFig 6.4 Trajectory: V(t)=V0+dV*(1-e^-kt)\n5-Year quantitative boardroom fiscal ROI"),
    ]
    by = 380
    for bh, bd in c2_boxes:
        draw_box(draw, [c2_x + 18, by, c2_x + col_w - 18, by + 128], fill=(18, 26, 42), outline=(36, 42, 75), width=1, radius=10)
        draw.text((c2_x + 32, by + 12), bh, font=f_box_hdr, fill=(255, 255, 255))
        draw.line([c2_x + 32, by + 40, c2_x + col_w - 32, by + 40], fill=(35, 45, 68), width=1)
        for li, line in enumerate(bd.split("\n")):
            draw.text((c2_x + 32, by + 48 + li * 22), line, font=f_box_sub, fill=(203, 213, 225))
        by += 144

    # COL 3: QUALIA LAB & FORENSIC DECEPTION (/ui/qualia)
    c3_x = 100 + 2 * (col_w + 25)
    draw_box(draw, [c3_x, 320, c3_x + col_w, 980], fill=(14, 20, 32), outline=(236, 72, 153), width=2, radius=14)
    draw.rounded_rectangle([c3_x, 320, c3_x + col_w, 365], radius=14, fill=(45, 20, 38))
    draw.rectangle([c3_x, 350, c3_x + col_w, 365], fill=(45, 20, 38))
    draw.text((c3_x + 20, 330), "WORKSPACE 3: QUALIA & DECEPTION", font=f_sec_hdr, fill=(244, 114, 182))

    c3_boxes = [
        ("Cognitive Vector Dynamics Engine", "Q0 (semantic prior), A0 (attention vector)\nS (stabilizing attractor field)\nAlpha (persistence), Beta (pull), Gamma (coherence)\nGamma Cap clamping & trajectory curves"),
        ("Multi-Model Spider Radar Vector Plots", "Plots live multi-model vector distributions\nQuantifies semantic drift vs response anxiety\nEmpirical visualization of model attention"),
        ("Courtroom Forensic Deception Suite", "Dr. Wepener Criminal Psychology Architecture\nSCAN & CBCA Statement Analysis Taxonomy\nDetects agency dissociation, perjury evasion,\ncandor leakage oaths, euphemistic spin"),
        ("Noise Decoupling & Merciless A4 Audit", "Strips rhetorical spin to expose naked facts\nOutputs formal APA 7th referenced 1-page A4\nPrintable cross-examination audit sheet\nComputes Projected Research ROI %"),
    ]
    by = 380
    for bh, bd in c3_boxes:
        draw_box(draw, [c3_x + 18, by, c3_x + col_w - 18, by + 128], fill=(18, 26, 42), outline=(58, 28, 48), width=1, radius=10)
        draw.text((c3_x + 32, by + 12), bh, font=f_box_hdr, fill=(255, 255, 255))
        draw.line([c3_x + 32, by + 40, c3_x + col_w - 32, by + 40], fill=(48, 25, 42), width=1)
        for li, line in enumerate(bd.split("\n")):
            draw.text((c3_x + 32, by + 48 + li * 22), line, font=f_box_sub, fill=(203, 213, 225))
        by += 144

    # COL 4: LEARNING INDEX & ASSESSMENT LADDER (/ui/learning)
    c4_x = 100 + 3 * (col_w + 25)
    draw_box(draw, [c4_x, 320, c4_x + col_w, 980], fill=(14, 20, 32), outline=(56, 189, 248), width=2, radius=14)
    draw.rounded_rectangle([c4_x, 320, c4_x + col_w, 365], radius=14, fill=(16, 36, 52))
    draw.rectangle([c4_x, 350, c4_x + col_w, 365], fill=(16, 36, 52))
    draw.text((c4_x + 20, 330), "WORKSPACE 4: LEARNING LADDER", font=f_sec_hdr, fill=(125, 211, 252))

    c4_boxes = [
        ("% Learned Progress Telemetry", "Continuous audit of active comprehension\nVerifies that ingested corpus is actively\nunderstood rather than memorized statically"),
        ("Humanity's Last Exam (HLE) Rig", "Integration with the most demanding global\nmultimodal academic benchmark across fields\nTests frontier reasoning & complex math"),
        ("SWE-Bench Pro Autonomous Grading", "Isolated execution harnesses for automated\nsoftware repair, testing & execution proofs\nVerifies real-world engineering proficiency"),
        ("Strict Prerequisite Calibration Gate Laws", "Formative Gate (60%) -> Unlocks Calibration\nCalibration Gate (55%) -> Unlocks HLE Rig\nHLE Gate (50%) -> Unlocks Pro Workbench\nBrier score drift safeguards & fail-closed"),
    ]
    by = 380
    for bh, bd in c4_boxes:
        draw_box(draw, [c4_x + 18, by, c4_x + col_w - 18, by + 128], fill=(18, 26, 42), outline=(24, 48, 68), width=1, radius=10)
        draw.text((c4_x + 32, by + 12), bh, font=f_box_hdr, fill=(255, 255, 255))
        draw.line([c4_x + 32, by + 40, c4_x + col_w - 32, by + 40], fill=(22, 38, 54), width=1)
        for li, line in enumerate(bd.split("\n")):
            draw.text((c4_x + 32, by + 48 + li * 22), line, font=f_box_sub, fill=(203, 213, 225))
        by += 144

    # Lateral dataflow arrows between columns
    draw_arrow(draw, (c1_x + col_w, 520), (c2_x, 520), fill=(16, 185, 129), width=2)
    draw_arrow(draw, (c2_x + col_w, 660), (c3_x, 660), fill=(99, 102, 241), width=2)
    draw_arrow(draw, (c3_x + col_w, 800), (c4_x, 800), fill=(236, 72, 153), width=2)

    # 4. BOTTOM LAYER: UNIFIED DUAL EXECUTION PLANE & EXTERNAL DELIVERABLES (Y: 1010 - 1310)
    draw_box(draw, [100, 1010, w - 100, 1310], fill=(16, 22, 38), outline=(139, 92, 246), width=2, radius=14)
    draw.rounded_rectangle([100, 1010, w - 100, 1055], radius=14, fill=(32, 24, 52))
    draw.rectangle([100, 1035, w - 100, 1055], fill=(32, 24, 52))
    draw.text((125, 1022), "UNIFIED DUAL EXECUTION PLANE & EXTERNAL DELIVERABLES (LOCAL + GOOGLE CLOUD RUN PRODUCTION)", font=f_sec_hdr, fill=(196, 181, 253))

    # Flow arrows down to Bottom Layer
    for ax in [380, 980, 1580, 2180]:
        draw_arrow(draw, (ax, 980), (ax, 1010), fill=(139, 92, 246), width=2)

    # 3 Delivery Pillars in Bottom Layer
    bot_w = (w - 200 - 2 * 25) // 3
    bot_pillars = [
        ("A. Bare-Metal Offline Resilience", "100% Fail-Closed Local Operation\nWorkstation NVMe Storage + SQLite WAL Mode\nLocal Gemma/Custom Weights Engine\nZero cloud dependence, immune to outages"),
        ("B. Google Cloud Run Production", "Live Service: sentinari-core-00035-bxf\nCloud SQL (PostgreSQL 16 + pgvector)\nGemini 2.5/3.0 reasoning loops via google-genai\nGlobal dynamic scaling with 100% traffic"),
        ("C. Enterprise & Boardroom Outputs", "Publication-Grade 15-Indicator R&D Papers\nFigure 6.4 5-Year Boardroom Fiscal Forecasts\nMerciless 1-Page A4 Forensic Governance Audits\nComplete 11-Minute Master Video Walkthrough"),
    ]
    for i, (b_hdr, b_bd) in enumerate(bot_pillars):
        bx = 125 + i * (bot_w + 25)
        by = 1075
        draw_box(draw, [bx, by, bx + bot_w, by + 215], fill=(22, 28, 46), outline=(48, 42, 85), width=1, radius=10)
        draw.text((bx + 20, by + 16), b_hdr, font=f_box_hdr, fill=(255, 255, 255))
        draw.line([bx + 20, by + 48, bx + bot_w - 20, by + 48], fill=(38, 32, 70), width=1)
        for li, line in enumerate(b_bd.split("\n")):
            draw.text((bx + 20, by + 60 + li * 26), line, font=f_box_sub, fill=(203, 213, 225))

    # Footer
    draw.line([100, 1345, w - 100, 1345], fill=(30, 41, 59), width=1)
    foot_l = "Dr. Pierre C. Wepener • Sole Author & Chief Architect • Copyright © 2026 Inspirari Research Initiative • 100% Personal Initiative"
    foot_r = "Live Production: https://sentinari-core-250830594433.us-central1.run.app • Showroom: https://ongalali.github.io/sentinari/"
    draw.text((100, 1362), foot_l, font=f_foot, fill=(148, 163, 184))
    r_bbox = draw.textbbox((0, 0), foot_r, font=f_foot)
    rw = r_bbox[2] - r_bbox[0]
    draw.text((w - 100 - rw, 1362), foot_r, font=f_foot, fill=(129, 140, 248))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    im.save(out_path, format="PNG")
    print(f"Rendered PNG schematic: {out_path} ({out_path.stat().st_size / 1024:.1f} KB)")

if __name__ == "__main__":
    png_target = Path("D:/Sentinari/docs/sentinari_functional_schematic.png")
    render_png(png_target)
    static_target = Path("D:/Sentinari/static/sentinari_functional_schematic.png")
    render_png(static_target)
