# freelance-timer

A [Claude Code](https://claude.com/claude-code) skill for freelancers who bill by the hour. It keeps an honest ledger of what each Claude session cost, per client and project, so you can build invoices from it.

- Asks which client and project a session is for, and whether it is billable.
- Logs elapsed time, estimated tokens and effort on every prompt. Gaps over 15 minutes count as you being away.
- Asks whether the previous work was billable whenever the topic changes, instead of guessing.
- Per-project hourly rate and currency. Currencies are never converted or summed: totals are listed per currency.
- Extra expenses (domain renewals, licences) can be logged next to the hours.
- Generates an HTML dashboard: client | project | rate | billable | hours | cost | total cost | additionals | notes.

## Install

Copy the skill folder into your Claude Code skills directory:

```bash
git clone https://github.com/<you>/freelance-timer-skill.git
cp -R freelance-timer-skill/.claude/skills/freelance-timer ~/.claude/skills/
```

Requires Python 3 (standard library only). Data lives in `~/.claude/freelance-timer/` (override with `FT_HOME`).

To have Claude run it at the start of every session, add a `SessionStart` hook to `~/.claude/settings.json` that tells Claude to invoke the skill (merge it into any existing `hooks` block):

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "echo '{\"hookSpecificOutput\":{\"hookEventName\":\"SessionStart\",\"additionalContext\":\"FREELANCE TIMER: Before doing anything else in this session, invoke the freelance-timer skill (Skill tool, skill name freelance-timer). Ask which client/project this session is for and whether it is billable, then follow the skill for per-prompt tracking.\"}}'",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

## Usage

Just work normally; the skill drives `scripts/ft.py` for you. Useful things to say:

- "show me the dashboard" opens `~/.claude/freelance-timer/dashboard.html`.
- "how long have we been at this" shows the open interaction.
- "log an extra of 12.50 EUR for a domain renewal".

You can also call the script directly:

```bash
python3 scripts/ft.py projects
python3 scripts/ft.py setup --client Acme --project website --rate 40 --currency USD --billable yes
python3 scripts/ft.py begin --client Acme --project website --billable yes   # prints a session id
python3 scripts/ft.py tick  --session ID --topic "fix login" --tokens 1200 --effort medium
python3 scripts/ft.py close --session ID --billable yes --note "login fix"
python3 scripts/ft.py end   --session ID
python3 scripts/ft.py dashboard
```

Each `begin` creates its own state, so several sessions in one directory do not overwrite each other. `begin` refuses to start while an earlier session left an interaction open, so unbilled time is never silently dropped.

## Limits

Token counts are estimates (Claude cannot see exact usage), and amounts are only as good as the billable flags you confirm.

## License

[MIT](LICENSE)
