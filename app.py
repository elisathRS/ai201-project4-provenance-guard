import os
import re
import json
import uuid
import math
import statistics
from datetime import datetime, timezone

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from groq import Groq

load_dotenv()

app = Flask(__name__)
client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
LOG_PATH = os.path.join(os.path.dirname(__file__), "audit_log.jsonl")

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://",
)

SEMANTIC_PROMPT = """You are an AI-authorship detection expert.
Analyze the text below and return a single JSON object with keys:
- "score": a float between 0.0 and 1.0
- "attribution": one of "likely_human", "likely_ai", or "uncertain"

Scoring criteria:
- 0.0 = Highly likely Human (idiosyncratic metaphors, emotional leaps, unpredictable flow, personal voice)
- 1.0 = Highly likely AI (formulaic phrasing, uniform structure, exhaustive hedging, semantic predictability)

Instructions:
- Use values near 0.0 only for text that clearly reads as human-written.
- Use values near 1.0 only for text that clearly reads as AI-generated.
- Use mid-range values only for mixed or uncertain text.

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


def stylometric_score(text: str) -> dict:
    """
    Signal 2: stylometric heuristics.
    Computes sentence length variance and type-token ratio, then converts them into a single AI-likelihood score.
    """
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    tokens = [t for t in re.findall(r"\b\w+\b", text.lower())]

    if len(tokens) < 10 or len(sentences) < 2:
        return {"score": 0.5, "metrics": {"note": "text too short for reliable stylometry"}}

    sentence_lengths = [len(re.findall(r"\b\w+\b", sentence)) for sentence in sentences]
    avg_length = statistics.mean(sentence_lengths)
    variance = statistics.pvariance(sentence_lengths)
    ttr = len(set(tokens)) / len(tokens)

    cv = math.sqrt(variance) / avg_length if avg_length > 0 else 1.0
    length_uniformity = max(0.0, 1.0 - min(cv, 1.0))
    vocab_uniformity = 1.0 - min(ttr, 1.0)
    score = max(0.0, min(1.0, 0.75 * length_uniformity + 0.25 * vocab_uniformity))

    return {
        "score": score,
        "metrics": {
            "sentence_count": len(sentences),
            "avg_sentence_length": avg_length,
            "sentence_length_variance": variance,
            "type_token_ratio": ttr,
            "length_uniformity": length_uniformity,
            "vocab_uniformity": vocab_uniformity,
        },
    }


def combine_scores(semantic_score_value: float, stylometric_score_value: float) -> float:
    """
    Combine semantic and stylometric scores using baseline 60/40 weighting and a semantic veto.
    """
    sem = max(0.0, min(1.0, semantic_score_value))
    styl = max(0.0, min(1.0, stylometric_score_value))

    if sem <= 0.25 and styl >= 0.75:
        styl = styl * 0.25

    combined = 0.6 * sem + 0.4 * styl
    return max(0.0, min(1.0, combined))


def label_from_score(score: float) -> str:
    if score <= 0.20:
        return "Human Authored"
    if score >= 0.85:
        return "Automated Content"
    return "Uncertain Origin"


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

    if limit <= 0:
        return entries
    return entries[-limit:]


@app.route("/submit", methods=["POST"])
@limiter.limit("10 per minute;100 per day")
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
        semantic_result = semantic_score(text)
    except (ValueError, Exception) as exc:
        return jsonify({"error": f"Semantic analysis failed: {exc}"}), 502

    stylometric_result = stylometric_score(text)
    combined_score = combine_scores(semantic_result["score"], stylometric_result["score"])
    attribution = _attribution_from_score(combined_score)
    label = label_from_score(combined_score)

    content_id = str(uuid.uuid4())
    audit_entry = {
        "content_id": content_id,
        "creator_id": creator_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "attribution": attribution,
        "confidence": combined_score,
        "semantic_score": semantic_result["score"],
        "stylometric_score": stylometric_result["score"],
        "status": "classified",
    }
    append_audit_log(audit_entry)

    payload = {
        "content_id": content_id,
        "attribution": attribution,
        "confidence": combined_score,
        "label": label,
        "semantic_score": semantic_result["score"],
        "stylometric_score": stylometric_result["score"],
    }

    if app.debug:
        payload["_debug"] = {
            "semantic_score": semantic_result["score"],
            "stylometric_score": stylometric_result["score"],
            "combined_score": combined_score,
        }

    return jsonify(payload), 200


@app.route("/log", methods=["GET"])
def get_log_endpoint():
    """GET /log returns recent audit log entries for grading and documentation."""
    return jsonify({"entries": get_log()})


def persist_audit_log(entries: list[dict]) -> None:
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(LOG_PATH, "w", encoding="utf-8") as log_file:
        for entry in entries:
            log_file.write(json.dumps(entry, ensure_ascii=False) + "\n")


@app.route("/appeal", methods=["POST"])
def appeal():
    """POST /appeal accepts a content_id and creator_reasoning, updates status, and logs the appeal."""
    data = request.get_json(silent=True)
    if not data or "content_id" not in data or "creator_reasoning" not in data:
        return jsonify({"error": "Request body must be JSON with 'content_id' and 'creator_reasoning' fields."}), 400

    content_id = data["content_id"]
    creator_reasoning = data["creator_reasoning"]
    if not isinstance(content_id, str) or not content_id.strip():
        return jsonify({"error": "'content_id' must be a non-empty string."}), 400
    if not isinstance(creator_reasoning, str) or not creator_reasoning.strip():
        return jsonify({"error": "'creator_reasoning' must be a non-empty string."}), 400

    entries = get_log(limit=0)
    updated = False
    for entry in entries:
        if entry.get("content_id") == content_id:
            entry["status"] = "under_review"
            entry["appeal_reasoning"] = creator_reasoning
            entry["appeal_timestamp"] = datetime.now(timezone.utc).isoformat()
            updated = True
            break

    if not updated:
        return jsonify({"error": "Content ID not found."}), 404

    persist_audit_log(entries)
    return jsonify({"message": "Appeal received.", "content_id": content_id, "status": "under_review"}), 200


if __name__ == "__main__":
    app.run(debug=True)
