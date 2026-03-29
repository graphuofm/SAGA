# SAGA — Synthetic Agentic Graph Architecture

> **Temporal Graph Data Generator for VLDB 2026 Demo**

SAGA generates realistic temporal graphs with ground-truth anomaly labels, using a "skeleton-first, semantics-later" hybrid architecture.

## Architecture

```
Phase 1: igraph (C)  → Power-law skeleton + macro_time assignment
Phase 2: Dispatcher  → Task slicing by time blocks + UNKNOWN balance
Phase 3: LLM Agent   → RAG rules + semantic injection → micro_time edges
Phase 4: State Machine → Global time sort → business rules → anomaly labels
```

## Quick Start

```bash
cd /home/jding/SAGA
bash scripts/setup.sh        # Install Python + Node deps
cp .env.example .env         # Configure (edit if needed)
python3 server.py            # Start backend (terminal 1)
cd frontend && npm run dev   # Start frontend (terminal 2)
# Open http://localhost:3000
```

## Scenarios

| Scenario | RAG Source | Key Anomalies |
|----------|-----------|---------------|
| Financial AML | FATF, AMLSim | Smurfing, cycle, overdraft |
| Network IDS | CIC-IDS-2017 | DDoS, brute force, botnet |
| Cyber APT | MITRE ATT&CK | Lateral movement, exfiltration |
| Traffic | SUMO, Krauss | Accident cascade, congestion |
| Custom | User input | User-defined |

## Tech Stack

- **Backend**: Python 3.8+ / websockets / python-igraph / numpy / orjson
- **Frontend**: React 18 / Vite / MUI v5 (M3 Dark) / Recharts / Sigma.js
- **LLM**: Ollama / OpenAI / vLLM / Mock (via `.env`)
- **Protocol**: WebSocket (real-time) + HTTP (download)

## Time Dimension (First-Class Citizen)

```
Time Span (1 year)  →  Macro Block (by day = 365 blocks)  →  Micro Timestamp (minute)
```

## Project Structure

```
SAGA/
├── config.py              # Config + time helpers (reads .env)
├── server.py              # WS + HTTP server (pipeline orchestrator)
├── core/
│   ├── skeleton.py        # Phase 1: igraph BA + macro_time
│   ├── dispatcher.py      # Phase 2: task slicing + UNKNOWN
│   ├── agent.py           # Phase 3: LLM/Mock + RAG
│   └── state_machine.py   # Phase 4: sort + settle + anomaly
├── rag/                   # 4 industry rule sets + parameter inferrer
├── utils/                 # Logger + multi-format export
├── frontend/src/          # React + MUI + Sigma.js + Recharts
└── scripts/setup.sh       # One-click install
```

## Key APIs

**WebSocket**: `start_pipeline` / `pause` / `resume` / `stop` / `inject_event` / `get_node_detail` / `infer_parameters`

**HTTP**: `POST /estimate` / `GET /download` / `GET /download-log` / `GET /health`

## License

Academic use — VLDB 2026 Demo.
