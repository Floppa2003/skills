# Anthropic — full mechanics

## Hierarchy of invalidation

Anthropic enforces a strict chain: **Tools → System → Messages**.

- Changing **Tools** invalidates System and Messages.
- Changing **System** invalidates Messages.
- Changing **Messages** invalidates only from the point of change forward.

Consequence: adding one MCP tool mid-session resets the entire cache, including a huge system prompt and all conversation history. On production this equals the cost of "first message of a new session" × all remaining messages until TTL expiry. This is the single most expensive failure mode.

## 4 cache breakpoints

Maximum **4 explicit `cache_control` blocks** per request. Typical layout for a coding agent:

```python
# Breakpoint 1: end of tools array (on last tool)
tools = [
    {"name": "search", ...},
    {"name": "edit_file", ...},
    {"name": "bash", "cache_control": {"type": "ephemeral"}},  # ← BP1
]

# Breakpoint 2: end of static system
system = [
    {"type": "text", "text": STATIC_SYSTEM_PROMPT,
     "cache_control": {"type": "ephemeral"}},  # ← BP2
]

# Breakpoint 3: end of stable RAG/context block
messages = [
    {"role": "user", "content": [
        {"type": "text", "text": LARGE_CODEBASE_CONTEXT,
         "cache_control": {"type": "ephemeral"}},  # ← BP3
        {"type": "text", "text": "task description..."},
    ]},
    # ... history ...

    # Breakpoint 4: on last message (slides forward each turn)
    {"role": "user", "content": [
        {"type": "text", "text": f"Current date: {today}, cwd: {cwd}"},
        {"type": "text", "text": new_message,
         "cache_control": {"type": "ephemeral"}}  # ← BP4 sliding
    ]},
]
```

Environment values here are non-instructional data appended after reusable history. Keep authoritative instructions in system; an unmarked block is still part of every later cache prefix. Preserve historical text and environment values, but remove obsolete sliding cache markers from outgoing copies rather than accumulating them. Count all retained and new breakpoints against the four-marker limit.

## Automatic vs explicit mode

Anthropic added **automatic caching** in 2025: instead of placing `cache_control` on individual blocks, pass top-level `cache_control: {"type": "ephemeral"}` in the request body. The system places the breakpoint on the last cacheable block and **slides it forward as the conversation grows**. This is the right default for multi-turn agents.

**Important caveat:** automatic caching is available on direct Anthropic API and Microsoft Foundry. **Not available on Amazon Bedrock or Google Vertex AI** — those require explicit `cache_control` markers. If an AI stack dynamically routes between providers (e.g., LiteLLM/OpenRouter), this becomes a footgun.

## TTL: 5 minutes vs 1 hour

- **5 minutes (default):** cache write × **1.25** base price. TTL **resets on every cache hit**. An active session with >1 request per 5 minutes keeps the cache effectively "forever."
- **1 hour (extended):** cache write × **2.0** base price; hits refresh the cache lifetime. Check duration support for the selected model and hosting API.

### Break-even math (Sonnet-class, $3/M input, cache write 5min $3.75/M, cache read $0.30/M)

At these illustrative rates, one 5min write plus one read costs 1.35× versus 2× uncached; one 1h write plus two reads costs 2.2× versus 3×. Compare actual reuse intervals and current rates before choosing a TTL; 1h does not cover a nightly gap.

You can mix: **1h TTL must come BEFORE 5min TTL** in the request. This lets you cache tools+system for an hour and history for 5 minutes.

## Min thresholds (current as of early 2026)

| Model family | Min tokens for cache |
|---|---|
| Sonnet 4.x / Opus 4.x / Sonnet 3.7 | **1024** |
| Haiku 3.5 / 3 | **2048** |
| Newer Opus / Haiku (4.5+, 4.6+) | **2048–4096** |

Below threshold: no error, just silent no-cache. `cache_creation_input_tokens` will be 0 in the response.

## Parsing response usage

```python
usage = response.usage
cache_read = usage.cache_read_input_tokens
cache_write = usage.cache_creation_input_tokens
new_input = usage.input_tokens

hit_rate = cache_read / max(1, cache_read + cache_write + new_input)
```

A healthy active session in a well-structured agent (Claude Code-style) holds **hit_rate ~90–96%**. On extended sessions with 1h TTL and proper warmer-call setup, 99.5% has been documented (Veritas Supera analysis: 61-hour session, 1610 API calls, 748M cache-read tokens).

## Cache isolation (multi-tenant)

The [current provider contract](https://platform.claude.com/docs/en/build-with-claude/prompt-caching#cache-storage-and-sharing) isolates Claude API, Claude Platform on AWS and Microsoft Foundry caches by workspace; Bedrock and Google Cloud use organization-level isolation. Verify the selected service's boundary and retention policy. Exact matching alone is not a proof against cache-hit probing within a shared boundary. Choose application-tenant separation according to security requirements; never disable it solely to improve reuse. Do not equate a logical workspace boundary with a physical-separation guarantee.

## Bedrock and Vertex AI caveats

- **No automatic caching** on Bedrock/Vertex — explicit `cache_control` required everywhere.
- **No 1h TTL** on Bedrock.
- **Cache control parameter conventions differ slightly** between Bedrock InvokeModel/Converse APIs and the Anthropic-native API. Use the AWS docs for exact JSON shape on Bedrock.
- **Streaming responses on Vertex** may not surface cache usage stats reliably depending on SDK version.

## Anti-pattern specifically common with Anthropic

- Routing Anthropic through **OpenRouter without sticky routing**: cache_control headers don't propagate consistently, hit rate stays flat regardless of session length. Long sessions become "order of magnitude more expensive than Anthropic direct" (documented in sst/opencode issue #1245 and similar community reports). For cache-heavy workloads, prefer direct Anthropic API.
- Beta header `anthropic-beta: prompt-caching-2024-07-31` is no longer needed (caching is GA). Some pinned older versions of LiteLLM-based tools still send it and break — upgrade.

## Production hit-rate benchmarks (Anthropic stack)

| Setup | Hit rate |
|---|---|
| Claude Code production (Anthropic internal) | 92% average, 96% on good sessions |
| Claude Code Max + warmer + 1h TTL on long session | 99.5% (documented case) |
| OpenCode + Anthropic direct, well-structured | 80–90% |
| Cline + Anthropic direct | ~90% |
| Cline routed through OpenRouter | Flat, doesn't grow with session |
| Continue (VSCode) with default caching | 60–80% |
