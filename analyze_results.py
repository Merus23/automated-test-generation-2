import ast
import pandas as pd
import sys
from pathlib import Path


def analyze_results(csv_path: str) -> None:
    df = pd.read_csv(csv_path)
    total = len(df)

    print(f"=== Analysis: {Path(csv_path).name} ===")
    print(f"Total tests: {total}\n")

    # Compilation metrics
    compiled = df["compiles"].sum()
    compile_rate = compiled / total * 100
    print(f"--- Compilation ---")
    print(f"Compiled: {compiled}/{total} ({compile_rate:.1f}%)")

    failed = df[df["compiles"] == False]
    sut_build_failures = (failed["compilation_failure_cause"] == "sut_build_failure").sum()
    dep_failures       = (failed["compilation_failure_cause"] == "dependency").sum()
    syntax_failures    = (failed["compilation_failure_cause"] == "syntax").sum()
    other_failures     = len(failed) - sut_build_failures - dep_failures - syntax_failures

    print(f"SUT build failures:  {sut_build_failures}/{total} ({sut_build_failures/total*100:.1f}%)")
    print(f"Dependency failures: {dep_failures}/{total} ({dep_failures/total*100:.1f}%)")
    print(f"Syntax failures:     {syntax_failures}/{total} ({syntax_failures/total*100:.1f}%)")
    if other_failures > 0:
        print(f"Other failures:      {other_failures}/{total} ({other_failures/total*100:.1f}%)")

    eligible = total - sut_build_failures
    eligible_rate = compiled / eligible * 100 if eligible > 0 else 0.0
    print(f"Compiled (excl. SUT failures): {compiled}/{eligible} ({eligible_rate:.1f}%)")

    # Coverage metrics
    print(f"\n--- Coverage ---")
    cov_evaluated = df[df["coverage_evaluated"] == True]
    cov_rate = len(cov_evaluated) / total * 100
    if len(cov_evaluated) > 0:
        avg_line = cov_evaluated["line_coverage"].mean()
        print(f"Coverage evaluated: {len(cov_evaluated)}/{total} ({cov_rate:.1f}%)")
        print(f"Line coverage (n={len(cov_evaluated)}): avg={avg_line:.3f}")
    else:
        print(f"Coverage evaluated: 0/{total} (0.0%)")
        print("Line coverage: no evaluated samples")

    branch_evaluated = df[df["has_branches"] == True]
    branch_rate = len(branch_evaluated) / total * 100
    if len(branch_evaluated) > 0:
        avg_branch = branch_evaluated["branch_coverage"].mean()
        print(f"Tests with branches: {len(branch_evaluated)}/{total} ({branch_rate:.1f}%)")
        print(f"Branch coverage (n={len(branch_evaluated)}): avg={avg_branch:.3f}")
    else:
        print(f"Tests with branches: 0/{total} (0.0%)")
        print("Branch coverage: no samples with branches")

    mut_evaluated = df[df["mutation_evaluated"] == True]
    mut_rate = len(mut_evaluated) / total * 100
    if len(mut_evaluated) > 0:
        avg_mut = mut_evaluated["mutation_score"].mean()
        print(f"Mutation evaluated: {len(mut_evaluated)}/{total} ({mut_rate:.1f}%)")
        print(f"Mutation score (n={len(mut_evaluated)}): avg={avg_mut:.3f}")
    else:
        print(f"Mutation evaluated: 0/{total} (0.0%)")
        print("Mutation score: no evaluated samples")

    # Quality metrics (only compiled tests)
    compiled_df = df[df["compiles"] == True]
    print(f"\n--- Quality Metrics (compiled tests, n={len(compiled_df)}) ---")

    metrics = {
        "avg_ccn": "Cyclomatic Complexity (avg_ccn)",
        "avg_nloc": "Lines of Code (avg_nloc)",
        "smell_count": "Smell Count",
        "smell_density": "Smell Density",
    }

    for col, label in metrics.items():
        if col in compiled_df.columns and len(compiled_df) > 0:
            series = compiled_df[col]
            print(f"{label}: avg={series.mean():.3f}, min={series.min():.3f}, max={series.max():.3f}")

    if "smell_count" in compiled_df.columns and len(compiled_df) > 0:
        no_smell = (compiled_df["smell_count"] == 0).sum()
        print(f"Tests without smells: {no_smell}/{len(compiled_df)} ({no_smell/len(compiled_df)*100:.1f}%)")
        percentiles = compiled_df["smell_count"].quantile([0.25, 0.50, 0.75, 0.90, 0.95])
        print(f"Smell Count percentiles: p25={percentiles[0.25]:.1f}, p50={percentiles[0.50]:.1f}, p75={percentiles[0.75]:.1f}, p90={percentiles[0.90]:.1f}, p95={percentiles[0.95]:.1f}")


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else input("CSV path: ").strip()
    analyze_results(path)
