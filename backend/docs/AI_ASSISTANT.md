# AI_ASSISTANT.md — Gemini Assistant

Two Django integrations talk to Gemini:

* `assistant/` — the legacy app that has served the frontend widget since
  launch (`/api/assistant/chat`, `/api/assistant/history`,
  `/api/assistant/suggestions`). It still powers the live widget.
* `ai/` — the current app, added as a strangler-pattern rewrite of the same
  feature on fresh routes (`/api/ai/health`, `/api/ai/chat`). It reuses the
  assistant app's conversation storage, tool and turn engines, and adds its
  own Gemini service, error taxonomy, health probe and serializers.

This document is the operational runbook: env switches, endpoints, how to run
locally, what Render needs, and how to tell a "Gemini broke" outage from an
auth outage.

---

## The switches

Read in `botique_backend/settings.py`.

| Variable | Default | Meaning |
| --- | --- | --- |
| `GEMINI_API_KEY` | *(empty)* | The Google auth key for `ai/`. **`assistant/` reads the exact same key.** If it is empty, `GeminiUnavailable: GEMINI_API_KEY is not configured` is raised and every chat turns into a 502. |
| `GOOGLE_API_KEY` | *(empty)* | Legacy variable. The production key value is shared with `GEMINI_API_KEY` — both are set to the same value so the old variable keeps working for legacy product/image features. Do not delete one while the other is empty. |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` | Interactions model for both apps. `gemini-2.5-flash-lite` returns 404 ("no longer available to new users"); `gemini-3.5-flash` works but is slower and costlier. |
| `GEMINI_TIMEOUT_SECONDS` | `30` | Per-interaction network timeout. |
| `GEMINI_MAX_RETRIES` | `3` | Retries **transient** failures only (timeout, network, 429, 5xx) with exponential backoff (`GEMINI_RETRY_BACKOFF_SECONDS`, default `2`). Auth, model-not-found and content-blocked are never retried. |
| `GEMINI_HEALTH_CACHE_SECONDS` | `60` | How long `GET /api/ai/health/` results are cached (cache key `modeza:ai:health`). Successes and most errors are cached; auth errors are not. |
| `AI_MAX_MESSAGE_LENGTH` | `2000` | Max chat message length (serializer `max_length`). |

> **Tip:** if `GEMINI_API_KEY` and `GOOGLE_API_KEY` are both set, the SDK logs
> "Both GOOGLE_API_KEY and GEMINI_API_KEY are set. Using GOOGLE_API_KEY."
> Harmless; both point at the same value.

---

## Endpoints

### `GET /api/ai/health/` (also no-slash `/api/ai/health`)

Public, throttled (same `assistant_anon` 15/min / `assistant_user` 30/min
bucket as chat). Runs a minimal single-turn interaction (`MODEZA_AI_OK`,
capped at `GEMINI_TIMEOUT_SECONDS`) and reports the SDK client health.

Success — HTTP 200:

```json
{
  "success": true,
  "status": "healthy",
  "provider": "google_gemini",
  "model": "gemini-3.5-flash-lite",
  "response": "MODEZA_AI_OK",
  "latency_ms": 2712
}
```

Failure — HTTP 503 (shape reused by chat):

```json
{
  "success": false,
  "error": {
    "code": "ai_model_error",
    "message": "Model gemini-x unavailable."
  }
}
```

Error codes map to a status code in `ai/views.py` `_ERROR_HTTP_STATUS`
(auth 502, model 503, timeout 504, rate limit 429, quota 402, blocked 400,
provider 503, everything else 500). Conditions get `Retry-After` where
meaningful. Chinese-friendly: a probe costs ~2–16s and is cached for 60s.

### `POST /api/ai/chat/` (also no-slash `/api/ai/chat`)

Throttled like health. Body:

```json
{ "message": "…", "conversationId": "optional-uuid" }
```

`conversationId` may also be sent as `conversation_id`. **`customer_id` in the
body is ignored on purpose** — identity never comes from the client; it comes
from Django's auth (JWT session) so a caller can never attach to another
customer's thread.

Two reply modes, chosen the same way as `assistant/`:

* **JSON** — request `stream: false`, or an `Accept` header that is not
  `text/event-stream`. Returns:

  ```json
  {
    "success": true,
    "message": "…",
    "conversation_id": "uuid",
    "latency_ms": 8080,
    "usage": { "total_input_tokens": 2273, "total_output_tokens": 49 },
    "unanswered": false
  }
  ```

* **SSE** — default. `text/event-stream` with `meta` → (`delta` | `tool` |
  `products` | `action`)* → `done` (or `error`). Identical event contract to
  `assistant/`, so any existing stream consumer works unchanged.

Validation failures return HTTP 400 with the DRF error shape.

---

## Local development

1. `backend/.env` must contain `GEMINI_API_KEY` (and `GEMINI_MODEL`).
   The production value is also `GOOGLE_API_KEY` — both share one key.
   This file is gitignored; there is no fallback key in code.
2. `python manage.py migrate` — chat rows live in the shared
   `assistant_conversation`/`assistant_message` tables, so the assistant
   migration must have run (it only creates new tables locally).
3. `python manage.py runserver` then probe:

   ```powershell
   Invoke-WebRequest http://127.0.0.1:8000/api/ai/health/
   Invoke-WebRequest http://127.0.0.1:8000/api/ai/chat/ -Method Post `
     -Body '{"message":"Do you have dresses under KES 6000?"}' `
     -ContentType 'application/json'
   ```

### Live integration tests (opt-in)

`ai/tests/test_integration.py` calls the real Gemini API and is **skipped by
default**. To run it:

```powershell
$env:RUN_GEMINI_INTEGRATION=1
$env:GEMINI_API_KEY='…'
python manage.py test ai.tests.test_integration
```

---

## Render deployment

* `render.yaml` ships `GEMINI_MODEL: "gemini-3.5-flash-lite"` for the web
  service. `GEMINI_API_KEY` is `sync: false` — the key **must be entered by
  hand in the Render dashboard** for the web service. If it was copied from
  the legacy `GOOGLE_API_KEY`, keep both in sync.
* The deploy uses `backend/.env.example` as a template; it already carries
  `GEMINI_MODEL` and an empty `GEMINI_API_KEY`.

---

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| Every chat answers 502 `gemini_not_configured` | `GEMINI_API_KEY` empty in `settings` | Set `GEMINI_API_KEY` in `backend/.env`/Render (same value as `GOOGLE_API_KEY`). |
| Health/chat return 404 model error | `GEMINI_MODEL` retired (e.g. `gemini-2.5-flash-lite`) | Set `gemini-3.5-flash-lite` (or `gemini-3.5-flash`). |
| `/api/ai/chat` 500, "no such table: assistant_assistantconversation" | Local DB never migrated for `assistant` | `python manage.py migrate` (creates the shared tables). |
| 429s in production | Throttle bucket exhausted | 15/min anonymous, 30/min signed-in; raise in `assistant/throttling.py` if product needs it. |
| Slow first answer (~10–16s) | Cold model start + tool round-trips | Expected. Subsequent turns within a conversation reuse the interaction context. |
| `Both GOOGLE_API_KEY and GEMINI_API_KEY are set…` banner | Both vars populated | Harmless. Delete only if both are removed together. |

## Tests

`ai/` ships ~54 tests (health, chat, serializer, classification, retries) that
mock both the SDK and the turn engine — they make no network calls and run as
part of the normal suite. The integration tests above are the only ones that
hit Google. `python manage.py test` runs everything.