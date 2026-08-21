import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from model_graph import ModelGraph
from src.pathway import agent_edges

LEVELS = {1: "increased", -1: "decreased"}


def counterparts(equation):
    stripped = equation.removeprefix("-(").removesuffix(")")
    return {equation, f"-({equation})", stripped, f"-({stripped})"}


class Anchors:
    def __init__(self, graph, variables, fluxes, live):
        self.graph = graph
        self.live = live
        self.by_equation = defaultdict(set)
        for quantity in graph.quantities.values():
            for formula in quantity.rhs:
                self.by_equation[graph.formulas[formula].equation].add(quantity.id)

        self.anchors = {}
        self.carried = {}
        for name, specification in variables.items():
            if "structure" in specification:
                self.anchors[name] = self._pool(name, specification["structure"])
            elif name in fluxes:
                self.anchors[name] = self._flux(fluxes[name])
            else:
                raise ValueError(f"'{name}' declares no structure and is not an exposed output")

    def _pool(self, name, pattern):
        owned = {
            quantity.id for quantity in self.graph.quantities.values()
            if quantity.kind == "species" and re.search(pattern, quantity.path)
        }
        if not owned:
            raise ValueError(f"'{name}' structure pattern matches no species")
        owned = self._derived(owned & self.live)
        self.carried[name] = set()
        return {
            "owned": owned,
            "inputs": set().union(*(self.graph.consumes[node] for node in owned)) - owned,
            "outputs": set().union(*(self.graph.produces[node] for node in owned)) - owned,
        }

    def _derived(self, owned):
        pool, growing = set(owned), True
        while growing:
            growing = False
            for identifier, quantity in self.graph.quantities.items():
                if identifier in pool or quantity.rhs:
                    continue
                sources = self.graph.consumes[identifier]
                if not sources & pool:
                    continue
                if all(source in pool or source not in self.live for source in sources):
                    pool.add(identifier)
                    growing = True
        return pool

    def _flux(self, output):
        if "parameter" in output:
            quantity = self.graph.by_path(output["parameter"])
            self.carried[output["variable"]] = set()
            return {
                "owned": set(),
                "inputs": set(self.graph.formulas[quantity.formula].references.values()),
                "outputs": set(self.graph.produces[quantity.id]),
            }

        species = self.graph.by_path(output["species"])
        matched = [
            formula for formula in species.rhs
            if self.graph.formulas[formula].equation == output["equation"]
        ]
        if len(matched) != 1:
            raise ValueError(
                f"'{output['variable']}' matched {len(matched)} terms of {output['species']}"
            )
        acts_on = set().union(*(
            self.by_equation[equation] for equation in counterparts(output["equation"])
        ))
        self.carried[output["variable"]] = {
            (source, target)
            for target in acts_on
            for formula in self.graph.quantities[target].rhs
            if self.graph.formulas[formula].equation in counterparts(output["equation"])
            for source in self.graph.formulas[formula].references.values()
        }
        return {
            "owned": set(),
            "inputs": set(self.graph.formulas[matched[0]].references.values()),
            "outputs": acts_on,
        }

    def edges(self):
        owned = {name: anchor["owned"] for name, anchor in self.anchors.items()}
        found = []
        for source in self.anchors:
            for target in self.anchors:
                if source == target:
                    continue
                blocked = set().union(*(
                    nodes for name, nodes in owned.items() if name not in (source, target)
                ))
                severed = set().union(*(
                    edges for name, edges in self.carried.items() if name not in (source, target)
                ))
                goal = owned[target] or self.anchors[target]["inputs"]
                if self._reaches(self.anchors[source]["outputs"], goal, blocked, severed):
                    found.append((source, target))
        return found

    def _reaches(self, start, goal, blocked, severed):
        frontier = [node for node in start if node in self.live and node not in blocked]
        if goal & set(frontier):
            return True
        seen = set(frontier)
        while frontier:
            emerged = []
            for node in frontier:
                for downstream in self.graph.produces[node]:
                    if downstream in blocked or downstream in seen:
                        continue
                    if downstream not in self.live or (node, downstream) in severed:
                        continue
                    if downstream in goal:
                        return True
                    seen.add(downstream)
                    emerged.append(downstream)
            frontier = emerged
        return False


def events(trajectories, variables, detection):
    series = defaultdict(list)
    for row in trajectories:
        series[row["variable"]].append((float(row["time"]), float(row["value"])))

    detected = {}
    for name, specification in variables.items():
        samples = sorted(series[name])
        marks = [(time, specification["sign"] * value) for time, value in samples]
        detected[name] = [
            {
                "variable": name,
                "level": LEVELS[1 if extremum[1] > anchor[1] else -1],
                "onset": anchor[0],
                "end": extremum[0],
                "amplitude": extremum[1] - anchor[1],
            }
            for anchor, extremum in _phases(
                marks, _cutoff(specification["threshold"], marks[0][1]), detection["amplitude"]
            )
        ]
    return detected


def _cutoff(threshold, baseline):
    if threshold["mode"] == "relative":
        return threshold["value"] * abs(baseline)
    if threshold["mode"] == "absolute":
        return threshold["value"]
    raise ValueError(f"unknown threshold mode '{threshold['mode']}'")


def _phases(marks, cutoff, amplitude):
    turns = [0]
    for index in range(1, len(marks) - 1):
        if (marks[index][1] < marks[index + 1][1]) != (marks[index - 1][1] < marks[index][1]):
            turns.append(index)
    turns.append(len(marks) - 1)

    spans = [(marks[start], marks[stop]) for start, stop in zip(turns, turns[1:])]
    peak = max(abs(extremum[1] - anchor[1]) for anchor, extremum in spans)
    if peak < cutoff:
        return []

    kept = []
    for anchor, extremum in spans:
        if abs(extremum[1] - anchor[1]) >= amplitude * peak:
            kept.append((anchor, extremum))
        elif kept:
            break
    return kept


def build(structural, detected, variables, perturbation):
    edges = []
    for source, target in structural:
        for cause, effect in zip(detected[source], _responses(detected[target], perturbation)):
            edges.append({
                "from": cause["variable"],
                "from_level": cause["level"],
                "from_agent": variables[source]["owners"][0],
                "to": effect["variable"],
                "to_level": effect["level"],
                "agent": variables[target]["owners"][0],
                "round": int(effect["onset"]),
            })
    return edges


def _responses(phases, perturbation):
    rooted = phases and (phases[0]["variable"], phases[0]["level"]) == perturbation
    return phases[1:] if rooted else phases


def main():
    parser = argparse.ArgumentParser(description="Build a ground-truth pathway from a simulator run")
    parser.add_argument("--run", required=True)
    parser.add_argument("--evaluation", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--variable", required=True)
    parser.add_argument("--level", required=True, choices=["decreased", "increased"])
    arguments = parser.parse_args()

    run = Path(arguments.run)
    manifest = json.loads((run / "manifest.json").read_text())
    scenario = manifest["scenario"]
    evaluation = yaml.safe_load(Path(arguments.evaluation).read_text())
    variables = evaluation["variables"]

    graph = ModelGraph(manifest["model_path"])
    live = graph.dynamic()

    fluxes = {output["variable"]: output for output in scenario["exposed_outputs"]}
    anchors = Anchors(graph, variables, fluxes, live)
    structural = anchors.edges()

    with (run / "trajectories.csv").open() as handle:
        detected = events(list(csv.DictReader(handle)), variables, evaluation["detection"])

    perturbation = (arguments.variable, arguments.level)
    rooted = detected[arguments.variable]
    if not rooted or (rooted[0]["variable"], rooted[0]["level"]) != perturbation:
        raise ValueError(f"{arguments.variable} does not open this run {arguments.level}")

    edges = build(structural, detected, variables, perturbation)
    pathway = {
        "scenario": scenario["id"],
        "perturbation": {"variable": arguments.variable, "level": arguments.level},
        "active_events": [event for name in variables for event in detected[name]],
        "structural_edges": [{"from": source, "to": target} for source, target in structural],
        "variable_edges": edges,
        "agent_edges": agent_edges(edges),
    }
    Path(arguments.output).write_text(json.dumps(pathway, indent=2, ensure_ascii=False))

    print(f"live quantities  : {len(live)} of {len(graph.quantities)}")
    print(f"structural edges : {len(structural)} of {len(variables) * (len(variables) - 1)} pairs")
    print(f"active events    : {sum(len(detected[name]) for name in variables)}")
    print(f"active edges     : {len(edges)}")
    print(f"written          : {arguments.output}")


if __name__ == "__main__":
    main()
