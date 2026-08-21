from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

from src.schemas import Event


class Runner:
    def __init__(self, body, router, tracker, llm, config):
        self.body = body
        self.router = router
        self.tracker = tracker
        self.llm = llm
        self.max_rounds = config["max_rounds"]
        self.max_llm_calls = config["max_llm_calls"]
        self.workers = config["workers"]

    def run(self, perturbation):
        self.tracker.begin(perturbation)
        events = [perturbation]
        visited = set()

        for index in range(self.max_rounds):
            mark = len(self.llm.log)
            bundles, dropped = self._dispatch(events, visited)
            self.tracker.begin_round(index, bundles, dropped, self.llm.log[mark:])

            if not bundles:
                return "no_unvisited_events"
            if len(self.llm.log) + len(bundles) > self.max_llm_calls:
                return "max_llm_calls"

            events = self._react(bundles, index, visited)

        return "max_rounds"

    def _dispatch(self, events, visited):
        routes = self.router.route(events)
        bundles, dropped = defaultdict(list), []
        for event in events:
            leaves = routes[event.key]
            if not leaves:
                dropped.append(event)
                continue
            for leaf in leaves:
                key = (leaf.id, event.variable, event.level)
                if key not in visited:
                    visited.add(key)
                    bundles[leaf].append(event)
        return bundles, dropped

    def _react(self, bundles, index, visited):
        batches = sorted(bundles.items(), key=lambda batch: batch[0].id)
        registry = self.body.registry

        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            reactions = list(pool.map(lambda batch: batch[0].react(batch[1], registry), batches))

        events = []
        for (leaf, incoming), reaction in zip(batches, reactions):
            local, foreign = self._localize(leaf, reaction.effects, set(registry))
            self.tracker.record(index, leaf, incoming, local, foreign, reaction.trace)
            for effect in local:
                visited.add((leaf.id, effect.variable, effect.level))
                events.append(
                    Event(effect.variable, effect.level, leaf.id, tuple(effect.caused_by), index + 1)
                )
        return events

    @staticmethod
    def _localize(leaf, effects, registry):
        local, foreign = [], []
        for effect in effects:
            owned = effect.variable in leaf.variables or effect.variable not in registry
            (local if owned else foreign).append(effect)
        return local, foreign
