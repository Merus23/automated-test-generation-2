"""
Java Parser — Structural extraction from Java source files
============================================================
Parses .java files and extracts package, imports, fields, constructors, and methods.
Recursively indexes a Java codebase.

Uses a JavaParser (AST) JAR via subprocess for accurate extraction.

Usage:
    parser = JavaParser()
    class_info = parser.parse_file("MyClass.java")

    index = CodebaseIndex("/path/to/sf110")
    index.build_index()
    info = index.get_class("com.example.MyClass")
"""

import json
import logging
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------

@dataclass
class FieldInfo:
    modifier: str
    type_name: str
    name: str
    raw: str


@dataclass
class MethodInfo:
    name: str
    return_type: str
    parameters: str
    modifiers: str
    body: str          # full body (empty if unavailable)
    signature_only: bool = False
    _method_calls: Optional[set] = field(default=None, repr=False)
    _types_used: Optional[set] = field(default=None, repr=False)

    @property
    def signature(self) -> str:
        return f"{self.modifiers} {self.return_type} {self.name}({self.parameters})".strip()


@dataclass
class ConstructorInfo:
    name: str
    parameters: str
    modifiers: str
    body: str

    @property
    def signature(self) -> str:
        return f"{self.modifiers} {self.name}({self.parameters})".strip()


@dataclass
class ClassInfo:
    package: str
    class_name: str
    full_name: str          # package.ClassName
    imports: list[str]
    fields: list[FieldInfo]
    constructors: list[ConstructorInfo]
    methods: list[MethodInfo]
    source_path: str
    raw_source: str


# ---------------------------------------------------------------------------
# AST-based Java Parser (uses JavaParser JAR via subprocess)
# ---------------------------------------------------------------------------

class ASTJavaParser:
    """
    Parser that delegates to a JavaParser (AST) JAR for accurate extraction.
    Extracts method calls and types used from the AST via a body-keyed cache.
    """

    def __init__(self, jar_path: str = "javaparser-extractor/target/javaparser-extractor.jar"):
        self.jar_path = str(Path(jar_path).resolve())
        if not Path(self.jar_path).is_file():
            raise FileNotFoundError(
                f"JavaParser JAR not found at: {self.jar_path}\n"
                "Run ./build_jar.sh to build it."
            )
        # Cache: method body -> (method_calls, types_used) from JAR
        self._body_cache: dict[str, tuple[set[str], set[str]]] = {}

    def parse_file(self, filepath: str) -> Optional[ClassInfo]:
        try:
            proc = subprocess.run(
                ["java", "-jar", self.jar_path, filepath],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            logger.warning("JAR timeout parsing: %s", filepath)
            return None
        except FileNotFoundError:
            logger.warning("Java runtime not found. Is 'java' on PATH?")
            return None

        if proc.returncode != 0:
            logger.debug("JAR error for %s: %s", filepath, proc.stderr.strip())
            return None

        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError:
            logger.warning("Invalid JSON from JAR for: %s", filepath)
            return None

        class_name = data.get("className", "")
        if not class_name:
            return None

        package = data.get("package", "")
        full_name = f"{package}.{class_name}" if package else class_name

        # Read raw source from file
        try:
            raw_source = Path(filepath).read_text(encoding="utf-8", errors="ignore")
        except Exception:
            raw_source = ""

        fields = [
            FieldInfo(
                modifier=f.get("modifier", ""),
                type_name=f.get("typeName", ""),
                name=f.get("name", ""),
                raw=f.get("raw", ""),
            )
            for f in data.get("fields", [])
        ]

        constructors = [
            ConstructorInfo(
                name=c.get("name", ""),
                parameters=c.get("parameters", ""),
                modifiers=c.get("modifiers", ""),
                body=c.get("body", ""),
            )
            for c in data.get("constructors", [])
        ]

        methods = []
        for m in data.get("methods", []):
            method_calls = set(m.get("methodCalls", []))
            types_used = set(m.get("typesUsed", []))
            body = m.get("body", "")

            # Cache AST-extracted data keyed by body string
            if body:
                self._body_cache[body] = (method_calls, types_used)

            methods.append(MethodInfo(
                name=m.get("name", ""),
                return_type=m.get("returnType", ""),
                parameters=m.get("parameters", ""),
                modifiers=m.get("modifiers", ""),
                body=body,
                _method_calls=method_calls if method_calls else None,
                _types_used=types_used if types_used else None,
            ))

        return ClassInfo(
            package=package,
            class_name=class_name,
            full_name=full_name,
            imports=data.get("imports", []),
            fields=fields,
            constructors=constructors,
            methods=methods,
            source_path=filepath,
            raw_source=raw_source,
        )

    def extract_method_calls(self, method_body: str) -> set[str]:
        """
        Extracts method names called within a method body.
        Uses cached AST data populated by parse_file.
        """
        cached = self._body_cache.get(method_body)
        if cached is not None:
            return cached[0]
        return set()

    def extract_types_used(self, method_body: str, fields: list[FieldInfo],
                           parameters: str) -> set[str]:
        """
        Extracts types referenced in a method.
        Uses cached AST data populated by parse_file.
        """
        cached = self._body_cache.get(method_body)
        if cached is not None:
            return cached[1]
        return set()


# ---------------------------------------------------------------------------
# Factory: convenience alias
# ---------------------------------------------------------------------------

class JavaParser:
    """
    Convenience factory that creates an ASTJavaParser instance.
    """
    def __new__(cls, jar_path: str = "javaparser-extractor/target/javaparser-extractor.jar"):
        return ASTJavaParser(jar_path)


# ---------------------------------------------------------------------------
# Codebase Index
# ---------------------------------------------------------------------------

class CodebaseIndex:
    """
    Indexes all .java files in a directory lazily/recursively.
    Uses parallel threads to speed up JAR subprocess calls.
    """

    # Default to 2x CPU cores (subprocess calls are I/O-bound)
    DEFAULT_WORKERS = min(os.cpu_count() * 2, 16)

    def __init__(self, base_path: str, max_workers: int = None):
        self.base_path = Path(base_path)
        self._class_map: dict[str, ClassInfo] = {}   # full_name -> ClassInfo
        self._simple_map: dict[str, ClassInfo] = {}   # class_name -> ClassInfo (last found)
        self._parser = JavaParser()
        self._max_workers = max_workers or self.DEFAULT_WORKERS
        self._indexed = False

    def build_index(self, verbose: bool = False):
        """Traverses the entire base and indexes classes using parallel threads."""
        java_files = list(self.base_path.rglob("*.java"))
        total = len(java_files)
        if verbose:
            print(f"[Index] Found {total} .java files in '{self.base_path}'")
            print(f"[Index] Parsing with {self._max_workers} threads...")

        filepaths = [str(f) for f in java_files]
        done = 0

        with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
            futures = {
                executor.submit(self._parser.parse_file, fp): fp
                for fp in filepaths
            }

            for future in as_completed(futures):
                done += 1
                if verbose and done % 500 == 0:
                    print(f"[Index] Processing {done}/{total}...")

                info = future.result()
                if info:
                    self._class_map[info.full_name] = info
                    self._simple_map[info.class_name] = info

        self._indexed = True
        if verbose:
            print(f"[Index] {len(self._class_map)} classes indexed.")

    def get_class(self, name: str) -> Optional[ClassInfo]:
        """Looks up by simple name or fully qualified name (package.ClassName)."""
        if not self._indexed:
            self.build_index()
        return self._class_map.get(name) or self._simple_map.get(name)

    def find_classes_by_simple_name(self, simple_name: str) -> list[ClassInfo]:
        """Returns all classes with that simple name (may have duplicates across packages)."""
        return [c for c in self._class_map.values() if c.class_name == simple_name]
