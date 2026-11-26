# Sentinari — Architecture Tree (§45)

Rendered reference for the documentation image. Generated at the §45 rebrand;
keep it in sync when the layout changes.

```
Sentinari/
│
├── run_smi.py                     # Core entrypoint — uvicorn app.main:app on 127.0.0.1:8099
├── launch-sentinari.bat / .sh     # Core launcher (never duplicates a running server)
├── adversarial_battery.py         # Live SENTINEL gauntlet (owner-facing, stays at root)
├── 1-run-key.txt                  # Owner-local key material (kept deliberately, uncommitted usage)
├── pubmedapi.md / pubmedprocess.md# Owner-local API notes
├── README.md                      # Overview + quickstart (this repo's front door)
│
├── app/                           # THE CORE (FastAPI + SQLite, port 8099)
│   ├── main.py                    #   HTTP surface: UI routes, /api/*, startup gates
│   ├── config.py                  #   Settings loader (settings.yaml + env belt-and-braces)
│   ├── security.py                #   Admin auth, session cookies, localhost-only fence
│   ├── llm_gateway.py             #   Provider-agnostic gateway — LOCAL providers only
│   ├── llm_firewall.py            #   Provider allowlist + blocked-model substrings (defense)
│   ├── llm_boundary.py            #   Runtime boundary status
│   ├── ollama_client.py           #   Ollama transport (current local engine)
│   ├── conversation.py            #   Chat brain: modes, persona, fallbacks, escalation filing
│   ├── playground.py              #   Playground engine: reasoning profiles, benchmarks
│   ├── retrieval.py / rag/        #   Vector retrieval over the library
│   ├── ingestion.py / auto_ingest.py / chunking.py / parsing.py / text_pdf.py
│   │                              #   Ingestion pipeline: PDF layers, chunking, embed budget
│   ├── library_router.py          #   Routes corpora to library DBs
│   ├── db.py                      #   Schema: chat, tasks, qualia_history (trajectories)
│   ├── qualia.py                  #   Qualia state model (S/A/Q vectors, stability)
│   ├── qualia_recommendation.py   #   Parameter recommendations from history
│   ├── operator_control.py        #   Operator console state + qualia history recorder
│   ├── learning_index.py          #   The examiner: probe → grade → persist (paused §41)
│   ├── unsupervised.py            #   Clustering layer (rung 2: closed curriculum loop)
│   ├── pattern_api / _store / _worker / _report
│   │                              #   Pattern Discovery (DARPA project 2)
│   ├── sentinel_pipeline / _firewall / _domains / _prototype
│   │                              #   SENTINEL verification pipeline (DARPA project 1)
│   ├── external_validation.py     #   Four-stage verification support
│   ├── victus.py                  #   Dormant challenger (state machine, kill switch, audit)
│   ├── assessment_pipeline.py     #   5-stage ladder: HLE gate at 65% → SWE-bench Pro (§47)
│   ├── escalation_queue.py        #   Local ticket queue — manual answers only, zero network
│   ├── task_worker / load_queue / load_progress
│   │                              #   Background work routing
│   ├── session_memory / discussion_memory
│   │                              #   Conversation memory
│   ├── skills_store / skill_review#   Skill packs (shared root env)
│   ├── openalex_worker / pubmed_worker
│   │                              #   Dataset sourcing workers (manual runs)
│   ├── video_lab / video_jobs     #   CPU video studio (Workflow 2)
│   ├── coding_corpus / coding_governance / shell_policy / scan_workspace
│   │                              #   Corpus + governance + workspace safety
│   ├── output_sanitizer / response_guardrails / fuzzy_logic / ayscio_pipeline
│   │                              #   Output hygiene + scoring support
│   ├── taxonomy.py                #   Knowledge taxonomy maintenance
│   └── gateway_guardian.py        #   Guardian-routed gateway logic
│
├── sentinel/                      # GUARDIAN LAYER (importable package)
│   ├── guardian.py                #   Sentinel class + trace chain
│   ├── domains.py                 #   Scientific domain registry
│   ├── api_registry.py            #   External API registry (routed, not called directly)
│   ├── gateway_guardian.py        #   Field/API routing decisions
│   ├── relationships.py           #   Domain relationships
│   └── benchmarks.py              #   Per-field benchmarks
│
├── config/
│   ├── settings.yaml              #   Single runtime source: paths, llm, firewall, victus gates
│   ├── persona_sentinari.yaml     #   Canonical persona seed (sole source)
│   ├── adapter_registry.yaml      #   Adapter metadata
│   └── sentinel_policy.yaml       #   SENTINEL policy
│
├── templates/                     # USER CONSOLES (all Sentinari-branded, §45)
│   ├── sentinari_start_console.html   # /ui/start — the front desk
│   ├── playground_console.html        # /ui/playground — domains grid + training
│   ├── qualia_console.html            # /ui/qualia — Qualia Lab
│   ├── direct_console.html            # /ui/direct — direct chat
│   ├── chat_console.html              # /ui/chat — knowledge chat + uploads
│   ├── admin_console.html             # /ui/admin — operator console
│   ├── admin_login.html               # /ui/login
│   ├── learning_workspace.html        # /ui/learning — examiner UI
│   ├── patterns_workspace.html        # /ui/patterns — Pattern Discovery
│   ├── search_workspace.html          # /ui/search — library by field
│   ├── model_deviation_lab.html       # /ui/model-lab — comparison scoring
│   ├── playground_workbench.html      # workbenches A/B
│   ├── wan_console.html               # CPU video studio
│   └── a1_logs_console.html           # /ui/a1-logs — qualia audit logs
│
├── Sentinari-server/              # INFERENCE SERVER (port 8100)
│   ├── server_onnx.py             #   ONNX runtime server (degraded until weights land)
│   ├── launch-all.bat             #   One double-click: 8100 + 8099 + browser
│   ├── convert_to_onnx.py         #   Converter CLI wrapper (rig day)
│   ├── requirements-inference.txt #   Runtime deps (transformer-free by design)
│   ├── requirements-conversion.txt#   Converter-only deps (never installed into runtime venv)
│   └── RIG_DAY_RUNBOOK.md         #   The migration-day script (mirrored in docs/)
│
├── scripts/                       # One-shot maintenance utilities
│
├── assessments/                   # ASSESSMENT LADDER (§47)
│   ├── hle.py                     #   cais/hle loader (GATED — owner HF token in .env)
│   ├── swe_pro.py                 #   ScaleAI/SWE-bench_Pro loader (642 tasks, cached)
│   ├── _hf.py                     #   Shared HF token/cache plumbing (in-tree cache)
│   └── swe-workbench/             #   Owner-downloaded execution harness (untracked, 132MB)
│
├── ml/                            # ML WORKSHOP (§48, isolated venv .venv-ml)
│   ├── pytorch.py                 #   GPU verification + baseline training loop
│   ├── scientific_ml.py           #   PINN template (data + physics constraint loss)
│   ├── sci_ml_core.py             #   PINN core (Jacobian residual, §48 grad fix)
│   ├── requirements-ml.txt        #   Day-1 CUDA torch spec (exact +cu128 pin)
│   ├── environment.yml            #   Rig-day miniconda spec (Ubuntu, sm_120)
│   └── README.md                  #   Verified results + run instructions
│
├── tests/                         # Self-verifying test modules
│   └── test_sentinel.py           #   python -m tests.test_sentinel
│
├── docs/                          # THE MEMORY + PAPER TRAIL
│   ├── CONTINUITY_LOG.md          #   §-entries: the project's memory across sessions
│   ├── VALIDATION_PROTOCOL.md     #   Verification protocol
│   ├── SENTINEL-v2_Review.md      #   SENTINEL design review
│   ├── RIG_DAY_RUNBOOK.md         #   Rig-day migration script (mirror)
│   ├── architecture.md            #   This tree
│   └── CREDITS.md                 #   Credits
│
└── data/                          # RUNTIME STATE (git-ignored — never committed)
    ├── smi_vocationalllm.db       #   Core DB (renames to sentinari.db on MIGRATION DAY)
    ├── sentinari.db               #   vector library (§51 renamed from library_gemma.db)
    ├── patterns.db                #   Pattern Discovery store
    ├── knowledge_taxonomy/SMI_Log/#   Ingest logs + skills (path renames on migration day)
    ├── skills/                    #   Shared skill packs
    ├── escalation_queue/          #   Escalation tickets (manual answers)
    └── victus_audit_log.jsonl     #   Victus audit (dormant → append-only)
```

## Ports and seams

- **8099** — core (FastAPI). Owns settings, DB, UI, all orchestration.
- **8100** — inference (ONNX). Rests `degraded:true` until `model.path` is
  set on rig day; then the examiner wires to it and rung 2 opens.
- **Rig day** — convert → flip `model.path` → verify real generation →
  re-point chat model labels → rename `data/` DB paths (backup-first).
