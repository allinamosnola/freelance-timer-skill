---
name: freelance-timer
description: Freelance time and cost tracking for every session. Run this at the very start of EVERY session, before anything else, to ask which client/project is being worked on and whether it is billable, then keep logging time, estimated tokens and effort on each prompt, and ask whether the previous piece of work was billable whenever the topic changes. Also use when the user asks for the dashboard, hours, costs, invoices, rates, "how much did I bill", or to log an additional expense.
---

# Freelance timer

The user is a freelancer who bills clients by the hour. This skill produces an honest ledger of what each session cost, per client and project, so invoices can be built from it. Accuracy matters more than speed: a wrong billable flag becomes a wrong invoice, which is why the topic-change check below asks instead of guessing.

All state is handled by `scripts/ft.py` (path relative to this skill; call it with `python3`). Data lives in `~/.claude/freelance-timer/`, one global place, so the dashboard can aggregate every client no matter which directory the session ran in. Never edit those files by hand.

## 1. Session start (before doing anything else)

1. Run `python3 scripts/ft.py projects` to list known projects and their rates.
2. Ask the user, in one message, which client and project this session is for (offer the known ones) and whether it is billable. If the answer is already in the opening message, skip the question and confirm in a sentence.
3. For a **new** project, ask for the hourly rate and currency now, then save it:
   `python3 scripts/ft.py setup --client C --project P --rate 40 --currency USD --billable yes`
   The rate is set once per project and reused; only ask again if the user wants to change it.
4. Open the session: `python3 scripts/ft.py begin --client C --project P --billable yes|no`

If the user says the session is not for client work at all, run `begin` with `--billable no` on a project named for what it is (e.g. client "internal") so the time is still visible.

## 2. After every prompt

Treat each user prompt as one tick, and do it before answering so elapsed time is measured up to this prompt:

1. Decide whether this prompt continues the **same task** as the open interaction (same goal, follow-up, correction, clarification) or starts a **different** one (new goal, different project, unrelated question). When unsure, treat a clear change of goal as different; a refinement as the same.
2. If it is different and an interaction is open: ask the user "Was the previous work (`<topic>`) billable?" and wait. Then close it:
   `python3 scripts/ft.py close --billable yes|no --note "short note" [--extra 12.5 --extra-note "domain renewal"]`
   Offer the extra/note fields only if relevant, don't interrogate. If the project itself changed, run `begin` for the new project after closing.
3. Record the prompt: `python3 scripts/ft.py tick --topic "short topic" --tokens N --effort low|medium|high`
   - `--tokens` is an estimate (about 4 characters per token across the prompt plus your reply, plus tool output you read). Claude cannot see exact usage, so say "estimated" whenever you report it.
   - `--effort` is your judgment of the work: low = quick answer, medium = normal coding, high = long multi-step or deep debugging.

Time is computed from timestamps between ticks, with gaps over 15 minutes counted as the user being away rather than working, so you never need to track time yourself.

## 3. End of session

When the user says they are done (or says goodbye), ask whether the final interaction is billable, run `close`, then `python3 scripts/ft.py end`. If the user just stops responding, the open interaction stays in the state file and is closed the next time `begin`/`tick` runs for that directory: ask about it then.

## 4. Dashboard

When asked, run `python3 scripts/ft.py dashboard`. It writes `~/.claude/freelance-timer/dashboard.html` and opens it. Columns: client | project | billable | hours | cost | total cost | additionals | notes. Cost = billable hours × rate; total cost = cost + additionals. Non-billable rows show hours but no cost. Summarise the footer totals in your reply.

`python3 scripts/ft.py status` shows the open interaction at any time; use it when asked "how long have we been at this".

## Notes

- Keep the bookkeeping quiet. One short line per tick at most, and nothing when the topic is unchanged, because the user came here to work, not to watch a timer.
- Several Claude sessions in the same directory share one state file; that is a known limitation.
