from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from src.body import Body
from src.pathway import build
from src.schemas import FLIP, INPUT_NODE, Event, OutputState


@dataclass
class Message:
    event: Event
    source_node_id: str


@dataclass
class ForwardResult:
    pathway: dict
    outputs: list[OutputState]
    termination: str
    trace: dict
    calls: list

    def dump(self):
        return {
            "termination": self.termination,
            "outputs": [output.model_dump() for output in self.outputs],
            "rounds": len(self.trace["rounds"]),
            "reactions": len(self.trace["records"]),
        }

    def critic_dump(self):
        events = {event["id"]: event for event in self.trace["events"]}
        return {
            **self.dump(),
            "rounds": [
                {
                    "round": entry["round"],
                    "dispatch": entry["dispatch"],
                    "dropped": entry["dropped"],
                    "homeostatic_closures": entry["homeostatic_closures"],
                    "not_reexpanded": entry["not_reexpanded"],
                }
                for entry in self.trace["rounds"]
            ],
            "reactions": [
                {
                    "round": record["round"],
                    "agent": record["agent"],
                    "incoming": [event_state(events[event_id]) for event_id in record["incoming"]],
                    "emitted": [event_state(events[event_id]) for event_id in record["events"]],
                }
                for record in self.trace["records"]
            ],
        }


class ForwardRunner:
    def __init__(self, graph, body, llm, schema, config):
        self.graph = graph
        self.body = body
        self.llm = llm
        self.schema = schema
        self.max_rounds = config["max_rounds"]
        self.max_llm_calls = config["max_llm_calls"]
        self.workers = config["workers"]
        for name, value in (
            ("max_rounds", self.max_rounds),
            ("max_llm_calls", self.max_llm_calls),
            ("workers", self.workers),
        ):
            if value <= 0:
                raise ValueError(f"forward.{name} must be positive")
        self.agents = {agent.id: agent for agent in body.agents}
        self.successors = defaultdict(list)
        for edge in graph.edges:
            self.successors[edge.source].append(edge.target)
        self.next_event_id = 1
        self.expanded = set()
        self.events = {}
        self.normalizations = []
        self.rounds = []
        self.records = []
        self.calls = []
        self.call_start = 0

    def run(self, perturbation):
        if perturbation.type != "input":
            raise ValueError("forward perturbation must have type 'input'")
        self.call_start = self.llm.call_count
        self.events[perturbation.id] = perturbation
        frontier = [self._normalize(Message(perturbation, INPUT_NODE))]

        for index in range(self.max_rounds):
            candidates, closures = self._partition(frontier, perturbation)
            active, not_reexpanded = self._novel(candidates)
            bundles, dispatch, dropped = self._dispatch(active)
            self.rounds.append({
                "round": index,
                "dispatch": dispatch,
                "dropped": [message.event.id for message in dropped],
                "homeostatic_closures": [message.event.id for message in closures],
                "not_reexpanded": [message.event.id for message in not_reexpanded],
            })

            if not bundles:
                if closures and not active:
                    return self._result("homeostatic_closure")
                if not_reexpanded and not active:
                    return self._result("no_novel_events")
                return self._result("no_graph_successors")
            if self._used_calls() + len(bundles) > self.max_llm_calls:
                return self._result("max_llm_calls")

            emitted = self._react(bundles, index)
            frontier = [self._normalize(message) for message in emitted]

        return self._result("max_rounds")

    def _partition(self, messages, perturbation):
        closures = [
            message
            for message in messages
            if message.event.type == "response"
            and message.event.variable == perturbation.variable
            and message.event.level == FLIP[perturbation.level]
        ]
        closure_ids = {message.event.id for message in closures}
        active = [message for message in messages if message.event.id not in closure_ids]
        return active, closures

    def _novel(self, messages):
        active = []
        not_reexpanded = []
        for message in messages:
            event = message.event
            expansion_key = message.source_node_id, event.type, event.key
            if expansion_key in self.expanded:
                not_reexpanded.append(message)
                continue
            self.expanded.add(expansion_key)
            active.append(message)
        return active, not_reexpanded

    def _dispatch(self, messages):
        bundles = defaultdict(list)
        decisions = []
        dropped = []
        for message in messages:
            target_ids = self.successors.get(message.source_node_id, [])
            decisions.append({
                "event": message.event.id,
                "source_node": message.source_node_id,
                "target_agents": list(target_ids),
            })
            if not target_ids:
                dropped.append(message)
                continue
            for target_id in target_ids:
                bundles[self.agents[target_id]].append(message.event)
        dispatch = {
            agent.id: [event.id for event in events]
            for agent, events in sorted(bundles.items(), key=lambda item: item[0].id)
        }
        return bundles, {"decisions": decisions, "bundles": dispatch}, dropped

    def _react(self, bundles, index):
        batches = sorted(bundles.items(), key=lambda item: item[0].id)
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            reactions = list(pool.map(lambda batch: batch[0].react(batch[1]), batches))

        emitted = []
        for (agent, incoming), reaction in zip(batches, reactions):
            messages = self._messages(agent, incoming, reaction.changes)
            self.calls.append(reaction.trace)
            self.records.append({
                "round": index,
                "agent": agent.id,
                "incoming": [event.id for event in incoming],
                "events": [message.event.id for message in messages],
                "trace": reaction.trace.dump(),
            })
            emitted.extend(messages)
        return emitted

    def _messages(self, component, incoming, changes):
        incoming_by_id = {event.id: event for event in incoming}
        messages = []
        for change in changes:
            if change.variable not in component.owned_variables:
                raise ValueError(
                    f"'{component.id}' returned variable '{change.variable}' that it does not own"
                )
            if change.caused_by not in incoming_by_id:
                raise ValueError(
                    f"'{component.id}' cited event '{change.caused_by}' that it did not receive"
                )
            event = self._event(component.id, change, incoming_by_id[change.caused_by])
            messages.append(Message(event, component.id))
        return messages

    def _normalize(self, message):
        current = message
        translated = False
        while True:
            change = self.body.translator.translate(current.event)
            if change is None:
                if not translated:
                    self.normalizations.append({
                        "source": current.event.id,
                        "result": current.event.id,
                        "translated": False,
                    })
                return current
            result = self._event(self.body.translator.id, change, current.event)
            self.normalizations.append({
                "source": current.event.id,
                "result": result.id,
                "translated": True,
            })
            current = Message(result, message.source_node_id)
            translated = True

    def _event(self, agent_id, change, cause):
        event = Event(
            id=f"e{self.next_event_id}",
            agent_id=agent_id,
            variable=change.variable,
            level=change.level,
            type="response",
            caused_by=cause.id,
            round=cause.round + 1,
        )
        self.next_event_id += 1
        self.events[event.id] = event
        return event

    def _used_calls(self):
        return self.llm.call_count - self.call_start

    def _result(self, termination):
        events = list(self.events.values())
        pathway = build(self.graph.scenario_id, events, self.schema)
        outputs = terminal_outputs(events)
        trace = {
            "events": [event.trace_dump() for event in self.events.values()],
            "normalizations": self.normalizations,
            "rounds": self.rounds,
            "records": self.records,
        }
        return ForwardResult(pathway, outputs, termination, trace, self.calls)


def run(graph, scenario, schema, llm, knowledge_dir, config):
    body = Body(schema, llm, knowledge_dir, graph.nodes)
    perturbation = Event(
        id="e0",
        agent_id=scenario.input.agent_id,
        variable=scenario.input.variable,
        level=scenario.input.level,
        type="input",
        caused_by=None,
        round=0,
    )
    return ForwardRunner(graph, body, llm, schema, config).run(perturbation)


def terminal_outputs(events):
    causal_sources = {event.caused_by for event in events if event.caused_by is not None}
    outputs = []
    found = set()
    for event in events:
        if event.type != "response" or event.id in causal_sources or event.key in found:
            continue
        found.add(event.key)
        outputs.append(OutputState(
            agent_id=event.agent_id,
            variable=event.variable,
            level=event.level,
        ))
    return outputs


def event_state(event):
    return {
        "agent_id": event["agent_id"],
        "variable": event["variable"],
        "level": event["level"],
    }
