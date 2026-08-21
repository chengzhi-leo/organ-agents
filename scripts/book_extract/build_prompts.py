import argparse
import json
from collections import defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]

SYSTEM_PROMPT = """You extract local physiological knowledge from one chapter of a medical textbook.

Every module in the target model is a local dynamical system, and the knowledge it needs is exactly
the four things such a system is made of:

  State     what the module owns and can change: processes, fluxes, stores, and the activities of
            its own receptors, transporters, enzymes, and channels
  Inputs    what reaches the module, and how it senses what reaches it
  Dynamics  how its state changes when its inputs change, and through what machinery
  Outputs   which of its state changes the rest of the body can observe

You are writing for an agent that has to reason about interventions this chapter never mentions.
That single requirement decides everything below.

# What each section holds

State. Name the processes, fluxes, and stores, with the numbers the chapter gives: basal rates,
capacities, normal values, thresholds. Then name the activities of the specific receptors,
transporters, enzymes, and channels the module contains. Those activities are what a drug or a
mutation acts on; a module that does not own them cannot be perturbed at all. Add prose for
structural facts such as cell types, zonation, and compartments.

Inputs. List what arrives, then say in prose how it is sensed: receptor subtype, transporter and its
kinetics, anatomical exposure, innervation. "Hepatocytes carry beta-adrenergic receptors" and "GLUT2
is bidirectional, high-Km, and insulin-independent" belong here, because that is where a beta-blocker
and a transport inhibitor act.

Dynamics. Prose. Every statement says through what. Write "insulin inactivates phosphorylase and
induces glucokinase (Km about 10 mM), so glycogenolysis stops while glucose uptake continues", not
"insulin reduces hepatic glucose production". The first lets a reader work out what a glucokinase
inhibitor would do; the second does not. Keep conditions and timescales inside the sentence they
qualify: fed versus fasting, acute versus chronic, fast versus slow, saturable, dose-dependent.

Outputs. What the module releases, secretes, or clears, by route, with rates when the chapter gives
them.

# What not to write

Do not reduce a mechanism to a signed edge. "A increases B" is the one form this extraction exists to
avoid.

Do not follow a change past the edge of the module. Stop at "the liver releases glucose". Do not
continue with "so blood glucose rises, so insulin is secreted" - a different module owns that, and
the model works it out at run time. Feedback loops that leave the module are never yours to write.

Do not add biology the chapter does not state, and do not summarise detail away. Molecular names,
numbers, and qualifying conditions are the point of the exercise, not decoration.

# Attribution

A chapter almost always describes several modules, and often describes a downstream module's response
at length. Put that material under the downstream module's own name. Never discard it, and never file
it under the module the chapter happens to be titled after. Use only module ids from the list you are
given.

# Format

For each module this chapter contributes to:

## MODULE: <module_id>

### State
### Inputs
### Dynamics
### Outputs

Everything you write comes from this one chapter, so do not cite it. Drop a section if the chapter
says nothing about it, drop a module if the chapter says nothing about it, and output nothing else."""


def load(path):
    return yaml.safe_load((ROOT / path).read_text())


def check(profile, chapters):
    ids = [module["id"] for module in profile["modules"]]
    duplicates = {id for id in ids if ids.count(id) > 1}
    if duplicates:
        raise ValueError(f"duplicate module ids: {sorted(duplicates)}")
    known = set(chapters)
    for module in profile["modules"]:
        unknown = set(module["primary"] + module["supporting"]) - known
        if unknown:
            raise ValueError(f"module '{module['id']}' cites missing chapters {sorted(unknown)}")
        if not module["primary"]:
            raise ValueError(f"module '{module['id']}' has no primary chapter")


def assignments(profile):
    mapping = defaultdict(dict)
    for module in profile["modules"]:
        for role in ("primary", "supporting"):
            for number in module[role]:
                mapping[number].setdefault(module["id"], role)
    return mapping


def strip_frontmatter(text):
    if not text.startswith("---\n"):
        raise ValueError("chapter file has no frontmatter")
    return text.split("\n---\n", 1)[1].lstrip("\n")


def build_prompt(profile, chapter, roles, text):
    listing = "\n".join(
        f"{'*' if module['id'] in roles else ' '} {module['id']} - {module['description']}"
        for module in profile["modules"]
    )
    return (
        f"Book: {chapter['book']}\n"
        f"Unit: {chapter['unit']}\n"
        f"Chapter {chapter['number']}: {chapter['title']}\n\n"
        f"Available modules. This chapter is expected to contribute to the starred ones, but write to"
        f" any module the chapter genuinely describes:\n{listing}\n\n"
        f"Chapter text:\n\n{text}"
    )


def main():
    parser = argparse.ArgumentParser(description="Build knowledge hierarchy and extraction prompts")
    parser.add_argument("profile")
    parser.add_argument("--chapters", nargs="+", type=int)
    args = parser.parse_args()

    profile = load(args.profile)
    book = load(profile["book"])
    index = json.loads((ROOT / book["output"] / "index.json").read_text())
    chapters = {chapter["number"]: chapter for chapter in index["chapters"]}

    check(profile, chapters)
    mapping = assignments(profile)

    output = ROOT / profile["output"]
    prompts = output / "prompts"
    prompts.mkdir(parents=True, exist_ok=True)
    (prompts / "system.txt").write_text(SYSTEM_PROMPT + "\n")

    hierarchy = {
        "book": index["book"],
        "groups": sorted({module["group"] for module in profile["modules"]}),
        "modules": profile["modules"],
        "chapters": {
            str(number): {
                "title": chapters[number]["title"],
                "characters": chapters[number]["characters"],
                "modules": roles,
            }
            for number, roles in sorted(mapping.items())
        },
        "scenarios": {str(number): chapters[number]["title"] for number in profile["scenarios"]},
    }
    (output / "hierarchy.json").write_text(json.dumps(hierarchy, indent=2, ensure_ascii=False))

    selected = args.chapters or sorted(mapping)
    for number in selected:
        if number not in mapping:
            raise ValueError(f"chapter {number} is not mapped to any module")
        chapter = dict(chapters[number], book=index["book"])
        text = strip_frontmatter((ROOT / book["output"] / chapter["file"]).read_text())
        user = build_prompt(profile, chapter, mapping[number], text)
        (prompts / f"ch{number:02d}.txt").write_text(user + "\n")
        print(f"ch{number:02d}  {len(SYSTEM_PROMPT) + len(user):7d} chars  ->  {', '.join(mapping[number])}")

    unmapped = sorted(set(chapters) - set(mapping) - set(profile["scenarios"]))
    print(f"\n{len(profile['modules'])} modules, {len(mapping)} chapters mapped, {len(selected)} prompts")
    print(f"unscanned chapters: {unmapped}")


if __name__ == "__main__":
    main()
