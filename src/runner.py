from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

from src.schemas import FLIP, Event


class Runner:
    def __init__(self, router, tracker, llm, config, enforce_vocabulary):
        self.router = router
        self.tracker = tracker
        self.llm = llm
        self.max_rounds = config["max_rounds"]
        self.max_llm_calls = config["max_llm_calls"]
        self.workers = config["workers"]
        self.enforce_vocabulary = enforce_vocabulary
        self.next_event_id = 1

    def run(self, perturbation):
        if perturbation.type != "input":
            raise ValueError("runner perturbation must have type 'input'")
        self.next_event_id = 1
        self.tracker.begin(perturbation)
        events = [perturbation]

        for index in range(self.max_rounds):
            mark = len(self.llm.log)
            active, closures = self._partition(events, perturbation)
            bundles, dropped = self._dispatch(active)
            self.tracker.begin_round(
                index,
                bundles,
                dropped,
                closures,
                self.llm.log[mark:],
            )

            if not bundles:
                if closures and not active:
                    return "homeostatic_closure"
                return "no_routed_events"
            pending_calls = sum(leaf.uses_llm for leaf in bundles)
            if len(self.llm.log) + pending_calls > self.max_llm_calls:
                return "max_llm_calls"

            events = self._react(bundles, index)

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

    def _dispatch(self, events):
        routes = self.router.route(events)
        bundles, dropped = defaultdict(list), []
        for event in events:
            leaves = routes[event.key]
            if not leaves:
                dropped.append(event)
                continue
            for leaf in leaves:
                bundles[leaf].append(event)
        return bundles, dropped

    def _react(self, bundles, index):
        batches = sorted(bundles.items(), key=lambda batch: batch[0].id)

        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            reactions = list(pool.map(lambda batch: batch[0].react(batch[1]), batches))

        emitted = []
        for (leaf, incoming), reaction in zip(batches, reactions):
            events = self._events(leaf, incoming, reaction.changes, index + 1)
            self.tracker.record(index, leaf, incoming, events, reaction.trace)
            emitted.extend(events)
        return emitted

    def _events(self, leaf, incoming, changes, round_index):
        incoming_ids = {event.id for event in incoming}
        events = []
        for change in changes:
            if self.enforce_vocabulary and change.variable not in leaf.variables:
                raise ValueError(
                    f"'{leaf.id}' returned variable '{change.variable}' outside its vocabulary"
                )
            if change.caused_by not in incoming_ids:
                raise ValueError(
                    f"'{leaf.id}' cited event '{change.caused_by}' that it did not receive"
                )
            events.append(Event(
                id=f"e{self.next_event_id}",
                agent_id=leaf.id,
                variable=change.variable,
                level=change.level,
                type="response",
                caused_by=change.caused_by,
                round=round_index,
                generated_by=leaf.id,
            ))
            self.next_event_id += 1
        return events
