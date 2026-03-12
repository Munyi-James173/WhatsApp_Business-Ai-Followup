# WhatsApp AI Follow-Up System

An offline, on-premises AI system that reads WhatsApp Business conversations,
decides whether a follow-up is warranted, schedules it intelligently, drafts
a human-sounding message, and sends it automatically—all without keyword lists.

---

## Architecture Overview

```
WhatsApp Cloud API / Twilio
        │
        ▼
  Webhook Receiver  (src/webhook.py)
        │
        ▼
  Conversation Store (SQLite)
        │
        ▼
  AI Analyser  ──────────────────►  Local LLM (Ollama / llama.cpp)
  (src/analyser.py)                  models/   (offline, on-prem)
        │
        ▼
  Scheduler  (src/scheduler.py)
        │
        ▼
  Message Drafter  (src/drafter.py)
        │
        ▼
  Sender  (src/sender.py)
        │
        ▼
  Audit Logger  (src/logger.py)  →  logs/audit.jsonl
```

---

## Requirements

| Requirement | Detail |
|---|---|
| Python | 3.10+ |
| Local LLM runtime | Ollama (recommended) OR llama.cpp server |
| Recommended model | `mistral:7b-instruct` or `llama3:8b-instruct` |
| RAM | 16 GB minimum (8 GB VRAM if GPU) |
| OS | Linux / macOS / Windows (WSL2) |
| WhatsApp | Cloud API (Meta) **or** Twilio WhatsApp |

---

## Quick Start

```bash
# 1. Clone / extract the project
cd whatsapp-ai-followup

# 2. Create virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Install Ollama and pull a model (one-time, needs internet)
curl -fsSL https://ollama.com/install.sh | sh
ollama pull mistral:7b-instruct  # ~4 GB download

# 5. Copy and edit configuration
cp config/settings.example.yaml config/settings.yaml
# Edit config/settings.yaml with your WhatsApp credentials and preferences

# 6. Initialise the database
python -m src.db init

# 7. Start the system (runs webhook + scheduler in one process)
python main.py

# 8. Expose your webhook (development)
ngrok http 8000
# Then set the ngrok URL as your WhatsApp webhook endpoint
```

---

## Configuration Guide (`config/settings.yaml`)

Every tunable parameter lives in one file. Key sections:

### `llm` — Local model settings
```yaml
llm:
  provider: ollama          # ollama | llamacpp
  model: mistral:7b-instruct
  base_url: http://localhost:11434
  temperature: 0.7          # Higher = more creative messages
  confidence_threshold: 0.72  # Min score to trigger follow-up (0–1)
```

### `timing` — When to follow up
```yaml
timing:
  rules:
    unanswered_quote:   { days: 6, business_hours_only: true }
    brochure_sent:      { days: 1, business_hours_only: true }
    general_inquiry:    { days: 3, business_hours_only: true }
    after_meeting:      { days: 1, business_hours_only: false }
    default:            { days: 2, business_hours_only: true }
  business_hours:
    start: "09:00"
    end:   "17:30"
    timezone: "Africa/Nairobi"   # change to your TZ
    working_days: [Mon, Tue, Wed, Thu, Fri]
```

### `whatsapp` — API credentials
```yaml
whatsapp:
  provider: cloud_api       # cloud_api | twilio
  # Meta Cloud API
  phone_number_id: "YOUR_PHONE_NUMBER_ID"
  access_token:   "YOUR_ACCESS_TOKEN"
  verify_token:   "YOUR_WEBHOOK_VERIFY_TOKEN"
  # Twilio (leave blank if using cloud_api)
  twilio_account_sid: ""
  twilio_auth_token:  ""
  twilio_from_number: ""
```

### `opt_out` — Suppression rules
```yaml
opt_out:
  keywords: ["stop", "unsubscribe", "no thanks", "not interested"]
  suppress_after_days: 30   # Don't follow up on very old threads
  max_follow_ups_per_thread: 3
```

---

## Retraining / Fine-tuning

The system uses a **prompt-engineered** local LLM—no weights need retraining
for normal use. To improve accuracy on your specific domain:

### Option A — Improve prompts (easiest)
Edit `src/prompts.py`. The analyser and drafter prompts are clearly labelled.
Run `python -m tests.eval` after changes to measure accuracy.

### Option B — Fine-tune with your own data (advanced)
```bash
# 1. Export labelled conversations
python -m src.export_training --output data/training.jsonl

# 2. Fine-tune using Ollama's Modelfile approach
#    or use llama.cpp's finetune binary
#    See docs/finetuning.md for a step-by-step guide

# 3. Point settings.yaml at new model name
```

### Option C — Swap the base model
Change `llm.model` in `settings.yaml` to any Ollama-compatible model.
Larger models (13B, 34B) will be more accurate but need more RAM.

---

## Logging & Audit Trail

Every action writes a JSON line to `logs/audit.jsonl`:

```json
{
  "ts": "2025-03-12T09:14:32Z",
  "thread_id": "254712345678",
  "action": "follow_up_sent",
  "confidence": 0.88,
  "stage": "unanswered_quote",
  "message": "Hi Sarah, just checking in on that quote...",
  "llm_reasoning": "Customer requested quote 6 days ago, no response..."
}
```

View a live tail: `tail -f logs/audit.jsonl | python -m src.log_viewer`

---

## Performance Targets

| Metric | Target | How measured |
|---|---|---|
| Suppress follow-up on responded threads | ≥ 90 % | `python -m tests.eval --suite suppression` |
| Human-sounding messages (3-colleague blind test) | ≥ 95 % | `tests/human_eval_sheet.csv` |
| End-to-end latency per conversation | < 10 s | Logged automatically |

---

## Directory Structure

```
whatsapp-ai-followup/
├── main.py                  # Entry point
├── requirements.txt
├── config/
│   ├── settings.example.yaml
│   └── settings.yaml        # Your live config (git-ignored)
├── src/
│   ├── db.py                # SQLite store
│   ├── webhook.py           # Incoming message receiver
│   ├── analyser.py          # LLM-based intent/stage/sentiment
│   ├── scheduler.py         # Timing engine
│   ├── drafter.py           # Message generation
│   ├── sender.py            # WhatsApp API dispatch
│   ├── logger.py            # Audit trail
│   ├── prompts.py           # All LLM prompts (edit here)
│   └── config_loader.py     # Config parsing
├── tests/
│   ├── eval.py              # Automated accuracy suite
│   ├── conversations/       # Sample test threads
│   └── human_eval_sheet.csv
├── docs/
│   └── finetuning.md
└── logs/
    └── audit.jsonl
```
