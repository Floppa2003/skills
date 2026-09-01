# OpenAI — full mechanics

## Base rules

- **Automatic** for all models gpt-4o and newer (including GPT-5, o-series, fine-tuned variants).
- Activates at prompt length **≥1024 tokens**. After that, cache hits go in **128-token increments**.
- Cache read discount: **~50%** on most models. Newer models (per OpenAI Cookbook "Prompt Caching 201") have steeper discounts up to ~75%.
- **No charge for cache writes** (unlike Anthropic). This is the cheapest-to-use mechanism of the three providers.

## Routing and `prompt_cache_key`

OpenAI hashes the **first ~256 tokens** of the request to select a machine. Cache lookup then happens **only on that machine**. Identical-prefix requests routed to different machines = cache miss.

**`prompt_cache_key`** is a hint that **combines with the prefix hash** during routing. Goal: increase the probability that similar users' requests land on the same machine.

### Critical RPM constraint

If a single (prefix + cache_key) combination exceeds **~15 RPM**, overflow routes to other machines where the cache is cold. Granulate `prompt_cache_key` carefully:

- Small traffic → one shared key.
- High traffic → per-user OR per-segment key — but never so narrow that each bucket gets <15 RPM (otherwise write overhead dominates).

```python
response = client.chat.completions.create(
    model="gpt-4o",
    messages=[...],
    prompt_cache_key=f"agent-v3-{user_segment}",  # stable per segment
)

# Read cache stats:
cached = response.usage.prompt_tokens_details.cached_tokens
```

## Extended retention (24h)

OpenAI supports `prompt_cache_retention` with values `"in_memory"` (default, 5–10 minutes) or `"24h"`. The 24h cache stores KV tensors on GPU-local storage.

**Same price for both options** — this is the major divergence from Anthropic where you pay 2× write for 1h. For newer models (gpt-5.5+), default is `"24h"`.

```python
response = client.chat.completions.create(
    model="gpt-5",
    messages=[...],
    prompt_cache_retention="24h",
)
```

## What's cached

Per OpenAI Cookbook:
- **Messages** — full system + user + assistant array.
- **Images** — in user messages, the `detail` parameter must match exactly.
- **Tool definitions** — order must be stable.
- **Structured output schema** — treated as a prefix to the system.

Reordering tools = guaranteed cache miss.

## Anti-patterns specific to OpenAI

- Setting `prompt_cache_key` per-user-id with low traffic: each bucket gets <15 RPM and effectively never cached. Use coarser granularity (segment, tier, locale).
- Changing the order of tools array between releases without versioning the `prompt_cache_key`: cache misses for the whole user base on the rollout.
- Different `detail` levels on the same image in two requests: cache miss.
- Streaming responses: cache stats are still available in the final chunk, but if telemetry isn't collected at chunk-end, you lose visibility.

## Observability

```python
log_entry = {
    "prompt_tokens": response.usage.prompt_tokens,
    "cached_tokens": response.usage.prompt_tokens_details.cached_tokens or 0,
    "hit_rate": (cached / total) if total else 0,
    "prompt_cache_key": "agent-v3-..." ,  # for grouping in dashboards
}
```

Dashboard panel that matters: **hit rate per `prompt_cache_key`**. Outliers reveal segments that are too small (RPM under threshold) or have mutating prefixes.

## When NOT to bother with `prompt_cache_key`

- Single-tenant dev/staging workload — automatic routing works fine.
- Workload where prefix changes every request anyway (e.g., per-user RAG context that's never reused). Caching won't help regardless.

## Realistic savings on OpenAI stack

With 50% cache hit discount and 80% hit rate on a 10K-token system prompt:

- Without cache: 1M req × 10K tokens × $5/M = $50,000/mo (using gpt-4o input pricing example)
- With 80% hit, 50% discount: 0.2M × $5/M + 0.8M × $2.5/M = $1,000 + $2,000 = **$3,000/mo (-94% on cached portion, -78% overall)**

OpenAI's 50% discount is less aggressive than Anthropic/Google's 90%, so the absolute savings ceiling is lower — but the zero cache-write cost and `prompt_cache_retention=24h` at no extra charge makes the mechanics simpler to reason about.
