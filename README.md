# i201-project4-provenance-guard

## API Endpoints

- `POST /submit`
  - Accepts JSON: `text`, `creator_id`
  - Returns: `content_id`, `attribution`, `confidence`, `label`
  - Rate limited to `10 per minute` and `100 per day` per client IP
- `POST /appeal`
  - Accepts JSON: `content_id`, `creator_reasoning`
  - Updates the matching audit log entry to `status: under_review`
  - Records `appeal_reasoning` and `appeal_timestamp`
- `GET /log`
  - Returns recent audit log entries as JSON

## Rate limiting

The app uses `flask-limiter` with in-memory storage for local development. This protects the submit endpoint from abuse while still allowing normal writer usage.

- `10 per minute` allows casual submission activity without rapid flooding.
- `100 per day` allows sustained real use while capping excessive automation.

Example proof of rate limiting:

```bash
for i in $(seq 1 12); do
  curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost:5000/submit \
    -H "Content-Type: application/json" \
    -d '{"text": "This is a test submission for rate limit testing purposes only.", "creator_id": "ratelimit-test"}'
 done
```

Expected response codes:

- first 10 requests: `200`
- requests after the limit: `429`

## Notes

The audit log is persisted in `audit_log.jsonl` with structured JSON entries, including separate `semantic_score`, `stylometric_score`, and combined `confidence` values.