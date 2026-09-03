import argparse
import json
from collections import defaultdict
from html import escape
from pathlib import Path

TEMPLATE = Path(__file__).with_name("graph_page.html")

NODE_H, ROW_GAP, LANE_PAD = 34, 10, 13
COL_GAP, GUTTER, RIGHT_PAD, TOP = 62, 146, 24, 30
CHAR, GLYPH, PAD_X = 6.95, 20, 13
GLYPHS = {"increased": "&#9650;", "decreased": "&#9660;"}


def title(path):
    return " ".join(path.stem.split("_")[1:]).capitalize()


def load(directory):
    scenarios = []
    for path in sorted(directory.glob("*.json")):
        graph = json.loads(path.read_text())
        events = {event["id"] for event in graph["events"]}
        unknown = {end for edge in graph["edges"] for end in edge.values()} - events
        if unknown:
            raise ValueError(f"{path.name} has edges to unknown events: {sorted(unknown)}")
        scenarios.append(graph | {"title": title(path)})
    if not scenarios:
        raise ValueError(f"no ground-truth files under {directory}")
    return scenarios


def layout(graph):
    parents = defaultdict(list)
    for edge in graph["edges"]:
        parents[edge["target"]].append(edge["source"])

    depth = {}

    def resolve(identifier):
        if identifier not in depth:
            depth[identifier] = 0
            depth[identifier] = max((resolve(p) for p in parents[identifier]), default=-1) + 1
        return depth[identifier]

    rank = {}
    for index, event in enumerate(graph["events"]):
        rank.setdefault(event["agent_id"], (resolve(event["id"]), index))
    lanes = sorted(rank, key=rank.get)

    columns = max(depth.values()) + 1
    widths = [0.0] * columns
    for event in graph["events"]:
        span = max(132, len(event["variable"]) * CHAR + GLYPH + PAD_X * 2)
        widths[depth[event["id"]]] = max(widths[depth[event["id"]]], span)

    x, cursor = [], GUTTER
    for width in widths:
        x.append(cursor)
        cursor += width + COL_GAP

    boxes, bands, top = {}, [], TOP
    for agent in lanes:
        members = [event for event in graph["events"] if event["agent_id"] == agent]
        stacks = defaultdict(int)
        for event in members:
            column = depth[event["id"]]
            boxes[event["id"]] = {
                "x": x[column],
                "w": widths[column],
                "y": top + LANE_PAD + stacks[column] * (NODE_H + ROW_GAP),
                "event": event,
            }
            stacks[column] += 1
        rows = max(stacks.values())
        height = rows * NODE_H + (rows - 1) * ROW_GAP + LANE_PAD * 2
        bands.append({"agent": agent, "y": top, "height": height})
        top += height

    return {
        "boxes": boxes, "bands": bands, "lanes": lanes, "x": x, "columns": columns,
        "width": cursor - COL_GAP + RIGHT_PAD, "height": top + 18,
    }


def svg(graph):
    plan = layout(graph)
    width, boxes = plan["width"], plan["boxes"]
    marks = []

    for index, band in enumerate(plan["bands"]):
        if index % 2 == 0:
            marks.append(
                f'<rect class="lane-band" x="0" y="{band["y"]}" '
                f'width="{width:.0f}" height="{band["height"]}"/>'
            )
        marks.append(f'<line class="lane-rule" x1="0" y1="{band["y"]}" x2="{width:.0f}" y2="{band["y"]}"/>')
        marks.append(
            f'<text class="lane-label" x="14" y="{band["y"] + band["height"] / 2 + 4:.0f}">'
            f'{escape(band["agent"].replace("_", " "))}</text>'
        )
    closing = plan["bands"][-1]["y"] + plan["bands"][-1]["height"]
    marks.append(f'<line class="lane-rule" x1="0" y1="{closing}" x2="{width:.0f}" y2="{closing}"/>')
    for index, left in enumerate(plan["x"]):
        label = "INPUT" if index == 0 else f"STEP {index}"
        marks.append(f'<text class="depth-tick" x="{left:.0f}" y="{TOP - 12}">{label}</text>')

    for edge in graph["edges"]:
        source, target = boxes[edge["source"]], boxes[edge["target"]]
        x1, y1 = source["x"] + source["w"], source["y"] + NODE_H / 2
        x2, y2 = target["x"], target["y"] + NODE_H / 2
        bend = max(26, (x2 - x1) * 0.45)
        marks.append(
            f'<path class="edge" d="M{x1:.0f} {y1:.0f} C{x1 + bend:.0f} {y1:.0f} '
            f'{x2 - bend:.0f} {y2:.0f} {x2 - 7:.0f} {y2:.0f}"/>'
        )
        marks.append(
            f'<polygon class="arrow" points="{x2 - 7:.0f},{y2 - 4:.0f} '
            f'{x2:.0f},{y2:.0f} {x2 - 7:.0f},{y2 + 4:.0f}"/>'
        )

    for identifier, box in boxes.items():
        event = box["event"]
        tone = "input" if event["type"] == "input" else ("up" if event["level"] == "increased" else "down")
        marks.append(
            f'<g class="node {tone}">'
            f'<rect x="{box["x"]:.0f}" y="{box["y"]}" width="{box["w"]:.0f}" height="{NODE_H}"/>'
            f'<text class="var" x="{box["x"] + PAD_X:.0f}" y="{box["y"] + 21}">{escape(event["variable"])}</text>'
            f'<text class="glyph" x="{box["x"] + box["w"] - PAD_X:.0f}" y="{box["y"] + 22}" '
            f'text-anchor="end">{GLYPHS[event["level"]]}</text>'
            f'<text class="eid" x="{box["x"] + 2:.0f}" y="{box["y"] - 4}">{escape(identifier)}</text>'
            f'</g>'
        )

    caption = (
        f'{graph["title"]}: {len(graph["events"])} events across {len(plan["lanes"])} agents, '
        f'{len(graph["edges"])} causal edges, {plan["columns"]} causal steps'
    )
    return (
        f'<svg viewBox="0 0 {width:.0f} {plan["height"]:.0f}" width="{width:.0f}" '
        f'role="img" aria-label="{escape(caption)}">{"".join(marks)}</svg>'
    )


def panel(graph):
    source = graph["source"]
    meta = [
        f'{len(graph["events"])} events',
        f'{len(graph["edges"])} edges',
        f'{len({event["agent_id"] for event in graph["events"]})} agents',
        f'p. {", ".join(map(str, source["pages"]))} · lines {", ".join(source["line_ranges"])}',
        f'evidence: {source["evidence"]}',
    ]
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


def main():
    parser = argparse.ArgumentParser(description="Render ground-truth pathway graphs as one page")
    parser.add_argument("--ground-truth", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()

    scenarios = load(arguments.ground_truth)
    page = TEMPLATE.read_text()
    for placeholder, value in {
        "__RAIL__": rail(scenarios),
        "__PANELS__": "".join(panel(graph) for graph in scenarios),
        "__MATRIX__": matrix(scenarios),
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
