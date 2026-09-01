# Benchmarks — academic and production data

## The academic reference paper

**Lumer et al., *Don't Break the Cache: An Evaluation of Prompt Caching for Long-Horizon Agentic Tasks*, arxiv 2601.06007 (v2, Jan 31, 2026).**

First systematic academic evaluation of prompt caching on multi-turn agentic tasks. Cite this in architecture reviews.

### Setup

- DeepResearch Bench, 500+ agentic sessions.
- 10,000-token system prompts.
- All three major providers (Anthropic, OpenAI, Google).
- Three caching strategies compared:
  1. **Full context caching** (naive: cache everything).
  2. **System prompt only caching.**
  3. **Caching excluding dynamic tool results.** ← winner.

### Quantitative results

- **API cost reduction: 41–80%** depending on provider and strategy.
- **TTFT improvement: 13–31%** on the same tests.
- **Universal linear scaling** across ablation from 500 to 50,000-token system prompts and from 3 to 50 tool calls.

### Key findings for production

1. **Naive full-context caching can paradoxically increase latency** — because dynamic tool results constantly invalidate the prefix, forcing you to pay for cache writes without subsequent reads.
2. **Best practice:** "strategic prompt cache block control — placing dynamic content at the end of the system prompt, avoiding dynamic traditional function calling, and excluding dynamic tool results."
3. **Tool results should NOT be cached.** Place the breakpoint *before* them. Cache only tool *definitions* and stable context.

## Provider-claimed savings

- **Anthropic** (Dec 2024 blog, reaffirmed 2025–2026): "up to 90% cost reduction and 85% latency reduction for long prompts."
- **OpenAI** (Cookbook "Prompt Caching 201"): up to ~50% discount on cached portion, with newer models reaching ~75%.
- **Google** (Vertex AI docs, early 2026): 90% off cached tokens on newer Flash/Pro families, 75% on older 2.0 generation.

## Production hit rates documented in the wild

| Source | Setup | Hit rate |
|---|---|---|
| Anthropic engineering threads | Claude Code production | 92% average; SEV-level alerting if it drops |
| LMCache blog (Dec 2025) | Claude Code trace analysis | 92% prefix reuse |
| Veritas Supera analysis | Claude Code Max + warmer + 1h TTL, 61-hour session | 99.5% (1610 API calls, 748M cache-read tokens) |
| Claude Code Camp (Feb 2026) | Empirical experiments | Documented 2-letter case change breaking cache for 2727 tokens |
| sst/opencode DeepWiki | OpenCode + Anthropic direct | 80–90% |
| 4sysops | Cline + Anthropic direct | ~90% |
| sst/opencode issue #1245 | Cline/OpenCode via OpenRouter | Flat baseline; doesn't grow with session |

## Worked cost examples

### Example A — 10K-token system prompt, 1M req/mo, Anthropic Sonnet-class

Base $3/M, cache write 5min $3.75/M, cache read $0.30/M.

| Hit rate | Monthly input cost |
|---|---|
| 0% | $30,000 |
| 30% (naive) | ~$8,775 |
| 80% (good) | ~$990 |
| 92% (Claude Code-style) | ~$576 |

**52× difference between worst and best.**

### Example B — 50-turn agent session, 20K system, Anthropic Sonnet-class

- No cache: $3.50–4.50/session
- System-only cache: $0.50–0.70/session
- Multi-breakpoint sliding: ~$0.19/session

10K sessions/day:
- No cache: ~$35K/mo input
- System-only: ~$5K/mo
- Sliding: ~$1.9K/mo

### Example C — Cheap-tier model (Flash-class), 10K system, 1M req/mo

Base $0.50/M, cache hit $0.05/M (90% off).

| Hit rate | Monthly cost |
|---|---|
| 0% | $5,000 |
| 80% | $1,400 |

### Example D — OpenAI GPT-class, 10K system, 1M req/mo

Base $5/M, cached ~$2.50/M (50% off, conservative).

| Hit rate | Monthly cost |
|---|---|
| 0% | $50,000 |
| 80% | $13,000 |

OpenAI's 50% discount is less aggressive than Anthropic/Google's 90%, so the absolute ceiling is lower. But zero cache-write cost and free `prompt_cache_retention=24h` make mechanics simpler.

## What to monitor

Per the paper and production traces, the metrics that catch regressions:

1. **Hit rate per session over time.** Should rise to 80%+ after turn 2–3. Falling within a session = something mutating the prefix.
2. **`system_prompt_hash` distribution per day.** If you have logical "v1" but 50 distinct hashes — invisible mutator (analytics injector, trace ID, plugin).
3. **Cost split by category** (new input / cache read / cache write / output). Write/read ratio should drop fast in active sessions.
4. **TTFT p50/p95.** Prompt cache hits reduce TTFT by 13–85% depending on prefix length; if your TTFT isn't dropping with hit rate, the cache might be reading but not pre-loading attention KV (rare provider bug).

Alert thresholds for production agents:
- Hit rate <70% sustained for >5 min on a long-prefix workload.
- `cached_tokens` is 0 for >10 consecutive requests when prefix exceeds min threshold.
- Single `system_prompt_hash` accounts for <50% of daily traffic (suggests fragmentation).
