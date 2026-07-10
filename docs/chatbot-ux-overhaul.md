# Chatbot UX overhaul — research findings & implementation report

*2026-07-09. Companion to the changes that introduced `telegram/inbox.py`, `telegram/turns.py`,
`telegram/rendering.py`, conversation sessions, long-term memory, voice notes, and the hardened
OpenRouter client.*

## Why

The bot answered every Telegram message with an isolated agent run: two quick messages meant two
racing agent loops and two disjointed answers; the typing indicator died after 5 seconds while
tool loops ran for 30+; raw LLM markdown rendered as literal asterisks; the conversation was one
eternal thread with a 20-message window that silently dropped tool context; a transient OpenRouter
hiccup produced a generic apology (or complete silence, when the model returned empty content);
voice notes — a primary way Brazilians text — were ignored without feedback.

Each gap was researched against what production chat assistants actually ship (LangGraph platform
docs, Telegram Bot API/FAQ, aiogram 3 source, OpenRouter docs, Microsoft Bot Framework, the Mem0
paper, open-source Telegram LLM bots). Findings were adversarially verified (multi-voter
refutation against primary sources) before being adopted. The result below maps each finding to
the decision taken in this codebase.

## Findings → decisions

### 1. Multi-message aggregation (the "double texting" problem)
**Finding.** The industry taxonomy (LangGraph) names four strategies for a message arriving
mid-run: *reject*, *enqueue*, *interrupt*, *rollback* — with **enqueue** as the production
default. For messages arriving in a rapid burst *before* a run starts, the production fix
(shipped by messaging-gateway products) is a per-chat **debounce window that merges the burst
into one turn**; 2–3 s is the recommended window for Telegram (which also splits >4096-char
pastes into separate updates).

**Decision.** `ChatInbox` (`telegram/inbox.py`): one lazily-created worker task per chat pulls
from a per-chat queue, drains with a sliding `AGENT_DEBOUNCE_SECONDS` (default 2.5 s) window,
joins the texts (`\n\n`) and hands ONE batch to processing. Messages arriving mid-run queue up
and become the *next* batch — merge for bursts, enqueue for mid-run, never interrupt (aborting a
mid-flight tool loop with DB writes buys little for a finance Q&A bot and costs a lot of
complexity).

### 2. Per-chat serialization
**Finding.** aiogram 3 dispatches every update as its own `asyncio.Task` — no per-chat ordering
at all. Community fixes are per-chat locks in middleware or per-chat queue workers; aiogram's
`SimpleEventIsolation` exists but is tied to FSM storage keys.

**Decision.** No extra mechanism needed: the single worker-per-chat in `ChatInbox` *is* the
serialization (verified by test: turns never overlap within a chat, do overlap across chats).
Commands (`/sync`, `/reset`) intentionally bypass the inbox — they're explicit, rare actions.

### 3. Typing indicator & long operations
**Finding.** Telegram clears a chat action after ~5 s; aiogram ships `ChatActionSender`
(context manager, re-sends every 5 s) exactly for this. Streaming via `editMessageText` is
possible but flood-control-fragile; for tool-loop-dominated bots (latency comes from tool
rounds and bank syncs, not token generation) the production norm is typing indicator + single
final message.

**Decision.** `TurnProcessor.process()` wraps the whole agent run in
`ChatActionSender.typing(...)` and sends the reply *after* leaving the context (sending clears
the status client-side anyway). Streaming was deliberately deferred — wrong cost/benefit here.

### 4. Reply formatting & chunking
**Finding.** `telegramify-markdown` is the de-facto standard for LLM output → Telegram. Its
modern `convert()` API returns plain text + `MessageEntity` objects (UTF-16 offsets), which are
sent with `entities=` and **no `parse_mode`** — the entire class of "can't parse entities"
errors becomes structurally impossible. `split_entities()` chunks at newline boundaries within
Telegram's 4096-UTF-16-unit limit, clipping entities across chunks. The universal safety net is
catch-`TelegramBadRequest` → resend plain.

**Decision.** `telegram/rendering.py::send_markdown()` implements exactly that pipeline, plus an
empty-reply guard (the bot can no longer go silent) and a plain-text fallback chunked on line
boundaries. A session-level `RetryAfterSessionMiddleware` sleeps and retries on Telegram flood
control (`retry_after`), the officially sanctioned handling. The system prompt now tells the
model which Telegram-friendly markdown to use (bold/short lists; no tables/headers).

### 5. Conversation sessions & context
**Finding.** The documented production pattern (Microsoft Bot Framework) for conversation expiry
is **lazy**: store a last-activity timestamp, compare on the next message, and start fresh when a
TTL is exceeded — no background jobs. Replaying recent tool results keeps follow-ups ("e
ontem?") grounded; the token cost is bounded by truncating replayed payloads.

**Decision.** Conversations became sessions: dropped the unique (user, chat) constraint, added
`closed_at`/`last_message_at`, `get_active_or_create()` rolls over after
`AGENT_SESSION_TTL_MINUTES` (default 6 h) and `/reset` closes on demand (new command, registered
in the bot's command menu alongside pt-BR descriptions for all commands). History now replays
ALL roles — assistant tool calls and tool results included — within a 40-message window, tool
payloads truncated at `AGENT_TOOL_REPLAY_MAX_CHARS` (2000), and the window is trimmed to start at
a user message so no orphaned tool round ever reaches the API. Rolling summarization was
deferred: with 6-hour sessions, a 40-message window and durable memory (below), it would add an
LLM call + failure mode for context this bot no longer loses.

### 6. Long-term memory
**Finding.** The canonical pattern (Mem0, ChatGPT memory) is two-phase: extract candidate facts,
then consolidate against similar stored memories via ADD/UPDATE/DELETE decided by the LLM. The
full pattern needs embeddings + a vector store.

**Decision.** Scale-appropriate simplification: a `user_memories` table, two agent tools —
`remember_fact` (used proactively for durable facts: income, rent, goals, recurring bills) and
`forget_fact` (by the short id shown in the prompt) — and full injection of memories into the
system prompt (capped at `AGENT_MEMORY_LIMIT`, 50). With one user and dozens of facts, semantic
retrieval/consolidation is overhead without benefit; the LLM-in-the-loop add/forget covers the
lifecycle. The Mem0-style consolidator is the documented upgrade path if memory count grows.

### 7. LLM API robustness
**Finding.** OpenRouter supports a `models` fallback array (via `extra_body` in the OpenAI SDK)
that fails over on downtime/429/context-length/moderation, on top of automatic provider-level
failover; `provider.require_parameters` keeps tool-capable providers only. The SDK's own
`timeout`/`max_retries` handle transport retries (default timeout is 10 minutes — far too long
for chat). Two failure modes need explicit guards because the SDK returns them as "success":
an in-band `{"error": ...}` body with HTTP 200, and empty choices / empty content with no tool
calls (widely reported; treat as retry-once). Usage + cost now come free in every response
(`usage.cost` via `model_extra`).

**Decision.** The client sets `httpx.Timeout(90, connect=10)` + `max_retries=2`, sends the
fallback `models` array when `OPENROUTER_FALLBACK_MODELS` is configured, raises typed errors for
in-band errors/empty choices, and logs `llm_call` (model actually used, tokens, cost in USD) via
structlog on every call. `AgentService` retries once on an empty completion, then answers with an
honest pt-BR fallback line instead of silence. Inbox-level error handling replies apologetically
and keeps the worker alive (handler-level `@router.errors()` can't see inbox workers).

### 8. Voice notes
**Finding.** Telegram voice = OGG/Opus, downloadable in one `bot.download()` call (≤20 MB API
limit; voice notes are ~KBs). As of May 2026 OpenRouter proxies `/audio/transcriptions`
(OpenAI-SDK compatible, OGG accepted) — meaning Whisper pt-BR transcription with the **existing
OpenRouter key**, no new vendor. (Groq's hosted whisper-large-v3 free tier is the cheapest
alternative if a dedicated vendor is ever wanted.)

**Decision.** `OpenRouterClient.transcribe()` (`OPENROUTER_TRANSCRIPTION_MODEL`, default
`openai/whisper-1`, `language="pt"`); the voice handler downloads, transcribes, echoes
`🎙️ "<transcript>"` as a reply (so mishearings are visible), and submits the transcript into the
same inbox — voice and text merge into the same debounced turn. Audios over 5 minutes are
politely declined; transcription failures get an honest pt-BR reply. Other content types
(photos, stickers, documents) now get a friendly "text and audio only" response instead of
silence.

## Deliberately deferred (and why)

- **Streaming replies** (`editMessageText` at ~1 edit/s): latency here is tool rounds + bank
  syncs, not token generation; flood-control risk outweighs perceived-speed gain at this scale.
- **Rolling summarization**: redundant given sessions + 40-message replay + durable memories.
- **Embedding-based memory consolidation** (full Mem0): single-user scale doesn't need retrieval;
  plain prompt injection is strictly more reliable at <100 memories.
- **Edited-message handling**: no handler registered means Telegram doesn't even deliver those
  updates; reprocessing edits of already-answered questions is standard-practice "ignore".
- **Anti-flood throttling middleware**: the allowlist plus debounce already gate a single user.

## Verification

`make lint`, `make typecheck` (mypy strict), `make test` and `make test-all` (42 tests, including
new integration coverage for session expiry/rollover, tool-round replay, memory round-trip, and
the two-messages-one-turn contract against a real Postgres), plus
`poetry run pre-commit run --all-files` — all green. The app was also smoke-booted (polling
disabled) against the migrated dev database: health endpoints OK, clean shutdown including inbox
drain. The Alembic migration backfills `last_message_at` from `created_at` so existing databases
upgrade in place.

## New configuration

| Variable | Default | Meaning |
|---|---|---|
| `AGENT_DEBOUNCE_SECONDS` | 2.5 | burst-merge window per chat |
| `AGENT_SESSION_TTL_MINUTES` | 360 | inactivity before a fresh session |
| `AGENT_HISTORY_LIMIT` | 40 | replayed messages (all roles) |
| `AGENT_TOOL_REPLAY_MAX_CHARS` | 2000 | truncation for replayed tool results |
| `AGENT_MEMORY_LIMIT` | 50 | memories injected into the prompt |
| `OPENROUTER_FALLBACK_MODELS` | (empty) | comma-separated fallback model ids |
| `OPENROUTER_TIMEOUT_SECONDS` | 90.0 | request timeout |
| `OPENROUTER_MAX_RETRIES` | 2 | SDK transport retries |
| `OPENROUTER_TRANSCRIPTION_MODEL` | `openai/whisper-1` | voice STT model |
