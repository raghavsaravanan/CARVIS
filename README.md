# Carvis

Hands-free AI mechanic copilot for manual-grounded automotive answers.

## Repository layout

```text
backend/    FastAPI API, ingestion, Qdrant retrieval, tests
frontend/   Vite/React browser and iPhone-camera demo
docs/       architecture, integration plans, and platform decisions
ios/        Meta CameraAccess native integration handoff
```

Hands-free voice RAG for automotive technicians. Ask torque and install specs out loud; Carvis answers in one or two clear sentences from shop manuals — not from guesswork.

```text
┌─────────────┐     ┌──────────────────┐     ┌─────────────────┐
│ Manual PDFs │ ──► │ backend/ingest.py│ ──► │ Qdrant Cloud    │
│ (local only)│     │ LlamaParse +     │     │ carvis_specs    │
└─────────────┘     │ FastEmbed        │     │ + shop_id       │
                    └──────────────────┘     └────────┬────────┘
                                                      │
Mechanic ──► Vapi ──► Render backend/main.py /vapi-tool ◄─┘
                         FastEmbed search
                         spoken 1–2 sentences ──► headset
```

## Why two Python files?

| File | Role | When it runs |
| --- | --- | --- |
| `backend/ingest.py` | Offline seeder | You add/update PDFs (laptop / CI) |
| `backend/main.py` | Live Vapi webhook | Every Call / tool hit (Render) |

Decoupled on purpose: eating manuals is slow and credit-sensitive; answering must stay sub-second.

## Repository map

```text
Carvis/
├── backend/                 # FastAPI + ingest + Qdrant tooling
│   ├── main.py              # /vapi-tool, /upload, /health
│   ├── ingest.py            # PDF → chunks → Qdrant Cloud
│   ├── purge_db.py          # Wipe/recreate empty carvis_specs
│   ├── setup.sh             # Prerequisite check
│   ├── requirements.txt
│   ├── Procfile             # Backend-local Render start command
│   ├── runtime.txt          # Python 3.12
│   ├── DEMO.md              # Shop-demo runbook
│   ├── tests/
│   ├── .env.example
│   ├── *.pdf                # Local manuals only (gitignored)
│   ├── carvis_mvp_db/       # Optional local Qdrant (gitignored)
│   └── .carvis_parse_cache/ # Parse cache (gitignored)
├── frontend/                # Vite/React vision-query demo client
├── docs/                    # Architecture and integration decisions
├── ios/                     # Meta CameraAccess handoff
├── render.yaml              # Render Blueprint
├── README.md
└── .gitignore
```

**Note:** PDF manuals are kept on disk for ingest but are **not** tracked in git. Runtime answers come from Qdrant Cloud.

## Phase 1 — Ingest (build the brain)

```text
PDF
 │
 ├─ local cache hit? ──yes──► skip LlamaParse (no credits)
 │
 └─no──► LlamaParse (tier=cost_effective)
           │
           ▼
        Markdown tables (+ torque fallback for scans)
           │
           ▼
        Expand units (lb. ft. → foot-pounds)
           │
           ▼
        Atomic table chunks (never split mid-table)
           │
           ▼
        FastEmbed (BAAI/bge-small-en-v1.5, 384-d)
           │
           ▼
        Qdrant upsert by document_ref
        payload: text, year, make, model, section
```

**Demo corpus to ingest**

| PDF | Tags |
| --- | --- |
| `intake_manifold_guide.pdf.pdf` | 2019 · chevrolet · silverado |
| `AMS Performance VR30 Guide.pdf` | 2016 · nissan · vr30 |

These PDFs are local-only inputs and are not currently present in the repository. Qdrant must contain at least one correctly tagged manual before the API can start answering.

```bash
cd backend
../.venv/bin/python ingest.py "intake_manifold_guide.pdf.pdf" --year 2019 --make chevrolet --model silverado
../.venv/bin/python ingest.py "AMS Performance VR30 Guide.pdf" --year 2016 --make nissan --model vr30
# PDF changed? add --force-parse   | hard scan? add --premium
```

## Phase 2 — Live voice (use the brain)

```text
"What's the lower intake torque on a VR30?"
                │
                ▼
         Vapi STT + LLM
                │
                ▼
   POST /vapi-tool
   { query, make, model, year }
                │
                ▼
   Hybrid search in Qdrant
   1) exact year+make+model
   2) soft OR match
   3) semantic fallback
                │
                ▼
   format_voice_answer → 1–2 sentences
                │
                ▼
   { "results": [{ "toolCallId": "vapi-call", "result": "..." }] }
                │
                ▼
         Vapi TTS → mechanic
```

## Vision-query web demo

The first glasses-independent vertical slice is available in `frontend/`. It accepts a JPEG from an iPhone/browser, requires explicit year/make/model, sends the image and question to `POST /vision-query`, identifies only visual component context with a vision model, and retrieves the answer from the matching manual through the existing Qdrant pipeline. The browser speaks the returned answer with its local speech-synthesis route.

Backend environment additions:

| Variable | Purpose |
| --- | --- |
| `NVIDIA_API_KEY` | Server-side Nemotron inference only; never expose to the browser |
| `NEMOTRON_MODEL` | Optional override; defaults to `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` |
| `NEMOTRON_BASE_URL` | Optional NVIDIA-compatible endpoint override |
| `VISION_PROVIDER` | `nemotron` by default; set to `openai` only for the explicit fallback |

Run locally:

```bash
cd backend
uvicorn main:app --host 127.0.0.1 --port 8000

# second terminal
cd frontend
npm install
npm run dev
```

Open the Vite URL, choose a JPEG, confirm the manual vehicle fields, and ask a question. A matching uploaded manual is required; the image never establishes vehicle year, make, or model.

## State and database architecture

Qdrant is the only database required for the current demo: it stores the embedded service-manual chunks and vehicle metadata used for retrieval. Request/session state is short-lived in the FastAPI and client flow. SpacetimeDB is deferred until it provides a fundamental product capability such as multi-device live state or persistent shop workflow; it is not part of the current runtime path.

## Quick start (local Call test)

```bash
# Terminal 1
cd backend
../.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000

# Terminal 2
ngrok http 8000
```

Vapi tool `lookup_spec` Server URL: `https://YOUR-NGROK-HOST/vapi-tool`

See [backend/DEMO.md](backend/DEMO.md) for smoke questions and curl examples.

## Deploy API on Render

The live webhook is [`backend/main.py`](backend/main.py). Ingest stays on your laptop (or CI) against Qdrant Cloud — do **not** run `ingest.py` as the Render web process.

1. Push this repo to GitHub (secrets stay in Render env vars, never in git).
2. [Render](https://dashboard.render.com) → **New** → **Blueprint** (uses [`render.yaml`](render.yaml))  
   or **Web Service** from the repo with:
   - **Root Directory:** leave blank (repo root)
   - **Build:** `pip install -r backend/requirements.txt`
   - **Start:** `cd backend && uvicorn main:app --host 0.0.0.0 --port $PORT`
   - **Health check path:** `/health`
3. Set environment variables (Dashboard → Environment):

| Variable | Required on Render |
| --- | --- |
| `QDRANT_URL` | Yes |
| `QDRANT_API_KEY` | Yes |
| `VAPI_WEBHOOK_SECRET` | Yes (match Vapi `X-Vapi-Secret` header) |
| `LLAMA_CLOUD_API_KEY` | No (ingest only) |

4. First boot downloads the FastEmbed model — expect a slow deploy / cold start.
5. Point Vapi `lookup_spec` Server URL to:
   `https://YOUR-SERVICE.onrender.com/vapi-tool`  
   Keep the `X-Vapi-Secret` header equal to `VAPI_WEBHOOK_SECRET`.
6. Smoke test:
   ```bash
   curl -s https://YOUR-SERVICE.onrender.com/health
   curl -s -X POST https://YOUR-SERVICE.onrender.com/vapi-tool \
     -H "Content-Type: application/json" \
     -H "x-vapi-secret: YOUR_SECRET" \
     -d '{"query":"lower intake manifold torque AMS VR30"}'
   ```

## Stack

| Layer | Choice |
| --- | --- |
| Parse | LlamaParse (`cost_effective`) + local `backend/.carvis_parse_cache/` |
| Embed | FastEmbed local CPU (also on Render) |
| Store | Qdrant Cloud `carvis_specs` (local `backend/carvis_mvp_db` for offline only) |
| API | FastAPI on Render |
| Voice | Vapi (WebRTC + STT/TTS) |
| Tunnel | Ngrok (local dev only) |

## Design rules

- **Verbal:** ≤2 spoken sentences, no filler
- **Units:** always `foot-pounds` / `inch-pounds` / `newton-meters`
- **Tables:** never clip across chunk boundaries
- **Credits:** cache-first; never force-parse unless the PDF changed
- **Tenancy:** every vector and every search is scoped by `shop_id` (default `shop_demo`)

## What’s next

Integrate Meta's official CameraAccess sample after Xcode and physical-glasses prerequisites are available. Then connect the captured JPEG to `/vision-query` and verify audio output. SpacetimeDB remains deferred; its design is preserved in [`docs/spacetime-integration-plan.md`](docs/spacetime-integration-plan.md) if the demo scope later requires it. See [`ios/README.md`](ios/README.md).
