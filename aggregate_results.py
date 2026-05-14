import sys
import csv
from pathlib import Path

import pandas as pd


def compute_metrics(df: pd.DataFrame) -> dict:
    total = len(df)

    compiled = int(df["compiles"].sum())
    failed = df[df["compiles"] == False]
    sut_failures = int((failed["compilation_failure_cause"] == "sut_build_failure").sum())
    dep_failures = int((failed["compilation_failure_cause"] == "dependency").sum())
    syntax_failures = int((failed["compilation_failure_cause"] == "syntax").sum())
    other_failures = len(failed) - sut_failures - dep_failures - syntax_failures

    eligible = total - sut_failures
    compile_rate = compiled / total * 100 if total > 0 else 0.0
    compile_rate_excl_sut = compiled / eligible * 100 if eligible > 0 else 0.0

    cov_eval = df[df["coverage_evaluated"] == True]
    avg_line = cov_eval["line_coverage"].mean() if len(cov_eval) > 0 else float("nan")

    branch_eval = df[df["has_branches"] == True]
    avg_branch = branch_eval["branch_coverage"].mean() if len(branch_eval) > 0 else float("nan")

    mut_eval = df[df["mutation_evaluated"] == True]
    avg_mut = mut_eval["mutation_score"].mean() if len(mut_eval) > 0 else float("nan")

    compiled_df = df[df["compiles"] == True]
    n_compiled = len(compiled_df)

    def _stat(col):
        if col in compiled_df.columns and n_compiled > 0:
            s = compiled_df[col]
            return s.mean(), s.min(), s.max()
        return float("nan"), float("nan"), float("nan")

    ccn_avg, ccn_min, ccn_max = _stat("avg_ccn")
    nloc_avg, nloc_min, nloc_max = _stat("avg_nloc")
    smell_avg, smell_min, smell_max = _stat("smell_count")
    density_avg, density_min, density_max = _stat("smell_density")

    no_smell = int((compiled_df["smell_count"] == 0).sum()) if "smell_count" in compiled_df.columns and n_compiled > 0 else 0
    no_smell_pct = no_smell / n_compiled * 100 if n_compiled > 0 else 0.0

    pcts = {}
    if "smell_count" in compiled_df.columns and n_compiled > 0:
        q = compiled_df["smell_count"].quantile([0.25, 0.50, 0.75, 0.90, 0.95])
        pcts = {k: q[k] for k in [0.25, 0.50, 0.75, 0.90, 0.95]}
    else:
        pcts = {k: float("nan") for k in [0.25, 0.50, 0.75, 0.90, 0.95]}

    return {
        "total": total,
        "compiled": compiled,
        "compile_rate_pct": round(compile_rate, 4),
        "sut_build_failures": sut_failures,
        "sut_build_failures_pct": round(sut_failures / total * 100, 4) if total > 0 else 0.0,
        "dep_failures": dep_failures,
        "dep_failures_pct": round(dep_failures / total * 100, 4) if total > 0 else 0.0,
        "syntax_failures": syntax_failures,
        "syntax_failures_pct": round(syntax_failures / total * 100, 4) if total > 0 else 0.0,
        "other_failures": other_failures,
        "other_failures_pct": round(other_failures / total * 100, 4) if total > 0 else 0.0,
        "eligible": eligible,
        "compile_rate_excl_sut_pct": round(compile_rate_excl_sut, 4),
        "cov_evaluated": len(cov_eval),
        "cov_evaluated_pct": round(len(cov_eval) / total * 100, 4) if total > 0 else 0.0,
        "avg_line_coverage": round(avg_line, 6) if not pd.isna(avg_line) else "",
        "branch_tests": len(branch_eval),
        "branch_tests_pct": round(len(branch_eval) / total * 100, 4) if total > 0 else 0.0,
        "avg_branch_coverage": round(avg_branch, 6) if not pd.isna(avg_branch) else "",
        "mut_evaluated": len(mut_eval),
        "mut_evaluated_pct": round(len(mut_eval) / total * 100, 4) if total > 0 else 0.0,
        "avg_mutation_score": round(avg_mut, 6) if not pd.isna(avg_mut) else "",
        "n_compiled": n_compiled,
        "avg_ccn": round(ccn_avg, 6) if not pd.isna(ccn_avg) else "",
        "min_ccn": round(ccn_min, 6) if not pd.isna(ccn_min) else "",
        "max_ccn": round(ccn_max, 6) if not pd.isna(ccn_max) else "",
        "avg_nloc": round(nloc_avg, 6) if not pd.isna(nloc_avg) else "",
        "min_nloc": round(nloc_min, 6) if not pd.isna(nloc_min) else "",
        "max_nloc": round(nloc_max, 6) if not pd.isna(nloc_max) else "",
        "avg_smell_count": round(smell_avg, 6) if not pd.isna(smell_avg) else "",
        "min_smell_count": round(smell_min, 6) if not pd.isna(smell_min) else "",
        "max_smell_count": round(smell_max, 6) if not pd.isna(smell_max) else "",
        "avg_smell_density": round(density_avg, 6) if not pd.isna(density_avg) else "",
        "min_smell_density": round(density_min, 6) if not pd.isna(density_min) else "",
        "max_smell_density": round(density_max, 6) if not pd.isna(density_max) else "",
        "tests_without_smells": no_smell,
        "tests_without_smells_pct": round(no_smell_pct, 4),
        "smell_p25": pcts[0.25] if not pd.isna(pcts[0.25]) else "",
        "smell_p50": pcts[0.50] if not pd.isna(pcts[0.50]) else "",
        "smell_p75": pcts[0.75] if not pd.isna(pcts[0.75]) else "",
        "smell_p90": pcts[0.90] if not pd.isna(pcts[0.90]) else "",
        "smell_p95": pcts[0.95] if not pd.isna(pcts[0.95]) else "",
    }


def aggregate(results_dir: str, output_path: str) -> None:
    root = Path(results_dir)
    csv_files = sorted(root.rglob("*.csv"))
    if not csv_files:
        print(f"No CSV files found under {root}")
        return

    rows = []
    for csv_file in csv_files:
        relative = csv_file.relative_to(root)
        parts = relative.parts
        model_id = parts[0] if len(parts) > 1 else ""
        prompt_type = csv_file.stem

        df = pd.read_csv(csv_file)

        model_name = ""
        if "model" in df.columns and len(df) > 0:
            model_name = df["model"].iloc[0]

        metrics = compute_metrics(df)
        row = {"model_id": model_id, "model_name": model_name, "prompt_type": prompt_type, "file": str(relative)}
        row.update(metrics)
        rows.append(row)

    out_df = pd.DataFrame(rows)
    out_df.to_csv(output_path, index=False)
    print(f"Saved {len(rows)} rows to {output_path}")
    for r in rows:
        print(f"  {r['model_id']}/{r['prompt_type']}: total={r['total']}, compiled={r['compiled']}, cov_eval={r['cov_evaluated']}")


if __name__ == "__main__":
    results_dir = sys.argv[1] if len(sys.argv) > 1 else "experiments/results"
    output_path = sys.argv[2] if len(sys.argv) > 2 else "experiments/aggregated_metrics.csv"
    aggregate(results_dir, output_path)
