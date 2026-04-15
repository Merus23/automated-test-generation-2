#!/usr/bin/env python3
"""Script to recursively delete all files named 'results.json' in a directory."""

import argparse
import sys
from pathlib import Path


def find_and_delete(root: Path, dry_run: bool) -> int:
    targets = list(root.rglob("results.json"))

    if not targets:
        print("No 'results.json' files found.")
        return 0

    for path in targets:
        if dry_run:
            print(f"[dry-run] Would delete: {path}")
        else:
            path.unlink()
            print(f"Deleted: {path}")

    return len(targets)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Recursively delete all 'results.json' files inside a directory."
    )
    parser.add_argument("directory", help="Root directory to search")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show which files would be deleted without actually deleting them",
    )
    args = parser.parse_args()

    root = Path(args.directory)
    if not root.is_dir():
        print(f"Error: '{root}' is not a valid directory.", file=sys.stderr)
        sys.exit(1)

    count = find_and_delete(root, dry_run=args.dry_run)
    action = "Would delete" if args.dry_run else "Deleted"
    print(f"\n{action} {count} file(s).")


if __name__ == "__main__":
    main()
