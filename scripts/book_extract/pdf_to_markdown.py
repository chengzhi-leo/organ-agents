import argparse
import json
import re
from collections import Counter
from pathlib import Path

import pymupdf
import yaml

WHITESPACE = re.compile(r"[\s     ]+")
HEADINGS = {"h2": "##", "h3": "###", "h4": "####"}
SENTENCE_END = (".", "?", "!", ":", "”", "\"")


def load_profile(path):
    profile = yaml.safe_load(Path(path).read_text())
    profile["roles"].sort(key=lambda rule: -len(rule["font"]))
    return profile


def match_role(span, roles, previous):
    for rule in roles:
        if span["font"].startswith(rule["font"]) and abs(span["size"] - rule["size"]) < 0.05:
            return rule, span["size"], False
    if previous and span["size"] < previous[1]:
        return *previous, True
    return None


def clean(text):
    return WHITESPACE.sub(" ", text.replace("\xad", "")).strip()


def chapters(doc):
    toc = doc.get_toc()
    boundaries = sorted({page for level, _, page in toc if level <= 2})
    unit, found = None, []
    for level, title, page in toc:
        if level == 1 and title.startswith("UNIT"):
            unit = title.split(" - ", 1)[-1]
        elif level == 2 and (match := re.match(r"(\d+)\.\s*(.+)", title)):
            end = next((edge for edge in boundaries if edge > page), doc.page_count + 1) - 1
            found.append({
                "number": int(match.group(1)),
                "title": clean(match.group(2)),
                "unit": unit,
                "pages": [page, end],
            })
    return found


def keep(block, profile):
    spans = [span for line in block["lines"] for span in line["spans"] if span["text"].strip()]
    dropped = [span for span in spans if span["font"].startswith(tuple(profile["drop_fonts"]))]
    if any(match_role(span, profile["roles"], None) is None for span in dropped):
        return False
    if any(span["font"].startswith(profile["prose_font"]) for span in spans):
        return True
    return max((span["size"] for span in spans), default=0) >= profile["min_heading_size"]


def runs(page, profile):
    blocks = [
        block for block in page.get_text("dict")["blocks"]
        if block.get("type") == 0
        and profile["body_top"] < block["bbox"][1]
        and block["bbox"][3] < profile["body_bottom"]
        and keep(block, profile)
    ]
    blocks.sort(key=lambda block: (block["bbox"][0] >= profile["column_split"], block["bbox"][1]))
    bottom, previous = None, None
    for block in blocks:
        margin = Counter(round(line["bbox"][0]) for line in block["lines"]).most_common(1)[0][0]
        detached = bottom is None or block["bbox"][1] - bottom > profile["heading_gap"]
        bottom = block["bbox"][3]
        for line in block["lines"]:
            grouped = []
            for span in line["spans"]:
                matched = match_role(span, profile["roles"], previous)
                if matched is None:
                    continue
                rule, size, script = matched
                previous = (rule, size)
                if grouped and grouped[-1][0] is rule and grouped[-1][2] == script:
                    grouped[-1][1] += span["text"]
                else:
                    grouped.append([rule, span["text"], script])
            if len(grouped) > 1 and all(rule["role"] in HEADINGS for rule, _, _ in grouped):
                widest = max(grouped, key=lambda group: len(group[1]))[0]
                grouped = [[widest, "".join(text for _, text, _ in grouped), False]]
            for position, (rule, text, script) in enumerate(grouped):
                fresh = detached and line is block["lines"][0] and position == 0
                yield (rule, text, line["bbox"][0] - margin > 3 and position == 0,
                       position == 0, fresh, script)


def append(blocks, rule, text, indented, line_start, fresh, script):
    previous = blocks[-1] if blocks else None
    broken = previous is None or previous["role"] != rule["role"]
    broken = broken or (fresh and rule["role"] in HEADINGS)
    broken = broken or (indented and previous["text"].rstrip().endswith(SENTENCE_END))
    if broken:
        blocks.append({"role": rule["role"], "stream": rule["stream"], "text": text})
    elif previous["text"].endswith(("\xad", "-")):
        previous["text"] = previous["text"].rstrip("\xad") + text
    else:
        previous["text"] += " " + text if line_start and not script else text


def chapter_blocks(doc, chapter, profile):
    main, aside = [], []
    for number in range(chapter["pages"][0] - 1, chapter["pages"][1]):
        page_has_aside = False
        for rule, text, indented, line_start, fresh, script in runs(doc[number], profile):
            target = aside if rule["stream"] == "aside" else main
            append(target, rule, text, indented, line_start, fresh, script)
            page_has_aside = page_has_aside or target is aside
        if aside and not page_has_aside:
            main, aside = main + aside, []
    return main + aside


def render(chapter, blocks, profile):
    front = {
        "book": profile["title"],
        "unit": chapter["unit"],
        "chapter": chapter["number"],
        "title": chapter["title"],
        "pages": chapter["pages"],
    }
    lines = ["---", yaml.safe_dump(front, sort_keys=False, allow_unicode=True).strip(), "---", ""]
    lines.append(f"# {chapter['number']}. {chapter['title']}")
    sections = []
    for block in blocks:
        text = clean(block["text"])
        if not text:
            continue
        if block["role"] in HEADINGS:
            marker = HEADINGS[block["role"]]
            text = text.rstrip(".")
            sections.append({"level": len(marker), "title": text,
                             "stream": block["stream"], "line": len(lines) + 2})
            lines += ["", f"{marker} {text}"]
        else:
            lines += ["", text]
    return "\n".join(lines) + "\n", sections


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("profile")
    parser.add_argument("--chapters", type=int, nargs="*")
    args = parser.parse_args()

    profile = load_profile(args.profile)
    doc = pymupdf.open(profile["pdf"])
    output = Path(profile["output"])
    output.mkdir(parents=True, exist_ok=True)

    index = []
    for chapter in chapters(doc):
        if args.chapters and chapter["number"] not in args.chapters:
            continue
        markdown, sections = render(chapter, chapter_blocks(doc, chapter, profile), profile)
        name = f"ch{chapter['number']:02d}.md"
        (output / name).write_text(markdown)
        index.append({**chapter, "file": name, "characters": len(markdown), "sections": sections})
        print(f"ch{chapter['number']:02d}  p{chapter['pages'][0]:>4}-{chapter['pages'][1]:<4} "
              f"{len(markdown):>7} chars {len(sections):>3} sections  {chapter['title'][:56]}")

    (output / "index.json").write_text(
        json.dumps({"book": profile["title"], "chapters": index}, indent=2, ensure_ascii=False)
    )


if __name__ == "__main__":
    main()
