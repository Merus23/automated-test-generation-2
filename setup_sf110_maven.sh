#!/usr/bin/env bash
# setup_sf110_maven.sh
# Builds and installs SF110 project JARs into the local Maven repository.
# Only processes projects that appear in generated_tests/.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GENERATED_TESTS_DIR="${SCRIPT_DIR}/generated_tests"
SF110_DIR="/home/mateus-silva/Documents/MasterDegree/files/localLLM/SF110"
GROUP_ID="sf110"
VERSION="1.0"

log()  { echo "[INFO]  $*"; }
warn() { echo "[WARN]  $*" >&2; }
err()  { echo "[ERROR] $*" >&2; }

# Collect unique SF110 project names from generated_tests/{model}/{project}/
# Structure: generated_tests/{pasta_do_test}/{sf110_project}/
mapfile -t PROJECTS < <(
  find "$GENERATED_TESTS_DIR" -maxdepth 2 -mindepth 2 -type d \
    -exec basename {} \; | sort -u
)

if [[ ${#PROJECTS[@]} -eq 0 ]]; then
  err "No project directories found in $GENERATED_TESTS_DIR"
  exit 1
fi

log "Found ${#PROJECTS[@]} project(s) to process: ${PROJECTS[*]}"

SUCCEEDED=()
FAILED=()

for PROJECT in "${PROJECTS[@]}"; do
  PROJECT_DIR="${SF110_DIR}/${PROJECT}"

  log "------------------------------------------------------------"
  log "Processing: $PROJECT"

  if [[ ! -d "$PROJECT_DIR" ]]; then
    warn "SF110 directory not found: $PROJECT_DIR — skipping"
    FAILED+=("$PROJECT (directory not found)")
    continue
  fi

  # Build with Ant
  log "Running: ant jar in $PROJECT_DIR"
  if ! (cd "$PROJECT_DIR" && ant jar -q -Dcompile.source=8 -Dcompile.target=8 2>&1); then
    warn "ant jar failed for $PROJECT — skipping"
    FAILED+=("$PROJECT (ant jar failed)")
    continue
  fi

  # Find the generated JAR in the project root (exclude lib/ subdirectory)
  JAR_FILE="$(find "$PROJECT_DIR" -maxdepth 1 -name "*.jar" ! -name "*-tests.jar" ! -name "*-evosuite.jar" | head -1)"

  if [[ -z "$JAR_FILE" ]]; then
    warn "JAR not found after build in $PROJECT_DIR — skipping"
    FAILED+=("$PROJECT (JAR not found after build)")
    continue
  fi

  log "Found JAR: $JAR_FILE"

  # Install into local Maven repository
  log "Installing $JAR_FILE into ~/.m2 (groupId=$GROUP_ID, artifactId=$PROJECT, version=$VERSION)"
  if mvn install:install-file \
      -Dfile="$JAR_FILE" \
      -DgroupId="$GROUP_ID" \
      -DartifactId="$PROJECT" \
      -Dversion="$VERSION" \
      -Dpackaging=jar \
      -q 2>&1; then
    log "Installed: $PROJECT"
    SUCCEEDED+=("$PROJECT")
  else
    warn "mvn install failed for $PROJECT"
    FAILED+=("$PROJECT (mvn install failed)")
  fi
done

echo ""
echo "============================================================"
echo "Summary"
echo "============================================================"
echo "Succeeded (${#SUCCEEDED[@]}): ${SUCCEEDED[*]:-none}"
echo "Failed    (${#FAILED[@]}):    ${FAILED[*]:-none}"

if [[ ${#FAILED[@]} -gt 0 ]]; then
  exit 1
fi
