"""
Compare metrics of a full CSV filtered by the test cases present in a sample CSV.

The sample CSV (m4 amostral) contains a subset of focal methods.
The full CSV (m1/m2/m3 complete) covers all focal methods.

This script:
  1. Reads both CSVs.
  2. Identifies the sample's test cases by (sut_project, focal_class, focal_method).
  3. Filters the full CSV to only those test cases.
  4. Computes and prints accuracy metrics for the filtered subset.

Usage:
    python compare_sample_vs_full.py <full_csv> <sample_csv>

Example:
    python compare_sample_vs_full.py experiments/results/m3/as.csv experiments/results/m4/as.csv
"""

import sys
import pandas as pd

JOIN_KEYS = ["sut_project", "focal_class", "focal_method"]


def load(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df = df.dropna(subset=JOIN_KEYS)
    df["compiles"] = df["compiles"].astype(str).str.strip().str.lower() == "true"
    df["coverage_evaluated"] = df["coverage_evaluated"].astype(str).str.strip().str.lower() == "true"
    df["mutation_evaluated"] = df["mutation_evaluated"].astype(str).str.strip().str.lower() == "true"
    return df


def compute_metrics(df: pd.DataFrame, label: str) -> dict:
    total = len(df)
    compiles = df["compiles"].sum()
    cov_eval = df["coverage_evaluated"].sum()
    mut_eval = df["mutation_evaluated"].sum()

    compiled_df = df[df["compiles"]]
    cov_df = df[df["coverage_evaluated"]]
    branch_df = df[df["has_branches"].astype(str).str.strip().str.lower() == "true"]
    branch_cov_df = branch_df[branch_df["coverage_evaluated"]]
    mut_df = df[df["mutation_evaluated"]]

    metrics = {
        "label": label,
        "total_tests": total,
        "compilation_rate_%": round(compiles / total * 100, 2) if total else 0,
        "coverage_evaluation_rate_%": round(cov_eval / total * 100, 2) if total else 0,
        "avg_line_coverage_%": round(cov_df["line_coverage"].mean() * 100, 2) if len(cov_df) else 0,
        "avg_branch_coverage_%": round(branch_cov_df["branch_coverage"].mean() * 100, 2) if len(branch_cov_df) else 0,
        "mutation_evaluation_rate_%": round(mut_eval / total * 100, 2) if total else 0,
        "avg_mutation_score_%": round(mut_df["mutation_score"].mean() * 100, 2) if len(mut_df) else 0,
        "avg_smell_density": round(compiled_df["smell_density"].mean(), 4) if len(compiled_df) else 0,
    }
    return metrics


def print_metrics(m: dict) -> None:
    width = 45
    print(f"\n{'=' * (width + 15)}")
    print(f"  {m['label']}")
    print(f"{'=' * (width + 15)}")
    print(f"  {'Total de testes':<{width}} {m['total_tests']}")
    print(f"  {'Taxa de compilação':<{width}} {m['compilation_rate_%']}%")
    print(f"  {'Taxa de avaliação de cobertura':<{width}} {m['coverage_evaluation_rate_%']}%")
    print(f"  {'Cobertura de linha média (avaliados)':<{width}} {m['avg_line_coverage_%']}%")
    print(f"  {'Cobertura de branch média (com branches)':<{width}} {m['avg_branch_coverage_%']}%")
    print(f"  {'Taxa de avaliação de mutação':<{width}} {m['mutation_evaluation_rate_%']}%")
    print(f"  {'Score de mutação médio (avaliados)':<{width}} {m['avg_mutation_score_%']}%")
    print(f"  {'Densidade de smells média (compilados)':<{width}} {m['avg_smell_density']}")


def main():
    if len(sys.argv) != 3:
        print("Usage: python compare_sample_vs_full.py <full_csv> <sample_csv>")
        sys.exit(1)

    full_path, sample_path = sys.argv[1], sys.argv[2]

    full_df = load(full_path)
    sample_df = load(sample_path)

    sample_keys = sample_df[JOIN_KEYS].drop_duplicates()
    print(f"\nCSV completo  : {full_path}  ({len(full_df)} linhas)")
    print(f"CSV amostral  : {sample_path}  ({len(sample_df)} linhas)")
    print(f"Chaves únicas na amostra: {len(sample_keys)}")

    filtered_df = full_df.merge(sample_keys, on=JOIN_KEYS, how="inner")
    print(f"Linhas do completo cobertas pela amostra: {len(filtered_df)}")

    not_in_full = sample_keys.merge(full_df[JOIN_KEYS].drop_duplicates(), on=JOIN_KEYS, how="left", indicator=True)
    missing = not_in_full[not_in_full["_merge"] == "left_only"]
    if not missing.empty:
        print(f"\nAVISO: {len(missing)} chave(s) do amostral NAO encontradas no completo:")
        print(missing[JOIN_KEYS].to_string(index=False))

    # Restrict sample to the intersection: only keys present in both datasets
    intersection_keys = filtered_df[JOIN_KEYS].drop_duplicates()
    sample_df = sample_df.merge(intersection_keys, on=JOIN_KEYS, how="inner")
    print(f"Linhas do amostral na interseção: {len(sample_df)}")

    metrics_full_filtered = compute_metrics(filtered_df, f"Completo filtrado pela amostra  [{full_path}]")
    metrics_sample = compute_metrics(sample_df, f"Amostral                         [{sample_path}]")

    print_metrics(metrics_full_filtered)
    print_metrics(metrics_sample)

    print(f"\n{'=' * 60}")
    print("  Diferença (Completo filtrado - Amostral)")
    print(f"{'=' * 60}")
    skip = {"label", "total_tests"}
    for key in metrics_full_filtered:
        if key in skip:
            continue
        diff = round(metrics_full_filtered[key] - metrics_sample[key], 2)
        sign = "+" if diff >= 0 else ""
        print(f"  {key:<45} {sign}{diff}")


if __name__ == "__main__":
    main()
