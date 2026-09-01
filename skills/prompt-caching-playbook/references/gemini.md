# Google Gemini — full mechanics

Google offers **two independent caching systems**.

## Implicit caching (default)

Enabled by default for all Gemini 2.5+ and Gemini 3 families. No code required. Google automatically applies the cache hit discount.

### Min thresholds (current Vertex AI docs, early 2026)

| Model | Min for implicit cache |
|---|---|
| Gemini 2.5 Flash / 2.5 Pro | **2048 tokens** (older docs cited 1024 for Flash) |
| Gemini 3 Flash / 3 Pro / 3.1 Flash-Lite / 3.1 Pro | **4096 tokens** |

Declared cache hit discount: **90% off base input** on Gemini 2.5/3 families, **75%** on Gemini 2.0.

### Pitfalls of implicit caching

1. **Cost savings not guaranteed.** Official Google notebooks state: *"implicit caching is enabled by default for all Gemini 3 and 2.5 models but cost savings only apply to Gemini 2.5 models"* — that phrasing has tightened over time and Gemini 3 does get savings as of early 2026, but they remain **best-effort**, not contractual.
2. **Known bug with tools.** Vercel AI SDK Issue #11513 (Dec 2025): "Implicit caching does not appear to work when using `@ai-sdk/google` with Gemini 3 Flash Preview and tools defined, even when token counts exceed the documented minimum." This aligns with a public Google error message: `CachedContent cannot be used with GenerateContent request setting system_instruction, tools or tool_config`. In a production agent with active tool-use on Gemini 3, implicit cache may silently fail to activate.
3. **Stickiness.** To improve hit probability: keep an identical prefix, send requests in close temporal proximity (TTL ≈ 3–5 minutes), and prefer a single region or global endpoint.

## Explicit caching (Context Caching API)

Gives **guaranteed** discount. Used via `client.caches.create()`:

```python
from google import genai
from google.genai import types

client = genai.Client()
cache = client.caches.create(
    model='models/gemini-3-flash-preview',
    config=types.CreateCachedContentConfig(
        display_name='agent-base-context',
        system_instruction=SYSTEM_PROMPT,
        contents=[LARGE_CODEBASE_CONTEXT],
        ttl='3600s',  # 1 hour (no upper bound), default 60min
    ),
)

# Subsequent calls pass cache name + new user query
response = client.models.generate_content(
    model='models/gemini-3-flash-preview',
    contents='What does the auth flow do?',
    config=types.GenerateContentConfig(cached_content=cache.name),
)
```

### Explicit cache billing

- **Cache write:** counted as input tokens at regular price.
- **Cache read:** ~90% discount.
- **Cache storage:** per-hour fee for cached token volume (unique to Google — Anthropic and OpenAI don't bill storage separately). See Vertex AI pricing for the exact rate per model.

### Hard limitation of explicit cache

**`CachedContent` cannot be used with a `GenerateContent` request setting `system_instruction`, `tools`, or `tool_config`.**

This is a serious architectural limit for agents. Workarounds:
- Use only implicit caching (accept some miss rate).
- Split the chain: tool-less calls use explicit cache; tool-using calls don't get explicit cache.

## Min prefix to activate caching

For implicit caching, the system + history + current user content must exceed the model's min threshold (1024 / 2048 / 4096 depending on the model). Below threshold = silent no-cache. Strategy: don't skimp on system prompt tokens; add stable context/style/conventions to push above threshold.

## Reading cache stats

```python
usage = response.usage_metadata
cached_count = usage.cached_content_token_count
# Works for both implicit and explicit
```

If `cached_content_token_count` is 0 with a sufficient prefix size, implicit cache did not activate. Most common causes: tools in the request, changes at the start of prompt, or simply "the provider didn't get to it" (best-effort).

## Production recommendations

1. **Aim for 4096+ token system prompt** to activate implicit caching on newer models. Don't economize tokens below threshold; add stable context and style.
2. **Implicit caching is the default** for tool-using agents. Use explicit only when you have a huge (50K+ tokens) reusable context **without tools** in the same request.
3. **Monitor `cached_content_token_count` in production**, especially on long sessions with tools. Alert if it stays 0 for >10 consecutive requests.
4. **Static-first structure:** tools → system_instruction → history → new user.
5. **Sticky routing on Vertex AI:** use the global endpoint or one region consistently; implicit cache is local to a serving instance.
6. **Provisioned Throughput on Vertex AI** supports implicit caching — relevant for stable high-QPS workloads.

## Multi-tenant on Google

Implicit caching is content-hashed and per-project. Cross-project leakage isn't possible by design. For workloads where users share an org, implicit cache reuse across users is a feature, not a leak (the cache stores attention KV tensors, not output; the hash match guarantees identical input).

For explicit caches, each `CachedContent` resource is scoped to the project and can be deleted via API. Lifecycle management is the developer's responsibility.
