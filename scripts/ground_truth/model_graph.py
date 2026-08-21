from collections import defaultdict
from dataclasses import dataclass, field
from xml.etree import ElementTree

NAMESPACE = "{http://www.systems-biology.com}"


@dataclass
class Quantity:
    id: str
    path: str
    kind: str
    formula: str | None
    rhs: list = field(default_factory=list)


@dataclass
class Formula:
    id: str
    equation: str
    references: dict


class ModelGraph:
    def __init__(self, path):
        root = ElementTree.parse(path).getroot()
        self.quantities = {}
        self.formulas = {}

        for element in root.iter():
            tag = element.tag.removeprefix(NAMESPACE)
            if tag in ("V", "P", "Observer"):
                self._add_quantity(tag, element)
            elif tag == "ExplicitFormula":
                self._add_formula(element)

        self.produces = defaultdict(set)
        self.consumes = defaultdict(set)
        for quantity in self.quantities.values():
            for formula in self._defining(quantity):
                for source in self.formulas[formula].references.values():
                    if source in self.quantities:
                        self.produces[source].add(quantity.id)
                        self.consumes[quantity.id].add(source)

    def _add_quantity(self, tag, element):
        identifier = element.get("id")
        self.quantities[identifier] = Quantity(
            identifier,
            element.get("path"),
            {"V": "species", "P": "parameter", "Observer": "observer"}[tag],
            element.get("formulaId"),
            [child.get("id") for child in element.iter(f"{NAMESPACE}RHSFormula")],
        )

    def _add_formula(self, element):
        equation = element.findtext(f"{NAMESPACE}Equation") or ""
        references = {
            child.get("alias"): child.get("id")
            for child in element.iter(f"{NAMESPACE}R")
        }
        self.formulas[element.get("id")] = Formula(element.get("id"), equation, references)

    def _defining(self, quantity):
        formulas = list(quantity.rhs)
        if quantity.formula:
            formulas.append(quantity.formula)
        return [formula for formula in formulas if formula in self.formulas]

    def dynamic(self):
        seeds = {
            identifier for identifier, quantity in self.quantities.items()
            if quantity.kind == "species" and quantity.rhs
        }
        reached, frontier = set(seeds), list(seeds)
        while frontier:
            emerged = []
            for identifier in frontier:
                for target in self.produces[identifier]:
                    if target not in reached:
                        reached.add(target)
                        emerged.append(target)
            frontier = emerged
        return reached

    def by_path(self, path):
        matches = [q for q in self.quantities.values() if q.path.endswith(path)]
        if len(matches) != 1:
            raise ValueError(f"'{path}' matches {len(matches)} quantities")
        return matches[0]
