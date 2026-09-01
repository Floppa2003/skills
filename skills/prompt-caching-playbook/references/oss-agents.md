# Open-source agents — cache strategies, reverse-engineered

The fastest way to learn cache-aware prompt construction is to read the code of OSS agents that ship to thousands of developers. Reference implementations below, ordered by how instructive each is.

## sst/opencode — the reference implementation

**Most instructive cache architecture in OSS.** Used in production by SST's user base.

Pipeline (`packages/opencode/src/session/`):
1. `SessionPrompt.prompt()` accepts `PromptInput`.
2. `SessionPrompt.loop()` runs the main state machine.
3. Before sending: `ProviderTransform.applyCaching()` injects cache markers.

### `applyCaching()` strategy (`transform.ts:118–158, 192–205`)

For Anthropic-routed providers:

- **Coalesces all system prompt components into exactly 2 system messages** to align with Anthropic cache boundaries.
- **First 2 system messages are marked `cache_control`** — this is the static prefix (system + AGENTS.md/CLAUDE.md custom instructions + environment).
- **Last 2 messages in the messages array are marked `cache_control`** — sliding points for multi-turn caching (typically: last assistant + last user).

OpenCode uses **up to 4 breakpoints** exactly as Anthropic recommends: 2 for static (tools+system) + 2 for sliding history. This is the reference implementation.

### Environment block (`SystemPrompt.environment()`)

```
<env>
Working directory: {Instance.directory}
Is directory a git repo: {yes|no}
Platform: {process.platform}
Today's date: {date}
</env>
<project>
{Ripgrep.tree() output — up to 200 lines}
</project>
```

This is **dynamic content**, and OpenCode places it in a **separate system message AFTER the static prompt** — i.e., after the cache breakpoint. So a date or cwd change doesn't break the cache.

### Known issue — Anthropic via OpenRouter (Issue #1245)

`cache_control` doesn't propagate correctly through OpenRouter, so history doesn't get sliding breakpoints — long sessions become "order of magnitude more expensive than Anthropic direct." Production recommendation: **avoid OpenRouter for Anthropic if cache matters**.

## Aider

- Flag `--cache-prompts` enables caching. Uses LiteLLM to translate `cache_control` into Bedrock/Vertex format.
- Repo map (1024–4096 tokens) automatically lands in the cacheable prefix.
- Known regression in 0.72.1 (Jan 2026): broke Vertex AI caching due to outdated `anthropic-beta: prompt-caching-2024-07-31` header — caching is now GA and the beta header isn't needed. Upgrade required on pinned versions.
- Direct warning in aider docs: *"Due to limitations in the provider APIs, caching statistics and costs are not available when streaming responses."* For cache-debug sessions, disable streaming.

## Cline / Roo Code / Continue

### Cline
Caching works only with **direct Anthropic API key** — not with subscription-based Claude Code providers (per Anthropic policy changes in Jan 2026, RFC #9892 still in discussion). System prompt is set at **spawn time** — if it changes (mode switch, MCP add/remove), the process restarts and cache busts. Cline marks initial instructions with `cache_control`; subsequent requests send only the user prompt + cache reference.

### Roo Code (fork of Cline)
Same approach. Removed Claude Code provider support after Anthropic's Jan 2026 policy changes.

### Continue (continue.dev)
VSCode extension supporting Anthropic, OpenAI, Google, local models. Its cache layer is simpler: for Anthropic, it applies `cache_control` to system prompt and context blocks via standard LiteLLM-style mapping. No 4-breakpoint sliding strategy like OpenCode, and in practice hit rate is more modest (60–80% vs OpenCode's 90%+). Public roadmap includes cache-aware compaction improvements, not yet released as of early 2026.

## OpenHands (formerly OpenDevin)

- Cache breakpoints marked in `codeact_agent.py` → `llm.py`.
- Issue #6858 (Feb 2025) simplified the implementation: *"Anthropic API only needs the user to set ONE cache marker to write, and then will always hit that one even though, in subsequent requests, the prefix grows."*
- Stateless request handling for ZDR compliance — but this conflicts with stateful caching, requiring workarounds.

## OpenAI Codex CLI (Rust, open source)

- Open source since April 2025. ZenML LLMOps Database describes "strategic prompt caching optimization to achieve linear rather than quadratic performance."
- Supports persistent multi-turn without process restart (via `previous_response_id` on Responses API).
- AGENTS.md as the stable prefix source (analogous to CLAUDE.md).
- **Limitation:** uses Responses API with `store: true`, making it **incompatible with organizations that have ZDR enabled**.

## Claude Code — what's publicly known

Not open source, but Anthropic engineers and community traces give a clear picture:

- **Production cache hit rate: 92%.** The team **declares a SEV** if hit rate drops.
- Layout: System prompt (~4K tokens) → Tool definitions (~12K tokens) → CLAUDE.md → conversation history → new user message.
- **Warmer calls** at session start: Claude Code makes 4 "no-op" calls to prime the cache for subagents (Extract Bash Command, summarization agent, etc.). LMCache blog captured this in trace analysis showing **92% prefix reuse** in production traces.
- **`CLAUDE_CODE_DISABLE_GIT_INSTRUCTIONS=1`** — flag that removes live `git status` from the system prompt (changes every edit, invalidates cache). Saves ~1800 tokens per call and stabilizes system prompt. Community-validated: 18 tokens cache creation across git changes with the flag vs thousands without.

## Cursor — what's known

Cursor is proprietary; **no public information on exact prompt structure**. From indirect data (leaked system prompts on reddit/HN 2024–2025, community reverse-engineering via MITM proxies):

- Cursor uses Anthropic prompt caching when on Claude (visible from `cache_read` tokens in intercepted requests).
- System prompt is stable per product version (~8–15K tokens by various estimates), including large blocks on tool use, code editing conventions, and project rules.
- AGENTS.md / `.cursorrules` injected as a stable block after the core system prompt.
- Unlike OpenCode, Cursor runs multi-level orchestration (apply model, tab autocomplete, chat) — each model has its own cacheable prefix. No public hit-rate figures, but reverse-engineering suggests chat mode achieves ~80–90%.

Use Cursor as a "black-box reference," not a blueprint.

## Production hit-rate cheat sheet

| Agent | Hit rate (production) |
|---|---|
| Claude Code (Anthropic internal) | 92% average, 96% good session, 99.5% (Max plan + warmer + 1h TTL on 61-hour session) |
| OpenCode + Anthropic direct | 80–90% |
| Cline + Anthropic direct | ~90% |
| Cline routed via OpenRouter→Anthropic | Flat baseline, doesn't grow with session length |
| Continue (VSCode) | 60–80% |
| Cursor (chat mode, RE'd) | ~80–90% |
| Aider with `--cache-prompts` | varies; 70–85% in healthy sessions |

## Hermes — clarification

"Hermes" in LLM context typically means NousResearch's Hermes family (open-weight fine-tunes). It's **a model family, not an agent framework.** If a user mentions "Hermes" and means a specific agent framework, ask for clarification — the term has been overloaded in some internal/proprietary projects. For self-hosted Hermes models, see `references/self-hosted.md`.
