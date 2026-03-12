# whatsapp-ai-followup

Three things to do before going live

Copy config: cp config/settings.example.yaml config/settings.yaml and fill in your WhatsApp credentials, timezone, and business description
Pull the model: ollama pull mistral:7b-instruct (one-time, ~4 GB, then fully offline)
Run eval: python -m tests.eval to confirm the system passes on the 8 included test cases before connecting to real conversations
