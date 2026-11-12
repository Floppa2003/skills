---
name: research-ops
description: Use when gathering or verifying external evidence for factual answers, comparisons, people/company enrichment, recommendations, or recurring research, including source-access and extracted-result checks and combining new evidence with supplied context.
metadata:
  origin: ECC
---

# Research Ops

This is the operator wrapper around the repo's research stack. It is not a replacement for `deep-research`, `exa-search`, or `market-research`; it tells you when and how to use them together.

## Skill Stack

Pull these ECC-native skills into the workflow when relevant:

- `exa-search` for fast current-web discovery
- `deep-research` for multi-source synthesis with citations
- `market-research` when the end result should be a recommendation or ranked decision
- `lead-intelligence` when the task is people/company targeting instead of generic research
- `knowledge-ops` when the result should be stored in durable context afterward

## Guardrails

- do not answer current questions from stale memory when fresh search is cheap
- separate:
  - sourced fact
  - user-provided evidence
  - inference
  - recommendation
- do not spin up a heavyweight research pass if the answer is already in local code or docs

## Source access and result verification

1. **Localize failures.** Distinguish source-side errors from retrieval,
   rendering, provider limits, authentication, and regional restrictions.
   Report the observed failure and its scope; keep unverified causes uncertain.
   A failed request or empty extract does not establish that the source is down
   or that no matching result exists.
2. **Recover within the permitted route.** Use the lightest available method
   that can verify the required information. Make bounded diagnostic attempts
   or use a permitted alternative that addresses the failure. Stop ineffective
   retries and follow the applicable access, authentication, and tool policies.
   Check whether a fallback covers the original question.
3. **Verify the actual result.** Check source or item identity, selected inputs,
   relevant scope, and required fields in the returned result. A successful
   request, landing page, snippet, or advertised starting value is insufficient
   when a conclusion depends on a specific offer or record. Confirm all required
   selections before reporting a complete result.
4. **Compare on the same basis.** Check decision-relevant units, quantity,
   period, currency, included components, mandatory charges, and conditions.
   Label estimates, partial totals, and unresolved differences explicitly.
5. **Bound conclusions by inspected evidence.** Retain canonical links,
   verification dates, material access limits, and collection coverage. A
   partial or failed search cannot establish absence across the whole source;
   distinguish retrieved content from content actually inspected.
6. **Generalize lessons at the narrowest valid level.** Keep shared rules here,
   domain procedures in domain skills, and confirmed source-specific exceptions
   beside the source. Record transient failures in the run record. Date and
   scope durable source notes, retain their evidence, and revalidate them before
   relying on them.

## Workflow

### 1. Start from what the user already gave you

Normalize any supplied material into:

- already-evidenced facts
- needs verification
- open questions

Do not restart the analysis from zero if the user already built part of the model.

### 2. Classify the ask

Choose the right lane before searching:

- quick factual answer
- comparison or decision memo
- lead/enrichment pass
- recurring monitoring candidate

### 3. Take the lightest useful evidence path first

- use `exa-search` for fast discovery
- escalate to `deep-research` when synthesis or multiple sources matter
- use `market-research` when the outcome should end in a recommendation
- hand off to `lead-intelligence` when the real ask is target ranking or warm-path discovery

### 4. Report with explicit evidence boundaries

For important claims, say whether they are:

- sourced facts
- user-supplied context
- inference
- recommendation

Freshness-sensitive answers should include concrete dates.

### 5. Decide whether the task should stay manual

If the user is likely to ask the same research question repeatedly, say so explicitly and recommend a monitoring or workflow layer instead of repeating the same manual search forever.

## Output Format

```text
QUESTION TYPE
- factual / comparison / enrichment / monitoring

EVIDENCE
- sourced facts
- user-provided context

INFERENCE
- what follows from the evidence

RECOMMENDATION
- answer or next move
- whether this should become a monitor
```

## Pitfalls

- do not mix inference into sourced facts without labeling it
- do not ignore user-provided evidence
- do not use a heavy research lane for a question local repo context can answer
- do not give freshness-sensitive answers without dates

## Verification

- important claims are labeled by evidence type
- freshness-sensitive outputs include dates
- the final recommendation matches the actual research mode used
