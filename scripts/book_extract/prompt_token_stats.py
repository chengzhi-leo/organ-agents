import argparse
import json
import math
import statistics
from pathlib import Path

import tiktoken


def percentile(values, probability):
    index = max(0, math.ceil(probability * len(values)) - 1)
    return sorted(values)[index]


def summarize(values):
    return {
        "min": min(values),
        "p25": percentile(values, 0.25),
        "median": percentile(values, 0.5),
        "p75": percentile(values, 0.75),
        "p90": percentile(values, 0.9),
        "p95": percentile(values, 0.95),
        "max": max(values),
        "mean": round(statistics.mean(values), 1),
        "total": sum(values),
    }


def analyze(prompt_dir, encoding_name):
    system_path = prompt_dir / "extractor_system.txt"
    if not system_path.is_file():
        raise FileNotFoundError(f"missing extractor system prompt: {system_path}")
    chapter_paths = sorted(prompt_dir.glob("ch[0-9][0-9].txt"))
    if not chapter_paths:
        raise ValueError(f"no chapter prompts found in {prompt_dir}")

    encoding = tiktoken.get_encoding(encoding_name)
    system = system_path.read_text()
    system_characters = len(system)
    system_tokens = len(encoding.encode(system))
    chapters = []
    for path in chapter_paths:
        user = path.read_text()
        user_characters = len(user)
        user_tokens = len(encoding.encode(user))
        total_characters = system_characters + user_characters
        chapters.append({
            "chapter": int(path.stem[2:]),
            "user_characters": user_characters,
            "total_characters": total_characters,
            "user_tokens": user_tokens,
            "total_tokens": system_tokens + user_tokens,
        })

    token_counts = [chapter["total_tokens"] for chapter in chapters]
    return {
        "method": {
            "kind": "tiktoken",
            "encoding": encoding_name,
            "includes_system_prompt": True,
            "system_prompt_characters": system_characters,
            "system_prompt_tokens": system_tokens,
        },
        "chapter_count": len(chapters),
        "token_distribution": summarize(token_counts),
        "chapters": chapters,
    }


def main():
    parser = argparse.ArgumentParser(description="Summarize extractor prompt token counts")
    parser.add_argument("prompt_dir", type=Path)
    parser.add_argument("--encoding", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    report = analyze(args.prompt_dir, args.encoding)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")

    distribution = report["token_distribution"]
    print(f"chapters: {report['chapter_count']}")
    print(f"tokens: {distribution}")
    print(f"report: {args.output}")


if __name__ == "__main__":
    main()
