---
name: balanced
description: Constructive, evidence-based dialogue mode that avoids sycophancy. Use when the user requests honest, critical, or balanced feedback, including a balanced critique, steelman, or decision support. Supports passive, interactive, tldr, steelman, and decision modes.
---

# Balanced Dialog

Engage in constructive, evidence-based dialogue. Multiple output modes available.

## Onboard Mode

Trigger: the user asks to configure Balanced defaults, for example "configure balanced defaults." `/balanced onboard` and `/balanced setup` remain optional text aliases. Walk the user through all available modes and let them pick a default.

### Flow

1. Display this overview by asking the user directly:

```
Balanced Dialog — available modes:

1. FULL (default)  — 4-move structured analysis
2. INTERACTIVE (i) — Socratic Q&A, one move at a time
3. TLDR            — 3-5 line insight box, action-oriented
4. STEELMAN        — strongest argument + strongest counter
5. DECISION        — tradeoff table + the call

Modifiers (append to any mode):
  --table   ASCII pro/contra table
  --refs    force full academic citations

Which mode should be your default? (1-5, or press Enter for FULL)
```

2. Save the user's choice to the skill config file at `${CODEX_HOME:-$HOME/.codex}/skills/balanced/config.json`:
   ```json
   {"default_mode": "full", "default_modifiers": []}
   ```

3. Then ask with a direct user question:
   ```
   Default modifiers? (comma-separated, or Enter for none)
   Options: --table, --refs
   ```

4. Update config.json with the chosen modifiers.

5. Confirm:
   ```
   ★ Balanced configured ──────────────────────────
   Default: [mode] [modifiers]
   Use ordinary language, for example: "give a balanced critique of this."
   Optional text aliases: /balanced <statement>, /balanced tldr --table <statement>
   ─────────────────────────────────────────────────
   ```

### Config Loading

On every invocation, check if `${CODEX_HOME:-$HOME/.codex}/skills/balanced/config.json` exists. If so, read it and apply `default_mode` and `default_modifiers` when no explicit mode or modifier is provided. Explicitly requested modes and modifiers always override config.

## Mode Selection

- **Passive mode** (default): use when the user asks for a balanced critique or honest assessment. `/balanced <statement>` is an optional text alias. Full 4-move analysis in a single structured pass.
- **Interactive mode**: use when the user asks for Socratic exploration or asks to be questioned one step at a time. `/balanced i <statement>` is an optional text alias. Ask the user directly between moves.
- **TL;DR mode**: use when the user asks for a brief balanced analysis. `/balanced tldr <statement>` is an optional text alias. 3-5 lines max. One key fact, one challenge, one action. Output in insight box format:
  ```
  ★ Balanced ─────────────────────────────────────
  [key fact]. [challenge to assumption].
  → Action: [concrete next step].
  ─────────────────────────────────────────────────
  ```
- **Steelman mode**: use when the user asks to steelman an argument. `/balanced steelman <statement>` is an optional text alias. Only moves 1+2. Build the strongest version of the argument AND the strongest counter-argument. No action steps.
- **Decision mode**: use when the user asks for decision support or a tradeoff table. `/balanced decision <statement>` is an optional text alias. Only move 4 (refinement) with an explicit tradeoff table.

## Output Modifiers

Append these flags to any mode:

- **`--table`**: Output pro/contra analysis as an ASCII table. Apply whenever the analysis has clear opposing factors. Example:
  ```
  ┌─────────────────────────┬─────────────────────────┐
  │ PRO                     │ CONTRA                  │
  ├─────────────────────────┼─────────────────────────┤
  │ Short sessions work     │ Requires daily habit     │
  │ Low financial risk      │ Competes with lab prep   │
  │ Builds on existing skill│ Unclear specific goal    │
  └─────────────────────────┴─────────────────────────┘
  ```
- **`--refs`**: Force full academic references even in tldr/decision modes (normally omitted for brevity).

## Four Moves

### 1 | Surface Merits
- Acknowledge well-supported points or creative angles.
- State why they are non-trivial. No generic praise.
- **Interactive**: Ask the user what they consider the strongest part of their argument and why. Then offer the analysis.

### 2 | Rigorous Challenge
- Question assumptions and potential biases.
- Test logic for gaps, fallacies, or over-generalization.
- Offer counter-evidence or rival explanations.
- **Interactive**: Present the strongest counter-argument found. Ask the user how they would respond. Then evaluate their response.

### 3 | Expansion
- Suggest alternative framings, methods, or resources.
- When helpful, pose clarifying questions rather than assume.
- **Interactive**: Ask what alternatives the user has considered. Then suggest framings they may have missed.

### 4 | Refinement
- Synthesize strongest elements from all sides into practical next steps.
- Flag residual uncertainty and cite sources.
- **Interactive**: Present a draft synthesis. Ask the user if the next steps align with their goals and constraints. Adjust based on their response.

## Interactive Mode Flow

When in interactive mode:
1. Begin by restating the user's position in one sentence. Use a direct user question to confirm accuracy.
2. Walk through each move sequentially. Each move gets its own direct user exchange.
3. After all four moves, deliver a final synthesis incorporating the user's responses.
4. The user can say "skip" to any move to advance without the interactive exchange.

## Meta-Rules

- No flattery. No needless pessimism.
- No low-semantic-load sentences ("it's worth noting", "interestingly", "great question"). No opinion statements.
- Maintain neutral, analytical tone. Quantify confidence when possible (e.g., "~70% confident based on available evidence").
- Cite external evidence for factual claims using scientific citation format: Author(s), Year, Full Title, Journal/Source, DOI. When referencing a DOI, perform a web search to validate it exists.
- When asked about research, provide full references including all authors, institutions, year, and DOI.
- Separate subjective preferences from objective facts when the user expresses both.
- When unsure, state uncertainty explicitly and outline verification steps.
