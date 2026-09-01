---
name: prompt-caching-playbook
description: Practical playbook for maximizing prompt cache hit rate and minimizing token spend on LLM/agentic systems (Anthropic, OpenAI, Google Gemini, self-hosted vLLM). Covers prompt structure rules, multi-turn cache breakpoint placement, tool definition stability, dynamic content handling, TTL choice, multi-tenant isolation, and known anti-patterns. Distilled from provider docs, the "Don't Break the Cache" arxiv paper, and OSS agents (OpenCode, Aider, Cline, Claude Code). Use whenever the user designs, audits, or debugs the prompt/message structure of an LLM-powered system — chat agents, RAG pipelines, coding agents, batch eval jobs, multi-tenant SaaS — or asks about cache hit rate, cache_control, prompt_cache_key, Context Caching API, cache TTL, cost optimization, "why is my LLM bill so high", "почему API LLM дорого", "как уменьшить токены", "cache miss", "kv-cache", "prefix matching", "static prefix dynamic suffix", or any phrasing about reusing prompt prefixes across requests.
---

# Prompt Caching Playbook for Production LLM/Agentic Systems

A practical lens + ordered playbook for structuring prompts and message arrays so the provider can reuse the KV-cache across requests. Get token cost down 5–50× on input and TTFT down 13–85% without touching the model.

This skill covers **Anthropic Claude, OpenAI GPT/o-series, Google Gemini, and self-hosted vLLM**. The structural rules are the same across all four; only syntax differs.

## How to apply

1. **Diagnose first.** Look at the user's existing prompt structure or system architecture before suggesting changes. Static-vs-dynamic content placement and tool definition stability are the two highest-leverage variables — check those before discussing TTL or breakpoint count.
2. **Apply the universal rule.** Static prefix → dynamic suffix. Order across all providers: tools → system → conversation history → new user message. Anything that changes per request must live **after** the last cache breakpoint.
3. **Name what NOT to do.** The anti-patterns list in §6 below catches ~80% of real production cache misses. Surface them proactively whenever the user describes their prompt structure.
4. **Quantify the win.** Every recommendation should come with an estimated cost/latency saving anchored in real numbers from §8 (worked examples) or §7 (provider mechanics), so the user can prioritize.
5. **Recommend a monitoring loop.** Cache hit rate must be logged per-request and dashboarded per-session, per-tenant. Without observability, regressions are invisible until the next billing cycle.

## TL;DR — the rules that matter

1. **Static prefix → dynamic suffix.** Order: tools → system static → system dynamic → long context / RAG → conversation history → new user message. Cache breakpoint goes after the last *stable* block.
2. **Multi-turn:** previous user and assistant messages stay in place (append-only). New user message appended at the end. Cache breakpoint slides forward each turn.
3. **Tool definitions are part of the cached prefix.** Reorder tools = full cache invalidation. Add/remove an MCP tool mid-session = full invalidation (system + all history).
4. **Min thresholds:** 1024 tokens (Anthropic Sonnet/Opus, OpenAI, some Gemini models), 2048 tokens (Anthropic Haiku, Gemini 2.5), 4096 tokens (newer Gemini models). Below threshold = silent no-cache.
5. **Cache hit pricing:** ~10% of base input (Anthropic, Google) or ~50% (OpenAI). Cache write costs: 1.25× base on Anthropic for 5min TTL, 2× for 1h TTL; OpenAI and Google charge nothing extra for writes.
6. **TTL choice:** 5 min default refreshes on every hit — fine for active sessions. 1 hour (Anthropic) or 24h (OpenAI) for spaced-out workloads (review agents, batch jobs).
7. **Anti-patterns that kill the cache:** timestamps/UUIDs at start of system prompt, live `git status` in every prompt, middleware injecting trace IDs, reordering tools, switching models mid-session, aggressive history reformatting, putting tool *results* inside the cached prefix.

## Decision tree — what to do for the user's stack

```
Is the user designing a new system?
├── YES → §1 (canonical structure) + §3 (provider-specific syntax) + §4 (monitoring)
└── NO, debugging existing system:
    ├── "Cache hit rate is low / unstable"
    │   → §6 (anti-patterns checklist) — walk through one by one
    ├── "Bill is too high"
    │   → §5 (cost math) → §1 → §6
    ├── "Hit rate was good, now it's not"
    │   → check for recent changes: tools added? middleware deployed? model switched?
    │   → §6 #4, #5, #6, #7
    ├── "Migrating providers"
    │   → §3 (per-provider mechanics) + §2 (multi-turn nuances per provider)
    ├── Multi-tenant SaaS concerns
    │   → §7 (cache isolation)
    └── "What's the right TTL"
        → §3 TTL subsection — depends on inter-request gap
```

For deep mechanics on any specific provider, read `references/anthropic.md`, `references/openai.md`, `references/gemini.md`, or `references/self-hosted.md`. For full benchmark numbers and the academic findings, see `references/benchmarks.md`. For analysis of OSS agents (OpenCode, Aider, Cline, OpenHands, Codex CLI, Claude Code), see `references/oss-agents.md`.

---

## 1. The canonical structure

All major providers use **prefix matching by exact byte equality**. The KV-cache stores attention Key/Value tensors for the prefix; on hit, the model skips re-processing those tokens and resumes forward pass only from the first un-cached byte. Any byte change in the prefix invalidates everything after it.

The mandatory ordering across **Anthropic, OpenAI, Google, and vLLM**:

```
[1] Tool definitions          ← most stable, cached first (part of prefix)
[2] System prompt — static    ← role, style, conventions, AGENTS.md/rules
[3] System prompt — dynamic   ← timestamp, cwd, user_location (END of system!)
[4] Long context / RAG        ← documents, codebase chunks (if reused)
[5] Conversation history      ← user/assistant turns, append-only
[6] New user message          ← always last
```

**Cache breakpoint** (where the provider should stop hashing the prefix and start treating content as variable) goes after the **last stable block**. In Anthropic terms — that's where `cache_control` is placed. In OpenAI/Google — the system decides automatically based on the prefix matcher.

### Canonical system prompt template

```text
# === BLOCK A: ROLE (stable forever) ===
You are an expert software engineering agent. Your role is...
[2000–4000 tokens of stable instructions]

# === BLOCK B: TOOL USAGE GUIDELINES (stable per agent version) ===
When calling tools, you must...
[1000–3000 tokens]

# === BLOCK C: PROJECT CONVENTIONS (AGENTS.md / .cursorrules / etc.) ===
[variable per project but stable within a project]

# === BLOCK D: STYLE / OUTPUT FORMAT ===
[stable]

# === [CACHE BREAKPOINT HERE] ===

# === BLOCK E: DYNAMIC ENVIRONMENT (after breakpoint, NOT cached) ===
<env>
date: 2026-05-14T10:30:00Z
cwd: /home/user/projects/foo
git_branch: feature/auth-v2
</env>
```

---

## 2. Multi-turn behavior — how the breakpoint moves

The most common confusion: "do I keep the previous user message in the array?" Yes — the previous user and assistant messages stay in place. Append-only.

Per-turn shape:

```
Turn 1: [tools] [system] [user_1]
Turn 2: [tools] [system] [user_1] [assistant_1] [user_2]
Turn 3: [tools] [system] [user_1] [assistant_1] [user_2] [assistant_2] [user_3]
```

The cache breakpoint **slides forward** each turn:
- Turn 2: prefix `[tools][system][user_1][assistant_1]` is cached (3 of 4 blocks reused from turn 1).
- Turn 3: prefix `[tools][system][user_1][assistant_1][user_2][assistant_2]` is cached.

**Provider mechanics:**
- **Anthropic** — top-level `cache_control: {"type":"ephemeral"}` automatically applies the breakpoint to the last cacheable block and advances it. Or place explicit `cache_control` on the last user message manually (up to 4 breakpoints).
- **OpenAI** — fully automatic, no markers. The provider hashes the prefix on every request and routes to a machine that has it cached.
- **Google Gemini** — implicit caching is automatic. Explicit Context Caching API is incompatible with tool use in the same request (limitation as of early 2026).

### Compaction / history truncation

When context grows past the limit, agents must compact. **Compaction is the #1 cache-killer in long sessions** because the summarized prefix breaks byte equality.

Two strategies:
1. **Make the summary itself stable.** Compact once, then the summarized prefix becomes the new stable prefix. Subsequent turns build on top of it. Hit rate recovers after one cold turn.
2. **Pruning, not summarizing.** Drop oldest tool outputs while keeping the message structure intact. Some agents (OpenHands, OpenCode) protect the most recent N tokens and mark older tool outputs as "compacted" without rewriting them.

---

## 3. Provider-specific mechanics

Compressed cheat sheet. For full mechanics, read the relevant reference file.

| | **Anthropic** | **OpenAI** | **Google Gemini** | **Self-hosted (vLLM)** |
|---|---|---|---|---|
| Activation | Explicit `cache_control` or top-level auto | Automatic | Implicit auto + explicit Context Caching API | `--enable-prefix-caching` (on by default v0.5+) |
| Min prefix | 1024 (Sonnet/Opus); 2048+ (Haiku, newer Opus/Haiku) | 1024, then +128 increments | 1024–4096 depending on model | None (any prefix) |
| Cache hit cost | 0.1× base | ~0.5× (some models ~0.25×) | ~0.1× on newer Flash/Pro families | Free (your GPU) |
| Cache write cost | 1.25× (5min) / 2× (1h) | Free | Free for implicit; storage fee for explicit | Free |
| TTL | 5min (default) or 1h (Opus 4.5+, Sonnet 4.5+, Haiku 4.5+) | ~5–10 min or 24h via `prompt_cache_retention` | 5min implicit / configurable explicit (default 60min) | LRU eviction by GPU memory |
| Multi-tenant key | Workspace (Bedrock/Foundry) or org-level | `prompt_cache_key` parameter | Auto by content hash | `cache_salt` parameter |
| Response field | `cache_read_input_tokens`, `cache_creation_input_tokens` | `prompt_tokens_details.cached_tokens` | `usage_metadata.cached_content_token_count` | varies |
| Max breakpoints | 4 explicit | N/A (auto) | N/A (auto) | N/A |
| Hierarchy | Tools → System → Messages (changing higher invalidates lower) | Same effective behavior | Same | Same |

### TTL decision guide

- **Active conversational agent (>1 req per 5min):** default 5min on Anthropic, default in-memory on OpenAI. The TTL refreshes on every hit.
- **Code review agent / sporadic queries (every 5–60min):** Anthropic 1h, OpenAI 24h.
- **Batch eval / nightly jobs:** Anthropic 1h, OpenAI 24h. The 2× write multiplier on Anthropic is recouped after ~3 reads.
- **RAG over stable docs:** Anthropic 1h for the document context, 5min for conversation history (mix is allowed — 1h must come *before* 5min in the request).

For deep provider-specific details (4-breakpoint placement on Anthropic, `prompt_cache_key` granularity on OpenAI, Context Caching API on Google, vLLM prefix caching tuning), see the reference files.

---

## 4. Monitoring — what to log

Every LLM call should log:

```python
log_entry = {
    "request_id": uuid,
    "session_id": session.id,
    "tenant_id": tenant.id,
    "model": model_name,
    "provider": provider_name,
    # Token accounting (parse from provider's usage object)
    "input_tokens_new": ...,         # cache miss portion
    "cache_read_tokens": ...,
    "cache_write_tokens": ...,       # 0 on OpenAI/Google implicit
    "output_tokens": ...,
    # Derived
    "hit_rate": cache_read / max(1, cache_read + cache_write + new_input),
    "cost_usd": calculate_cost(...),
    # Latency
    "ttft_ms": ...,
    "total_latency_ms": ...,
    # Diagnostics (catch silent prefix mutations)
    "system_prompt_hash": sha256(system_prompt)[:12],
    "tools_hash": sha256(tools_json)[:12],
    "first_256_token_hash": ...,     # detect prefix drift
}
```

Dashboard panels that matter:
1. **Hit rate over time per session.** Should rise to 80%+ after turn 2–3. If it falls within a session, something is mutating the prefix mid-conversation.
2. **Hit rate per tenant/segment.** Outliers reveal poorly-structured per-tenant prefixes.
3. **Unique `system_prompt_hash` count per day.** If you logically have "v1" but see 50 distinct hashes, an invisible mutator (analytics injector, trace ID middleware, plugin) is corrupting the prefix.
4. **Cost split: new input / cache read / cache write / output.** Ratio of write to read should drop fast in active sessions.

Alert thresholds:
- Hit rate < 70% sustained for >5min on an agentic workload → investigate.
- `cached_tokens` field is 0 for >10 consecutive requests on a long-prefix workload → check for prefix mutation or known provider bugs (Gemini-with-tools edge cases, OpenRouter sticky-routing issues).

---

## 5. Cost math — worked examples

### Example A: 10K-token system prompt, 1M requests/month, Claude Sonnet-class model
Base input $3/M, cache write 5min $3.75/M, cache read $0.30/M.

| Scenario | Hit rate | Monthly input cost |
|---|---|---|
| No caching | 0% | **$30,000** |
| Naive caching (bad structure) | 30% | ~$8,775 |
| Good structure | 80% | ~$990 |
| Best-practice multi-breakpoint | 92% | ~$576 |

**52× difference between "no cache" and "92% hit rate."** Output cost unchanged.

### Example B: 50-turn agent session, 20K system prompt
- No caching: ~$3.50–4.50/session
- Caching system only: ~$0.50–0.70/session
- Multi-breakpoint sliding: ~$0.19/session

10K sessions/day → $35K/mo vs $5K/mo vs $1.9K/mo input.

### Example C: Cheap-tier model (e.g., Flash-class), 10K system, 1M req/mo
Base $0.50/M, cache hit $0.05/M (90% off).

| Hit rate | Monthly cost |
|---|---|
| 0% | $5,000 |
| 80% | $1,400 |

For high-volume workloads, the cheap-tier + good caching combo lands input cost at ~$1.5K/month per million requests. Output billed separately.

---

## 6. Anti-patterns checklist (the cache-killers)

Walk through this list when debugging low hit rate.

| # | Anti-pattern | Effect |
|---|---|---|
| 1 | Timestamp / current date in **start** of system prompt | 0% hit rate; every request is full reprocess |
| 2 | Session ID / request UUID anywhere in system | Same |
| 3 | Live `git status` / file listing in every prompt | Cache invalidates on every file edit |
| 4 | Middleware injecting trace ID / analytics token into system | Invisible mutator — hardest to find |
| 5 | Reorder of tool definitions between requests | Full invalidation of tools+system+messages |
| 6 | Adding/removing a tool mid-session (MCP, plugin) | Same |
| 7 | Switching model mid-session | Cache is per-model — cold start on new |
| 8 | Aggressive summarization/compaction every N turns | Each rewrite breaks byte equality |
| 9 | Reformatting history (case, whitespace, JSON re-serialization) | Two-letter change = thousands of tokens missed (empirically) |
| 10 | Streaming response with no usage telemetry | You lose visibility into cache stats |
| 11 | Anthropic routed through OpenRouter without sticky routing | Hit rate stays flat regardless of session length |
| 12 | Tool *results* placed inside the cached prefix | Dynamic content invalidates the prefix |
| 13 | Mixing explicit Context Cache with tool use on Google models | Documented API incompatibility |
| 14 | OpenAI: too-narrow `prompt_cache_key` (RPM per key < ~15) | Overflow routes to cold machines |
| 15 | `cache_control` breakpoint placed on a block that *changes* | Pay for write every time, never read |

The most expensive failure mode in practice is **#4 (middleware)**. Observability layers (Sentry, LangSmith, Helicone, custom analytics) often inject trace IDs into the system prompt. They work "correctly" and silently cost 10× more on input — discovered only when looking at the next bill.

---

## 7. Multi-tenant cache isolation

**Cross-tenant data leakage via cache is not a real risk** on any of the three major providers. Cache hashes exact content; a different tenant's prefix won't match. You do **not** need to add per-tenant salt to the prefix — that would kill the global cross-tenant cache and lose all the savings.

What you *might* need depending on compliance:

- **Anthropic** — cache entries isolated between organizations and between workspaces (on Bedrock and Microsoft Foundry). Direct Anthropic API: org-level only.
- **OpenAI** — granulate `prompt_cache_key` per tenant segment, not per user. Aim for >10 RPM per key. Per-user keys with low traffic suffer from overflow.
- **Google** — implicit caching is content-hashed and per-project. No per-tenant config needed.
- **Self-hosted vLLM** — use `cache_salt` parameter to isolate per-tenant on shared GPU.

ZDR (zero data retention) compatibility: all three major providers state cache lives in RAM/VRAM only, not written to disk, with short TTL. Anthropic's docs explicitly note "raw text of prompts is not stored — only KV representations and cryptographic hashes in memory."

---

## 8. Production code templates

### Anthropic-style (explicit cache_control)

```python
import anthropic
client = anthropic.Anthropic()

STATIC_SYSTEM = open("prompts/system.md").read()
TOOLS = load_tool_definitions()  # stable order, frozen per release

def call_agent(history, new_user_msg, dynamic_env):
    # Mark last tool to cache the whole tools array
    tools = TOOLS.copy()
    tools[-1] = {**tools[-1], "cache_control": {"type": "ephemeral"}}

    # System: static cached, dynamic appended without cache_control
    system = [
        {"type": "text", "text": STATIC_SYSTEM,
         "cache_control": {"type": "ephemeral", "ttl": "1h"}},
        {"type": "text",
         "text": f"<env>\ndate: {dynamic_env['date']}\ncwd: {dynamic_env['cwd']}\n</env>"},
    ]

    # Messages: history + new user with sliding breakpoint
    messages = history + [{
        "role": "user",
        "content": [{
            "type": "text", "text": new_user_msg,
            "cache_control": {"type": "ephemeral"},  # sliding BP
        }],
    }]

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        tools=tools, system=system, messages=messages,
    )

    u = response.usage
    hit_rate = u.cache_read_input_tokens / max(
        1, u.cache_read_input_tokens + u.cache_creation_input_tokens + u.input_tokens
    )
    return response, hit_rate
```

### OpenAI-style (automatic + cache key)

```python
from openai import OpenAI
client = OpenAI()

def call_agent(segment: str, messages: list):
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=messages,
        # Granulate per segment, not per user — keep RPM/key above ~15
        prompt_cache_key=f"agent-prod-v1-{segment}",
    )
    cached = response.usage.prompt_tokens_details.cached_tokens or 0
    total = response.usage.prompt_tokens
    return response, cached / total
```

### Google-style (implicit, with tools — watch for known caveats)

```python
# Pseudocode — actual SDK varies; the structural rule is what matters.
def call_with_implicit(system: str, history: list, new_msg: str, tools=None):
    """For agents with tools: implicit caching only. Some provider+model
    combinations have known issues activating implicit cache when tools
    are present — monitor cached_content_token_count in production."""
    response = generate_content(
        model=MODEL,
        system_instruction=system,            # stable, at start
        contents=history + [new_msg],
        tools=tools or [],
        # Ensure system + history >= model's min threshold (1024–4096 tokens)
    )
    cached = response.usage_metadata.cached_content_token_count or 0
    return response, cached
```

---

## 9. Audit checklist for existing systems

Walk through this when reviewing a user's existing agent/LLM stack:

1. [ ] Every LLM call logs `cache_read`, `cache_write`, `new_input` token counts.
2. [ ] System prompt is hashed on send — metric "unique system_prompt_hash per day" exists.
3. [ ] Tool definitions: one shared list, fixed order, versioned with the release.
4. [ ] Timestamp / date / cwd / random_id are **out of the start** of system prompt.
5. [ ] Conversation history is append-only — never reformatted between turns.
6. [ ] Compaction triggers only on overflow, and the summarized prefix is itself stable across subsequent turns.
7. [ ] Model is **not switched** mid-session.
8. [ ] Anthropic: `cache_control` present on at least one block (or top-level auto).
9. [ ] OpenAI: `prompt_cache_key` set, granular enough but >10 RPM/key.
10. [ ] Google: `cached_content_token_count > 0` verified in production traces (especially with tools).
11. [ ] Dashboard shows hit rate per session, p50/p95 TTFT, cost split.
12. [ ] Alert configured for hit_rate < threshold (e.g., 70% for agents).
13. [ ] Middleware/plugins audited for injection into system prompt.
14. [ ] If using LiteLLM/OpenRouter/proxy — sticky routing verified, otherwise prefer direct provider for cache-heavy workloads.

---

## Reference files

For deeper mechanics on specific topics, load the corresponding file from `references/`:

- `references/anthropic.md` — full Anthropic mechanics: 4-breakpoint placement, automatic vs explicit modes, 1h vs 5min TTL break-even math, hierarchy of invalidation, response usage parsing, Bedrock/Vertex caveats.
- `references/openai.md` — `prompt_cache_key` routing, 15 RPM rule, `prompt_cache_retention`, what's cached (messages, images, tools, structured output schema).
- `references/gemini.md` — implicit vs explicit Context Caching API, known incompatibility with tools, min thresholds per model family, storage billing.
- `references/self-hosted.md` — vLLM prefix caching tuning, `cache_salt`, SGLang, TGI.
- `references/oss-agents.md` — reverse-engineered cache strategies of OpenCode (the reference implementation), Aider, Cline/Roo Code, Continue, OpenHands, OpenAI Codex CLI, and what's known about Claude Code and Cursor.
- `references/benchmarks.md` — production hit-rate numbers from various agents, the *Don't Break the Cache* arxiv paper findings (41–80% cost savings, 13–31% TTFT improvement), and the methodology behind them.

## Sources

Official:
- Anthropic Prompt Caching docs (`platform.claude.com/docs/en/build-with-claude/prompt-caching`).
- Anthropic blog "Prompt caching with Claude" (Dec 2024).
- Google Vertex AI Context Caching docs.
- Google AI Studio docs (`ai.google.dev/gemini-api/docs/caching`).
- OpenAI Prompt Caching guide + Cookbook "Prompt Caching 101 / 201".
- Azure OpenAI Foundry docs — `prompt_cache_retention`.

Academic:
- Lumer et al., *Don't Break the Cache: An Evaluation of Prompt Caching for Long-Horizon Agentic Tasks*, arxiv 2601.06007 (v2, Jan 2026) — 41–80% cost, 13–31% TTFT.

Production analysis:
- Anthropic engineering threads on Claude Code (cache hit rate ~92% in production, SEV-level alerting).
- LMCache blog (Dec 2025) — trace analysis of Claude Code.
- Claude Code Camp empirical experiments (Feb 2026) — two-letter change breaking cache.
- Veritas Supera analysis — 99.5% hit rate on 61-hour long session.

Open-source code:
- sst/opencode `packages/opencode/src/provider/transform.ts` (`applyCaching()`) — reference 2-system + last-2-message caching for Anthropic.
- aider-AI/aider `--cache-prompts` flag.
- cline/cline RFC discussions (#9892, #5092).
- OpenHands `codeact_agent.py` + Issue #6858.
- openai/codex (Rust) — Responses API caching.
