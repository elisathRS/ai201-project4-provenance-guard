import os
import re
import json
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from groq import Groq

load_dotenv()

app = Flask(__name__)
client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
LOG_PATH = os.path.join(os.path.dirname(__file__), "audit_log.jsonl")

SEMANTIC_PROMPT = """You are an AI-authorship detection expert.
Analyze the text below and return a single JSON object with keys:
- "score": a float between 0.0 and 1.0
- "attribution": one of "likely_human", "likely_ai", or "uncertain"

Scoring criteria:
- 0.0 = Highly likely Human (idiosyncratic metaphors, emotional leaps, unpredictable flow, personal voice)
- 1.0 = Highly likely AI (formulaic phrasing, uniform structure, exhaustive hedging, semantic predictability)

Text to analyze:
\"\"\"
{text}
\"\"\"

Response:"""


def semantic_score(text: str) -> dict:
    """
    Signal 1: LLM-based semantic analyzer via Groq.
    Returns a dict with score and attribution.
    """
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": SEMANTIC_PROMPT.format(text=text)}],
        temperature=0.0,
        max_tokens=50,
    )
    raw = response.choices[0].message.content.strip()

    cleaned = raw
    # Remove markdown code fences or any leading/trailing text.
    cleaned = re.sub(r"^```[a-zA-Z]*\n", "", cleaned)
    cleaned = re.sub(r"\n```$", "", cleaned)
    cleaned = cleaned.strip()

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        if "{" in cleaned and "}" in cleaned:
            start = cleaned.index("{")
            end = cleaned.rindex("}") + 1
            cleaned = cleaned[start:end]
        parsed = json.loads(cleaned)

    score = float(parsed.get("score", 0.0))
    attribution = parsed.get("attribution") or _attribution_from_score(score)

    return {
        "score": max(0.0, min(1.0, score)),
        "attribution": attribution,
    }


def _attribution_from_score(score: float) -> str:
    if score >= 0.85:
        return "likely_ai"
    if score <= 0.20:
        return "likely_human"
    return "uncertain"


def append_audit_log(entry: dict) -> None:
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as log_file:
        log_file.write(json.dumps(entry, ensure_ascii=False) + "\n")


def get_log(limit: int = 100) -> list[dict]:
    entries = []
    if not os.path.exists(LOG_PATH):
        return entries

    with open(LOG_PATH, "r", encoding="utf-8") as log_file:
        for line in log_file:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    return entries[-limit:]


@app.route("/submit", methods=["POST"])
def submit():
    """
    POST /submit
    Body (JSON): { "text": "<content>", "creator_id": "<required>" }
    Returns (JSON): content_id, attribution, confidence, label.
    """
    data = request.get_json(silent=True)
    if not data or "text" not in data or "creator_id" not in data:
        return jsonify({"error": "Request body must be JSON with 'text' and 'creator_id' fields."}), 400

    text = data["text"]
    creator_id = data["creator_id"]
    if not isinstance(text, str) or not text.strip():
        return jsonify({"error": "'text' must be a non-empty string."}), 400
    if not isinstance(creator_id, str) or not creator_id.strip():
        return jsonify({"error": "'creator_id' must be a non-empty string."}), 400

    try:
        signal_result = semantic_score(text)
    except (ValueError, Exception) as exc:
        return jsonify({"error": f"Semantic analysis failed: {exc}"}), 502

    content_id = str(uuid.uuid4())
    confidence = signal_result["score"]
    attribution = signal_result["attribution"]
    label = _stub_label(confidence)

    audit_entry = {
        "content_id": content_id,
        "creator_id": creator_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "attribution": attribution,
        "confidence": confidence,
        "llm_score": confidence,
        "status": "classified",
    }
    append_audit_log(audit_entry)

    payload = {
        "content_id": content_id,
        "attribution": attribution,
        "confidence": confidence,
        "label": label,
    }

    if app.debug:
        payload["_debug"] = {"llm_score": confidence}

    return jsonify(payload), 200


def _stub_label(score: float) -> str:
    """Temporary label mapper — replace with full Label Generator in M5."""
    if score <= 0.20:
        return "Human Authored"
    if score >= 0.85:
        return "Automated Content"
    return "Uncertain Origin"


@app.route("/log", methods=["GET"])
def get_log_endpoint():
    """GET /log returns recent audit log entries for grading and documentation."""
    return jsonify({"entries": get_log()})


@app.route("/appeal", methods=["POST"])
def appeal():
    """POST /appeal — stub, implemented in M5."""
    return jsonify({"message": "Appeal endpoint not yet implemented."}), 501


if __name__ == "__main__":
    app.run(debug=True)
