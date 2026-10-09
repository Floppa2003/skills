# Research Protocol

Use this reference for multi-source or recurring platform research. Keep materially different subjects or periods separate.

## Research Frame

Define the subject, required evidence, time range, language/region, requested platforms, and relevance criteria. Start from an existing user-provided or task-local prior run, verify freshness, and otherwise state that no prior corpus was available.

## Collection And Classification

1. Make a broad discovery pass using the subject and natural alternative formulations.
2. Make a gap-closing pass using missed platforms, platform-native search, alternative terminology, language variants, and bounded `site:` searches.
3. Label material as `Exact`, `Close analogue`, or `Background`.
4. Label evidence separately as official source, firsthand account, original recording, repost/mirror, educational/editorial material, or analyst inference.
5. Deduplicate by canonical source or underlying material. Keep mirrors and reposts as provenance notes rather than independent evidence.
6. Verify date, authorship, scope, current availability, and access before relying on a source. State missing context instead of filling it with inference.
7. Stop candidate expansion when no stated coverage gap can be addressed by a permitted route or the available task/tool budget is exhausted. Report the remaining gap.

## Reusable Retrieval

For recurring browser-backed collection, reuse an adequate approved tool or adapter first. When none covers the required retrieval, follow this method within the [route contract](route-contracts.md); observing a request grants no new access, transport, or tooling permission.

1. Observe the approved browser's traffic while it displays the required data. Select the request whose response matches that data, not an analytics beacon that merely echoes the input.
2. Compare requests under changed inputs; separate input parameters from constants and nonces/signatures. A changing value alone is not evidence of a parameter.
3. Build a parameterized read call preserving the method, body structure, and encoding. Use structural serializers for nested JSON, forms, and URLs, not blind string replacement. If replay requires unavailable session values or signatures, use an existing permitted route or report the gap; do not copy credentials or recreate access controls.
4. Check an input not used to build the call against the browser: identity, required fields, pagination/coverage, and semantic status. HTTP success or an empty response is not enough.
5. Keep one maintained adapter or task-local script with a sanitized request recipe, extraction rules, known limits, and its verification command/control. Do not retain credentials or raw captures. Diagnose drift before changing the recipe, then repeat the control; honor the contract's stop conditions rather than turning failures into empty results.

An HTTP function is usually sufficient. Use a CLI entry point when repeated runs need one; expose MCP only when agent-tool reuse warrants it. Do not require a universal operation format or a new server.

## Evidence Output

For each material, record the platform and canonical URL, author/channel, publication date, excerpt or timestamp, fit, evidence type, source scope, verification time, and limitation. Collect first and synthesize second; a source is not evidence for a conclusion until its context and date are checked.

## Search Coverage

For substantial research, state:

- Checked platforms and source types.
- Partial or unavailable access, indexing, date, or retrieval coverage.
- Exact, Close analogue, and Background findings.
- Changes since the prior run: newly found, updated, excluded, or deduplicated material.
