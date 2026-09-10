import json
import sys
from html import escape
from pathlib import Path

import yaml

from src.pathway import ARROWS, depths
from utils.graph_view import STYLE as GRAPH_STYLE
from utils.graph_view import render_svg

STYLE = """
:root {
  color-scheme: light dark;
  --surface: #fbfbfa;
  --sunken: #f1f0ec;
  --ink: #171716;
  --muted: #74736c;
  --line: #dddcd6;
  --accent: #167668;
  --accent-soft: #dceeea;
  --up: #d44a49;
  --up-soft: #f8e5e1;
  --down: #397bc0;
  --down-soft: #e2ebf5;
}
@media (prefers-color-scheme: dark) {
  :root {
    --surface: #1a1a19;
    --sunken: #242422;
    --ink: #f7f7f5;
    --muted: #9a9990;
    --line: #393832;
    --accent: #51b8a8;
    --accent-soft: #173a34;
    --up: #e36d6b;
    --up-soft: #3a2421;
    --down: #64a0df;
    --down-soft: #1d3043;
  }
}
* { box-sizing: border-box; }
body { margin: 0; padding: 40px 24px 80px; background: var(--sunken); color: var(--ink);
       font: 14px/1.55 system-ui, sans-serif; }
main { max-width: 1080px; margin: auto; }
h1 { margin: 0; font-size: 26px; }
h2 { margin: 34px 0 12px; font-size: 15px; text-transform: uppercase; color: var(--muted); }
.sub { color: var(--muted); }
.card { padding: 18px; border: 1px solid var(--line); border-radius: 10px; background: var(--surface); }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 1px;
         overflow: hidden; border: 1px solid var(--line); border-radius: 10px; background: var(--line); }
.tile { padding: 14px; background: var(--surface); }
.label { color: var(--muted); font-size: 12px; }
.value { margin-top: 3px; font-size: 22px; font-weight: 600; }
.chips { display: flex; flex-wrap: wrap; gap: 8px; }
.chip { padding: 4px 9px; border-radius: 999px; background: var(--accent-soft); color: var(--accent); }
table { width: 100%; border-collapse: collapse; }
th, td { padding: 8px 12px 8px 0; text-align: left; border-bottom: 1px solid var(--line); }
th { color: var(--muted); font-size: 12px; }
code { color: var(--accent); }
details { margin-top: 9px; padding: 10px 13px; border: 1px solid var(--line); border-radius: 8px; }
summary { cursor: pointer; font-weight: 600; }
pre { overflow: auto; max-height: 420px; padding: 12px; background: var(--sunken); border-radius: 7px;
      white-space: pre-wrap; font: 12px/1.5 ui-monospace, monospace; }
""" + GRAPH_STYLE


def build(run_dir):
    run_dir = Path(run_dir)
    graph = read_json(run_dir / "best_execution_graph.json")
    pathway = read_json(run_dir / "best_pathway.json")
    optimization = read_json(run_dir / "optimization.json")
    config = yaml.safe_load((run_dir / "run_config.yaml").read_text())
    path = run_dir / "report.html"
    path.write_text(page(graph, pathway, optimization, config), encoding="utf-8")
    return path


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def page(graph, pathway, optimization, config):
    usage = optimization["usage"]
    tiles = {
        "Best iteration": optimization["best_iteration"],
        "Complexity": optimization["best_complexity"],
        "Mutations": optimization["mutations_attempted"],
        "LLM calls": usage["llm_calls"],
        "Agent calls": usage["agents"]["llm_calls"],
        "Total tokens": usage["total_tokens"],
    }
    target = output_table(optimization["requested_output"])
    prediction = output_table(optimization["best_prediction"]["outputs"])
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        f"<title>{escape(optimization['scenario_id'])} — best found</title>"
        f"<style>{STYLE}</style></head><body><main>"
        f"<h1>{escape(optimization['scenario_id'])}</h1>"
        f"<p class=\"sub\">Best-found agent causal graph · stopped on "
        f"<code>{escape(optimization['stop_reason'])}</code> · "
        f"model <code>{escape(config['model']['name'])}</code></p>"
        f"<div class=\"tiles\">{tile_html(tiles)}</div>"
        f"<h2>Final outputs</h2><div class=\"card\"><h3>Target</h3>{target}"
        f"<h3>Prediction</h3>{prediction}</div>"
        f"<h2>Execution graph</h2>{execution_graph(graph)}"
        f"<h2>Predicted pathway</h2>{pathway_graph(pathway)}"
        f"<h2>Optimization history</h2>{attempt_history(optimization['attempts'])}"
        "</main></body></html>"
    )


def tile_html(tiles):
    return "".join(
        f"<div class=\"tile\"><div class=\"label\">{escape(label)}</div>"
        f"<div class=\"value\">{value:,}</div></div>"
        for label, value in tiles.items()
    )


def output_table(outputs):
    rows = "".join(
        f"<tr><td>{escape(output['agent_id'])}</td>"
        f"<td>{escape(output['variable'])}</td>"
        f"<td>{ARROWS[output['level']]} {escape(output['level'])}</td></tr>"
        for output in outputs
    )
    return (
        "<table><tr><th>Component</th><th>Variable</th><th>Level</th></tr>"
        f"{rows}</table>"
        if rows
        else "<p class=\"sub\">No terminal response events.</p>"
    )


def execution_graph(graph):
    nodes = "".join(
        f"<span class=\"chip\">{escape(node)}</span>" for node in graph["nodes"]
    )
    edges = "".join(
        f"<tr><td>{escape(edge['source'])}</td><td>→</td>"
        f"<td>{escape(edge['target'])}</td></tr>"
        for edge in graph["edges"]
    )
    edge_table = (
        f"<table><tr><th>Source</th><th></th><th>Target</th></tr>{edges}</table>"
        if edges
        else "<p class=\"sub\">No execution edges.</p>"
    )
    return (
        f"<div class=\"card\"><div class=\"chips\">{nodes}</div>"
        f"<div style=\"margin-top:16px\">{edge_table}</div></div>"
    )


def pathway_graph(pathway):
    steps = depths(pathway)
    labels = [
        "INPUT" if index == 0 else f"DEPTH {index}"
        for index in range(max(steps.values()) + 1)
    ]
    svg = render_svg(
        pathway["events"],
        pathway["edges"],
        steps,
        labels,
        "best-pathway-arrow",
        "Best predicted pathway",
    )
    return f"<div class=\"card\">{svg}</div>"


def attempt_history(attempts):
    blocks = []
    for attempt in attempts:
        status = "accepted" if attempt["accepted"] else "rejected"
        payload = escape(json.dumps(attempt, indent=2, ensure_ascii=False))
        blocks.append(
            f"<details><summary>Iteration {attempt['iteration']} · {status}</summary>"
            f"<pre>{payload}</pre></details>"
        )
    return "<div class=\"card\">" + "".join(blocks) + "</div>"


if __name__ == "__main__":
    print(build(sys.argv[1]))
