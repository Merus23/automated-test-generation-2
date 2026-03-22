#!/bin/bash
# build_jar.sh — Compiles the JavaParser extractor JAR
set -e
cd "$(dirname "$0")/javaparser-extractor"
mvn clean package -q
echo "[OK] JAR generated at: javaparser-extractor/target/javaparser-extractor.jar"
