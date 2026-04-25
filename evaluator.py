"""
Evaluator — Metrics pipeline for LLM-generated Java tests.

Runs five metrics in order for each generated test:
  1. Compilability (gate)   — javac
  2. Readability            — Lizard (CCN + NLOC)
  3. Test Smells            — TsDetect
  4. Coverage               — JaCoCo via Maven
  5. Mutation Score         — PIT via Maven

A composite quality score is computed from the results.

Usage:
    from evaluator import evaluate_test, evaluate_batch
    result = evaluate_test("generated_tests/1_tullibee/Foo_calcTotal_abc123/")
    evaluate_batch("generated_tests/", "evaluation_results.csv")
"""

import csv
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import uuid
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from string import Template
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Guards concurrent builds of the same SUT JAR when evaluate_batch runs in parallel.
_sut_jar_locks: dict[str, threading.Lock] = {}
_sut_jar_locks_lock = threading.Lock()

M2_REPO = Path.home() / ".m2" / "repository"
TSDETECT_JAR = BASE_DIR / "TestSmellDetector" / "target" / "TestSmellDetector-0.1-jar-with-dependencies.jar"
POM_TEMPLATE_PATH = BASE_DIR / "templates" / "pom_template.xml"
SF110_DIR = Path(os.environ.get("SF110_DIR", Path.home() / "Documents/MasterDegree/files/localLLM/SF110"))

# Fields that must be present AND non-empty
REQUIRED_METADATA_FIELDS = [
    "sut_project",
    "sut_class_path",
    "sut_artifact_id",
    "focal_method",
    "focal_class",
    "model",
    "prompt_type",
]

# Fields that must be present but may be empty (e.g. default package → sut_package = "")
OPTIONAL_PRESENT_FIELDS = ["sut_package"]


# ---------------------------------------------------------------------------
# Fase 2.1 — Metadata reader
# ---------------------------------------------------------------------------

def load_metadata(test_dir: str) -> dict:
    """Reads and validates metadata.json from a test directory.

    Args:
        test_dir: Path to the directory containing test.java and metadata.json.

    Returns:
        Parsed metadata dict.

    Raises:
        FileNotFoundError: If metadata.json is absent.
        ValueError: If any required field is missing.
    """
    meta_path = Path(test_dir) / "metadata.json"
    if not meta_path.exists():
        raise FileNotFoundError(
            f"metadata.json not found in '{test_dir}'. "
            "The generation pipeline must produce this file alongside test.java."
        )

    with open(meta_path, encoding="utf-8") as f:
        metadata = json.load(f)

    missing = [field for field in REQUIRED_METADATA_FIELDS if not metadata.get(field)]
    if missing:
        raise ValueError(
            f"metadata.json in '{test_dir}' is missing required fields: {missing}"
        )

    absent = [field for field in OPTIONAL_PRESENT_FIELDS if field not in metadata]
    if absent:
        raise ValueError(
            f"metadata.json in '{test_dir}' is missing keys: {absent}"
        )

    return metadata


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _extract_class_name(test_java_path: str) -> str:
    """Returns the public class name declared in test.java, or 'GeneratedTest'."""
    content = Path(test_java_path).read_text(encoding="utf-8")
    match = re.search(r'\bpublic\s+class\s+(\w+)', content)
    return match.group(1) if match else "GeneratedTest"


def _extract_package(test_java_path: str) -> str:
    """Returns the package declared in test.java, or '' for the default package."""
    content = Path(test_java_path).read_text(encoding="utf-8")
    match = re.search(r'^\s*package\s+([\w.]+)\s*;', content, re.MULTILINE)
    return match.group(1) if match else ""


# ---------------------------------------------------------------------------
# SF110 JAR setup (lazy, on-demand)
# ---------------------------------------------------------------------------

def _ensure_sut_jar(sut_artifact_id: str) -> bool:
    """Ensures the SUT JAR is installed in the local Maven repository.

    Checks ~/.m2 first. If the JAR is absent, builds it with Ant and installs
    it via mvn install:install-file. This mirrors setup_sf110_maven.sh but
    runs only for the specific project that is about to be evaluated.

    Thread-safe: concurrent calls for the same artifact are serialised via a
    per-artifact lock so the JAR is only built once even in parallel evaluation.

    Args:
        sut_artifact_id: The Maven artifactId, which matches the SF110 project
                         directory name (e.g. '17_inspirento').

    Returns:
        True if the JAR is available in ~/.m2 after the call, False otherwise.
    """
    jar_path = M2_REPO / "sf110" / sut_artifact_id / "1.0" / f"{sut_artifact_id}-1.0.jar"
    if jar_path.exists():
        return True

    with _sut_jar_locks_lock:
        if sut_artifact_id not in _sut_jar_locks:
            _sut_jar_locks[sut_artifact_id] = threading.Lock()
        artifact_lock = _sut_jar_locks[sut_artifact_id]

    with artifact_lock:
        # Re-check inside the lock — another thread may have built it already.
        if jar_path.exists():
            return True

    print(f"  [Setup] JAR not in ~/.m2 for '{sut_artifact_id}'. Building...")
    project_dir = SF110_DIR / sut_artifact_id

    if not project_dir.exists():
        print(f"  [Setup] SF110 directory not found: {project_dir}")
        print(f"  [Setup] Set the SF110_DIR environment variable to the correct path.")
        return False

    ant = subprocess.run(
        ["ant", "jar", "-q", "-Dcompile.source=8", "-Dcompile.target=8"],
        cwd=str(project_dir),
        capture_output=True,
        text=True,
    )
    if ant.returncode != 0:
        print(f"  [Setup] ant jar failed for '{sut_artifact_id}':\n{ant.stderr[-500:]}")
        return False

    jars = [
        f for f in project_dir.glob("*.jar")
        if not f.name.endswith(("-tests.jar", "-evosuite.jar"))
    ]
    if not jars:
        print(f"  [Setup] No JAR found after build in {project_dir}")
        return False

    mvn = subprocess.run(
        [
            "mvn", "install:install-file",
            f"-Dfile={jars[0]}",
            "-DgroupId=sf110",
            f"-DartifactId={sut_artifact_id}",
            "-Dversion=1.0",
            "-Dpackaging=jar",
            "-q",
        ],
        capture_output=True,
        text=True,
    )
    if mvn.returncode != 0:
        print(f"  [Setup] mvn install:install-file failed for '{sut_artifact_id}':\n{mvn.stderr[-500:]}")
        return False

    print(f"  [Setup] JAR installed for '{sut_artifact_id}'")
    return True


# ---------------------------------------------------------------------------
# Fase 2.2 — Temporary Maven project creator
# ---------------------------------------------------------------------------

def create_maven_project(test_dir: str, metadata: dict) -> str:
    """Creates a temporary Maven project for dynamic metric evaluation.

    Copies test.java into the project and renders the pom.xml template with
    SUT-specific values.

    Args:
        test_dir: Source directory containing test.java.
        metadata: Validated metadata dict (from load_metadata).

    Returns:
        Path to the created temporary project directory.
    """
    eval_id = uuid.uuid4().hex[:8]
    project_dir = Path(tempfile.gettempdir()) / f"eval_{eval_id}"
    test_src_dir = project_dir / "src" / "test" / "java"
    test_src_dir.mkdir(parents=True, exist_ok=True)
    # PIT skips projects that have no compile source root directory on disk,
    # even when the production bytecode is already unpacked into target/classes.
    (project_dir / "src" / "main" / "java").mkdir(parents=True, exist_ok=True)

    # Copy test.java into the Maven project using the declared class name as filename.
    # javac requires that a public class Foo resides in Foo.java, and the file must
    # be placed under the directory tree that matches its package declaration.
    src_test = Path(test_dir) / "test.java"
    class_name = _extract_class_name(str(src_test))
    test_content = src_test.read_text(encoding="utf-8")
    test_package = _extract_package(str(src_test))
    sut_package = metadata["sut_package"]

    # If the model dropped the package declaration, inject it from metadata.
    if not test_package and sut_package:
        test_content = f"package {sut_package};\n\n" + test_content
        test_package = sut_package

    if test_package:
        pkg_dir = test_src_dir.joinpath(*test_package.split("."))
        pkg_dir.mkdir(parents=True, exist_ok=True)
        dst_test = pkg_dir / f"{class_name}.java"
    else:
        dst_test = test_src_dir / f"{class_name}.java"
    dst_test.write_text(test_content, encoding="utf-8")

    # Render pom.xml from template
    # Use the exact focal class as PIT target to avoid broad glob matching issues,
    # especially for default-package classes where "*" may produce no mutations.
    focal_class = metadata["focal_class"]
    pit_target_classes = f"{sut_package}.{focal_class}" if sut_package else focal_class
    pom_template = POM_TEMPLATE_PATH.read_text(encoding="utf-8")
    pom_content = (
        pom_template
        .replace("${eval_id}", eval_id)
        .replace("${sut_artifact_id}", metadata["sut_artifact_id"])
        .replace("${sut_package}", sut_package)
        .replace("${pit_target_classes}", pit_target_classes)
    )
    (project_dir / "pom.xml").write_text(pom_content, encoding="utf-8")

    return str(project_dir)


# ---------------------------------------------------------------------------
# Fase 2.3 — Compilability (gate metric)
# ---------------------------------------------------------------------------

_DEPENDENCY_PATTERNS = (
    "Could not resolve dependencies",
    "Artifact",
    "not found",
    "Could not transfer artifact",
    "Cannot access",
    "Non-resolvable",
    "dependency resolution",
)

_SYNTAX_PATTERNS = (
    "error:",
    "';' expected",
    "illegal start",
    "reached end of file",
    "cannot find symbol",
    "incompatible types",
    "unexpected token",
)


def _classify_compilation_failure(errors: list[str], stdout: str) -> str:
    """Returns 'dependency', 'syntax', or 'unknown' for a failed compilation."""
    combined = "\n".join(errors) + "\n" + stdout
    if any(p in combined for p in _DEPENDENCY_PATTERNS):
        return "dependency"
    if any(p in combined for p in _SYNTAX_PATTERNS):
        return "syntax"
    return "unknown"


def check_compilability(maven_project_path: str) -> dict:
    """Checks whether the generated test compiles via Maven (mvn test-compile).

    Using Maven instead of raw javac ensures all test dependencies (JUnit,
    Mockito, SUT JAR) are resolved automatically from ~/.m2 or downloaded.

    Args:
        maven_project_path: Path to the temporary Maven project directory.

    Returns:
        {"compiles": bool, "errors": list[str], "compilation_failure_cause": str | None}
    """
    try:
        result = subprocess.run(
            [
                "mvn",
                "-f", str(Path(maven_project_path) / "pom.xml"),
                "-Djava.awt.headless=true",
                "test-compile",
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        return {
            "compiles": False,
            "errors": ["mvn test-compile timed out after 300s"],
            "compilation_failure_cause": "timeout",
        }

    if result.returncode != 0:
        # Maven sends compiler errors to stdout; stderr has stack traces
        errors = [
            line for line in result.stdout.splitlines()
            if "ERROR" in line or "error:" in line
        ]
        cause = _classify_compilation_failure(errors, result.stdout)
        return {"compiles": False, "errors": errors, "compilation_failure_cause": cause}

    return {"compiles": True, "errors": [], "compilation_failure_cause": None}


# ---------------------------------------------------------------------------
# Fase 2.4 — Coverage (JaCoCo)
# ---------------------------------------------------------------------------

def check_coverage(maven_project_path: str, focal_class: str = "", focal_method: str = "") -> dict:
    """Runs the test suite and collects JaCoCo line/branch coverage for the focal method.

    Expects the Maven project to have JaCoCo configured (provided by the
    pom_template.xml). Runs `mvn test` which triggers both the test execution
    and the JaCoCo report goal.

    When focal_class and focal_method are provided, coverage is computed from
    the method-level counters in jacoco.xml for that specific method (aggregating
    overloads if any). Falls back to report-level counters if the method is not
    found in the report.

    Args:
        maven_project_path: Path to the temporary Maven project.
        focal_class: Simple class name of the focal method (e.g. "UIResources").
        focal_method: Name of the focal method (e.g. "getString").

    Returns:
        {"line_coverage": float, "branch_coverage": float}
    """
    try:
        result = subprocess.run(
            [
                "mvn",
                "-f", str(Path(maven_project_path) / "pom.xml"),
                "-Djava.awt.headless=true",
                # Ignore test failures so JaCoCo still generates the report even
                # when tests throw exceptions at runtime (e.g. GUI tests, I/O failures).
                "-Dmaven.test.failure.ignore=true",
                "test",
                "-q",
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        print("  [JaCoCo] mvn test timed out after 300s (likely a hung test)")
        return {"line_coverage": 0.0, "branch_coverage": 0.0, "has_branches": False, "coverage_evaluated": False}

    if result.returncode != 0:
        # Maven test failures go to stdout; stderr has build/plugin errors.
        output = (result.stdout + result.stderr)[-1000:]
        print(f"  [JaCoCo] mvn test failed (build error):\n{output}")
        return {"line_coverage": 0.0, "branch_coverage": 0.0, "has_branches": False, "coverage_evaluated": False}

    jacoco_xml = Path(maven_project_path) / "target" / "site" / "jacoco" / "jacoco.xml"
    if not jacoco_xml.exists():
        print("  [JaCoCo] jacoco.xml not found after mvn test")
        return {"line_coverage": 0.0, "branch_coverage": 0.0, "has_branches": False, "coverage_evaluated": False}

    tree = ET.parse(jacoco_xml)
    root = tree.getroot()

    if focal_class and focal_method:
        line_cov, branch_cov, has_branches = _focal_method_coverage(root, focal_class, focal_method)
        if line_cov is not None:
            return {
                "line_coverage": line_cov,
                "branch_coverage": branch_cov,
                "has_branches": has_branches,
                "coverage_evaluated": True,
            }
        print(f"  [JaCoCo] Method '{focal_method}' not found in '{focal_class}'; falling back to report-level coverage.")

    def _report_coverage(counter_type: str) -> tuple:
        # Use report-level aggregate counters (direct children of <report>).
        for counter in root.findall("counter"):
            if counter.attrib.get("type") == counter_type:
                missed = int(counter.attrib["missed"])
                covered = int(counter.attrib["covered"])
                total = missed + covered
                return covered / total if total > 0 else 0.0, total > 0
        return 0.0, False

    line_cov, _ = _report_coverage("LINE")
    branch_cov, has_branches = _report_coverage("BRANCH")
    return {
        "line_coverage": line_cov,
        "branch_coverage": branch_cov,
        "has_branches": has_branches,
        "coverage_evaluated": True,
    }


def _focal_method_coverage(root: ET.Element, focal_class: str, focal_method: str) -> tuple:
    """Extracts line and branch coverage for a specific method from a JaCoCo report.

    JaCoCo XML structure: report > package > class > method > counter.
    Class names in JaCoCo use slashes (e.g. "ui/UIResources"), so we match by
    the trailing simple name. All overloads of focal_method are aggregated.

    Returns:
        (line_coverage, branch_coverage, has_branches) or (None, None, None) if not found.
        has_branches is True when the method contains at least one conditional branch,
        distinguishing genuine 0% branch coverage from methods with no branches at all.
    """
    line_missed = line_covered = 0
    branch_missed = branch_covered = 0
    found = False

    for cls in root.iter("class"):
        cls_name = cls.attrib.get("name", "")
        # Match "UIResources" against "ui/UIResources" or "UIResources"
        simple_name = cls_name.split("/")[-1]
        if simple_name != focal_class:
            continue
        for method in cls.findall("method"):
            if method.attrib.get("name") != focal_method:
                continue
            found = True
            for counter in method.findall("counter"):
                t = counter.attrib.get("type")
                m = int(counter.attrib.get("missed", 0))
                c = int(counter.attrib.get("covered", 0))
                if t == "LINE":
                    line_missed += m
                    line_covered += c
                elif t == "BRANCH":
                    branch_missed += m
                    branch_covered += c

    if not found:
        return None, None, None

    line_total = line_missed + line_covered
    branch_total = branch_missed + branch_covered
    return (
        line_covered / line_total if line_total > 0 else 0.0,
        branch_covered / branch_total if branch_total > 0 else 0.0,
        branch_total > 0,
    )


# ---------------------------------------------------------------------------
# Fase 2.5 — Readability (Lizard)
# ---------------------------------------------------------------------------

def check_complexity(test_java_path: str) -> dict:
    """Measures cyclomatic complexity and NLOC of the generated test using Lizard.

    Args:
        test_java_path: Absolute path to test.java.

    Returns:
        {"avg_ccn": float, "avg_nloc": float, "methods": list[dict]}
    """
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
        csv_out = tmp.name

    try:
        result = subprocess.run(
            [
                "lizard", "-l", "java",
                "-EIgnoreAssert",
                "--csv",
                "-o", csv_out,
                test_java_path,
            ],
            capture_output=True,
            text=True,
        )

        # Lizard CSV has no header row; columns are fixed-position:
        # NLOC, CCN, token_count, param_count, length, location,
        # filename, FUNCTION_NAME, long_name, start_line, end_line
        LIZARD_FIELDS = [
            "NLOC", "CCN", "token_count", "param_count", "length",
            "location", "filename", "FUNCTION_NAME", "long_name",
            "start_line", "end_line",
        ]
        methods = []
        if Path(csv_out).exists():
            with open(csv_out, encoding="utf-8") as f:
                reader = csv.DictReader(f, fieldnames=LIZARD_FIELDS)
                for row in reader:
                    try:
                        methods.append({
                            "method": row.get("FUNCTION_NAME", ""),
                            "ccn": int(row.get("CCN", 0)),
                            "nloc": int(row.get("NLOC", 0)),
                            "tokens": int(row.get("token_count", 0)),
                        })
                    except (ValueError, KeyError):
                        continue
    finally:
        Path(csv_out).unlink(missing_ok=True)

    avg_ccn = sum(m["ccn"] for m in methods) / len(methods) if methods else 0.0
    avg_nloc = sum(m["nloc"] for m in methods) / len(methods) if methods else 0.0

    return {"avg_ccn": avg_ccn, "avg_nloc": avg_nloc, "methods": methods}


# ---------------------------------------------------------------------------
# Fase 2.6 — Test Smells (TsDetect)
# ---------------------------------------------------------------------------

def check_test_smells(test_java_path: str, sut_class_path: str) -> dict:
    """Detects test smells using TsDetect (TestSmellDetector).

    Produces a temporary input CSV with the (test, production) file pair and
    invokes the TsDetect JAR. Parses the output CSV for smell flags.

    Args:
        test_java_path: Absolute path to test.java.
        sut_class_path: Absolute path to the SUT .java file.

    Returns:
        {"smells_detected": list[str], "smell_count": int, "smell_density": float}
    """
    if not TSDETECT_JAR.exists():
        print(f"  [TsDetect] JAR not found at {TSDETECT_JAR}. Skipping.")
        return {"smells_detected": [], "smell_count": 0, "smell_density": 0.0}

    with tempfile.TemporaryDirectory() as tmpdir:
        input_csv = Path(tmpdir) / "tsdetect_input.csv"
        output_csv = Path(tmpdir) / "tsdetect_output.csv"

        # TsDetect does NOT expect a header row — first line is treated as data
        with open(input_csv, "w", encoding="utf-8") as f:
            f.write(f"eval,{test_java_path},{sut_class_path}\n")

        result = subprocess.run(
            ["java", "-jar", str(TSDETECT_JAR), "-f", str(input_csv), "-o", str(output_csv)],
            capture_output=True,
            text=True,
            cwd=tmpdir,
        )

        if result.returncode != 0:
            print(f"  [TsDetect] Failed:\n{result.stderr[-500:]}")
            return {"smells_detected": [], "smell_count": 0, "smell_density": 0.0}

        if not output_csv.exists():
            print("  [TsDetect] Output CSV not found.")
            return {"smells_detected": [], "smell_count": 0, "smell_density": 0.0}

        # Columns to skip when collecting smell flags
        NON_SMELL_COLS = {
            "App", "TestClass", "TestFilePath", "ProductionFilePath",
            "RelativeTestFilePath", "RelativeProductionFilePath", "NumberOfMethods",
        }

        smells_detected = []
        total_methods = 1  # conservative denominator when method count is unknown

        with open(output_csv, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Boolean smell columns (value == "true")
                smells_detected += [k for k, v in row.items()
                                     if str(v).lower() == "true" and k not in NON_SMELL_COLS]
                if "NumberOfMethods" in row:
                    try:
                        total_methods = max(1, int(row["NumberOfMethods"]))
                    except ValueError:
                        pass

        smell_count = len(smells_detected)
        smell_density = smell_count / total_methods

        return {
            "smells_detected": smells_detected,
            "smell_count": smell_count,
            "smell_density": smell_density,
        }


# ---------------------------------------------------------------------------
# Fase 2.7 — Mutation Score (PIT)
# ---------------------------------------------------------------------------

def check_mutation_score(maven_project_path: str, focal_method: str = "") -> dict:
    """Runs PIT mutation testing and returns the mutation score.

    Assumes the Maven project has PIT configured (provided by pom_template.xml)
    and that `mvn test` has already passed (compilability gate).

    When focal_method is provided, only mutations targeting that method are
    counted, giving a method-level score instead of a class-level score.

    Args:
        maven_project_path: Path to the temporary Maven project.
        focal_method: If non-empty, count only mutations in this method.

    Returns:
        {"mutation_score": float, "killed": int, "total_mutants": int, "mutation_evaluated": bool}
    """
    _default = {"mutation_score": 0.0, "killed": 0, "total_mutants": 0, "mutation_evaluated": False}

    try:
        result = subprocess.run(
            [
                "mvn", "-f", str(Path(maven_project_path) / "pom.xml"),
                "-Djava.awt.headless=true",
                "org.pitest:pitest-maven:mutationCoverage", "-q",
            ],
            capture_output=True,
            text=True,
            timeout=600,
        )
    except subprocess.TimeoutExpired:
        print("  [PIT] mutationCoverage timed out after 600s")
        return _default

    if result.returncode != 0:
        combined = result.stdout + result.stderr
        if "Tests failing without mutation" in combined:
            print("  SKIP — PIT aborted: tests fail in PIT's minion JVM (env/filesystem dependency).")
        else:
            print(f"  [PIT] mutationCoverage failed:\n{combined[-800:]}")
        return _default

    mutations_xml = Path(maven_project_path) / "target" / "pit-reports" / "mutations.xml"
    if not mutations_xml.exists():
        print("  [PIT] mutations.xml not found")
        return _default

    tree = ET.parse(mutations_xml)
    root = tree.getroot()

    total = 0
    killed = 0
    for mutation in root.findall("mutation"):
        if focal_method and mutation.findtext("mutatedMethod", "") != focal_method:
            continue
        total += 1
        if mutation.attrib.get("detected") == "true":
            killed += 1

    if total == 0:
        print("  SKIP — no mutations found for the focal method.")
        return _default

    mutation_score = killed / total
    return {"mutation_score": mutation_score, "killed": killed, "total_mutants": total, "mutation_evaluated": True}


# ---------------------------------------------------------------------------
# Fase 3.1 — Single-test orchestrator
# ---------------------------------------------------------------------------

def evaluate_test(test_dir: str, keep_temp: bool = False) -> dict:
    """Runs the full evaluation pipeline for a single generated test.

    Pipeline:
        load_metadata → check_compilability (gate) → check_complexity
        → check_test_smells → create_maven_project → check_coverage
        → check_mutation_score → save results.json

    Args:
        test_dir: Directory containing test.java and metadata.json.
        keep_temp: If True, the temporary Maven project is not deleted.

    Returns:
        Dict with all metric values.
    """
    test_dir = str(Path(test_dir).resolve())
    test_java = str(Path(test_dir) / "test.java")

    print(f"\n{'='*60}")
    print(f"Evaluating: {test_dir}")
    print(f"{'='*60}")

    # --- Load metadata (fail fast if absent or incomplete) ---
    metadata = load_metadata(test_dir)

    result: dict = {
        "test_dir": test_dir,
        "sut_project": metadata["sut_project"],
        "focal_class": metadata["focal_class"],
        "focal_method": metadata["focal_method"],
        "model": metadata["model"],
        "prompt_type": metadata["prompt_type"],
        "evaluated_at": datetime.now().isoformat(timespec="seconds"),
    }

    # --- Ensure SUT JAR is in ~/.m2 (build + install on demand if absent) ---
    if not _ensure_sut_jar(metadata["sut_artifact_id"]):
        print(f"  FAIL — SUT JAR unavailable for '{metadata['sut_artifact_id']}'. Pipeline halted.")
        result.update({
            "compiles": False,
            "errors": [f"SUT JAR not found and could not be built for '{metadata['sut_artifact_id']}'"],
            "compilation_failure_cause": "sut_build_failure",
            "line_coverage": 0.0, "branch_coverage": 0.0, "has_branches": False, "coverage_evaluated": False,
            "mutation_score": 0.0, "killed": 0, "total_mutants": 0, "mutation_evaluated": False,
            "avg_ccn": 0.0, "avg_nloc": 0.0,
            "smell_count": 0, "smell_density": 0.0, "smells_detected": [],
        })
        _save_results(test_dir, result)
        return result

    # --- Create Maven project (needed for compilability and dynamic metrics) ---
    maven_project = create_maven_project(test_dir, metadata)

    # --- Gate: compilability ---
    print("[1/5] Compilability...")
    comp = check_compilability(maven_project)
    result.update(comp)

    if not comp["compiles"]:
        print("  FAIL — test does not compile. Pipeline halted.")
        shutil.rmtree(maven_project, ignore_errors=True)
        result["line_coverage"] = 0.0
        result["branch_coverage"] = 0.0
        result["has_branches"] = False
        result["coverage_evaluated"] = False
        result["mutation_score"] = 0.0
        result["killed"] = 0
        result["total_mutants"] = 0
        result["mutation_evaluated"] = False
        result["avg_ccn"] = 0.0
        result["avg_nloc"] = 0.0
        result["smell_count"] = 0
        result["smell_density"] = 0.0
        result["smells_detected"] = []
        _save_results(test_dir, result)
        return result

    print("  OK")

    # --- Static: readability (Lizard) ---
    print("[2/5] Readability (Lizard)...")
    complexity = check_complexity(test_java)
    result.update(complexity)
    print(f"  avg_ccn={complexity['avg_ccn']:.2f}  avg_nloc={complexity['avg_nloc']:.2f}")

    # --- Static: test smells (TsDetect) ---
    print("[3/5] Test Smells (TsDetect)...")
    smells = check_test_smells(test_java, metadata["sut_class_path"])
    result.update(smells)
    print(f"  smell_count={smells['smell_count']}  smell_density={smells['smell_density']:.3f}")

    # --- Dynamic: coverage and mutation ---
    print("[4/5] Coverage (JaCoCo)...")
    try:
        coverage = check_coverage(maven_project, metadata["focal_class"], metadata["focal_method"])
        result.update(coverage)
        print(f"  line={coverage['line_coverage']:.2%}  branch={coverage['branch_coverage']:.2%}")

        # --- Dynamic: mutation score (PIT) ---
        print("[5/5] Mutation Score (PIT)...")
        if not coverage.get("coverage_evaluated") or coverage.get("line_coverage", 0.0) == 0.0:
            print("  SKIP — line coverage is 0%; tests do not reach the SUT.")
            result["mutation_score"] = 0.0
            result["killed"] = 0
            result["total_mutants"] = 0
            result["mutation_evaluated"] = False
        else:
            mutation = check_mutation_score(maven_project, metadata["focal_method"])
            result["mutation_score"] = mutation["mutation_score"]
            result["killed"] = mutation["killed"]
            result["total_mutants"] = mutation["total_mutants"]
            result["mutation_evaluated"] = mutation["mutation_evaluated"]
            print(f"  score={mutation['mutation_score']:.2%}  ({mutation['killed']}/{mutation['total_mutants']})")
    finally:
        if not keep_temp:
            shutil.rmtree(maven_project, ignore_errors=True)

    _save_results(test_dir, result)
    return result


def _save_results(test_dir: str, result: dict) -> None:
    """Saves evaluation results to results.json inside the test directory."""
    out_path = Path(test_dir) / "results.json"
    # Remove non-serialisable 'methods' list to keep results.json concise
    serialisable = {k: v for k, v in result.items() if k != "methods"}
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(serialisable, f, indent=2, ensure_ascii=False)
    print(f"Results saved to {out_path}")


# ---------------------------------------------------------------------------
# Fase 3.2 + 3.3 — Batch evaluator and consolidated report
# ---------------------------------------------------------------------------

CSV_FIELDS = [
    "test_id",
    "sut_project",
    "focal_class",
    "focal_method",
    "model",
    "prompt_type",
    "compiles",
    "compilation_failure_cause",
    "line_coverage",
    "branch_coverage",
    "has_branches",
    "coverage_evaluated",
    "mutation_score",
    "mutation_evaluated",
    "avg_ccn",
    "avg_nloc",
    "smell_count",
    "smell_density",
]


def evaluate_batch(tests_dir: str, output_csv: str = "evaluation_results.csv",
                   concurrency: int = 4) -> list[dict]:
    """Evaluates all generated tests found under tests_dir.

    Discovers test directories by looking for folders that contain both
    test.java and metadata.json. Results are saved per-test as results.json
    and consolidated into a CSV report.

    Args:
        tests_dir: Root directory containing generated tests
                   (e.g. generated_tests/).
        output_csv: Path for the consolidated CSV report.
        concurrency: Number of parallel workers (default: 4). Each worker
                     runs a full Maven evaluation pipeline, so keep this low
                     enough to avoid I/O and CPU saturation.

    Returns:
        List of result dicts, one per evaluated test.
    """
    tests_root = Path(tests_dir)
    test_dirs = sorted(
        d for d in tests_root.rglob("metadata.json")
        if (d.parent / "test.java").exists()
    )

    total = len(test_dirs)
    print(f"Found {total} test(s) in '{tests_dir}' — running with {concurrency} worker(s)")

    print_lock = threading.Lock()
    counter = {"n": 0}

    def _run(meta_path: Path) -> dict:
        td = str(meta_path.parent)
        with print_lock:
            counter["n"] += 1
            print(f"\n[{counter['n']}/{total}] {td}")
        try:
            return evaluate_test(td)
        except Exception as exc:
            with print_lock:
                print(f"  ERROR: {exc}")
            return {"test_dir": td, "error": str(exc)}

    all_results = []
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = {executor.submit(_run, p): p for p in test_dirs}
        for future in as_completed(futures):
            all_results.append(future.result())

    all_results.sort(key=lambda r: r.get("test_dir", ""))

    out_path = Path(output_csv)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for i, res in enumerate(all_results):
            row = {"test_id": f"test_{i:04d}", **res}
            writer.writerow(row)

    print(f"\n[Batch] Report saved to {out_path}")
    return all_results
