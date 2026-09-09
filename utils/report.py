import json
import sys
from html import escape
from pathlib import Path

import yaml

from utils.graph_view import STYLE as GRAPH_STYLE
from utils.graph_view import render_svg
from src.pathway import ARROWS, depths, longest_chain, signed

STYLE = """
:root {
  color-scheme: light;
  --surface-0: #f7f7f5;
  --surface-1: #fcfcfb;
  --surface-2: #efeeea;
  --border: #e2e1dc;
  --text-primary: #0b0b0b;
  --text-secondary: #52514e;
  --text-muted: #78776f;
  --up: #e34948;
  --down: #2a78d6;
  --edge: #a9a89f;
  --in: #8557d6;
  --out: #1c8a63;
  --surface: var(--surface-1);
  --sunken: var(--surface-2);
  --ink: var(--text-primary);
  --muted: var(--text-muted);
  --line: var(--border);
  --accent: #0e6a5e;
  --accent-soft: #d9ebe7;
  --up-soft: #f4e3dc;
  --down-soft: #dde7f1;
}
@media (prefers-color-scheme: dark) {
  :root {
    color-scheme: dark;
    --surface-0: #131312;
    --surface-1: #1a1a19;
    --surface-2: #242422;
    --border: #35352f;
    --text-primary: #ffffff;
    --text-secondary: #c3c2b7;
    --text-muted: #8e8d84;
    --up: #e66767;
    --down: #3987e5;
    --edge: #5c5b53;
    --in: #a988ec;
    --out: #48b98d;
    --accent: #48bca9;
    --accent-soft: #143630;
    --up-soft: #3a221a;
    --down-soft: #17293a;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0;
  padding: 40px 24px 96px;
  background: var(--surface-0);
  color: var(--text-primary);
  font: 15px/1.55 ui-sans-serif, system-ui, -apple-system, "Segoe UI", Helvetica, Arial, sans-serif;
}
main { max-width: 1080px; margin: 0 auto; }
h1 { font-size: 25px; font-weight: 600; margin: 0 0 6px; letter-spacing: -0.01em; }
h2 { font-size: 15px; font-weight: 600; margin: 0 0 14px; letter-spacing: 0.02em;
     text-transform: uppercase; color: var(--text-secondary); }
h3 { font-size: 14px; font-weight: 600; margin: 0 0 8px; }
section { margin-top: 34px; }
.sub { color: var(--text-secondary); margin: 0 0 22px; }
.card { background: var(--surface-1); border: 1px solid var(--border); border-radius: 12px; padding: 20px; }
.meta { display: flex; flex-wrap: wrap; gap: 10px 28px; margin-bottom: 24px; }
.meta div { font-size: 13px; color: var(--text-muted); }
.meta b { display: block; font-size: 14px; font-weight: 500; color: var(--text-primary); }
.badge { display: inline-block; padding: 2px 9px; border-radius: 999px; font-size: 12px;
         border: 1px solid var(--border); background: var(--surface-2); color: var(--text-secondary); }
.hero { font-size: 52px; font-weight: 600; line-height: 1.05; letter-spacing: -0.02em; }
.hero-label { color: var(--text-secondary); font-size: 14px; margin-top: 2px; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 1px;
         background: var(--border); border: 1px solid var(--border); border-radius: 12px; overflow: hidden; }
.tile { background: var(--surface-1); padding: 15px 17px; }
.tile .label { font-size: 12.5px; color: var(--text-secondary); }
.tile .value { font-size: 23px; font-weight: 600; letter-spacing: -0.01em; margin-top: 3px; }
.graph-card + .graph-card { margin-top: 14px; }
.graph-head { display: flex; flex-wrap: wrap; align-items: baseline; gap: 4px 16px; margin-bottom: 4px; }
.graph-head h3 { margin: 0; flex: 1 1 320px; }
.graph-stats { font: 11.5px ui-monospace, monospace; color: var(--text-muted); }
.graph-note { margin: 0 0 14px; color: var(--text-secondary); font-size: 13px; max-width: 78ch; }
.graph-card .scroll svg { max-width: 100%; }
.legend { display: flex; flex-wrap: wrap; gap: 8px 22px; margin-top: 16px;
          font-size: 12.5px; color: var(--text-secondary); }
.legend span { display: inline-flex; align-items: center; gap: 7px; }
.legend i { display: inline-block; flex: none; }
.swatch { width: 13px; height: 13px; border-radius: 3px; border: 2px solid; }
.swatch.up { border-color: var(--up); background: color-mix(in oklab, var(--up) 9%, var(--surface-1)); }
.swatch.down { border-color: var(--down); background: color-mix(in oklab, var(--down) 9%, var(--surface-1)); }
.swatch.input { border-color: var(--accent); background: var(--accent-soft); }
.dash { width: 24px; height: 0; border-top: 2px dashed var(--text-secondary); }
.solid { width: 24px; height: 0; border-top: 2px solid var(--edge); }
table { border-collapse: collapse; width: 100%; font-size: 13.5px; }
th { text-align: left; font-weight: 600; color: var(--text-secondary); font-size: 12.5px;
     padding: 7px 12px 7px 0; border-bottom: 1px solid var(--border); }
td { padding: 7px 12px 7px 0; border-bottom: 1px solid var(--border); vertical-align: top; }
td.num { font-variant-numeric: tabular-nums; color: var(--text-muted); }
.chain { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; font-size: 13.5px; }
.chain b { font-weight: 600; }
.chain i { color: var(--text-muted); font-style: normal; }
details { border: 1px solid var(--border); border-radius: 10px; background: var(--surface-1);
          margin-bottom: 10px; }
details[open] { background: var(--surface-1); }
summary { cursor: pointer; padding: 13px 17px; font-weight: 600; font-size: 14px;
          display: flex; align-items: center; gap: 12px; }
summary::-webkit-details-marker { display: none; }
summary::before { content: "▸"; color: var(--text-muted); font-size: 11px; }
details[open] > summary::before { content: "▾"; }
summary .tag { font-weight: 400; font-size: 12.5px; color: var(--text-muted); }
.body { padding: 0 17px 17px; }
.inner { border-color: var(--border); background: var(--surface-0); }
pre { background: var(--surface-0); border: 1px solid var(--border); border-radius: 8px;
      padding: 13px; font-size: 12px; line-height: 1.5; white-space: pre-wrap;
      word-break: break-word; margin: 0; color: var(--text-secondary); max-height: 460px;
      overflow-y: auto; }
.call { margin-bottom: 22px; }
.io { margin-bottom: 12px; }
.io-label { display: flex; align-items: center; gap: 9px; margin-bottom: 6px;
            font-size: 13px; font-weight: 600; }
.io-label span { padding: 1px 8px; border-radius: 999px; font-size: 10.5px; font-weight: 600;
                 letter-spacing: 0.06em; text-transform: uppercase; border: 1px solid; }
.io-label i { font-style: normal; font-weight: 400; font-size: 12px; color: var(--text-muted);
              font-variant-numeric: tabular-nums; }
.io.in .io-label span { color: var(--in); border-color: color-mix(in oklab, var(--in) 45%, transparent);
                        background: color-mix(in oklab, var(--in) 12%, var(--surface-1)); }
.io.out .io-label span { color: var(--out); border-color: color-mix(in oklab, var(--out) 45%, transparent);
                         background: color-mix(in oklab, var(--out) 12%, var(--surface-1)); }
.io.in pre { border-left: 3px solid color-mix(in oklab, var(--in) 55%, var(--border)); }
.io.out pre { border-left: 3px solid color-mix(in oklab, var(--out) 55%, var(--border)); }
.empty { color: var(--text-muted); font-size: 13.5px; margin: 0; }
.warn { color: var(--up); font-size: 12.5px; margin: 6px 0 0; }
.note { color: var(--text-muted); font-size: 12.5px; margin: 6px 0 0; }
"""
STYLE += GRAPH_STYLE


def build(run_dir):
    run_dir = Path(run_dir)
    trace = _read(run_dir / "trace.json")
    pathway = _read(run_dir / "pathway.json")
    run = _read(run_dir / "run.json")
    config = yaml.safe_load((run_dir / "run_config.yaml").read_text())

    path = run_dir / "report.html"
    path.write_text(_page(f"{run_dir.parent.name}_{run_dir.name}", trace, pathway, run, config), encoding="utf-8")
    return path


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _page(name, trace, pathway, run, config):
    events = {event["id"]: event for event in pathway["events"]}
    inputs = [events[event_id] for event_id in pathway["input_event_ids"]]
    title = ", ".join(
        f"{event['agent_id']}.{event['variable']} {ARROWS[event['level']]}"
        for event in inputs
    )
    return (
        f"<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        f"<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>{escape(title)} — organ agents</title><style>{STYLE}</style></head><body><main>"
        f"{_header(name, title, run, config)}"
        f"{_summary(pathway, run)}"
        f"{_meta_agent_section(trace)}"
        f"{_graph_section(trace, pathway)}"
        f"{_normalization_section(trace)}"
        f"{_rounds_section(trace)}"
        f"</main></body></html>"
    )


def _header(name, title, run, config):
    simulation = config["simulation"]
    fields = {
        "Perturbation": title,
        "Model": run["model"],
        "Temperature": config["generation"]["temperature"],
        "Router": config["routing"]["mode"],
        "Meta Agent": "enabled" if run["meta_agent"]["enabled"] else "disabled",
        "Max rounds": simulation["max_rounds"],
        "Workers": simulation["workers"],
        "Run": name,
    }
    meta = "".join(f"<div>{escape(k)}<b>{escape(str(v))}</b></div>" for k, v in fields.items())
    return (
        f"<h1>Pathway reconstruction — {escape(title)}</h1>"
        f"<p class=\"sub\">Physiological agents propagating a single perturbation, "
        f"with deterministic representation translation between agent rounds. Terminated on "
        f"<span class=\"badge\">{escape(run['termination'])}</span></p>"
        f"<div class=\"meta\">{meta}</div>"
    )


def _summary(pathway, run):
    usage = run["usage"]
    tiles = {
        "LLM calls": usage["llm_calls"],
        "Meta calls": usage["meta_agent"]["llm_calls"],
        "Router calls": usage["router"]["llm_calls"],
        "Agent calls": usage["agents"]["llm_calls"],
        "Prompt tokens": usage["prompt_tokens"],
        "Cached tokens": usage["cached_tokens"],
        "Output tokens": usage["output_tokens"],
        "Total tokens": usage["total_tokens"],
        "Max tokens / call": usage["max_tokens_per_call"],
    }
    cells = "".join(
        f"<div class=\"tile\"><div class=\"label\">{escape(label)}</div>"
        f"<div class=\"value\">{value:,}</div></div>"
        for label, value in tiles.items()
    )
    return (
        f"<section><h2>Result</h2><div class=\"card\">"
        f"<div class=\"hero\">{len(pathway['edges'])}</div>"
        f"<div class=\"hero-label\">causal edges discovered across "
        f"{run['rounds']} rounds and {run['reactions']} agent reactions</div>"
        f"</div>"
        f"<div class=\"tiles\" style=\"margin-top:14px\">{cells}</div></section>"
    )


def _meta_agent_section(trace):
    selection = trace["meta_agent"]
    agents = ", ".join(selection["selected_agents"]) or "no agents"
    if not selection["enabled"]:
        return (
            f"<section><h2>Agent selection</h2><div class=\"card\">"
            f"<p class=\"empty\">Meta Agent disabled. Active agents: {escape(agents)}.</p>"
            f"</div></section>"
        )
    call = selection["trace"]
    return (
        f"<section><h2>Meta Agent</h2><div class=\"card\">"
        f"<h3>Selected agents</h3><p>{escape(agents)}</p>{_call_block(call)}"
        f"</div></section>"
    )


def _graph_section(trace, pathway):
    raw_events = trace["events"]
    raw_event_ids = {event["id"] for event in raw_events}
    raw_edges = []
    for event in raw_events:
        if event["caused_by"] is None:
            continue
        if event["caused_by"] not in raw_event_ids:
            raise ValueError(
                f"trace event '{event['id']}' cites unknown cause '{event['caused_by']}'"
            )
        raw_edges.append({"source": event["caused_by"], "target": event["id"]})
    raw_steps = {event["id"]: event["round"] for event in raw_events}
    raw_labels = [
        "INPUT" if index == 0 else f"DEPTH {index}"
        for index in range(max(raw_steps.values()) + 1)
    ]

    canonical_steps = depths(pathway)
    canonical_event_ids = {event["id"] for event in pathway["events"]}
    if missing := canonical_event_ids - canonical_steps.keys():
        raise ValueError(f"canonical graph has unreachable events: {sorted(missing)}")
    canonical_labels = [
        "INPUT" if index == 0 else f"DEPTH {index}"
        for index in range(max(canonical_steps.values()) + 1)
    ]

    chain = longest_chain(pathway)
    events = {event["id"]: event for event in pathway["events"]}
    steps = "<i>→</i>".join(
        f"<b>{escape(events[event_id]['agent_id'] + '.' + signed(events[event_id]['variable'], events[event_id]['level']))}</b>"
        for event_id in chain
    )
    longest = (
        f"<h3 style=\"margin-top:22px\">Longest chain</h3>"
        f"<div class=\"chain\">{steps}</div>" if chain else ""
    )
    raw_note = (
        "Every emitted event occurrence from trace.json. Columns are causal depths; repeated "
        "states remain separate."
    )
    canonical_note = (
        "Deduplicated pathway.json used by evaluation. Columns are shortest causal depth; "
        "dashed edges run backward or within one depth after remapping."
    )
    raw_card = _graph_card(
        "1. Raw trace",
        raw_note,
        raw_events,
        raw_edges,
        raw_steps,
        raw_labels,
        "trace-arrow",
    )
    canonical_card = _graph_card(
        "2. Canonical graph",
        canonical_note,
        pathway["events"],
        pathway["edges"],
        canonical_steps,
        canonical_labels,
        "canonical-arrow",
        longest,
    )
    return (
        f"<section><h2>Pathway graphs</h2>"
        f"{raw_card}{canonical_card}"
        f"</section>"
    )


def _graph_card(title, note, events, edges, steps, labels, marker_id, extra=""):
    stats = (
        f"{len(events)} events · {len(edges)} edges · "
        f"{len({event['agent_id'] for event in events})} components"
    )
    graph = render_svg(events, edges, steps, labels, marker_id, f"{title}: {stats}")
    return (
        f'<div class="card graph-card"><div class="graph-head">'
        f'<h3>{escape(title)}</h3><span class="graph-stats">{escape(stats)}</span></div>'
        f'<p class="graph-note">{escape(note)}</p>{graph}{_legend()}{extra}</div>'
    )


def _normalization_section(trace):
    events = {event["id"]: event for event in trace["events"]}
    translated = [
        entry
        for entry in trace.get("normalizations", [])
        if entry["translated"]
    ]
    passthrough = sum(
        not entry["translated"]
        for entry in trace.get("normalizations", [])
    )
    rows = "".join(
        f"<tr><td>{escape(entry['source'])}</td>"
        f"<td>{escape(_event_label(events[entry['source']]))}</td>"
        f"<td>{escape(entry['result'])}</td>"
        f"<td>{escape(_event_label(events[entry['result']]))}</td></tr>"
        for entry in translated
    )
    table = (
        f"<table><tr><th>Source ID</th><th>Source</th><th>Result ID</th>"
        f"<th>Translated representation</th></tr>{rows}</table>"
        if rows else "<p class=\"empty\">No events required translation.</p>"
    )
    return (
        f"<section><h2>Representation translation</h2><div class=\"card\">{table}"
        f"<p class=\"note\">{passthrough} events passed through unchanged.</p>"
        f"</div></section>"
    )


def _rounds_section(trace):
    events = {event["id"]: event for event in trace["events"]}
    records = {}
    for record in trace["records"]:
        records.setdefault(record["round"], []).append(record)

    blocks = "".join(
        _round_block(entry, records.get(entry["round"], []), events)
        for entry in trace["rounds"]
    )
    return f"<section><h2>Rounds</h2>{blocks}</section>"


def _round_block(entry, records, events):
    index = entry["round"]
    agents = ", ".join(entry["dispatch"]) or "nothing dispatched"
    dropped = "".join(
        f"<p class=\"warn\">Unrouted: "
        f"{escape(signed(events[event_id]['variable'], events[event_id]['level']))}</p>"
        for event_id in entry["dropped"]
    )
    closures = "".join(
        f"<p class=\"note\">Homeostatic closure: "
        f"{escape(signed(events[event_id]['variable'], events[event_id]['level']))}</p>"
        for event_id in entry.get("homeostatic_closures", [])
    )
    not_reexpanded = "".join(
        f"<p class=\"note\">Not re-expanded: "
        f"{escape(signed(events[event_id]['variable'], events[event_id]['level']))}</p>"
        for event_id in entry.get("not_reexpanded", [])
    )
    routing = _routing_block(entry["routing"], events)
    agent_blocks = "".join(_agent_block(record, events) for record in records)

    return (
        f"<details><summary>Round {index}<span class=\"tag\">{escape(agents)}</span></summary>"
        f"<div class=\"body\">{dropped}{closures}{not_reexpanded}{routing}"
        f"{agent_blocks}</div></details>"
    )


def _routing_block(routing, events_by_id):
    trace = routing["trace"]
    cost = f"{trace['total_tokens']:,} tokens" if trace else "rule-based"
    call = _call_block(trace) if trace else ""
    rows = "".join(
        f"<tr><td>{escape(decision['event'])}</td>"
        f"<td>{escape(_event_label(events_by_id[decision['event']]))}</td>"
        f"<td>{escape(', '.join(decision['selected_agents']) or 'no agents')}</td></tr>"
        for decision in routing["decisions"]
    )
    table = (
        f"<table><tr><th>ID</th><th>Event</th><th>Agents</th></tr>{rows}</table>"
        if rows else "<p class=\"empty\">No events to route.</p>"
    )
    return (
        f"<details class=\"inner\"><summary>Router"
        f"<span class=\"tag\">{len(routing['decisions'])} events · {cost}</span></summary>"
        f"<div class=\"body\">{table}{call}</div></details>"
    )


def _agent_block(record, events_by_id):
    trace = record["trace"]
    incoming = ", ".join(
        signed(events_by_id[event_id]["variable"], events_by_id[event_id]["level"])
        for event_id in record["incoming"]
    )
    events = "".join(
        f"<tr><td>{escape(event['id'])}</td>"
        f"<td>{escape(event['agent_id'] + '.' + signed(event['variable'], event['level']))}</td>"
        f"<td>{escape(event['caused_by'])}</td></tr>"
        for event in (events_by_id[event_id] for event_id in record["events"])
    )
    table = (
        f"<table><tr><th>ID</th><th>Event</th><th>Caused by</th></tr>{events}</table>"
        if events else "<p class=\"empty\">No events emitted.</p>"
    )
    cost = f"{trace['total_tokens']:,} tokens"
    call = _call_block(trace)
    return (
        f"<details class=\"inner\"><summary>{escape(record['agent'])}"
        f"<span class=\"tag\">← {escape(incoming)} · {cost}</span></summary>"
        f"<div class=\"body\">{table}{call}</div></details>"
    )


def _event_label(event):
    return event["agent_id"] + "." + signed(event["variable"], event["level"])


CALL_PARTS = (
    ("in", "System prompt", "system_prompt"),
    ("in", "User prompt", "prompt"),
    ("out", "Model response", "response"),
)


def _call_block(call):
    return (
        f"<details class=\"inner\"><summary>LLM call"
        f"<span class=\"tag\">{call['total_tokens']:,} tokens</span></summary>"
        f"<div class=\"body\"><h3>{call['prompt_tokens']:,} input / "
        f"{call['output_tokens']:,} output tokens</h3>"
        f"<div class=\"call\">{_call_parts(call)}</div></div></details>"
    )


def _call_parts(call):
    return "".join(
        f"<div class=\"io {kind}\"><div class=\"io-label\">"
        f"<span>{'input' if kind == 'in' else 'output'}</span>{escape(name)}"
        f"<i>{len(call[key]):,} chars</i></div>"
        f"<pre>{escape(call[key])}</pre></div>"
        for kind, name, key in CALL_PARTS
    )


def _legend():
    return (
        "<div class=\"legend\">"
        "<span><i class=\"swatch input\"></i>input</span>"
        "<span><i class=\"swatch down\"></i>decreased ↓</span>"
        "<span><i class=\"swatch up\"></i>increased ↑</span>"
        "<span><i class=\"solid\"></i>forward</span>"
        "<span><i class=\"dash\"></i>backward or same-depth after remapping</span>"
        "</div>"
    )


if __name__ == "__main__":
    print(build(sys.argv[1]))
