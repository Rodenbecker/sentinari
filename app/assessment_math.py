"""Assessment Matrix math engine (§79) — implemented from the spec.

corrections/Assessment_Matrix.docx defines the scoring law for New Pattern
Discovery, and the owner directive is explicit: the equations are CODE, not
documentation — the numbers must be computed from the actual data each
discovered pattern produced. This module implements that engine:

1. Dimension operational levels  x_i (0-10)
   Derived per-dimension from the pattern's real extraction record:
   evidence-chunk depth, entity/relation graph mass, confidence, cross-field
   span, and recorded benefit analysis. Nothing is invented; each x_i is a
   measured quantity with its inputs stated.

2. Sustainability score functions  S_i(x_i)  (standardised 0-1)
   S_i(x) = G_i(x) / A_i — the normalised coupled bell curve at the
   pattern's measured operating level, so deviation from a dimension's
   sweet spot lowers the score exactly as the document prescribes.

3. Coupled bell curves  G_i(x) = A_i * exp(-(x - mu_i)^2 / (2 sigma_i^2))
   With the document's baseline parameters (mu, sigma, A) and its three
   interdependence (coupling) rules applied:
     Rule A  Intelligence > 7  -> Human Agency mu/sigma contract
     Rule B  Risk > 5          -> Societal sigma widens, Decision mu drops
     Rule C  Scientific > 7    -> Knowledge amplitude lifts (capped 1.0)

4. Normalized Dimension Impact  SD_i(%) = (W_i * S_i(x)) / NSIS * 100
   where NSIS = sum_j W_j * S_j(x) is the Net Sustainable Impact Score,
   and W is the fixed Sustainability Weight vector (sum = 1.0).

5. Impact level bands (the weights table): 0-33.33% Level 1 (Low),
   33.34-67.67% Level 2 (Medium), 67.68-100% Level 3 (High).

6. Net Sustainability Envelope: average of the seven coupled G_i curves
   across the 0-10 x-axis — the curve data the R&D paper plots.
"""

from __future__ import annotations

import math
from typing import Any

# ---------------------------------------------------------------------------
# Document baselines (Assessment_Matrix.docx, "The Mathematical Engine")
# ---------------------------------------------------------------------------

DIMENSIONS = ["Knowledge", "Intelligence", "Decision", "Human Agency", "Societal", "Scientific", "Risk"]

BASELINES: dict[str, dict[str, float]] = {
    "Knowledge":     {"mu": 8.0, "sigma": 2.5, "A": 0.90},
    "Intelligence":  {"mu": 6.0, "sigma": 2.0, "A": 0.85},
    "Decision":      {"mu": 5.0, "sigma": 1.8, "A": 0.80},
    "Human Agency":  {"mu": 9.0, "sigma": 1.5, "A": 0.95},
    "Societal":      {"mu": 7.5, "sigma": 2.2, "A": 0.90},
    "Scientific":    {"mu": 8.5, "sigma": 2.8, "A": 0.85},
    "Risk":          {"mu": 2.0, "sigma": 1.2, "A": 0.95},
}

# Sustainability Weights, sum = 1.0. Risk carries weight as an impact pillar
# (the document treats it as a first-class dimension of the matrix).
WEIGHTS: dict[str, float] = {
    "Knowledge":     0.18,
    "Intelligence":  0.14,
    "Decision":      0.14,
    "Human Agency":  0.16,
    "Societal":      0.16,
    "Scientific":    0.14,
    "Risk":          0.08,
}
assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9

# ---------------------------------------------------------------------------
# Physical & Mechanical Engineering Matrix (Custom Override Mode)
# ---------------------------------------------------------------------------
ENGINEERING_DIMENSIONS = [
    "Structural Rigidity",
    "Thermodynamic Efficiency",
    "Kinematic Reliability",
    "Thermal Dissipation",
    "Material Fatigue Life",
    "Mass & Power Density",
    "Manufacturability",
]

ENGINEERING_BASELINES: dict[str, dict[str, float]] = {
    "Structural Rigidity":      {"mu": 8.5, "sigma": 2.0, "A": 0.95},
    "Thermodynamic Efficiency": {"mu": 8.0, "sigma": 2.2, "A": 0.90},
    "Kinematic Reliability":    {"mu": 9.0, "sigma": 1.5, "A": 0.95},
    "Thermal Dissipation":      {"mu": 7.5, "sigma": 2.0, "A": 0.85},
    "Material Fatigue Life":    {"mu": 8.5, "sigma": 1.8, "A": 0.90},
    "Mass & Power Density":     {"mu": 8.0, "sigma": 2.4, "A": 0.85},
    "Manufacturability":        {"mu": 7.0, "sigma": 2.2, "A": 0.80},
}

ENGINEERING_WEIGHTS: dict[str, float] = {
    "Structural Rigidity":      0.18,
    "Thermodynamic Efficiency": 0.16,
    "Kinematic Reliability":    0.16,
    "Thermal Dissipation":      0.14,
    "Material Fatigue Life":    0.14,
    "Mass & Power Density":     0.12,
    "Manufacturability":        0.10,
}


LEVEL_BANDS = [
    (33.33, "Low Impact (Level 1)"),
    (67.67, "Medium Impact (Level 2)"),
    (100.0, "High Impact (Level 3)"),
]


def gaussian(x: float, mu: float, sigma: float, amplitude: float) -> float:
    """G_i(x) = A * exp(-(x - mu)^2 / (2 sigma^2)) — the document's engine."""
    sigma = max(0.5, float(sigma))
    return float(amplitude) * math.exp(-((float(x) - float(mu)) ** 2) / (2.0 * sigma * sigma))


def apply_coupling(params: dict[str, dict[str, float]], x: dict[str, float]) -> dict[str, dict[str, float]]:
    """Deep-copy the baselines and apply the document's coupling rules."""
    dyn = {k: dict(v) for k, v in params.items()}

    # Rule A: Runaway Intelligence suppresses Human Agency.
    if x.get("Intelligence", 0.0) > 7.0:
        excess = x["Intelligence"] - 7.0
        dyn["Human Agency"]["mu"] -= excess * 0.4
        dyn["Human Agency"]["sigma"] -= excess * 0.15

    # Rule B: Elevated Systemic Risk destabilises Societal and Decision.
    if x.get("Risk", 0.0) > 5.0:
        excess = x["Risk"] - 5.0
        dyn["Societal"]["sigma"] += excess * 0.3
        dyn["Decision"]["mu"] -= excess * 0.25

    # Rule C: Advancing Scientific capability lifts Knowledge amplitude.
    if x.get("Scientific", 0.0) > 7.0:
        dyn["Knowledge"]["A"] = min(1.0, dyn["Knowledge"]["A"] + 0.05)

    return dyn


def _level_band(percent: float) -> str:
    for ceiling, label in LEVEL_BANDS:
        if percent <= ceiling:
            return label
    return LEVEL_BANDS[-1][1]


# ---------------------------------------------------------------------------
# Measured dimension levels from the pattern's real extraction record
# ---------------------------------------------------------------------------

def _clamp10(v: float) -> float:
    return max(0.0, min(10.0, float(v)))


def measure_dimension_levels(pattern: dict[str, Any], graph: dict[str, Any] | None = None, mode: str = "canonical") -> dict[str, dict[str, Any]]:
    """Derive each dimension's operational level x_i (0-10) from actual data.

    Every level is a transparent sum of measured contributions — the caller
    can display exactly why a dimension scored what it did. Inputs:
      - evidence chunks actually stored for the pattern
      - entity/relation graph mass connected to the pattern (pattern_store)
      - the extraction pipeline's confidence
      - cross-field span of fields_involved
      - whether an LLM benefit analysis has been recorded
    """
    evidence = pattern.get("evidence") or []
    n_evidence = len(evidence)
    evidence_chars = sum(len(str((e or {}).get("chunk_text") or "")) for e in evidence)
    docs = len({int((e or {}).get("document_id") or 0) for e in evidence if (e or {}).get("document_id")})
    confidence = float(pattern.get("confidence") or 0.0)
    try:
        fields = [str(f) for f in __import__("json").loads(str(pattern.get("fields_involved") or "[]"))]
    except Exception:
        fields = []
    field_span = max(1, len(fields))
    has_benefits = bool(str(pattern.get("benefits") or "").strip())
    graph = graph or {}
    n_entities = int(graph.get("entities") or 0)
    n_relations = int(graph.get("relations") or 0)

    # Contribution primitives (each is a measured quantity):
    depth = min(3.0, 0.6 * n_evidence)                    # evidence-chunk depth
    breadth = min(2.0, 0.5 * docs)                        # distinct source documents
    graph_mass = min(2.5, 0.25 * n_entities + 0.35 * n_relations)
    confidence_term = 2.0 * confidence                    # pipeline confidence
    span_term = min(2.0, 0.7 * field_span)                # cross-field reach
    benefit_term = 1.0 if has_benefits else 0.0           # analysed benefits
    # Risk dimension is inverted: the more speculative the pattern
    # (low confidence, thin evidence), the higher the operational risk level.
    risk_speculation = max(0.0, 4.0 - 4.0 * confidence) + (1.5 if n_evidence < 2 else 0.0)

    def total(*terms: float) -> float:
        return _clamp10(sum(terms))


    if str(mode).lower() == "engineering":
        eng_contributions: dict[str, dict[str, float]] = {
            "Structural Rigidity":      {"evidence_depth": depth, "graph_mass": graph_mass, "confidence": confidence_term},
            "Thermodynamic Efficiency": {"evidence_depth": depth, "source_breadth": breadth, "confidence": confidence_term},
            "Kinematic Reliability":    {"graph_mass": graph_mass, "confidence": confidence_term, "benefits": benefit_term},
            "Thermal Dissipation":      {"field_span": span_term, "evidence_depth": depth, "confidence": confidence_term},
            "Material Fatigue Life":    {"evidence_depth": depth, "confidence": confidence_term, "graph_mass": graph_mass},
            "Mass & Power Density":     {"source_breadth": breadth, "field_span": span_term, "benefits": benefit_term},
            "Manufacturability":        {"field_span": span_term, "source_breadth": breadth, "confidence": confidence_term},
        }
        eng_levels = {dim: total(*c.values()) for dim, c in eng_contributions.items()}
        return {
            dim: {
                "level": round(eng_levels[dim], 2),
                "contributions": {k: round(v, 2) for k, v in c.items() if v},
            }
            for dim, c in eng_contributions.items()
        }

    contributions: dict[str, dict[str, float]] = {
        "Knowledge":     {"evidence_depth": depth, "source_breadth": breadth, "graph_mass": graph_mass, "confidence": confidence_term},
        "Intelligence":  {"evidence_depth": depth, "graph_mass": graph_mass, "confidence": confidence_term, "field_span": span_term},
        "Decision":      {"evidence_depth": depth, "source_breadth": breadth, "confidence": confidence_term, "benefits": benefit_term},
        "Human Agency":  {"benefits": benefit_term, "evidence_depth": depth, "confidence": confidence_term, "field_span": span_term},
        "Societal":      {"field_span": span_term, "source_breadth": breadth, "benefits": benefit_term, "evidence_depth": depth},
        "Scientific":    {"graph_mass": graph_mass, "evidence_depth": depth, "field_span": span_term, "confidence": confidence_term},
        "Risk":          {"speculation_gap": risk_speculation, "thin_evidence": 1.5 if n_evidence < 2 else 0.0},
    }
    levels = {dim: total(*c.values()) for dim, c in contributions.items()}
    return {
        dim: {
            "level": round(levels[dim], 2),
            "contributions": {k: round(v, 2) for k, v in c.items() if v},
        }
        for dim, c in contributions.items()
    }


# ---------------------------------------------------------------------------
# Full matrix evaluation for one pattern
# ---------------------------------------------------------------------------

def evaluate_pattern_matrix(pattern: dict[str, Any], graph: dict[str, Any] | None = None, mode: str = "canonical") -> dict[str, Any]:
    """Compute SD_i(%), levels, curves and NSIS for a discovered pattern."""
    eval_mode = str(mode or "canonical").strip().lower()
    is_eng = eval_mode == "engineering"
    is_unconstrained = eval_mode == "unconstrained"

    target_dims = ENGINEERING_DIMENSIONS if is_eng else DIMENSIONS
    target_baselines = ENGINEERING_BASELINES if is_eng else BASELINES
    target_weights = ENGINEERING_WEIGHTS if is_eng else WEIGHTS

    measured = measure_dimension_levels(pattern, graph, mode=eval_mode)
    x = {dim: m["level"] for dim, m in measured.items()}
    dyn = apply_coupling(target_baselines, x)

    # S_i(x) = G_i(x) / A_i — the standardised 0-1 sustainability score.
    s_scores: dict[str, float] = {}
    g_values: dict[str, float] = {}
    for dim in target_dims:
        p = dyn[dim]
        g = gaussian(x[dim], p["mu"], p["sigma"], p["A"])
        g_values[dim] = g
        if is_unconstrained:
            s_scores[dim] = 1.0  # Zero limiting constraint on frontier exploration
        else:
            s_scores[dim] = min(1.0, g / p["A"]) if p["A"] else 0.0

    nsis = 1.0 if is_unconstrained else sum(target_weights[d] * s_scores[d] for d in target_dims)
    sd_percent: dict[str, float] = {}
    for dim in target_dims:
        raw = (target_weights[dim] * s_scores[dim] / nsis * 100.0) if nsis > 0 else 0.0
        sd_percent[dim] = round(raw, 2)

    # Net envelope curve across the 0-10 axis (document's chart data).
    xs = [round(i / 10, 1) for i in range(101)]
    curves: dict[str, list[float]] = {}
    for dim in target_dims:
        p = dyn[dim]
        curves[dim] = [round(gaussian(v, p["mu"], p["sigma"], p["A"]), 4) for v in xs]
    envelope = [round(sum(curves[d][i] for d in target_dims) / len(target_dims), 4) for i in range(len(xs))]

    return {
        "mode": eval_mode,
        "dimensions": target_dims,
        "x_levels": {d: round(x[d], 2) for d in target_dims},
        "measured": measured,
        "dynamic_params": {d: {k: round(v, 3) for k, v in dyn[d].items()} for d in target_dims},
        "s_scores": {d: round(s_scores[d], 4) for d in target_dims},
        "g_values": {d: round(g_values[d], 4) for d in target_dims},
        "weights": target_weights,
        "nsis": round(nsis, 4),
        "sd_percent": sd_percent,
        "level_bands": {d: _level_band(sd_percent[d]) for d in target_dims},
        "curve_x": xs,
        "curves": curves,
        "envelope": envelope,
    }
