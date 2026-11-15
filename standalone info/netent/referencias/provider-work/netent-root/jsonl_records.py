"""JSON Lines uses literal LF boundaries; Unicode separators may occur in strings."""
import json

def parse_jsonl(text):
    return [json.loads(line) for line in text.split('\n') if line.strip()]
