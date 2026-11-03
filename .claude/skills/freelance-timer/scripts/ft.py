#!/usr/bin/env python3
"""Freelance timer: session state, ledger and dashboard.

Data lives in ~/.claude/freelance-timer/ (override with FT_HOME):
  config.json     projects and their hourly rates
  ledger.jsonl    one closed interaction per line (append-only)
  state/<id>.json the open session + interaction (id printed by `begin`, pass it as --session)
"""
import argparse, hashlib, html, json, os, re, secrets, sys, time, webbrowser
from datetime import datetime, timezone
from pathlib import Path

HOME = Path(os.environ.get("FT_HOME", Path.home() / ".claude" / "freelance-timer"))
CONFIG, LEDGER, STATE_DIR = HOME / "config.json", HOME / "ledger.jsonl", HOME / "state"
IDLE_CAP = 15 * 60  # a gap longer than this between prompts counts as away, not work
EFFORT = {"low": 1, "medium": 2, "high": 3}


def now():
    return time.time()


def cwd_id():
    return hashlib.sha1(os.getcwd().encode()).hexdigest()[:12]


def session_id(a):
    """Explicit --session / FT_SESSION wins; otherwise the legacy per-directory id."""
    sid = getattr(a, "session", None) or os.environ.get("FT_SESSION") or ""
    if sid and not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", sid):
        sys.exit(f"invalid session id {sid!r}")
    return sid


def state_path(a):
    return STATE_DIR / ((session_id(a) or cwd_id()) + ".json")


def open_here():
    """State files in this directory with an unclosed interaction whose session went quiet
    (a live session in the same directory ticks within IDLE_CAP and is left alone)."""
    found = []
    for p in sorted(STATE_DIR.glob("*.json")) if STATE_DIR.exists() else []:
        st = load(p, None)
        if (st and st.get("interaction") and now() - st["last_ts"] > IDLE_CAP
                and (st.get("cwd") == os.getcwd() or p.stem == cwd_id())):
            found.append((p, st))
    return found


def load(path, default):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


def key(client, project):
    return f"{client}/{project}"


def out(obj):
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def cmd_projects(a):
    out(load(CONFIG, {"projects": {}}))


def cmd_setup(a):
    cfg = load(CONFIG, {"projects": {}})
    cfg["projects"][key(a.client, a.project)] = {
        "client": a.client, "project": a.project, "rate": a.rate,
        "currency": a.currency, "billable": a.billable == "yes",
    }
    save(CONFIG, cfg)
    out(cfg["projects"][key(a.client, a.project)])


def cmd_begin(a):
    cfg = load(CONFIG, {"projects": {}})
    proj = cfg["projects"].get(key(a.client, a.project))
    if not proj:
        sys.exit(f"unknown project {key(a.client, a.project)}; run setup first")
    sid = session_id(a) or secrets.token_hex(4)
    a.session = sid
    mine = state_path(a)
    # an abandoned interaction is unbilled time: never overwrite it, make the caller close it
    stale = dict(open_here())
    own = load(mine, None)
    if own and own.get("interaction"):
        stale[mine] = own
    if stale and not a.discard:
        lines = [f"  session {p.stem if p.stem != cwd_id() else '(none: omit --session)'}: "
                 f"{key(s['client'], s['project'])}, topic '{s['interaction']['topic']}', "
                 f"{round(s['interaction']['seconds'] / 60)} min" for p, s in stale.items()]
        sys.exit("unclosed interaction(s) in this directory; ask whether each was billable, "
                 "run `close --billable yes|no [--session ID]` on it, then begin again "
                 "(or pass --discard to drop them):\n" + "\n".join(lines))
    for p in stale:
        p.unlink(missing_ok=True)
    st = {"session": sid, "cwd": os.getcwd(), "client": a.client, "project": a.project,
          "rate": proj["rate"], "currency": proj["currency"],
          "billable_default": a.billable == "yes", "last_ts": now(), "interaction": None}
    save(mine, st)
    out(st)


def cmd_tick(a):
    """Record one prompt. Adds elapsed time since the previous prompt (capped)."""
    st = load(state_path(a), None)
    if not st:
        sys.exit("no open session; run begin first")
    t = now()
    gap = min(t - st["last_ts"], IDLE_CAP)
    it = st["interaction"] or {"started": t, "seconds": 0.0, "tokens": 0,
                               "prompts": 0, "effort": 0, "topic": a.topic}
    # the gap before a prompt is the previous prompt's work (thinking + running),
    # so it belongs to the interaction already open; a brand-new one starts at 0
    if st["interaction"]:
        it["seconds"] += gap
    it["tokens"] += a.tokens
    it["prompts"] += 1
    it["effort"] += EFFORT[a.effort]
    st["interaction"], st["last_ts"] = it, t
    save(state_path(a), st)
    out({"interaction": it, "hours": round(it["seconds"] / 3600, 3)})


def cmd_close(a):
    """Finish the open interaction: bill it (or not) and append it to the ledger."""
    st = load(state_path(a), None)
    if not st or not st["interaction"]:
        sys.exit("no open interaction to close")
    t = now()
    it = st["interaction"]
    it["seconds"] += min(t - st["last_ts"], IDLE_CAP)  # tail: time to finish the last reply
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "client": st["client"], "project": st["project"],
        "billable": a.billable == "yes", "rate": st["rate"], "currency": st["currency"],
        "seconds": round(it["seconds"]), "tokens_est": it["tokens"],
        "prompts": it["prompts"], "effort_avg": round(it["effort"] / it["prompts"], 2),
        "topic": it["topic"], "additional": a.extra, "additional_note": a.extra_note,
        "additional_currency": (a.extra_currency or st["currency"]).upper(),
        "note": a.note,
    }
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    st["interaction"], st["last_ts"] = None, t
    save(state_path(a), st)
    out(entry)


def cmd_end(a):
    p = state_path(a)
    st = load(p, None)
    if st and st["interaction"]:
        sys.exit("an interaction is still open; close it first")
    p.unlink(missing_ok=True)
    print("session ended")


def cmd_status(a):
    st = load(state_path(a), None)
    if not st:
        print("no open session"); return
    it = st["interaction"]
    out({"project": key(st["client"], st["project"]), "rate": st["rate"],
         "open_interaction": it and {**it, "hours": round(it["seconds"] / 3600, 3)}})


def add_money(d, cur, v):
    if v:
        d[cur] = d.get(cur, 0.0) + v


def fmt(d, billable=True):
    """'95.00 USD + 10.00 EUR'; amounts of different currencies are never summed."""
    parts = [f"{v:,.2f} {c}" for c, v in sorted(d.items()) if v]
    return " + ".join(parts) if parts else ("0.00" if billable else "—")


def rows():
    agg = {}
    for line in LEDGER.read_text().splitlines() if LEDGER.exists() else []:
        e = json.loads(line)
        k = (e["client"], e["project"], e["billable"])
        r = agg.setdefault(k, {"seconds": 0, "tokens": 0, "cost": {}, "extra": {},
                               "rate": e["rate"], "currency": e["currency"], "notes": []})
        r["seconds"] += e["seconds"]
        r["tokens"] += e["tokens_est"]
        r["rate"], r["currency"] = e["rate"], e["currency"]
        if e["billable"]:
            add_money(r["cost"], e["currency"], e["seconds"] / 3600 * e["rate"])
        add_money(r["extra"], e.get("additional_currency") or e["currency"], e.get("additional") or 0)
        for n in (e.get("note"), e.get("additional_note")):
            if n and n not in r["notes"]:
                r["notes"].append(n)
    return agg


def cmd_dashboard(a):
    agg = rows()
    body, tot_h, tot_c, tot_x = [], {}, {}, {}
    for (client, project, billable), r in sorted(agg.items()):
        h = r["seconds"] / 3600
        total = dict(r["cost"])
        for c, v in r["extra"].items():
            add_money(total, c, v)
        if billable:
            add_money(tot_h, r["currency"], h)
            for c, v in r["cost"].items():
                add_money(tot_c, c, v)
            for c, v in r["extra"].items():
                add_money(tot_x, c, v)
        body.append(
            "<tr>" + "".join(f"<td{c}>{html.escape(str(v))}</td>" for v, c in [
                (client, ""), (project, ""),
                (f"{r['rate']:,.2f} {r['currency']}/h", ' class="n"'),
                ("billable" if billable else "non-billable", ' class="b"' if billable else ' class="nb"'),
                (f"{h:.2f}", ' class="n"'),
                (fmt(r["cost"], billable) if billable else "—", ' class="n"'),
                (fmt(total, billable) if billable else fmt(r["extra"], False), ' class="n"'),
                (fmt(r["extra"], billable), ' class="n"'),
                ("; ".join(r["notes"]), ' class="notes"'),
            ]) + "</tr>")
    # one footer row per currency; currencies are never summed together
    foot = []
    for c in sorted(set(tot_h) | set(tot_c) | set(tot_x)):
        cost, extra = tot_c.get(c, 0.0), tot_x.get(c, 0.0)
        foot.append(f'<tr><td colspan=3>Billable total ({html.escape(c)})<td><td class="n">{tot_h.get(c, 0.0):.2f}'
                    f'<td class="n">{cost:,.2f} {c}<td class="n">{cost + extra:,.2f} {c}'
                    f'<td class="n">{extra:,.2f} {c}<td></tr>')
    doc = f"""<!doctype html><meta charset="utf-8"><title>Freelance timer</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{{--bg:#fafaf9;--fg:#1c1917;--mut:#78716c;--line:#e7e5e4;--ok:#15803d;--nb:#a8a29e}}
@media(prefers-color-scheme:dark){{:root{{--bg:#1c1917;--fg:#f5f5f4;--mut:#a8a29e;--line:#44403c;--ok:#4ade80;--nb:#78716c}}}}
body{{background:var(--bg);color:var(--fg);font:15px system-ui,sans-serif;margin:0;padding:24px 16px}}
h1{{font-size:20px;margin:0 0 4px}}p{{color:var(--mut);margin:0 0 16px}}
.w{{overflow-x:auto}}table{{border-collapse:collapse;width:100%;min-width:820px}}
th,td{{padding:8px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}
th{{color:var(--mut);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.04em}}
.n{{text-align:right;font-variant-numeric:tabular-nums}}th.n{{text-align:right}}
.b{{color:var(--ok)}}.nb{{color:var(--nb)}}.notes{{color:var(--mut);max-width:320px}}
tfoot td{{font-weight:600;border-top:2px solid var(--line)}}
</style>
<h1>Freelance timer</h1><p>Generated {datetime.now():%Y-%m-%d %H:%M}. Cost = hours x rate (billable only); total = cost + additionals. Each currency is totalled separately. Tokens are estimates.</p>
<div class="w"><table><thead><tr><th>Client<th>Project<th class="n">Rate<th>Billable<th class="n">Hours<th class="n">Cost<th class="n">Total cost<th class="n">Additionals<th>Notes</tr></thead>
<tbody>{''.join(body) or '<tr><td colspan=9>No entries yet.</td></tr>'}</tbody>
<tfoot>{''.join(foot)}</tfoot></table></div>"""
    path = HOME / "dashboard.html"
    HOME.mkdir(parents=True, exist_ok=True)
    path.write_text(doc)
    print(path)
    if not a.no_open:
        webbrowser.open(path.as_uri())


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(required=True)

    def add(name, fn, **args):
        sp = sub.add_parser(name)
        for flag, kw in args.items():
            sp.add_argument("--" + flag.replace("_", "-"), **kw)
        if name not in ("projects", "setup", "dashboard"):
            sp.add_argument("--session", default="")
        sp.set_defaults(fn=fn)

    yn = {"choices": ["yes", "no"], "required": True}
    add("projects", cmd_projects)
    add("setup", cmd_setup, client=dict(required=True), project=dict(required=True),
        rate=dict(type=float, required=True), currency=dict(default="USD"),
        billable=dict(choices=["yes", "no"], default="yes"))
    add("begin", cmd_begin, client=dict(required=True), project=dict(required=True), billable=yn,
        discard=dict(action="store_true"))
    add("tick", cmd_tick, topic=dict(required=True), tokens=dict(type=int, default=0),
        effort=dict(choices=list(EFFORT), default="medium"))
    add("close", cmd_close, billable=yn, note=dict(default=""),
        extra=dict(type=float, default=0.0), extra_note=dict(default=""),
        extra_currency=dict(default=""))
    add("end", cmd_end)
    add("status", cmd_status)
    add("dashboard", cmd_dashboard, no_open=dict(action="store_true"))
    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
