# ai201-project4-provenance-guard

A provenance detection system that analyzes text submissions and assigns a confidence score for AI authorship, displaying a transparency label to indicate the likely origin.

---

## Architecture Overview

A submission flows through the following pipeline:

1. **Input**: User submits `text` and `creator_id` via `POST /submit`
2. **Semantic Analysis** (Signal 1): LLM-based scoring using Groq's Llama 3.3-70B
3. **Stylometric Analysis** (Signal 2): Computational heuristics measuring sentence uniformity and vocabulary diversity
4. **Score Combination**: Weighted average (60% semantic + 40% stylometric) with semantic veto logic
5. **Label Generation**: Confidence score mapped to a transparency label (`Human Authored`, `Uncertain Origin`, or `Automated Content`)
6. **Audit Log**: Entry persisted in `audit_log.jsonl` with all intermediate scores, timestamp, and status tracking
7. **Response**: JSON payload returned with `content_id`, `attribution`, `confidence`, and `label`

---

## Detection Signals

### Signal 1: Semantic Analysis (via Groq LLM)

**What it measures:**
- Analyzes narrative structure, emotional authenticity, and linguistic predictability
- Scores on a 0–1 scale: 0.0 = highly likely human, 1.0 = highly likely AI

**Why chosen:**
- LLMs are trained on vast corpora and can recognize patterns in AI-generated text that heuristics miss
- Captures semantic coherence and stylistic consistency in ways that word-level statistics cannot
- Provides direct signal tuned for the specific LLM architecture in question

**What it misses:**
- Cannot detect adversarial prompting or fine-tuned models that explicitly mimic human patterns
- Depends on prompt quality and model reliability; subject to hallucination or drift
- May overweight formulaic human writing (e.g., technical documentation, legal prose) as AI-like

**Implementation:**
- Uses Groq's Llama 3.3-70B with zero temperature for deterministic output
- Prompt guides the model to recognize idiosyncratic voice, emotional leaps, and unpredictable flow as human markers
- Returns JSON with `score` and `attribution` (likely_human, likely_ai, or uncertain)

---

### Signal 2: Stylometric Analysis

**What it measures:**
- Sentence length coefficient of variation (CV): low CV indicates uniform sentence structure, typical of AI
- Type-token ratio (TTR): vocabulary diversity; high TTR (many unique words) suggests human authorship
- Combined metric: 75% sentence uniformity + 25% vocabulary uniformity

**Why chosen:**
- Computationally fast and deterministic (no external API calls)
- Does not require training data or fine-tuning; works generically across domains
- Captures measurable structural patterns that correlate with automated generation

**What it misses:**
- Does not account for semantic meaning or context
- Fails on short submissions (< 10 tokens or < 2 sentences)
- Can be manipulated by deliberately varying sentence length or vocabulary without changing authorship
- Does not distinguish between different AI models or human expertise levels

**Implementation:**
- Splits text into sentences and tokenizes into words
- Calculates sentence length variance and type-token ratio
- Maps CV to "length uniformity" and TTR to "vocab uniformity"
- Scores: `score = 0.75 * length_uniformity + 0.25 * vocab_uniformity`

---

## Confidence Scoring

### Combining Signals

The final confidence score is computed as:

$$\text{confidence} = 0.6 \times \text{semantic\_score} + 0.4 \times \text{stylometric\_score}$$

with a **semantic veto**:
- If semantic score ≤ 0.25 and stylometric score ≥ 0.75, reduce stylometric weight to 0.25× to avoid false positives from unusual human writing

**Rationale:**
- Semantic analysis is more reliable for AI detection but slower; weighted at 60%
- Stylometric analysis is fast and deterministic; weighted at 40% as a secondary signal
- Veto prevents misclassifying atypical human writing (e.g., repetitive technical writing) as AI

### Validation

The confidence score is validated against two criteria:

1. **Label consistency**: Score maps monotonically to label:
   - Score ≤ 0.20 → `Human Authored` (high confidence human)
   - Score ≥ 0.85 → `Automated Content` (high confidence AI)
   - 0.20 < Score < 0.85 → `Uncertain Origin` (ambiguous)

2. **Real-world performance**: Tested with extreme examples:
   - Very human-like text (personal memory, emotional detail) → low score
   - Very AI-like text (repetitive, formulaic, uniform structure) → high score

### Example Submissions

#### High-Confidence Human Text
**Input:**
```
"I still recall the crooked staircase at my grandmother's house, the smell of 
cardamom and old books, the way afternoon light pooled over her knitting 
basket. It was imperfect, warm, and deeply mine."
```

**Output:**
```json
{
  "content_id": "48de3b43-ac12-4d55-ad21-a74d1f7dd696",
  "attribution": "likely_human",
  "confidence": 0.192,
  "label": "Human Authored"
}
```

**Why low confidence:**
- Semantic signal detected idiosyncratic imagery and emotional authenticity (0.05)
- Stylometric signal found high variance in sentence length and vocabulary diversity (0.45)
- Combined: 0.6 × 0.05 + 0.4 × 0.45 = 0.192

---

#### High-Confidence AI Text
**Input:**
```
"The output is formulaic and repetitive with uniform sentence length and 
structured phrases. The output is formulaic and repetitive with uniform sentence 
length and structured phrases. [repeated 12 times]"
```

**Output:**
```json
{
  "content_id": "1edba40b-6774-48d4-9ce4-fdbd768b1357",
  "attribution": "likely_ai",
  "confidence": 0.986,
  "label": "Automated Content"
}
```

**Why high confidence:**
- Semantic signal detected repetitive syntax and formulaic structure (0.99)
- Stylometric signal found extremely uniform sentence length and low vocabulary diversity (0.96)
- Combined: 0.6 × 0.99 + 0.4 × 0.96 = 0.986

---

## API Endpoints

### `POST /submit`
Submits text for provenance analysis.

**Request:**
```json
{
  "text": "<content to analyze>",
  "creator_id": "<user identifier>"
}
```

**Response (200 OK):**
```json
{
  "content_id": "<uuid>",
  "attribution": "likely_human|likely_ai|uncertain",
  "confidence": 0.0–1.0,
  "label": "Human Authored|Automated Content|Uncertain Origin"
}
```

**Rate limits:** 10 per minute, 100 per day per client IP

---

### `POST /appeal`
Appeal a classification decision.

**Request:**
```json
{
  "content_id": "<uuid from /submit>",
  "creator_reasoning": "<explanation of why the label is wrong>"
}
```

**Response (200 OK):**
```json
{
  "message": "Appeal received.",
  "content_id": "<uuid>",
  "status": "under_review"
}
```

**Audit log:** Appeal reasoning and timestamp are recorded in `audit_log.jsonl` for review.

---

### `GET /log`
Returns recent audit log entries.

**Response (200 OK):**
```json
{
  "entries": [
    {
      "content_id": "<uuid>",
      "creator_id": "<user>",
      "timestamp": "<ISO 8601>",
      "attribution": "likely_human|likely_ai|uncertain",
      "confidence": 0.0–1.0,
      "semantic_score": 0.0–1.0,
      "stylometric_score": 0.0–1.0,
      "status": "classified|under_review",
      "appeal_reasoning": "<optional>",
      "appeal_timestamp": "<optional, ISO 8601>"
    },
    ...
  ]
}
```

---

## Rate Limiting

The app uses `flask-limiter` with in-memory storage. Protects the `/submit` endpoint from abuse:

- **10 per minute:** Allows casual submission activity without rapid flooding
- **100 per day:** Allows sustained use while capping excessive automation

Exceeding either limit returns HTTP `429 (Too Many Requests)`.

**Test example:**
```bash
for i in $(seq 1 12); do
  curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost:5000/submit \
    -H "Content-Type: application/json" \
    -d '{"text": "Test submission", "creator_id": "ratelimit-test"}'
done
```

Expected: first 10 requests return `200`, next 2 return `429`

---

## Audit Log

All submissions, appeals, and scores are recorded in `audit_log.jsonl` as structured JSON. Each entry captures:
- Submission metadata (content_id, creator_id, timestamp)
- Both detection signals separately (semantic_score, stylometric_score)
- Combined confidence score
- Classification status (classified or under_review)
- Appeal information if appealed (appeal_reasoning, appeal_timestamp)

This enables transparency, accountability, and the ability to re-evaluate decisions as the system improves.