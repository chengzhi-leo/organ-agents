import argparse
import json
import sys
from collections import defaultdict
from html import escape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.graph_view import STYLE as GRAPH_STYLE
from src.graph_view import render_svg

TEMPLATE = Path(__file__).with_name("graph_page.html")


def title(scenario_id):
    return " ".join(scenario_id.split("_")[1:]).capitalize()


def load(paths):
    scenarios = []
    for path in paths:
        graph = json.loads(path.read_text())
        events = {event["id"] for event in graph["events"]}
        unknown = {end for edge in graph["edges"] for end in edge.values()} - events
        if unknown:
            raise ValueError(f"{path.name} has edges to unknown events: {sorted(unknown)}")
        scenarios.append(graph | {"title": title(graph["scenario_id"])})
    if not scenarios:
        raise ValueError("no graph files provided")
    return scenarios


def presentation(mode, count):
    shared = (
        "A node is one directional change owned by one component &mdash; "
        "<code>(agent_id, variable, level)</code> &mdash; and an edge means the source change "
        "directly drives the target change. Rows are the agents that own the change; columns are "
        "causal depth from the input event."
    )
    if mode == "ground-truth":
        return {
            "page_title": "Glucose GT pathways",
            "eyebrow": "Ground truth &middot; OpenStax 37.3",
            "heading": "Glucose regulation ground-truth pathways",
            "description": f"{count} textbook-derived causal graphs. {shared}",
            "footer": "Source provenance is GT-only metadata and is ignored by evaluation.",
        }
    return {
        "page_title": "Glucose predicted pathways",
        "eyebrow": "Agent prediction &middot; pathway reconstruction",
        "heading": "Glucose regulation predicted pathways",
        "description": f"{count} agent-generated causal graphs rendered with the GT layout. {shared}",
        "footer": "Only the presentation changed; prediction events and edges are unmodified.",
    }


def graph_steps(graph):
    parents = defaultdict(list)
    for edge in graph["edges"]:
        parents[edge["target"]].append(edge["source"])

    depth = {}

    def resolve(identifier):
        if identifier not in depth:
            depth[identifier] = 0
            depth[identifier] = max((resolve(p) for p in parents[identifier]), default=-1) + 1
        return depth[identifier]

    for event in graph["events"]:
        resolve(event["id"])
    return depth


def svg(graph):
    steps = graph_steps(graph)
    labels = ["INPUT", *(f"STEP {index}" for index in range(1, max(steps.values()) + 1))]
    caption = (
        f'{graph["title"]}: {len(graph["events"])} events across '
        f'{len({event["agent_id"] for event in graph["events"]})} agents, '
        f'{len(graph["edges"])} causal edges, {len(labels)} causal steps'
    )
    return render_svg(
        graph["events"],
        graph["edges"],
        steps,
        labels,
        f'arrow-{graph["scenario_id"]}',
        caption,
    )


def panel(graph):
    meta = [
        f'{len(graph["events"])} events',
        f'{len(graph["edges"])} edges',
        f'{len({event["agent_id"] for event in graph["events"]})} agents',
    ]
    if source := graph.get("source"):
        meta.extend([
            f'p. {", ".join(map(str, source["pages"]))} · lines {", ".join(source["line_ranges"])}',
            f'evidence: {source["evidence"]}',
        ])
    cells = "".join(f"<span>{escape(item)}</span>" for item in meta)
    return (
        f'<section class="panel"><div class="panel-head">'
        f'<h2>{escape(graph["title"])}</h2>'
        f'<span class="sid mono">{escape(graph["scenario_id"])}</span>'
        f'<div class="meta mono">{cells}</div></div>'
        f'<div class="canvas">{svg(graph)}</div></section>'
    )


def rail(scenarios):
    counts = [
        (len(scenarios), "scenarios"),
        (sum(len(graph["events"]) for graph in scenarios), "events"),
        (sum(len(graph["edges"]) for graph in scenarios), "edges"),
        (len(agents(scenarios)), "agents"),
    ]
    return "".join(f"<span class='stat'><b>{value}</b><span>{name}</span></span>" for value, name in counts)


def agents(scenarios):
    return dict.fromkeys(event["agent_id"] for graph in scenarios for event in graph["events"])


def matrix(scenarios):
    owned = {
        agent: [any(event["agent_id"] == agent for event in graph["events"]) for graph in scenarios]
        for agent in agents(scenarios)
    }
    order = sorted(owned, key=lambda agent: (-sum(owned[agent]), agent))
    head = "".join(f'<th>{escape(graph["scenario_id"].replace("glucose_case_", ""))}</th>' for graph in scenarios)
    rows = "".join(
        f'<tr><td class="agent">{escape(agent)}</td>'
        + "".join('<td class="hit">●</td>' if hit else '<td class="miss">·</td>' for hit in owned[agent])
        + f"<td>{sum(owned[agent])}</td></tr>"
        for agent in order
    )
    return (
        f'<table><thead><tr><th class="agent">agent</th>{head}<th>n</th></tr></thead>'
        f"<tbody>{rows}</tbody></table>"
    )


def matrix_section(scenarios):
    if len(scenarios) == 1:
        return ""
    return (
        '<div class="matrix-wrap"><h3>Agent coverage</h3>'
        '<p class="note">Which component owns at least one event in each scenario. Every scenario '
        'is run against the same configured component set, so a sparse column is a scenario that '
        f'exercises few agents.</p>{matrix(scenarios)}</div>'
    )


def main():
    parser = argparse.ArgumentParser(description="Render pathway graphs as one page")
    sources = parser.add_mutually_exclusive_group(required=True)
    sources.add_argument("--ground-truth", type=Path)
    sources.add_argument("--pathway", type=Path, action="append")
    parser.add_argument("--mode", choices=("ground-truth", "prediction"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()

    paths = (
        sorted(arguments.ground_truth.glob("*.json"))
        if arguments.ground_truth
        else arguments.pathway
    )
    source = (
        f"{arguments.ground_truth}/*.json"
        if arguments.ground_truth
        else ", ".join(map(str, arguments.pathway))
    )
    scenarios = load(paths)
    labels = presentation(arguments.mode, len(scenarios))
    page = TEMPLATE.read_text()
    for placeholder, value in {
        "__PAGE_TITLE__": escape(labels["page_title"]),
        "__EYEBROW__": labels["eyebrow"],
        "__HEADING__": escape(labels["heading"]),
        "__DESCRIPTION__": labels["description"],
        "__GRAPH_STYLE__": GRAPH_STYLE,
        "__RAIL__": rail(scenarios),
        "__PANELS__": "".join(panel(graph) for graph in scenarios),
        "__MATRIX_SECTION__": matrix_section(scenarios),
        "__SOURCE__": escape(source),
        "__FOOTER__": escape(labels["footer"]),
    }.items():
        page = page.replace(placeholder, value)

    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(page, encoding="utf-8")
    print(f"scenarios : {len(scenarios)}")
    print(f"events    : {sum(len(graph['events']) for graph in scenarios)}")
    print(f"edges     : {sum(len(graph['edges']) for graph in scenarios)}")
    print(f"written   : {arguments.output}")


if __name__ == "__main__":
    main()
