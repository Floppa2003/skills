# Self-hosted inference (vLLM, SGLang, TGI)

If you self-host open-weight models (Llama, Qwen, Mistral, Hermes/Nous variants, Mixtral, etc.), prefix caching is your responsibility — and it's free.

## vLLM — automatic prefix caching

vLLM 0.5+ enables prefix caching by default (`--enable-prefix-caching`). Older versions need the flag explicitly. The mechanism:

- vLLM maintains a **radix tree** of KV-cache blocks in GPU memory.
- When a new request arrives, vLLM checks the prefix against the tree.
- Matching prefix blocks are reused — the model only computes forward pass on the unmatched suffix.
- LRU eviction when GPU memory pressure hits.

Throughput improvement on agentic workloads with stable system prompts: **14–24× higher throughput** vs naive setup (per vLLM benchmarks on shared-prefix workloads).

## `cache_salt` for per-tenant isolation

vLLM 0.5+ supports the `cache_salt` request parameter. When set, the salt is hashed into the prefix key, so two tenants' requests with identical content never reuse each other's cache blocks. Useful on shared GPU serving multiple SaaS tenants where compliance requires isolation.

```python
# Example: vLLM OpenAI-compatible API
response = client.chat.completions.create(
    model="qwen2.5-72b-instruct",
    messages=[...],
    extra_body={"cache_salt": f"tenant-{tenant_id}"},
)
```

## SGLang — RadixAttention

SGLang implements prefix caching as a first-class structural primitive ("RadixAttention"). Particularly strong for tree-structured prompts (e.g., branching agents where multiple "sub-agents" share a common parent prefix). If your workload has deep prompt trees rather than linear conversations, SGLang's throughput on prefix-heavy traffic outperforms vLLM in some benchmarks.

## TGI (Hugging Face Text Generation Inference)

TGI added prefix caching in mid-2024. Less aggressive than vLLM/SGLang by default — some workloads need manual tuning. Activate via `--enable-prefix-caching` flag.

## Min prefix and granularity

Unlike managed providers, self-hosted engines have **no minimum prefix size** — any shared prefix is cacheable. Block granularity is typically 16 tokens for vLLM, configurable. Smaller blocks = better cache hit rate but more bookkeeping overhead.

## Observability

vLLM exposes Prometheus metrics for cache stats:

- `vllm:gpu_prefix_cache_hit_rate` — gauge, current hit rate
- `vllm:gpu_prefix_cache_hits_total` — counter
- `vllm:gpu_prefix_cache_queries_total` — counter

Dashboard panel: hit rate per model + per tenant (if using `cache_salt`).

## When self-hosting wins vs managed providers

Self-hosting becomes economically viable when:
- Throughput is high enough to keep GPU utilization >60%.
- Prefix sharing is high (multi-tenant SaaS, agent fleets with similar system prompts).
- Latency requirements allow batching.

Below those thresholds, managed providers' prompt caching at 0.1–0.5× base price is hard to beat once you account for GPU rental, MLOps overhead, and update cadence.

## Hermes / NousResearch family

"Hermes" in LLM context usually refers to NousResearch's Hermes 2/3/4 — these are **fine-tuned open-weight models** (built on Llama/Mistral bases), not an agent framework. They don't have a separate prompt-caching API: caching is available only when hosted on infrastructure that supports it (vLLM with prefix caching, TGI, or managed providers like Together/Fireworks/OpenRouter that route to such infrastructure).

For self-hosted Hermes: vLLM with `--enable-prefix-caching` and optional `cache_salt` for per-tenant isolation.
