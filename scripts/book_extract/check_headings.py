import argparse
import json
import re
from pathlib import Path

import pymupdf
import yaml

IGNORED = {"bibliography"}


def normalise(title):
    return re.sub(r"[^a-z0-9]", "", title.lower())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("profile")
    parser.add_argument("--worst", type=int, default=10)
    args = parser.parse_args()

    profile = yaml.safe_load(Path(args.profile).read_text())
    toc = pymupdf.open(profile["pdf"]).get_toc()
    index = json.loads((Path(profile["output"]) / "index.json").read_text())

    report, totals = [], [0, 0, 0]
    for chapter in index["chapters"]:
        low, high = chapter["pages"]
        expected = {
            normalise(title) for level, title, page in toc
            if low <= page <= high and level >= 3 and normalise(title) not in IGNORED
        }
        found = {normalise(section["title"]) for section in chapter["sections"]}
        report.append((len(expected - found) + len(found - expected), chapter, expected, found))
        totals = [a + b for a, b in zip(totals, [len(expected), len(expected & found), len(found - expected)])]

    expected, matched, extra = totals
    print(f"chapters {len(index['chapters'])}  "
          f"characters {sum(c['characters'] for c in index['chapters']):,}")
    print(f"toc headings {expected}  matched {matched} ({100 * matched / expected:.1f}%)  "
          f"missing {expected - matched}  extra {extra}")
    for errors, chapter, want, got in sorted(report, key=lambda row: -row[0])[: args.worst]:
        if not errors:
            break
        print(f"\nch{chapter['number']:02d} {chapter['title'][:60]}  "
              f"({len(want & got)}/{len(want)} matched, {len(got - want)} extra)")
        for title in sorted(want - got):
            print(f"    missing  {title[:80]}")
        for title in sorted(got - want):
            print(f"    extra    {title[:80]}")


if __name__ == "__main__":
    main()
