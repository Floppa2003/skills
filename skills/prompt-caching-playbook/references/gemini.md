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
2. **Distinguish SDK failures from API constraints.** A tool-related cache miss in one SDK/model combination does not establish general incompatibility. Inspect the actual request and usage; the restriction on overriding an explicit cache's settings is separate from implicit caching.
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

### Tool configuration with explicit caches

The [CachedContent API](https://ai.google.dev/api/caching#CachedContent) accepts `tools`, `toolConfig` and `systemInstruction` at cache creation. In the Python SDK these are `tools`, `tool_config` and `system_instruction` in `CreateCachedContentConfig`. Generation requests reference `cached_content`; do not override those cached settings there. Tool use and explicit caching are compatible. Recreate the cache when its immutable configuration must change, and verify support for the selected API/model.

## Min prefix to activate caching

Check the selected model's minimum cacheable input length. A shorter prompt may remain uncached; compare its total cost and quality against any expanded alternative rather than padding it with irrelevant instructions.

## Reading cache stats

```python
usage = response.usage_metadata
cached_count = usage.cached_content_token_count
# Works for both implicit and explicit
```

For an API reporting this field, an explicit zero means no cached input was reported for that request; a missing field remains unknown. Investigate prefix changes, eligibility, expiry and observed SDK/model behavior before assigning a cause.

## Production recommendations

1. **Keep only useful context.** Compare total task cost and quality against the shorter baseline before expanding prompts to meet a caching threshold.
2. **Choose implicit or explicit caching from the workload.** Explicit caches can include tools; account for reuse, immutable configuration and storage costs rather than an arbitrary size cutoff.
3. **Monitor `cached_content_token_count` in production.** Calibrate alerts against expected reuse and observed variability.
4. **Static-first structure:** tools → system_instruction → history → new user.
5. **Sticky routing on Vertex AI:** use the global endpoint or one region consistently; implicit cache is local to a serving instance.
6. **Provisioned Throughput on Vertex AI** supports implicit caching — relevant for stable high-QPS workloads.

## Multi-tenant on Google

For explicit caches, each `CachedContent` resource is project-scoped. Enforce application-tenant authorization before reusing a cache name; project scope is not per-user isolation. Verify the chosen Gemini API or Vertex AI service's sharing, retention and access policies for implicit caches too. Exact prefix matching alone is not a proof against cache-hit probing. Do not weaken tenant separation for a higher hit rate; manage cache expiry and deletion explicitly.
