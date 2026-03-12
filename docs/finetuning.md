# Fine-tuning Guide

## When to fine-tune

The system works well out of the box using prompt engineering.
Fine-tuning is recommended only when:

- Your domain is very specialised (e.g., medical devices, legal services)
- The base model misclassifies more than 15% of your real conversations
- You have at least 200 labelled conversation examples

---

## Option A — Improve prompts (no GPU required, 30 minutes)

1. Open `src/prompts.py`
2. Locate `ANALYSER_SYSTEM` and add domain-specific stage labels or examples
3. Run `python -m tests.eval --suite suppression` before and after to measure improvement
4. Commit the improved prompt

---

## Option B — Ollama Modelfile fine-tune (intermediate)

Ollama supports custom models via Modelfile.  You can adapt an existing model
with a system prompt baked in, without full weight fine-tuning.

```bash
# Create a Modelfile
cat > Modelfile <<'EOF'
FROM mistral:7b-instruct

SYSTEM """
You are a sales conversation analyst for Acme Corp.
[paste your full ANALYSER_SYSTEM prompt here]
"""
EOF

# Build the custom model
ollama create acme-analyser -f Modelfile

# Update settings.yaml
# llm:
#   model: acme-analyser
```

This bakes the system prompt into the model weights, slightly improving
consistency and reducing token usage.

---

## Option C — LoRA fine-tune (advanced, needs GPU)

For best results with highly domain-specific conversations, use QLoRA
fine-tuning on your labelled data.

### 1. Export labelled data

```bash
python -m src.export_training --output data/training.jsonl --min-label-count 200
```

The export script reads your audit log and the conversation DB, then
creates Alpaca-format JSONL:

```json
{"instruction": "<analyser system prompt>", "input": "<thread>", "output": "<correct JSON>"}
```

### 2. Fine-tune with llama.cpp

```bash
# Build llama.cpp with CUDA support
git clone https://github.com/ggerganov/llama.cpp
cd llama.cpp && make LLAMA_CUDA=1

# Fine-tune (requires gguf base model)
./finetune \
  --model-base models/mistral-7b-instruct.Q4_K_M.gguf \
  --train-data ../data/training.jsonl \
  --lora-out models/acme-lora.bin \
  --ctx 2048 \
  --batch 4 \
  --epochs 3
```

### 3. Serve the fine-tuned model

```bash
# Merge LoRA into base model
./export-lora \
  --model-base models/mistral-7b-instruct.Q4_K_M.gguf \
  --lora-scaled models/acme-lora.bin 1.0 \
  --output models/acme-finetuned.gguf

# Start llama.cpp server
./server -m models/acme-finetuned.gguf --port 8080
```

Update `settings.yaml`:
```yaml
llm:
  provider: llamacpp
  llamacpp_server_url: http://localhost:8080
```

---

## Labelling guide for training data

When exporting conversations for fine-tuning, label each one with:

| Field | Values |
|---|---|
| `needs_follow_up` | true / false |
| `stage` | one of the stage labels in prompts.py |
| `confidence` | 0.0–1.0 (your certainty in the label) |

Low-confidence labels (< 0.7) should be reviewed by a second person before
inclusion in the training set.

---

## Adjusting confidence threshold

After fine-tuning, you may find the model is more or less confident than before.
Recalibrate by:

1. Running `python -m tests.eval --suite suppression` on a held-out set
2. Plotting a precision-recall curve across threshold values 0.5–0.95
3. Setting `llm.confidence_threshold` in `settings.yaml` to the value that
   gives you ≥90% suppression accuracy at acceptable recall
