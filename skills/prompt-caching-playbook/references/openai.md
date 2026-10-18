# OpenAI prompt caching

Checked 2026-10-18 against the [official guide](https://developers.openai.com/api/docs/guides/prompt-caching). Check the selected model's current contract and prices before applying these rules.

## GPT-5.6 and later

- At least 1024 visible input tokens are required. Matching depends on the cacheable representation and eligible endpoints, not just shared text.
- `prompt_cache_options.mode` is `implicit` (automatic endpoint, with optional explicit markers) or `explicit` (only marked endpoints). Explicit-only without markers neither reads nor writes a cache.
- Mark a supported content block with `prompt_cache_breakpoint: {"mode": "explicit"}`. A request supports at most four cache writes; implicit caching uses one, leaving three explicit writes.
- `prompt_cache_options.ttl` currently supports only `30m`, a minimum lifetime refreshed on reuse, not a hard expiry. Do not substitute older `prompt_cache_retention` settings.
- Writes cost 1.25 times the ordinary input rate. Reads cost 0.1 times on most models in this group and 0.05 times on GPT-6.1 Sol; verify the selected model's current rates. Repeated misses can cost more than uncached input.
- `prompt_cache_key` is optional for separate customer accounting and can help prevent cross-user cache-hit probing. It is not required for efficient routing; there is no minimum-RPM requirement. Keep access isolation intact.

Place an explicit endpoint after shared static content when suffixes vary between requests. An implicit write through a varying suffix does not itself create a reusable endpoint at the earlier shared prefix. Keep unchanged conversation messages and tool results; append rather than rewrite. Preserve tools and settings affecting prefix identity.

## Responses API example

Request-body example, assuming `stable_context` meets the model's minimum. Check SDK support before translating it into a client call. Top-level `instructions` cannot carry a breakpoint; use a developer input block instead.

```python
request = {
    "model": "gpt-6-sol",
    "prompt_cache_options": {"mode": "explicit", "ttl": "30m"},
    "input": [
        {"role": "developer", "content": [{
            "type": "input_text",
            "text": stable_context,
            "prompt_cache_breakpoint": {"mode": "explicit"},
        }]},
        {"role": "user", "content": current_question},
    ],
}
```

For Responses usage, `input_tokens` includes reads and writes. Normalize into disjoint buckets before pricing:

```python
reads = usage["input_tokens_details"]["cached_tokens"]
writes = usage["input_tokens_details"]["cache_write_tokens"]
ordinary = usage["input_tokens"] - reads - writes
output = usage["output_tokens"]
cost = (ordinary * input_rate + writes * write_rate
        + reads * read_rate + output * output_rate) / 1_000_000
```

These fields must be reported by the selected API/model. Missing counts remain unknown, not zero. Aggregate all requests in the task, including failed attempts, children, verification and compaction. Account for any other billed categories separately. CLI/subscription usage alone does not establish dollar cost.

## Models before GPT-5.6

Caching is automatic, without explicit breakpoint control or a separate write charge. Read discounts and minimum lengths vary by model and request settings; do not extrapolate the historical 1024-token/128-increment rule to every model.

A stable `prompt_cache_key` helps route matching prefixes. High traffic around 15 requests/minute on the same prefix/key can overflow to other machines and reduce hits; low traffic is not an overflow trigger or a cache failure condition.

Supported models use `prompt_cache_retention` (`in_memory` or `24h`); GPT-5.5 supports only `24h`. Verify availability per model rather than treating 24h as universal. Older Chat Completions exposes reads in `usage.prompt_tokens_details.cached_tokens`; do not assume Responses and Chat Completions share field names.

Historical price illustration, not current GPT-6 pricing: 1M requests with 10K input tokens each, ordinary input $5/M, cache reads $2.50/M, 80% full-prefix hits and no separate write charge. No-cache cost is $50,000; cached cost is `10_000 * (0.2 * 5 + 0.8 * 2.5) = $30,000`, a 40% reduction. Output is additional.

## Retention and diagnostics

Cached tensors may use encrypted GPU-local storage. Do not promise RAM-only retention, universal ZDR eligibility or absence of probing. Verify the model, API and organization data-control policy.

Log actual model, mode, TTL, stable key when present, disjoint usage, latency and prefix/tool hashes. Investigate unexpected misses by checking endpoint alignment, minimum length, changed history/tools/settings and expiry. Compare complete-task cost and quality, not hit percentage alone: compaction can reduce total cost despite fewer cache hits.
