from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

from src.schemas import FLIP, Event


class Runner:
    def __init__(self, translator, router, tracker, llm, config):
        self.translator = translator
        self.router = router
        self.tracker = tracker
        self.llm = llm
        self.max_rounds = config["max_rounds"]
        self.max_llm_calls = config["max_llm_calls"]
        self.workers = config["workers"]
        for name, value in (
            ("max_rounds", self.max_rounds),
            ("max_llm_calls", self.max_llm_calls),
            ("workers", self.workers),
        ):
            if value <= 0:
                raise ValueError(f"simulation.{name} must be positive")
        self.next_event_id = 1
        self.expanded = set()

    def run(self, perturbation):
        if perturbation.type != "input":
            raise ValueError("runner perturbation must have type 'input'")
        self.next_event_id = 1
        self.expanded = set()
        self.tracker.begin(perturbation)
        events = self._translate([perturbation])
        reference = events[0]

        for index in range(self.max_rounds):
            candidates, closures = self._partition(events, reference)
            active, not_reexpanded = self._novel(candidates)
            if self.llm.call_count + self.router.required_calls(active) > self.max_llm_calls:
                return "max_llm_calls"
            routing = self.router.route(active)
            bundles, dropped = self._dispatch(active, routing.routes)
            self.tracker.begin_round(
                index,
                routing,
                bundles,
                dropped,
                closures,
                not_reexpanded,
            )

            if not bundles:
                if closures and not active:
                    return "homeostatic_closure"
                if not_reexpanded and not active:
                    return "no_novel_events"
                return "no_routed_events"
            pending_calls = len(bundles)
            if self.llm.call_count + pending_calls > self.max_llm_calls:
                return "max_llm_calls"

            events = self._translate(self._react(bundles, index))

        return "max_rounds"

    @staticmethod
    def _partition(events, perturbation):
        closures = [
            event
            for event in events
            if event.type == "response"
            and event.variable == perturbation.variable
            and event.level == FLIP[perturbation.level]
        ]
        closure_ids = {event.id for event in closures}
        active = [event for event in events if event.id not in closure_ids]
        return active, closures

    def _novel(self, events):
        active = []
        not_reexpanded = []
        for event in events:
            expansion_key = event.type, event.key
            if expansion_key in self.expanded:
                not_reexpanded.append(event)
                continue
            self.expanded.add(expansion_key)
            active.append(event)
        return active, not_reexpanded

    @staticmethod
    def _dispatch(events, routes):
        bundles, dropped = defaultdict(list), []
        for event in events:
            agents = routes[event.id]
            if not agents:
                dropped.append(event)
                continue
            for agent in agents:
                bundles[agent].append(event)
        return bundles, dropped

    def _react(self, bundles, index):
        batches = sorted(bundles.items(), key=lambda batch: batch[0].id)

        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            reactions = list(pool.map(lambda batch: batch[0].react(batch[1]), batches))

        emitted = []
        for (agent, incoming), reaction in zip(batches, reactions):
            events = self._events(agent, incoming, reaction.changes)
            self.tracker.record(index, agent, incoming, events, reaction.trace)
            emitted.extend(events)
        return emitted

    def _events(self, component, incoming, changes):
        incoming_by_id = {event.id: event for event in incoming}
        events = []
        for change in changes:
            if change.variable not in component.owned_variables:
                raise ValueError(
                    f"'{component.id}' returned variable '{change.variable}' that it does not own"
                )
            if change.caused_by not in incoming_by_id:
                raise ValueError(
                    f"'{component.id}' cited event '{change.caused_by}' that it did not receive"
                )
            cause = incoming_by_id[change.caused_by]
            events.append(Event(
                id=f"e{self.next_event_id}",
                agent_id=component.id,
                variable=change.variable,
                level=change.level,
                type="response",
                caused_by=change.caused_by,
                round=cause.round + 1,
            ))
            self.next_event_id += 1
        return events

    def _translate(self, events):
        normalized = []
        for event in events:
            change = self.translator.translate(event)
            if change is None:
                self.tracker.record_normalization(event, event)
                normalized.append(event)
                continue
            translated = self._events(self.translator, [event], [change])[0]
            self.tracker.record_normalization(event, translated)
            normalized.append(translated)
        return normalized
