import json
import sys
from html import escape
from pathlib import Path

import yaml

from src.pathway import ARROWS, signed, variable_edges

CHIP_W, CHIP_H, CHIP_GAP, HEAD_H, BOX_PAD = 150, 32, 8, 15, 9
BOX_H = BOX_PAD * 2 + HEAD_H + CHIP_H
CHIP_Y = BOX_PAD + HEAD_H
GAP_X, GAP_Y, PAD, BOW = 22, 68, 18, 78

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
.scroll { overflow-x: auto; }
svg { display: block; }
.group rect { fill: var(--surface-2); stroke: var(--border); stroke-width: 1px; }
.node rect { fill: var(--surface-1); stroke-width: 2px; }
.node.up rect { stroke: var(--up); fill: color-mix(in oklab, var(--up) 9%, var(--surface-1)); }
.node.down rect { stroke: var(--down); fill: color-mix(in oklab, var(--down) 9%, var(--surface-1)); }
.node.neutral rect { stroke: var(--edge); fill: var(--surface-1); }
.n-var { font-size: 12.5px; font-weight: 600; fill: var(--text-primary); text-anchor: middle; }
.n-agent { font-size: 10.5px; fill: var(--text-muted); text-anchor: middle; }
.edge { fill: none; stroke: var(--edge); stroke-width: 2px; }
.edge.feedback { stroke: var(--text-secondary); stroke-dasharray: 5 4; }
.head { fill: var(--edge); }
.head-fb { fill: var(--text-secondary); }
.legend { display: flex; flex-wrap: wrap; gap: 8px 22px; margin-top: 16px;
          font-size: 12.5px; color: var(--text-secondary); }
.legend span { display: inline-flex; align-items: center; gap: 7px; }
.legend i { display: inline-block; flex: none; }
.swatch { width: 13px; height: 13px; border-radius: 3px; border: 2px solid; }
.swatch.up { border-color: var(--up); background: color-mix(in oklab, var(--up) 9%, var(--surface-1)); }
.swatch.down { border-color: var(--down); background: color-mix(in oklab, var(--down) 9%, var(--surface-1)); }
.swatch.neutral { border-color: var(--edge); background: var(--surface-1); }
.swatch.group { width: 22px; border-color: var(--border); background: var(--surface-2); }
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
    perturbation = run["perturbation"]
    title = f"{perturbation['variable']} {ARROWS[perturbation['level']]}"
    return (
        f"<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        f"<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>{escape(title)} — organ agents</title><style>{STYLE}</style></head><body><main>"
        f"{_header(name, title, run, config)}"
        f"{_summary(pathway, run)}"
        f"{_graph_section(pathway)}"
        f"{_agent_section(pathway)}"
        f"{_audit_section(run)}"
        f"{_rounds_section(trace)}"
        f"</main></body></html>"
    )


def _header(name, title, run, config):
    simulation = config["simulation"]
    fields = {
        "Perturbation": title,
        "Model": run["model"],
        "Routing": run["routing_mode"],
        "Temperature": config["generation"]["temperature"],
        "Max rounds": simulation["max_rounds"],
        "Workers": simulation["workers"],
        "Run": name,
    }
    meta = "".join(f"<div>{escape(k)}<b>{escape(str(v))}</b></div>" for k, v in fields.items())
    return (
        f"<h1>Pathway reconstruction — {escape(title)}</h1>"
        f"<p class=\"sub\">Hierarchical organ agents propagating a single perturbation, "
        f"one round per causal hop. Terminated on "
        f"<span class=\"badge\">{escape(run['termination'])}</span></p>"
        f"<div class=\"meta\">{meta}</div>"
    )


def _summary(pathway, run):
    usage = run["usage"]
    tiles = {
        "Reasoning calls": usage["reasoning_calls"],
        "Routing calls": usage["routing_calls"],
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
    coined = (
        f"<p class=\"warn\">Coined outside the registry: {escape(', '.join(run['coined']))}</p>"
        if run["coined"] else ""
    )
    return (
        f"<section><h2>Result</h2><div class=\"card\">"
        f"<div class=\"hero\">{len(pathway['variable_edges'])}</div>"
        f"<div class=\"hero-label\">causal edges discovered across "
        f"{run['rounds']} rounds and {run['reactions']} agent reactions</div>"
        f"{coined}</div>"
        f"<div class=\"tiles\" style=\"margin-top:14px\">{cells}</div></section>"
    )


def _graph_section(pathway):
    chain = pathway["longest_chain"]
    steps = "<i>→</i>".join(
        f"<b>{escape(signed(variable, level))}</b>" for variable, level in chain
    )
    longest = (
        f"<h3 style=\"margin-top:22px\">Longest chain</h3>"
        f"<div class=\"chain\">{steps}</div>" if chain else ""
    )
    return (
        f"<section><h2>Discovered pathway</h2>"
        f"<div class=\"card\">{_graph(pathway['variable_edges'])}{_legend()}{longest}</div></section>"
    )


def _agent_section(pathway):
    rows = "".join(
        f"<tr><td>{escape(edge['from'])}</td><td>{escape(edge['to'])}</td>"
        f"<td>{escape(', '.join(edge['via']))}</td>"
        f"<td class=\"num\">{escape(', '.join(str(r) for r in edge['rounds']))}</td></tr>"
        for edge in pathway["agent_edges"]
    )
    return (
        f"<section><h2>Organ-level flow</h2><div class=\"card\"><table>"
        f"<tr><th>From</th><th>To</th><th>Carried by</th><th>Rounds</th></tr>"
        f"{rows}</table></div></section>"
    )


def _audit_section(run):
    audit = run["routing_audit"]
    if not audit:
        return ""
    rows = "".join(
        f"<tr><td>{escape(signed(entry['variable'], entry['level']))}</td>"
        f"<td>{escape(entry['agent'])}</td><td>{escape(entry['status'])}</td></tr>"
        for entry in audit
    )
    return (
        f"<section><h2>Routing audit</h2><div class=\"card\"><table>"
        f"<tr><th>Change</th><th>Component</th><th>Status</th></tr>{rows}</table>"
        f"<p class=\"note\">proposed — routed by the model but unsupported by any knowledge link, "
        f"a candidate missing link. missed — implied by a knowledge link but not routed by the model."
        f"</p></div></section>"
    )


def _rounds_section(trace):
    records = {}
    for record in trace["records"]:
        records.setdefault(record["round"], []).append(record)

    blocks = "".join(_round_block(entry, records.get(entry["round"], [])) for entry in trace["rounds"])
    return f"<section><h2>Rounds</h2>{blocks}</section>"


def _round_block(entry, records):
    index = entry["round"]
    agents = ", ".join(entry["dispatch"]) or "nothing dispatched"
    edges = variable_edges(records)

    dropped = "".join(
        f"<p class=\"warn\">Unrouted: {escape(signed(event['variable'], event['level']))}</p>"
        for event in entry["dropped"]
    )
    routing = _calls_block("Routing calls", entry["routing"]) if entry["routing"] else ""
    agent_blocks = "".join(_agent_block(record) for record in records)

    return (
        f"<details><summary>Round {index}<span class=\"tag\">{escape(agents)}</span></summary>"
        f"<div class=\"body\">{_graph(edges)}{dropped}{routing}{agent_blocks}</div></details>"
    )


def _agent_block(record):
    call = record["call"]
    incoming = ", ".join(
        signed(event["variable"], event["level"]) for event in record["incoming"]
    )
    effects = "".join(
        f"<tr><td>{escape(signed(effect['variable'], effect['level']))}</td>"
        f"<td>{escape(', '.join(effect['caused_by']))}</td></tr>"
        for effect in record["effects"]
    )
    table = (
        f"<table><tr><th>Effect</th><th>Caused by</th></tr>{effects}</table>"
        if effects else "<p class=\"empty\">No effects emitted.</p>"
    )
    introduced_causes = record["introduced_causes"]
    introduced = (
        f"<p class=\"note\">Introduced cause nodes: "
        f"{escape(', '.join(introduced_causes))}</p>"
        if introduced_causes else ""
    )
    return (
        f"<details class=\"inner\"><summary>{escape(record['agent'])}"
        f"<span class=\"tag\">← {escape(incoming)} · {call['total_tokens']:,} tokens</span></summary>"
        f"<div class=\"body\">{table}{introduced}{_calls_block('LLM call', [call])}</div></details>"
    )


CALL_PARTS = (
    ("in", "System prompt", "system_prompt"),
    ("in", "User prompt", "prompt"),
    ("out", "Model response", "response"),
)


def _calls_block(label, calls):
    blocks = "".join(
        f"<h3>{escape(label)}{f' {index + 1}' if len(calls) > 1 else ''} · "
        f"{call['prompt_tokens']:,} input / {call['output_tokens']:,} output tokens</h3>"
        f"<div class=\"call\">{_call_parts(call)}</div>"
        for index, call in enumerate(calls)
    )
    return (
        f"<details class=\"inner\"><summary>{escape(label)}"
        f"<span class=\"tag\">{len(calls)} call{'s' if len(calls) > 1 else ''}</span></summary>"
        f"<div class=\"body\">{blocks}</div></details>"
    )


def _call_parts(call):
    return "".join(
        f"<div class=\"io {kind}\"><div class=\"io-label\">"
        f"<span>{'input' if kind == 'in' else 'output'}</span>{escape(name)}"
        f"<i>{len(call[key]):,} chars</i></div>"
        f"<pre>{escape(call[key])}</pre></div>"
        for kind, name, key in CALL_PARTS
    )


def _box_width(count):
    return BOX_PAD * 2 + count * CHIP_W + (count - 1) * CHIP_GAP


def _span(groups):
    return sum(_box_width(len(nodes)) for nodes in groups.values()) + GAP_X * (len(groups) - 1)


def _ordered(nodes, pairs):
    remaining, ordered = sorted(nodes), []
    while remaining:
        node = next(
            (node for node in remaining if not any(a in remaining for a, b in pairs if b == node)),
            remaining[0],
        )
        ordered.append(node)
        remaining.remove(node)
    return ordered


def _layout(edges):
    layers, agents = {}, {}
    for edge in edges:
        source, target = (edge["from"], edge["from_level"]), (edge["to"], edge["to_level"])
        layers[source] = min(layers.get(source, edge["round"]), edge["round"])
        layers[target] = min(layers.get(target, edge["round"] + 1), edge["round"] + 1)
        agents.setdefault(target, edge["agent"])
        agents.setdefault(source, edge["from_agent"])

    pairs = {
        ((edge["from"], edge["from_level"]), (edge["to"], edge["to_level"])) for edge in edges
    }
    rows = {}
    for node in sorted(layers, key=lambda node: (layers[node], agents[node])):
        rows.setdefault(layers[node], {}).setdefault(agents[node], []).append(node)

    width = max(_span(groups) for groups in rows.values())
    placed, boxes = {}, []
    for order, layer in enumerate(sorted(rows)):
        groups = rows[layer]
        x, y = PAD + (width - _span(groups)) / 2, PAD + order * (BOX_H + GAP_Y)
        for index, (agent, nodes) in enumerate(groups.items()):
            box = {"x": x, "y": y, "width": _box_width(len(nodes)), "agent": agent}
            boxes.append(box)
            for column, node in enumerate(_ordered(nodes, pairs)):
                placed[node] = {
                    "x": x + BOX_PAD + column * (CHIP_W + CHIP_GAP),
                    "y": y,
                    "right": x + box["width"],
                    "box": (layer, index),
                }
            x += box["width"] + GAP_X
    return placed, boxes, width, len(rows)


def _graph(edges):
    if not edges:
        return "<p class=\"empty\">No attributed causal edges.</p>"

    placed, boxes, width, depth = _layout(edges)
    paths, backward = [], 0
    for edge in edges:
        source = placed[(edge["from"], edge["from_level"])]
        target = placed[(edge["to"], edge["to_level"])]
        if source["box"] == target["box"]:
            continue
        if target["y"] > source["y"]:
            path, style = _forward(source, target), "edge"
        elif target["y"] == source["y"]:
            path, style = _sideways(source, target), "edge"
        else:
            path, style = _backward(source, target, width, backward), "edge feedback"
            backward += 1
        marker = "head-fb" if "feedback" in style else "head"
        paths.append(f"<path class=\"{style}\" marker-end=\"url(#{marker})\" d=\"{path}\"/>")

    groups = "".join(_box(box) for box in boxes)
    nodes = "".join(_chip(node, position) for node, position in placed.items())
    total_width = width + PAD * 2 + (BOW + backward * 12 if backward else 0)
    height = PAD * 2 + depth * (BOX_H + GAP_Y) - GAP_Y
    return (
        f"<div class=\"scroll\"><svg viewBox=\"0 0 {total_width:.0f} {height:.0f}\" "
        f"width=\"{total_width:.0f}\" height=\"{height:.0f}\" role=\"img\">"
        f"{_markers()}{groups}{''.join(paths)}{nodes}</svg></div>"
    )


def _box(box):
    return (
        f"<g class=\"group\"><title>{escape(box['agent'])}</title>"
        f"<rect x=\"{box['x']:.0f}\" y=\"{box['y']:.0f}\" "
        f"width=\"{box['width']:.0f}\" height=\"{BOX_H}\" rx=\"13\"/>"
        f"<text class=\"n-agent\" x=\"{box['x'] + box['width'] / 2:.0f}\" "
        f"y=\"{box['y'] + BOX_PAD + 10:.0f}\">{escape(box['agent'])}</text></g>"
    )


def _chip(node, position):
    variable, level = node
    label = variable if len(variable) <= 19 else variable[:18] + "…"
    style = {None: "neutral", "decreased": "down", "increased": "up"}[level]
    x, y = position["x"], position["y"] + CHIP_Y
    return (
        f"<g class=\"node {style}\"><title>{escape(signed(variable, level))}</title>"
        f"<rect x=\"{x:.0f}\" y=\"{y:.0f}\" width=\"{CHIP_W}\" height=\"{CHIP_H}\" rx=\"8\"/>"
        f"<text class=\"n-var\" x=\"{x + CHIP_W / 2:.0f}\" y=\"{y + CHIP_H / 2 + 4:.0f}\">"
        f"{escape(signed(label, level))}</text></g>"
    )


def _forward(source, target):
    x1, y1 = source["x"] + CHIP_W / 2, source["y"] + BOX_H
    x2, y2 = target["x"] + CHIP_W / 2, target["y"]
    middle = (y1 + y2) / 2
    return f"M{x1:.0f},{y1:.0f} C{x1:.0f},{middle:.0f} {x2:.0f},{middle:.0f} {x2:.0f},{y2:.0f}"


def _sideways(source, target):
    rightward = target["x"] > source["x"]
    x1 = source["x"] + CHIP_W if rightward else source["x"]
    x2 = target["x"] if rightward else target["x"] + CHIP_W
    y = source["y"] + CHIP_Y + CHIP_H / 2
    dip = y + CHIP_H * 0.7
    middle = (x1 + x2) / 2
    return f"M{x1:.0f},{y:.0f} C{middle:.0f},{dip:.0f} {middle:.0f},{dip:.0f} {x2:.0f},{y:.0f}"


def _backward(source, target, width, index):
    x1, y1 = source["right"], source["y"] + CHIP_Y + CHIP_H / 2
    x2, y2 = target["right"], target["y"] + CHIP_Y + CHIP_H / 2
    bow = width + PAD + BOW * 0.55 + index * 12
    return f"M{x1:.0f},{y1:.0f} C{bow:.0f},{y1:.0f} {bow:.0f},{y2:.0f} {x2:.0f},{y2:.0f}"


def _markers():
    return (
        "<defs>"
        "<marker id=\"head\" viewBox=\"0 0 9 9\" refX=\"8\" refY=\"4.5\" markerWidth=\"5.5\" "
        "markerHeight=\"5.5\" orient=\"auto\"><path class=\"head\" d=\"M0,0 L9,4.5 L0,9 z\"/></marker>"
        "<marker id=\"head-fb\" viewBox=\"0 0 9 9\" refX=\"8\" refY=\"4.5\" markerWidth=\"5.5\" "
        "markerHeight=\"5.5\" orient=\"auto\"><path class=\"head-fb\" d=\"M0,0 L9,4.5 L0,9 z\"/></marker>"
        "</defs>"
    )


def _legend():
    return (
        "<div class=\"legend\">"
        "<span><i class=\"swatch down\"></i>decreased ↓</span>"
        "<span><i class=\"swatch up\"></i>increased ↑</span>"
        "<span><i class=\"swatch neutral\"></i>direction not observed</span>"
        "<span><i class=\"swatch group\"></i>one organ · left causes right</span>"
        "<span><i class=\"solid\"></i>forward</span>"
        "<span><i class=\"dash\"></i>feedback (loop closure, not expanded)</span>"
        "</div>"
    )


if __name__ == "__main__":
    print(build(sys.argv[1]))
