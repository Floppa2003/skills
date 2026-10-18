---
name: prompt-caching-playbook
description: Practical playbook for maximizing prompt cache hit rate and minimizing token spend on LLM/agentic systems (Anthropic, OpenAI, Google Gemini, self-hosted vLLM). Covers prompt structure rules, multi-turn cache breakpoint placement, tool definition stability, dynamic content handling, TTL choice, multi-tenant isolation, and known anti-patterns. Distilled from provider docs, the "Don't Break the Cache" arxiv paper, and OSS agents (OpenCode, Aider, Cline, Claude Code). Use whenever the user designs, audits, or debugs the prompt/message structure of an LLM-powered system — chat agents, RAG pipelines, coding agents, batch eval jobs, multi-tenant SaaS — or asks about cache hit rate, cache_control, prompt_cache_key, Context Caching API, cache TTL, cost optimization, "why is my LLM bill so high", "почему API LLM дорого", "как уменьшить токены", "cache miss", "kv-cache", "prefix matching", "static prefix dynamic suffix", or any phrasing about reusing prompt prefixes across requests.
---

# Prompt Caching Playbook for Production LLM/Agentic Systems

A practical playbook for structuring prompts and messages to reuse the KV-cache. Measure complete-task cost and latency against a baseline; savings depend on the model, workload, cache writes and reads.

This skill covers **Anthropic Claude, OpenAI GPT/o-series, Google Gemini, and self-hosted vLLM**. Stable prefixes help across providers, but activation, retention, accounting and isolation differ by model generation.

## How to apply

1. **Diagnose first.** Look at the user's existing prompt structure or system architecture before suggesting changes. Static-vs-dynamic content placement and tool definition stability are the two highest-leverage variables — check those before discussing TTL or breakpoint count.
2. **Preserve reusable prefixes.** Keep stable content before changing content where the API permits, without changing instruction authority or required request structure. Place explicit endpoints at reusable boundaries.
3. **Name what NOT to do.** Use the anti-patterns in §6 as diagnostic hypotheses, then check them against the user's traces.
4. **Quantify the win.** Estimate savings only with stated workload assumptions and applicable rates; otherwise report savings as unknown.
5. **Recommend a monitoring loop.** Cache hit rate must be logged per-request and dashboarded per-session, per-tenant. Without observability, regressions are invisible until the next billing cycle.

## TL;DR — the rules that matter

1. **Static prefix → dynamic suffix.** Keep tools, stable instructions, reused documents and unchanged history before per-request updates where the API permits. Separate session-stable settings from changing environment data; mark reusable endpoints.
2. **Multi-turn:** previous user and assistant messages stay in place (append-only). New user message appended at the end. Cache breakpoint slides forward each turn.
3. **Keep tool definitions stable.** Replacing or reordering an earlier tool list can invalidate following content. Where supported, append-only tool discovery/updates can preserve the earlier prefix; changing callability need not require rewriting definitions.
4. **Min thresholds:** check the model's current documentation. OpenAI GPT-5.6+ requires at least 1024 visible input tokens; earlier models vary with model and request settings. Other providers also have model-specific minima.
5. **Cache pricing:** use the selected model's current read/write rates; see provider references. Anthropic 5min/1h writes cost 1.25×/2×; read discounts and Google explicit storage fees are model-specific.
6. **TTL choice:** OpenAI GPT-5.6+ supports only `30m` via `prompt_cache_options.ttl`; older models use different retention options. Anthropic offers 5min or 1h. Verify the model before choosing.
7. **Anti-patterns that kill the cache:** timestamps/UUIDs at start of system prompt, live `git status` in every prompt, middleware injecting trace IDs, reordering tools, switching models mid-session, aggressive history reformatting, inserting new or rewritten tool results before stable content. Unchanged historical tool results can be reused.

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

Prefix reuse requires an exact match of the provider's cacheable representation, including relevant tokens, tools, media and settings. Keep stable content unchanged; an earlier change can invalidate the following prefix. Matching bytes alone does not prove a hit.

Conceptual reuse order; respect the API's role and serialization rules:

```
[1] Tool definitions          ← most stable, cached first (part of prefix)
[2] System prompt — static    ← role, style, conventions, AGENTS.md/rules
[3] Session-stable settings   ← only values unchanged during intended reuse
[4] Long context / RAG        ← documents, codebase chunks (if reused)
[5] Conversation history      ← user/assistant turns, append-only
[6] Per-request updates       ← changing environment/context, preserving authority
[7] New user message          ← latest request
```

An explicit **cache breakpoint** requests a reusable prefix ending at that block; put it after stable content. Anthropic uses `cache_control`; OpenAI GPT-5.6+ supports explicit `prompt_cache_breakpoint` as well as implicit caching. Google supports implicit and explicit caching with different APIs.

### Canonical system prompt template

Blocks A-D form the static prefix. Send changing Block E after reusable history as a separate context/developer input where supported. If the API requires it earlier, expect reuse to stop there rather than claiming later history remains cacheable.

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

With eligible sliding breakpoints and matching, unexpired writes:
- Turn 2 can reuse the prefix through `user_1` written by turn 1, then write the extended input through `user_2`.
- Turn 3 can reuse the prefix through `user_2`, then write through `user_3`.
Do not count a generated assistant response as already present in the preceding request's prompt-cache write.

**Provider mechanics:**
- **Anthropic** — top-level `cache_control: {"type":"ephemeral"}` automatically applies the breakpoint to the last cacheable block and advances it. Or place explicit `cache_control` on the last user message manually (up to 4 breakpoints).
- **OpenAI** — GPT-5.6+ supports implicit and explicit caching; earlier models are automatic-only. Preserve unchanged history and tool results. See `references/openai.md` for generation-specific request fields.
- **Google Gemini** — implicit caching is automatic. Explicit caches can include tools and tool configuration at creation; do not override cached settings in a generation request. See `references/gemini.md`.

### Compaction / history truncation

Compaction can reduce prefix reuse because it rewrites history. Compare complete-task cost and quality: fewer input tokens may outweigh a lower hit rate.

Two strategies:
1. **Make the summary itself stable.** Subsequent turns build on it. Reuse can resume after an eligible write when later requests match an available endpoint; verify recovery in usage telemetry.
2. **Pruning, not summarizing.** Drop oldest tool outputs while keeping the message structure intact. Some agents (OpenHands, OpenCode) protect the most recent N tokens and mark older tool outputs as "compacted" without rewriting them.

---

## 3. Provider-specific mechanics

Compressed cheat sheet. For full mechanics, read the relevant reference file.

| | **Anthropic** | **OpenAI** | **Google Gemini** | **Self-hosted (vLLM)** |
|---|---|---|---|---|
| Activation | Explicit `cache_control` or top-level auto | GPT-5.6+: implicit/explicit via `prompt_cache_options.mode`; older: automatic | Implicit auto + explicit Context Caching API | `--enable-prefix-caching` (on by default v0.5+) |
| Min prefix | 1024 (Sonnet/Opus); 2048+ (Haiku, newer Opus/Haiku) | GPT-5.6+: 1024 visible input; older: model/settings-specific | 1024–4096 depending on model | None (any prefix) |
| Cache hit cost | Model-specific; see current pricing | Model-specific; see `references/openai.md` | Model-specific; see current pricing | Free (your GPU) |
| Cache write cost | 1.25× (5min) / 2× (1h) | GPT-5.6+: 1.25×; older: no separate write charge | Free for implicit; storage fee for explicit | Free |
| TTL | 5min (default) or 1h (Opus 4.5+, Sonnet 4.5+, Haiku 4.5+) | GPT-5.6+: `prompt_cache_options.ttl="30m"`; older: model-specific `prompt_cache_retention` | 5min implicit / configurable explicit (default 60min) | LRU eviction by GPU memory |
| Multi-tenant key | Hosting-specific boundary; see `references/anthropic.md` | Optional `prompt_cache_key`; verify isolation policy | Verify project and application-tenant boundaries | `cache_salt` parameter |
| Response field | `cache_read_input_tokens`, `cache_creation_input_tokens` | Responses: `input_tokens_details.cached_tokens`, `.cache_write_tokens` | `usage_metadata.cached_content_token_count` | varies |
| Max breakpoints | 4 explicit | GPT-5.6+: 4 writes total; implicit uses one; older: auto only | N/A (auto) | N/A |
| Hierarchy | Tools → System → Messages (changing higher invalidates lower) | Prefix identity and eligible endpoints; supported append-only tool updates preserve earlier content | Provider serialization dependent | Engine dependent |

### TTL decision guide

- **OpenAI:** GPT-5.6+ has only `30m`; do not request older `24h` retention on these models. For earlier generations, inspect supported retention before tuning.
- **Active conversational agent (>1 req per 5min):** default 5min on Anthropic, refreshed on hits.
- **Code review / sporadic / batch workloads:** consider Anthropic 1h when reuse occurs within it. Neither 1h nor 30m covers a nightly gap. Compare write costs against measured reads.
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
    "input_tokens_new": ...,         # ordinary input, excluding cache writes and reads
    "cache_read_tokens": ...,
    "cache_write_tokens": ...,       # provider-reported; unknown is not zero
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
1. **Hit rate over time per session.** Compare with a workload-specific baseline. Falls can reflect prefix mutation, new content, expiration or routing; inspect traces before assigning a cause.
2. **Hit rate per tenant/segment.** Outliers reveal poorly-structured per-tenant prefixes.
3. **Unique `system_prompt_hash` count per day.** If you logically have "v1" but see 50 distinct hashes, an invisible mutator (analytics injector, trace ID middleware, plugin) is corrupting the prefix.
4. **Cost split: new input / cache read / cache write / output.** Ratio of write to read should drop fast in active sessions.

Calibrate alert thresholds against the workload's expected reusable fraction and observed variability. Investigate sustained unexpected misses on eligible matching prefixes; check mutations, expiry, endpoint alignment and routing before attributing a provider bug.

---

## 5. Cost math — worked examples

Use disjoint ordinary-input, cache-write, cache-read and output token counts:
`cost = (ordinary * input_rate + writes * write_rate + reads * read_rate + output * output_rate) / 1_000_000`.
Normalize provider usage semantics first; never count a cache write again as ordinary input. Include retries, failures, child agents, verification and compaction across the complete task. Missing accounting stays unknown; subscription token usage is not dollar billing. Storage and other provider charges are separate.

All rates below are illustrative, not current price quotations. Hit fractions are workload assumptions, not measured effects of a prompt layout.

### Example A: 10K-token system prompt, 1M requests/month, Claude Sonnet-class model
Base input $3/M, cache write 5min $3.75/M, cache read $0.30/M.

1M requests × 10K tokens = 10B tokens. Every miss writes the whole prefix; every hit reads it. With hit fraction `h`, cost is `10_000 * ((1-h) * 3.75 + h * 0.30)`. The no-cache control uses the $3 rate instead.

| Scenario | Hit rate | Monthly input cost |
|---|---|---|
| No caching | 0% | **$30,000** |
| Assumed caching workload | 30% | $27,150 |
| Assumed caching workload | 80% | $9,900 |
| Assumed caching workload | 92% | $5,760 |

**About 5.21× lower input cost at 92% hits than without caching**, under these assumptions. Output cost unchanged. Multi-turn session estimates additionally require per-turn token counts and session frequency.

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
| 1 | Changing timestamp near the start of system prompt | Invalidates following content; any eligible earlier endpoint can still be reused |
| 2 | Changing session ID / request UUID before reusable content | Invalidates from the changed position onward, not every earlier prefix |
| 3 | Live `git status` / file listing before reusable content | Edits invalidate the following portion |
| 4 | Middleware injecting trace ID / analytics token into system | Invisible mutator — hardest to find |
| 5 | Reorder an earlier tool-definition list | Invalidates content from the changed position onward |
| 6 | Replace an earlier tool list mid-session | Same; prefer supported append-only updates when appropriate |
| 7 | Switching model mid-session | Cache is per-model — cold start on new |
| 8 | Aggressive summarization/compaction every N turns | Each rewrite breaks byte equality |
| 9 | Reformatting history (case, whitespace, JSON re-serialization) | Two-letter change = thousands of tokens missed (empirically) |
| 10 | Streaming response with no usage telemetry | You lose visibility into cache stats |
| 11 | Anthropic routed through OpenRouter without sticky routing | Hit rate stays flat regardless of session length |
| 12 | New or rewritten tool results inserted before stable content | Changes invalidate following content; unchanged historical results can be cached |
| 13 | Overriding cached Gemini tools/system settings in a generation request | Configure them at cache creation instead |
| 14 | Older OpenAI models: high traffic on one prefix/key (around 15 RPM) | Overflow may reduce reuse; this is not a minimum rate. GPT-5.6+ keys serve separate accounting |
| 15 | `cache_control` breakpoint placed on a block that *changes* | Pay for write every time, never read |

Inspect **#4 (middleware)** for trace IDs or other changing prefix content. Quantify any impact using actual misses, write/read rates and task totals; middleware presence alone does not establish a cost multiplier.

---

## 7. Multi-tenant cache isolation

Verify the provider, model, organization and tenancy policy before asserting isolation or ZDR compatibility. Exact prefix matching alone does not rule out cache-hit probing. Do not weaken tenant isolation to improve hit rates.

- **OpenAI GPT-5.6+:** optional tenant-scoped `prompt_cache_key` separates cache accounting and can help prevent probing of another tenant's hits. It is not a low-traffic routing requirement. Cached tensors may use encrypted GPU-local storage; do not describe all caches as RAM-only or automatically ZDR-compatible.
- **Anthropic / Google:** confirm current organization, workspace/project, hosting and retention boundaries for the selected API.
- **Self-hosted:** verify the engine's tenant separation mechanism (such as vLLM `cache_salt`) and storage lifecycle.

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
    tools[-1] = {**tools[-1], "cache_control": {"type": "ephemeral", "ttl": "1h"}}

    # Keep authoritative instructions stable; environment values below are data.
    system = [
        {"type": "text", "text": STATIC_SYSTEM,
         "cache_control": {"type": "ephemeral", "ttl": "1h"}},
    ]

    # Remove old sliding markers from outgoing copies, preserving historical data.
    messages = []
    for message in history:
        content = message["content"]
        if isinstance(content, list):  # API content is a string or a block list.
            content = [{k: v for k, v in block.items() if k != "cache_control"}
                       for block in content]
        messages.append({**message, "content": content})
    messages.append({
        "role": "user",
        "content": [{
            "type": "text",
            "text": f"<env>\ndate: {dynamic_env['date']}\ncwd: {dynamic_env['cwd']}\n</env>",
        }, {
            "type": "text", "text": new_user_msg,
            "cache_control": {"type": "ephemeral"},  # sliding BP
        }],
    })

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

Preserve historical text and environment values; only the outgoing cache markers move. Do not regenerate earlier environment blocks or mutate the stored history.

### Older OpenAI model (automatic + cache key)

Legacy illustration only. For GPT-5.6+ Responses syntax, modes and usage accounting, use `references/openai.md`.

```python
from openai import OpenAI
client = OpenAI()

def call_agent(segment: str, messages: list):
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=messages,
        # Stable key within the permitted isolation boundary; no minimum RPM.
        prompt_cache_key=f"agent-prod-v1-{segment}",
    )
    cached = response.usage.prompt_tokens_details.cached_tokens
    total = response.usage.prompt_tokens
    return response, cached / total
```

### Google-style (implicit, with tools — watch for known caveats)

```python
# Pseudocode — actual SDK varies; the structural rule is what matters.
def call_with_implicit(system: str, history: list, new_msg: str, tools=None):
    """Implicit caching example; explicit caches can also contain tools.
    Monitor observed cache usage for the selected model and SDK."""
    response = generate_content(
        model=MODEL,
        system_instruction=system,            # stable, at start
        contents=history + [new_msg],
        tools=tools or [],
        # Ensure system + history >= model's min threshold (1024–4096 tokens)
    )
    cached = response.usage_metadata.cached_content_token_count  # missing stays unknown
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
6. [ ] Compaction policy is justified by measured complete-task cost and quality; keep the resulting prefix stable when practical.
7. [ ] Model is **not switched** mid-session.
8. [ ] Anthropic: `cache_control` present on at least one block (or top-level auto).
9. [ ] OpenAI: generation-specific mode, TTL, usage fields and rates verified; optional key follows isolation/accounting needs, not a minimum RPM rule.
10. [ ] Google: `cached_content_token_count > 0` verified in production traces (especially with tools).
11. [ ] Dashboard shows hit rate per session, p50/p95 TTFT, cost split.
12. [ ] Alert thresholds calibrated against the workload's baseline, reusable fraction and variability.
13. [ ] Middleware/plugins audited for injection into system prompt.
14. [ ] If using LiteLLM/OpenRouter/proxy — sticky routing verified, otherwise prefer direct provider for cache-heavy workloads.

---

## Reference files

For deeper mechanics on specific topics, load the corresponding file from `references/`:

- `references/anthropic.md` — full Anthropic mechanics: 4-breakpoint placement, automatic vs explicit modes, 1h vs 5min TTL break-even math, hierarchy of invalidation, response usage parsing, Bedrock/Vertex caveats.
- `references/openai.md` — GPT-5.6+ modes, breakpoints, TTL, usage and pricing; older-model routing/retention differences; isolation limits.
- `references/gemini.md` — implicit vs explicit Context Caching API, cache-time tool configuration, min thresholds per model family, storage billing.
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
