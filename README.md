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
   "attribution": "likely_human",
    "confidence": 0.19235294117647062,
    "content_id": "bc50c07f-4582-4abe-aa0e-020685dce5fa",
    "label": "Human Authored",
    "semantic_score": 0.1,
    "stylometric_score": 0.3308823529411765
}
```

**Why low confidence:**
- Semantic signal detected idiosyncratic imagery and emotional authenticity (0.05)
- Stylometric signal found high variance in sentence length and vocabulary diversity (0.45)
- Combined: 0.6 × 0.1 + 0.4 × 0.33 = 0.192

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
    "attribution": "likely_ai",
    "confidence": 0.9786153846153847,
    "content_id": "10ec00a6-06e1-4adb-b9f3-17297bd771fb",
    "label": "Automated Content",
    "semantic_score": 0.99,
    "stylometric_score": 0.9615384615384616
}
```

**Why high confidence:**
- Semantic signal detected repetitive syntax and formulaic structure (0.99)
- Stylometric signal found extremely uniform sentence length and low vocabulary diversity (0.96)
- Combined: 0.6 × 0.99 + 0.4 × 0.96 = 0.978

---

## Transparency Labels

The system displays one of three labels to users, determined by the confidence score:

### Label 1: "Human Authored"
**Condition:** Confidence score ≤ 0.20  
**User message:** "Human Authored"  
**Meaning:** High confidence that the text was written by a human. Attribution is `likely_human`.  
**Example:** Personal narratives, emotional writing, idiosyncratic phrasing that suggests deliberate authorship.

### Label 2: "Uncertain Origin"
**Condition:** Confidence score between 0.20 and 0.85  
**User message:** "Uncertain Origin"  
**Meaning:** The system cannot confidently determine authorship. The text may be human-written, AI-generated, or a hybrid. Attribution is `uncertain`.  
**Example:** Mixed-style text, technical writing with both formulaic and unique elements, or text too short for reliable analysis.

### Label 3: "Automated Content"
**Condition:** Confidence score ≥ 0.85  
**User message:** "Automated Content"  
**Meaning:** High confidence that the text was generated by an AI system. Attribution is `likely_ai`.  
**Example:** Repetitive structure, uniform sentence length, predictable phrasing, or text that mimics LLM output patterns.

These labels are transparent, user-facing indicators. Each label is paired with a `confidence` score (0.0–1.0) and an `attribution` value for fine-grained interpretation.

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
  
  "attribution": "likely_human|likely_ai|uncertain",
  "confidence": 0.0–1.0,
  "content_id": "<uuid>",
  "label": "Human Authored|Automated Content|Uncertain Origin"
  "semantic_score": 0.0–1.0,
  "stylometric_score": 0.0–1.0,
  
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

- **10 per minute:** Limits rapid-fire submissions to prevent API scanning or brute-force testing. A human writer submitting text naturally would rarely exceed 10 per minute (roughly one every 6 seconds). This threshold allows normal interactive usage while preventing bot-driven abuse.

- **100 per day:** Allows bulk submission workflows (e.g., a writer submitting multiple articles in a single day) while capping unlimited, sustained automation. This is set conservatively to assume at most 100 legitimate submissions per creator per day; anything beyond suggests scripted exploitation.

**Rationale for these specific values:**
- **Per-minute limit (10):** Balances user experience against API resource protection. 10/min allows enough throughput for interactive use but prevents rapid enumeration attacks.
- **Per-day limit (100):** Targets the abuse vector of automated submission farms while preserving legitimate bulk usage. A newsroom or content platform might submit 50–100 articles/day; beyond that suggests malicious actors gaming the system.
- **Combined effect:** An attacker hitting the per-minute limit resets after 60 seconds but is still capped to 1,440 requests/day if persistent, so even cycling attackers remain bounded.

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

---

## Known Limitations

### Misclassification Risk: Technical and Legal Writing

**What the system gets wrong:**  
The system is likely to **misclassify highly structured, formal writing (e.g., legal documents, technical specifications, research abstracts) as AI-generated**, even when written by humans.

**Why:**  
- **Stylometric signal** (Signal 2) penalizes uniform sentence length and low vocabulary diversity, both of which are hallmarks of legal and technical prose. Lawyers and engineers naturally write with consistent, precise phrasing to minimize ambiguity.
- **Semantic signal** (Signal 1) may interpret formulaic, hedged language as AI-like, because LLM output often mimics academic hedging ("it can be argued that," "to some extent," etc.).
- Example: A software engineer's API documentation with repetitive structure and domain-specific vocabulary would score high as "Automated Content" despite being entirely human-written.

**Consequence:**  
False positives on professional, domain-specific content. Writers in legal, scientific, and technical fields may see their work incorrectly flagged as AI-generated.

**Mitigation:**  
Users can appeal via `POST /appeal` with reasoning. Long-term improvements would require domain-aware signal tuning or additional context (e.g., authorship history, document metadata).

---

### Other Known Gaps

- **Adversarial prompting:** A human using an AI model's API interactively and iteratively can produce text that looks AI-generated but is genuinely collaborative. The system cannot distinguish this from fully automated generation.
- **Short submissions:** Submissions under 10 tokens or 2 sentences fall back to a default score (0.5), making them essentially unclassifiable.
- **Model drift:** As LLMs evolve, the semantic signal may become obsolete without periodic re-tuning of the Groq prompt.
- **Language and culture:** The system is optimized for English idiomatic writing and may misclassify non-native English or culturally diverse styles.

---

## Spec Reflection

### One Way the Spec Helped

**Clarity on signal independence:**  
The specification required two *distinct* detection signals (one semantic, one stylometric) with separate scores persisted in the audit log. This requirement forced a clean separation of concerns and prevented feature creep. Instead of trying to build a single magic scoring function, we built two independent, interpretable signals that could be examined and debugged separately. When the system misclassifies, reviewers can immediately see whether it was the semantic or stylometric component that failed, enabling targeted improvements.

### One Way Implementation Diverged from the Spec (and Why)

**Score combination and veto logic:**  
The spec required combining two signals into a single confidence score but did not specify the exact weighting or veto mechanism. Implementation chose:
- **60/40 weighting** (semantic over stylometric) based on observed reliability differences
- **Semantic veto:** If semantic is very confident human (≤ 0.25) but stylometric is very confident AI (≥ 0.75), reduce stylometric weight to 0.25×

This divergence was necessary because raw 60/40 averaging alone produced false positives on atypical human writing (e.g., repetitive technical documentation). The veto prevents the system from misclassifying a lawyer's precisely-drafted contract as AI-generated solely because it has uniform phrasing. The spec prioritized the transparency label appearing in the response, not the exact algorithm; the veto was an implementation refinement to reduce harm.

---

## AI Usage: Directed Decisions and Revisions

### Instance 1: Groq JSON Output Cleaning

**What was directed:**  
Early versions of the semantic signal handler did not robustly handle Groq's response formatting. The system expected pure JSON but sometimes received JSON wrapped in markdown code fences (e.g., ` ```json\n{...}\n``` `). I directed the implementation to add a multi-step cleanup: first strip markdown fences, then regex-extract the JSON object if parsing failed.

**What was revised:**  
Initial regex logic was too aggressive and sometimes truncated valid JSON. User feedback showed that submissions were occasionally failing with `JSONDecodeError` even though the LLM response was valid. The cleanup was tightened to:
1. Remove leading ` ```[language]\n ` exactly
2. Remove trailing ` \n``` ` exactly
3. Fall back to substring extraction only if the first two steps fail

This reduced false failures and made the system more resilient.

---

### Instance 2: Label Boundary Thresholds

**What was directed:**  
The system needed three discrete labels from a continuous confidence score. I suggested symmetric thresholds: score ≤ 0.33 → "Human Authored", 0.33–0.67 → "Uncertain", ≥ 0.67 → "Automated Content". This seemed statistically balanced.

**What was overridden:**  
After testing with real submissions, these thresholds produced too many false positives in the middle band. A human-authored personal narrative that should be "Human Authored" would score 0.35 and fall into "Uncertain Origin" instead, creating user confusion. The thresholds were adjusted to:
- ≤ 0.20 → "Human Authored" (only high-confidence human)
- ≥ 0.85 → "Automated Content" (only high-confidence AI)
- 0.20–0.85 → "Uncertain Origin" (everything ambiguous)

This wider "Uncertain" band is more honest about the system's actual confidence limits and reduces false claims of AI authorship on borderline content. The trade-off is that fewer submissions receive a definitive label, but accuracy improved.


## Demo Video 

   [Watch the video](https://www.loom.com/share/fe141f1fce8a41bf8e22fea5f45d7baf)
