# Sentinari by Inspirari

[![License: Proprietary](https://img.shields.io/badge/License-Proprietary%20%26%20All%20Rights%20Reserved-red.svg?style=for-the-badge)](LICENSE.md)
[![GitHub Pages Showroom](https://img.shields.io/badge/Showroom-GitHub%20Pages-6366f1?style=for-the-badge&logo=github)](https://ongalali.github.io/sentinari/)
[![Google Cloud Run](https://img.shields.io/badge/Production%20Studio-Cloud%20Run-10b981?style=for-the-badge&logo=googlecloud)](https://sentinari-core-250830594433.us-central1.run.app)

> ⚠️ **PROPRIETARY INTELLECTUAL PROPERTY & EVALUATION NOTICE**  
> **Copyright © 2026 Dr. Pierre C. Wepener. All Rights Reserved.**  
> This codebase is published **strictly for view-only inspection, academic peer review, and due diligence evaluation**. Downloading, cloning (`git clone`), copying, reproducing, distributing, modifying, or utilizing this codebase for software development, commercial applications, or training external AI/ML models is **strictly prohibited** without prior written authorization. See [LICENSE.md](LICENSE.md).

> 🌐 **Live Public Showroom**: [https://ongalali.github.io/sentinari/](https://ongalali.github.io/sentinari/)  
> ⚡ **Cloud Run Production Studio**: [https://sentinari-core-250830594433.us-central1.run.app](https://sentinari-core-250830594433.us-central1.run.app)

A sovereign, zero-cloud AI research platform: a grounded knowledge library, a
Qualia state model over the conversation engine, an examiner that grades
applied knowledge, scientific pattern discovery, and an ONNX inference server
for the rig-day cutover.

## Quickstart

```
:: double-click (starts the inference server on :8100 and the core on :8099)
Sentinari-server\launch-all.bat

:: or, core only
launch-sentinari.bat
```

- Core (FastAPI + SQLite): `http://127.0.0.1:8099` — health at `/health`
- Inference server (ONNX): `http://127.0.0.1:8100` — `degraded:true` is the
  correct resting state until the ONNX engine is configured (see
  [docs/RIG_DAY_RUNBOOK.md](docs/RIG_DAY_RUNBOOK.md))
- The chat surface stays dark until a local model engine is present. That is
  the zero-cloud doctrine (§41), not a fault: nothing may call the cloud.

## Layout

| Path | Contents |
| --- | --- |
| `app/` | FastAPI core: conversation, playground, retrieval, ingestion, Qualia, examiner, firewall |
| `sentinel/` | Guardian layer: domains, gateway guardian, relationships, benchmarks |
| `config/` | `settings.yaml` (single source of runtime config), `persona_sentinari.yaml` (canonical persona seed) |
| `templates/` | User consoles (start menu, playground, qualia lab, direct chat, admin, learning, patterns, search, victus, video) |
| `assessments/` | Assessment ladder: HLE + SWE-bench Pro loaders (HF cache in data/), execution harness local-only |
| `Sentinari-server/` | ONNX inference server (:8100), converter kit, `launch-all.bat`, rig-day runbook |
| `scripts/` | One-shot maintenance scripts |
| `docs/` | Continuity log, validation protocol, SENTINEL review, credits, rig-day runbook |
| `tests/` | Self-verifying test modules (run with `python -m tests.<name>`) |
| `data/` | Runtime databases and artifacts (git-ignored; never commit) |

See [docs/architecture.md](docs/architecture.md) for the full tree with
annotations, suitable for the documentation image.

## Doctrine

- **Zero cloud.** All inference and embedding is local. Cloud providers are
  deleted from the code, not merely disabled; the LLM firewall polices the
  provider allowlist in `config/settings.yaml`.
- **The continuity log is the memory.** Every working session appends a `§`
  entry to [docs/CONTINUITY_LOG.md](docs/CONTINUITY_LOG.md) and commits it.
  Agents hold no memory between sessions; the log and git history do.
- **Fail closed.** Victus (the dormant challenger), the escalation queue, and
  every autonomous loop sit behind explicit config gates, all OFF by default.

## Verification

```
.venv\Scripts\python.exe -m app.victus        :: 13/13 self-test
.venv\Scripts\python.exe -m tests.test_sentinel
```

Owned and operated by Inspirari.
