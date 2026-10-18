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
3. **Separate changing results from reusable history.** Do not generalize the reported strategy into a ban on caching tool results. Unchanged historical results can be reused; inserting new or rewritten results before stable content invalidates the following prefix.

## Provider-claimed savings

- **Anthropic** (Dec 2024 blog, reaffirmed 2025–2026): "up to 90% cost reduction and 85% latency reduction for long prompts."
- **OpenAI:** older Cookbook discounts are historical. See `openai.md` for model-specific read/write rates; do not apply an older discount to current generations.
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

Illustrative rates, not current price quotations. Hit fractions are assumptions, not measured effects of a layout. Count ordinary input, cache writes and cache reads separately; output and other charges are additional.

### Example A — 10K-token system prompt, 1M req/mo, Anthropic Sonnet-class

Base $3/M, cache write 5min $3.75/M, cache read $0.30/M.

1M × 10K = 10B tokens. Every miss writes the full prefix and every hit reads it: `10_000 * ((1-h) * 3.75 + h * 0.30)`. No caching uses the $3/M rate instead.

| Hit rate | Monthly input cost |
|---|---|
| No caching | $30,000 |
| 30% | $27,150 |
| 80% | $9,900 |
| 92% | $5,760 |

**About 5.21× lower input cost at 92% hits than without caching.** Multi-turn session estimates additionally require per-turn token counts and session frequency.

### Example C — Cheap-tier model (Flash-class), 10K system, 1M req/mo

Base $0.50/M, cache hit $0.05/M (90% off).

| Hit rate | Monthly cost |
|---|---|
| 0% | $5,000 |
| 80% | $1,400 |

### Example D — OpenAI GPT-class, 10K system, 1M req/mo

Historical illustration: base $5/M, cached $2.50/M, no separate write charge. Not current GPT-6 pricing.

| Hit rate | Monthly cost |
|---|---|
| 0% | $50,000 |
| 80% | $30,000 |

`10_000 * (0.2 * 5 + 0.8 * 2.5) = $30,000`, a 40% reduction from $50,000. See `openai.md` for generation-specific rates and retention.

## What to monitor

Per the paper and production traces, the metrics that catch regressions:

1. **Hit rate per session over time.** Compare against a workload-specific baseline. Investigate prefix changes, new content, expiration and routing rather than assuming a universal target or cause.
2. **`system_prompt_hash` distribution per day.** If you have logical "v1" but 50 distinct hashes — invisible mutator (analytics injector, trace ID, plugin).
3. **Cost split by category** (new input / cache read / cache write / output). Write/read ratio should drop fast in active sessions.
4. **TTFT p50/p95.** Compare like-for-like workloads, separating provider processing from network and queueing. Historical improvements above are source-specific, not guaranteed; unchanged latency alone does not establish a provider bug.

Choose alert thresholds from the actual workload baseline, expected reusable fraction and variability. Investigate sustained unexpected misses on eligible matching prefixes or unexplained prompt-hash fragmentation; do not treat a universal percentage or request count as validated.
