---
name: audit-instruction-system
description: Use this skill when auditing or optimizing a repository-level instruction system across AGENTS.md, documentation routers, prompt templates, skills, configuration, and prompt-rendering code. Check current model guidance, SSOT ownership, duplication, contradictions, terminology, Markdown structure, and example quality or anchoring; propose exact preservation-safe additions, replacements, moves, and deletions. Do not use it for an isolated prompt rewrite without a surrounding instruction system.
---

# Audit Instruction System

Audit the actual repository instruction system, not an isolated prompt or a precombined text dump. Default to a read-only audit; apply changes only when the user separately authorizes them.

## Establish authority

1. Read every applicable `AGENTS.md` and follow its instruction hierarchy. Search the audited root, its ancestor chain, and nested scopes within that root; do not scan sibling repositories. Distinguish active instructions from templates, generated copies, and packaged resources by tracing runtime reachability.
2. Apply the `Source inspection and search discipline` section from the applicable `AGENTS.md` to every task-defining source inspected during the audit.
3. Load the `agents-best-practices` skill as the harness-architecture reference:
   - Within that skill, always read `references/system-prompts-instructions.md`.
   - Within that skill, read `references/agent-legibility-feedback-loops.md` when documentation ownership, source-of-truth routing, or validation loops are in scope.
   - Read its other reference files only when the audited surface requires them, such as skills, planning, permissions, context, observability, or prompt caching.
4. Use the `openai-docs` skill to fetch the current official model-specific prompt guidance. Preserve a model explicitly named by the user; otherwise identify active models from configuration and prompt assembly. Ask when the applicable model is materially ambiguous. During a read-only audit, do not install or reconfigure documentation tooling; report unavailable guidance as a limitation.
5. Use supplemental official vendor guidance only for a concrete gap that the primary guidance does not cover. Do not perform an exhaustive vendor survey by default.

## Map the instruction system

Inventory each active layer and trace how it reaches the model:

- applicable `AGENTS.md` files and their scopes;
- documentation indexes or routers and the documents they assign ownership to;
- prompt templates for each active role or workflow phase;
- skills and their activation or interface contracts;
- model, tool, permission, and runtime configuration;
- code that selects, assembles, renders, or injects instructions;
- generated or captured prompts used to verify the effective result.

Record precedence, scope, semantic owner, references, and data-versus-instruction boundaries. Treat the user input or task prompt as task-defining input: flag clear conflicts, but do not propose rewriting it unless the user explicitly asks.

## Build the audit checklist

Derive a compact task-local checklist from the current official guidance and the mapped system. Check whether:

- information is decomposed by meaning and each semantic rule has one authoritative owner;
- cross-references summarize only what is needed locally instead of reproducing the owner text;
- no topic is partially owned by multiple files or instruction layers;
- precedence and behavior remain consistent across documentation, templates, configuration, and assembly code;
- stale or superseded instructions are updated or removed instead of retained as competing compatibility guidance;
- repeated instructions, examples, and tool descriptions can be removed without weakening required behavior;
- autonomy, approval, scope, evidence, success, and stopping boundaries are explicit at the layer that owns them;
- prompt-only guidance is not standing in for a mechanical harness invariant;
- examples encode a product requirement, measured failure, or behaviorally important boundary rather than accidental task specificity;
- examples make the desired behavior more salient than any anti-example and remain relevant and diverse enough not to imply an exhaustive menu or incidental pattern. Use a clearly labeled anti-example only to distinguish a real near-miss or ambiguity; minimize copyable wrong detail, pair it with the canonical behavior, and retain it only when representative evaluation supports its value;
- skill descriptions and contracts, when present, have representative should-trigger, should-not-trigger, near-miss, and output-quality cases;
- skill content respects progressive-disclosure ownership: the frontmatter description states what the skill does and when it should activate; the `SKILL.md` body contains the post-activation operating contract; references contain detailed knowledge; scripts contain repeatable implementation; assets contain reusable output materials; and `agents/openai.yaml` contains UI metadata and supported invocation/dependency configuration, not procedural instructions;
- terminology names the same object consistently across all layers;
- Markdown headings, lists, and prose reflect semantic hierarchy and improve navigation;
- authoring-history or meta-prompt commentary is absent while operational rationale that changes decisions is preserved;
- response and style instructions specify what must be retained, not only broad adjectives or brevity requests.

Do not repeat the full official guide in the report unless the user asks. Include only the checks relevant to the system under audit.

## Audit manually

For every separable addition or change, first ask: where does this system already discuss the topic, down to file, section, and paragraph? Read that owner and its neighboring context before proposing an edit there.

Use machine searches to find candidates, not to establish meaning, completeness, duplication, or absence. Manually inspect representative and behavior-critical content, follow cross-references, and compare source templates with rendered prompt assembly where available.

Prefer a surgical edit to the existing owner. Create a new section or file only when no coherent owner exists. Do not elevate a narrow example above peer requirements, turn task-specific details into global rules, or duplicate the same fix across layers.

## Report proposed edits

Explain recommendations from your own perspective: identify the exact phrase to add, replace, move, or delete and why that wording should more consistently produce desired behavior or prevent the observed failure.

For each finding, provide:

1. priority and location;
2. the semantic problem, including competing owners or precedence conflicts;
3. the exact proposed edit in `replace`, `insert after`, `move`, or `delete` form;
4. the expected behavioral effect;
5. the authoritative owner or reference after the edit;
6. a preservation note for any removed or condensed information.

Present the result in this order:

1. compact instruction-system map;
2. relevant current-guidance checklist;
3. findings ordered by behavioral impact;
4. preservation audit;
5. deliberate non-changes and unresolved semantic questions.

## Preserve behavior

Before completing the audit, account for every instruction proposed for removal or replacement: show where it remains, what supersedes it, or why removing it is intentional. Recheck that no useful hard constraint, approval boundary, success criterion, evidence rule, interface contract, or example correcting a measured gap has disappeared.

Re-read affected source and runtime paths, including effective prompt assembly where present. Confirm that proposed edits do not contradict one another, create a second owner, or remove information needed outside the edited section. If the user later approves implementation, apply only the approved edits, repeat this preservation pass, and rerun existing representative evals for changed skills, prompts, tools, or runtime behavior; if no such evals exist, report that validation gap.
