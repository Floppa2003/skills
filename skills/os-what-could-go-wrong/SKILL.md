---
name: os-what-could-go-wrong
description: >-
  Use when the user requests a premortem, asks what could go wrong with a
  decision, or needs a failure-risk review before a costly or hard-to-reverse
  commitment. Not for routine status, ordinary code review, or executing an
  already approved action without a request to reassess it.
---

# os-what-could-go-wrong

Assume it already failed, then work backwards to find out why - while there is
still time to change it. The attack runs in a fresh agent that had no part in
the decision, because an agent that helped shape one reviews it far too
gently: it defends its own reasoning, and it misses the thing that kills the
plan out of politeness.

Use this after a proposed choice is concrete enough to examine and before it
can no longer be taken back. No other OpenSteps skill is required. The review
is read-only: a risk assessment does not authorize implementation, a merge,
purchase, reminder, or any other external write.

## Language

Write in the language the user speaks in this session, detected from the
conversation. Names, figures and identifiers stay as they are. The agent you
dispatch cannot see this conversation and does not inherit the writing style,
so the language has to travel with the handover - see step 2.

## Step 1 - write down what is actually being decided

Find the decision first. Given as text or a document, that is it. Asked at the
end of a discussion, it is the decision the discussion arrived at, and say
which one you took it to be. If neither, ask which decision to attack.

Then fill every line, marking unavailable information as unknown. This is the
only decision context the fresh agent will see; include relevant source paths
or links so it can check material claims.

```
DECISION BRIEF
What will be done: three to seven sentences
What it is for: the problem it solves, and what success looks like, measured
  wherever it can be
The main moves: the money, the people, the systems, the dates
What is fixed: the constraints, plus the surrounding facts that matter
Who it lands on: who and what is affected if this goes wrong
What cannot be undone: which parts are one-way
When we would know: the date success or failure actually gets judged
What we know: facts from documents, data, the repository, past incidents,
  each with where it came from
What we are assuming: every gap nobody could close, written as an assumption
```

Close the gaps in this order, and stop as soon as a gap is closed.

1. **Look it up yourself.** Relevant documents, data, repository state,
   canonical project reports, and past incidents within the authorized scope.
2. **Ask, but earn the ask.** Only a gap where guessing wrong would change the
   verdict; explain the consequence and ask one precise question at a time.
3. **Keep unresolved gaps explicit.** Do not invent missing facts, dates,
   probabilities, or thresholds to fill the template. A proposed assumption
   needs an evidence-based rationale and a check that could falsify it. If a
   material gap remains, make the affected conclusion conditional or unresolved.

The brief states facts and open questions. It never makes the case for the
decision: a brief that argues gets a report that agrees.

## Step 2 - hand it to an agent that had no part in it

Pick the depth, say which in one line, and carry on; the user can change it at any point.

| Depth | When |
|---|---|
| **Full** | Hard to undo, or being wrong costs money, trust or data beyond one team |
| **Quick** | Reversible, and cheap to be wrong about, whoever it touches |

When in doubt, Full. The cost of a full look is a few minutes; the cost of a
quick look at a one-way door is the door.

Read the full [analysis prompt](references/premortem-prompt.md); resolve all
relative paths from this skill's directory. Use the runtime's native subagent
tool with conversation inheritance disabled (`fork_context=false` in Codex
when that parameter is available). Check the actual tool schema, not a guessed
tool name or a nested CLI command.

Dispatch one read-only agent. Send only the analysis prompt, `MODE: Full` or
`MODE: Quick`, `LANGUAGE: <the language above>`, and the factual brief with
source locations. Do not send the conversation, the author's reasoning, an
expected verdict, or an instruction to run this skill. The child must not
delegate. Wait for its actual result and close it when the runtime requires
explicit cleanup.

Claim independence only after a fresh-context dispatch succeeds and returns a
report. If the tool is unavailable, fails, or cannot isolate the context,
disclose that before any findings and label any same-context analysis a
non-independent self-review. Do not bypass sandbox restrictions or launch
nested agents through a shell. If independent review is a required gate, it
remains unmet; a self-review does not clear it.

## Step 3 - give it to the user straight

Check returned claims against the cited evidence and brief. Send material
errors back to the same reviewer for correction. Preserve the corrected
verdict, caveats, and substantiated risks; do not silently soften or drop them.

Lead with a compact decision summary: verdict, decisive risks, required fixes,
and unresolved evidence. Keep detailed cards in the requested document or the
project's canonical artifact location when a full report would overwhelm chat;
link the detail without hiding a decision-changing fact. Do not create reports
under a fixed home-directory path or introduce a second project status file.
State actionable next steps without a generic follow-up question. Execute
them only within the user's authorization.

## Hard rules

1. **Independent review requires a fresh agent.** An author self-review is
   not a substitute and must be labelled as described in step 2.
2. **No quota of risks.** Publish what has a real chain behind it and nothing
   else. Two well-evidenced risks beat six padded ones, and "only two
   survived" is a finding worth saying out loud.
3. **The verdict is decided last and printed first.** Never make the reader
   assemble it from the risks.
4. **Every area of the sweep is accounted for**, including the ones that
   produced nothing. An area nobody mentions and an area nobody checked look
   the same to the reader.
5. **A skipped section keeps its one line saying why.**
6. **A lease and a database migration get the same treatment.** This is not a
   technical review; the nine areas apply to both, and the money and people
   ones are where technical decisions usually actually fail.
7. **"The plan is sound" is a legitimate answer** once the attack has run. It
   is never a substitute for running one.

## Known gotchas

- **Name the evaluation horizon.** Use a documented date or milestone; if none
  exists, ask when material or mark it unknown. Do not invent a deadline.
- **The brief is where this is won or lost.** The fresh agent sees nothing else.
- **Fewer than three risks is often the right answer.** Keep the record of what
  was checked.
- **Keep cheap, reversible decisions proportionate.** An explicit request gets
  a Quick look. Skip only an unsolicited review, not the user's request.
- **"Try it small first" is not a soft no.** Test unknowns before money moves.
- **The user may go ahead against all of it.** Note it once, set the tripwires
  up if they want them, and do not re-argue the report.

The reasoning behind these is in [`references/why-these-rules.md`](references/why-these-rules.md).

## References

- Read [references/premortem-prompt.md](references/premortem-prompt.md) before
  the analysis; it defines the sweep, evidence contract, and risk cards.
- [references/01-office-lease.md](references/01-office-lease.md) is an optional
  fictional example, not evidence or a source of reusable numeric thresholds.
  Its month-6/month-12 interval is inconsistent; the example's calculations
  are not validated.
