---
name: cognitive-toolkit
description: Evidence-based CBT and DBT intervention skills — guided thought records, opposite action, DEAR MAN roleplay, crisis skills with optional HRV biofeedback. Use when the user asks to work through a thought, cognitive distortion, difficult emotion, opposite action, or a thought record. Configurable therapeutic pushback.
---

# Cognitive Toolkit

Interactive CBT and DBT guided exercises with configurable therapeutic pushback and optional health data integration.

## Usage

Use ordinary-language requests:

- "Help me work through this" starts with a check-in and recommends a technique.
- "Guide me through a thought record" or "help me with opposite action" selects a technique directly.
- "Use firm pushback" changes the pushback level for this session.
- "Do not use health data" skips any optional health-data pull.

The slash forms remain Telegram aliases; see **Telegram Entry Points** below.

## How it works

1. Read `references/thought-record.md` — thought record protocol (ABC model, cognitive distortion taxonomy, reframe scaffold)
2. Read `references/opposite-action.md` — opposite action + DEAR MAN + TIPP crisis skills
3. Read `references/pushback-config.md` — pushback levels, triggers, and mid-session override commands
4. Read `references/health-integration.md` — HRV/sleep pull, biofeedback interpretation, skip logic

## Session Flow

**Without technique argument** (full flow):
1. Check-in — mood (0–10), brief situation summary
2. Recommend — match presenting issue to technique based on check-in
3. Load technique — read the relevant reference file
4. Protocol — run the full guided exercise
5. Close — summary, insight, one takeaway
6. Save — write the session to the confirmed output directory

**With technique argument** (direct jump):
1. Brief mood check (0–10, one line)
2. Load technique — read the relevant reference file
3. Protocol — run the full guided exercise
4. Close — summary, insight, one takeaway
5. Save — write the session to the confirmed output directory

## Available Techniques

| Command | Technique | Reference | Wave |
|---|---|---|---|
| `thought-record` | Thought Record (ABC + reframe) | `references/thought-record.md` | 1 |
| `opposite-action` | Opposite Action (DBT emotion regulation) | `references/opposite-action.md` | 1 |
| `dear-man` | DEAR MAN assertiveness roleplay | `references/opposite-action.md` | 2 |
| `tipp` | TIPP crisis/distress tolerance | `references/opposite-action.md` | 2 |
| `chain` | Chain Analysis (behavior chain) | `references/thought-record.md` | 3 |
| `activation` | Behavioral Activation (depression) | `references/thought-record.md` | 3 |
| `wise-mind` | Wise Mind (emotion vs. reason) | `references/opposite-action.md` | 3 |

## Pushback

See `references/pushback-config.md` for full configuration.

- Defaults loaded from `references/pushback-config.md` (default: `gentle`)
- Per-session override: the user asks for `gentle`, `moderate`, or `firm` pushback.
- Mid-session commands: `softer`, `harder`, `no pushback` adjust level in real time
- Pushback is Socratic, not confrontational — "What evidence supports that?" not "That's wrong"

## Health Data

See `references/health-integration.md` for full integration logic.

- Optional: pulled from health MCP if available at session start
- Surfaces HRV, sleep quality, resting HR as contextual framing only
- Skip silently if health data is unavailable or the user asks not to use it
- Never gate a session on health data — it's context, not gatekeeper

## Telegram Entry Points

| Command | Maps to |
|---|---|
| `/record` | `thought-record` |
| `/opposite` | `opposite-action` |
| `/dear` | `dear-man` |
| `/tipp` | `tipp` |
| `/checkin` | full check-in flow |
| `/wise` | `wise-mind` |
| `/settings` | adjust pushback level and health toggle |

## Anti-patterns

- NOT a diagnostic tool — never assess, label, or diagnose
- NOT a therapist replacement — this is a practice tool for between sessions
- Frame suggestions as "research suggests" not "you should"
- If user expresses emergency, suicidal ideation, or acute crisis: stop the technique immediately, acknowledge, and provide crisis resources (e.g., Telefonseelsorge 0800 111 0 111 in Germany, international directory at findahelpline.com)

## Session Output

Before saving a session, ask for and confirm an explicit output directory. Do not infer or create a personal vault path.

File name: `YYYYMMDD-[technique]-NN.md`

Format: frontmatter with date, technique, mood-before, mood-after + full session transcript.
