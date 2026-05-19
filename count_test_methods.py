#!/usr/bin/env python3
"""Count @Test methods per file in generated_tests and compute averages."""

import csv
import re
import sys
from pathlib import Path
from collections import defaultdict

BASE_DIR = Path(__file__).parent / "experiments" / "generated_tests"
OUTPUT_CSV = Path(__file__).parent / "test_methods_avg.csv"

TEST_ANNOTATION_PATTERN = re.compile(r"^\s*@Test(\s*\(.*?\))?\s*$", re.MULTILINE)


def count_test_methods(file_path: Path) -> int:
    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
        return len(TEST_ANNOTATION_PATTERN.findall(content))
    except Exception as e:
        print(f"Error reading {file_path}: {e}", file=sys.stderr)
        return 0


def main():
    # counts[model][strategy] = list of per-file counts
    counts: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))

    for java_file in BASE_DIR.rglob("test.java"):
        parts = java_file.relative_to(BASE_DIR).parts
        if len(parts) < 4:
            continue
        model, strategy = parts[0], parts[1]
        n = count_test_methods(java_file)
        counts[model][strategy].append(n)

    rows = []
    for model in sorted(counts):
        for strategy in sorted(counts[model]):
            values = counts[model][strategy]
            total_files = len(values)
            total_tests = sum(values)
            avg = total_tests / total_files if total_files > 0 else 0.0
            rows.append({
                "model": model,
                "strategy": strategy,
                "total_files": total_files,
                "total_test_methods": total_tests,
                "avg_test_methods_per_file": round(avg, 4),
            })

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "model", "strategy", "total_files", "total_test_methods", "avg_test_methods_per_file"
        ])
        writer.writeheader()
        writer.writerows(rows)

    print(f"CSV saved to: {OUTPUT_CSV}")
    for row in rows:
        print(f"  {row['model']}/{row['strategy']}: avg={row['avg_test_methods_per_file']} "
              f"({row['total_test_methods']} tests / {row['total_files']} files)")


if __name__ == "__main__":
    main()
