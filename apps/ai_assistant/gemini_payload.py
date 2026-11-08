"""Identical native request encoding for token reservation and actual transport."""
import json
from .openai_schema import schema, instructions


def encode(task, payload):
    return json.dumps({
        "systemInstruction": {"parts": [{"text": instructions(task)}]},
        "contents": [{"role": "user", "parts": [{"text": json.dumps(payload, ensure_ascii=False)}]}],
        "generationConfig": {
            "maxOutputTokens": task.output_tokens_cap,
            "thinkingConfig": {"thinkingLevel": "LOW", "includeThoughts": False},
            "responseFormat": {"text": {"mimeType": "APPLICATION_JSON", "schema": schema(task)}},
        },
    }, ensure_ascii=False).encode("utf-8")
