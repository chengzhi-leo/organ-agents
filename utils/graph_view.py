from collections import defaultdict
from html import escape

NODE_H, ROW_GAP, LANE_PAD = 34, 10, 13
COL_GAP, GUTTER, RIGHT_PAD, TOP = 62, 146, 24, 30
CHAR, GLYPH, PAD_X = 6.95, 20, 13
GLYPHS = {"increased": "&#9650;", "decreased": "&#9660;"}

STYLE = """
.scroll { overflow-x: auto; }
.scroll svg { display: block; height: auto; }
.lane-band { fill: var(--sunken); }
.lane-rule { stroke: var(--line); stroke-width: 1; }
.lane-label { font: 11px system-ui, sans-serif; fill: var(--muted); letter-spacing: 0.05em; text-transform: uppercase; }
.depth-tick { font: 10px ui-monospace, monospace; fill: var(--muted); letter-spacing: 0.1em; }
.node rect { fill: var(--surface); stroke: var(--line); stroke-width: 1.25; rx: 3; }
.node.up rect { stroke: var(--up); fill: var(--up-soft); }
.node.down rect { stroke: var(--down); fill: var(--down-soft); }
.node.input rect { stroke: var(--accent); stroke-width: 2; fill: var(--accent-soft); }
.node text.var { font: 11.5px ui-monospace, SFMono-Regular, Menlo, monospace; fill: var(--ink); }
.node text.glyph { font: 13px system-ui, sans-serif; }
.node.up text.glyph { fill: var(--up); }
.node.down text.glyph { fill: var(--down); }
.node.input text.glyph { fill: var(--accent); }
.node text.eid { font: 9.5px ui-monospace, monospace; fill: var(--muted); }
.edge { fill: none; stroke: var(--muted); stroke-width: 1.4; opacity: 0.5; }
.edge.feedback { stroke-dasharray: 5 4; opacity: 0.8; }
.arrow { fill: var(--muted); }
.node:hover rect { stroke-width: 2.5; }
"""


def render_svg(events, edges, steps, labels, marker_id, caption):
    plan = _layout(events, steps)
    width, boxes = plan["width"], plan["boxes"]
    marks = [_marker(marker_id)]

    for index, band in enumerate(plan["bands"]):
        if index % 2 == 0:
            marks.append(
                f'<rect class="lane-band" x="0" y="{band["y"]}" '
                f'width="{width:.0f}" height="{band["height"]}"/>'
            )
        marks.append(
            f'<line class="lane-rule" x1="0" y1="{band["y"]}" '
            f'x2="{width:.0f}" y2="{band["y"]}"/>'
        )
        marks.append(
            f'<text class="lane-label" x="14" '
            f'y="{band["y"] + band["height"] / 2 + 4:.0f}">'
            f'{escape(band["agent"].replace("_", " "))}</text>'
        )
    closing = plan["bands"][-1]["y"] + plan["bands"][-1]["height"]
    marks.append(
        f'<line class="lane-rule" x1="0" y1="{closing}" '
        f'x2="{width:.0f}" y2="{closing}"/>'
    )
    for index, left in enumerate(plan["x"]):
        marks.append(
            f'<text class="depth-tick" x="{left:.0f}" y="{TOP - 12}">'
            f'{escape(labels[index])}</text>'
        )

    for edge in edges:
        source, target = boxes[edge["source"]], boxes[edge["target"]]
        path, feedback = _edge_path(source, target)
        style = "edge feedback" if feedback else "edge"
        marks.append(
            f'<path class="{style}" marker-end="url(#{marker_id})" d="{path}"/>'
        )

    for identifier, box in boxes.items():
        event = box["event"]
        tone = (
            "input"
            if event["type"] == "input"
            else "up" if event["level"] == "increased" else "down"
        )
        marks.append(
            f'<g class="node {tone}"><title>'
            f'{escape(identifier + ": " + event["agent_id"] + "." + event["variable"])}</title>'
            f'<rect x="{box["x"]:.0f}" y="{box["y"]}" '
            f'width="{box["w"]:.0f}" height="{NODE_H}"/>'
            f'<text class="var" x="{box["x"] + PAD_X:.0f}" '
            f'y="{box["y"] + 21}">{escape(event["variable"])}</text>'
            f'<text class="glyph" x="{box["x"] + box["w"] - PAD_X:.0f}" '
            f'y="{box["y"] + 22}" text-anchor="end">{GLYPHS[event["level"]]}</text>'
            f'<text class="eid" x="{box["x"] + 2:.0f}" '
            f'y="{box["y"] - 4}">{escape(identifier)}</text></g>'
        )

    return (
        f'<div class="scroll"><svg viewBox="0 0 {width:.0f} {plan["height"]:.0f}" '
        f'width="{width:.0f}" role="img" aria-label="{escape(caption)}">'
        f'{"".join(marks)}</svg></div>'
    )


def _layout(events, steps):
    event_ids = {event["id"] for event in events}
    if missing := event_ids - steps.keys():
        raise ValueError(f"missing graph steps for events: {sorted(missing)}")

    rank = {}
    for index, event in enumerate(events):
        rank.setdefault(event["agent_id"], (steps[event["id"]], index))
    lanes = sorted(rank, key=rank.get)

    columns = max(steps.values()) + 1
    widths = [0.0] * columns
    for event in events:
        span = max(132, len(event["variable"]) * CHAR + GLYPH + PAD_X * 2)
        column = steps[event["id"]]
        widths[column] = max(widths[column], span)

    x, cursor = [], GUTTER
    for width in widths:
        x.append(cursor)
        cursor += width + COL_GAP

    boxes, bands, top = {}, [], TOP
    for agent in lanes:
        members = [event for event in events if event["agent_id"] == agent]
        stacks = defaultdict(int)
        for event in members:
            column = steps[event["id"]]
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
        "boxes": boxes,
        "bands": bands,
        "x": x,
        "width": cursor - COL_GAP + RIGHT_PAD,
        "height": top + 18,
    }


def _edge_path(source, target):
    y1 = source["y"] + NODE_H / 2
    y2 = target["y"] + NODE_H / 2
    if source["x"] < target["x"]:
        x1 = source["x"] + source["w"]
        x2 = target["x"]
        bend = max(26, (x2 - x1) * 0.45)
        return (
            f"M{x1:.0f} {y1:.0f} C{x1 + bend:.0f} {y1:.0f} "
            f"{x2 - bend:.0f} {y2:.0f} {x2:.0f} {y2:.0f}",
            False,
        )
    if source["x"] > target["x"]:
        x1 = source["x"]
        x2 = target["x"] + target["w"]
        bend = max(26, (x1 - x2) * 0.45)
        return (
            f"M{x1:.0f} {y1:.0f} C{x1 - bend:.0f} {y1:.0f} "
            f"{x2 + bend:.0f} {y2:.0f} {x2:.0f} {y2:.0f}",
            True,
        )
    x1 = source["x"] + source["w"]
    x2 = target["x"] + target["w"]
    bow = max(x1, x2) + 28
    return (
        f"M{x1:.0f} {y1:.0f} C{bow:.0f} {y1:.0f} "
        f"{bow:.0f} {y2:.0f} {x2:.0f} {y2:.0f}",
        True,
    )


def _marker(marker_id):
    return (
        f'<defs><marker id="{escape(marker_id)}" viewBox="0 0 9 9" refX="8" refY="4.5" '
        f'markerWidth="5.5" markerHeight="5.5" orient="auto">'
        f'<path class="arrow" d="M0,0 L9,4.5 L0,9 z"/></marker></defs>'
    )
