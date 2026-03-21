"""
Java Parser — Extração de estrutura de código Java via regex
=============================================================
Lê arquivos .java e extrai pacote, imports, campos, construtores e métodos.
Indexa recursivamente uma base de código Java.

Uso:
    parser = JavaParser()
    class_info = parser.parse_file("MyClass.java")

    index = CodebaseIndex("/path/to/sf110")
    index.build_index()
    info = index.get_class("com.example.MyClass")
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


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
    body: str          # corpo completo (vazio se não disponível)
    signature_only: bool = False

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
# Java Parser (regex-based, sem dependências externas)
# ---------------------------------------------------------------------------

class JavaParser:
    """
    Parser leve baseado em regex para extrair estrutura de arquivos .java.
    Cobre os padrões mais comuns encontrados em bases como SF110.
    """

    # --- Regex patterns ---
    RE_PACKAGE    = re.compile(r'^\s*package\s+([\w.]+)\s*;', re.MULTILINE)
    RE_IMPORT     = re.compile(r'^\s*import\s+([\w.*]+)\s*;', re.MULTILINE)
    RE_CLASS_DECL = re.compile(
        r'(?:public|protected|private|abstract|final|\s)*\s*class\s+(\w+)'
        r'(?:\s+extends\s+[\w<>, ]+)?(?:\s+implements\s+[\w<>, ]+)?\s*\{',
        re.MULTILINE
    )
    RE_FIELD = re.compile(
        r'^\s*((?:(?:public|private|protected|static|final|volatile|transient)\s+)*)'
        r'([\w<>\[\],\s]+?)\s+(\w+)\s*(?:=\s*[^;]+)?;\s*$',
        re.MULTILINE
    )

    def parse_file(self, filepath: str) -> Optional[ClassInfo]:
        try:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                source = f.read()
        except Exception:
            return None

        # Remove comentários de bloco e de linha para facilitar parsing
        source_clean = self._remove_comments(source)

        package = self._extract_package(source_clean)
        imports = self._extract_imports(source_clean)
        class_name = self._extract_class_name(source_clean)

        if not class_name:
            return None

        full_name = f"{package}.{class_name}" if package else class_name

        # Isola o corpo da classe
        class_body = self._extract_class_body(source_clean)
        if not class_body:
            return None

        fields       = self._extract_fields(class_body)
        constructors = self._extract_constructors(class_body, class_name)
        methods      = self._extract_methods(class_body, class_name)

        return ClassInfo(
            package=package,
            class_name=class_name,
            full_name=full_name,
            imports=imports,
            fields=fields,
            constructors=constructors,
            methods=methods,
            source_path=filepath,
            raw_source=source,
        )

    # ------------------------------------------------------------------ #
    #  Helpers de extração                                                 #
    # ------------------------------------------------------------------ #

    def _remove_comments(self, source: str) -> str:
        # Remove comentários /* ... */
        source = re.sub(r'/\*.*?\*/', '', source, flags=re.DOTALL)
        # Remove comentários // ...
        source = re.sub(r'//[^\n]*', '', source)
        return source

    def _extract_package(self, source: str) -> str:
        m = self.RE_PACKAGE.search(source)
        return m.group(1) if m else ""

    def _extract_imports(self, source: str) -> list[str]:
        return self.RE_IMPORT.findall(source)

    def _extract_class_name(self, source: str) -> Optional[str]:
        m = self.RE_CLASS_DECL.search(source)
        return m.group(1) if m else None

    def _extract_class_body(self, source: str) -> Optional[str]:
        """Extrai o conteúdo entre { } da declaração de classe (primeiro nível)."""
        m = self.RE_CLASS_DECL.search(source)
        if not m:
            return None
        start = m.end() - 1  # posição do '{'
        return self._extract_balanced_braces(source, start)

    def _extract_balanced_braces(self, source: str, start: int) -> str:
        """Extrai conteúdo balanceando chaves a partir de `start` (onde está o '{')."""
        depth = 0
        i = start
        begin = start
        while i < len(source):
            if source[i] == '{':
                if depth == 0:
                    begin = i + 1
                depth += 1
            elif source[i] == '}':
                depth -= 1
                if depth == 0:
                    return source[begin:i]
            i += 1
        return source[begin:]

    def _extract_fields(self, class_body: str) -> list[FieldInfo]:
        fields = []
        for m in self.RE_FIELD.finditer(class_body):
            modifier  = m.group(1).strip()
            type_name = m.group(2).strip()
            name      = m.group(3).strip()
            # Evita capturar declarações de métodos como campos
            if type_name in ('return', 'throw', 'new', 'if', 'for', 'while'):
                continue
            # Evita capturar linhas dentro de corpos de método (heurística)
            raw_line = m.group(0).strip()
            fields.append(FieldInfo(
                modifier=modifier,
                type_name=type_name,
                name=name,
                raw=raw_line
            ))
        return fields

    def _extract_constructors(self, class_body: str, class_name: str) -> list[ConstructorInfo]:
        pattern = re.compile(
            rf'((?:(?:public|private|protected)\s+)?){re.escape(class_name)}'
            r'\s*\(([^)]*)\)\s*(?:throws\s+[\w,\s]+)?\s*\{',
            re.MULTILINE
        )
        constructors = []
        for m in pattern.finditer(class_body):
            modifiers  = m.group(1).strip()
            parameters = m.group(2).strip()
            body_start = m.end() - 1
            body       = self._extract_balanced_braces(class_body, body_start)
            constructors.append(ConstructorInfo(
                name=class_name,
                parameters=parameters,
                modifiers=modifiers,
                body=body.strip()
            ))
        return constructors

    def _extract_methods(self, class_body: str, class_name: str) -> list[MethodInfo]:
        """
        Extrai métodos do corpo da classe.
        Captura: modificadores, tipo retorno, nome, parâmetros e corpo.
        """
        pattern = re.compile(
            r'((?:(?:public|private|protected|static|final|synchronized|abstract|native|default)\s+)*)'
            r'([\w<>\[\]]+)\s+'
            rf'(?!{re.escape(class_name)}\s*\()'  # não é construtor
            r'(\w+)\s*\(([^)]*)\)\s*(?:throws\s+[\w,\s]+)?\s*\{',
            re.MULTILINE
        )
        methods = []
        seen = set()
        for m in pattern.finditer(class_body):
            modifiers   = m.group(1).strip()
            return_type = m.group(2).strip()
            name        = m.group(3).strip()
            parameters  = m.group(4).strip()

            # Ignora palavras reservadas capturadas como nome de método
            if name in ('if', 'for', 'while', 'switch', 'catch', 'else', 'new', 'return'):
                continue

            # Evita duplicatas
            key = f"{name}_{parameters}"
            if key in seen:
                continue
            seen.add(key)

            body_start = m.end() - 1
            body       = self._extract_balanced_braces(class_body, body_start)

            methods.append(MethodInfo(
                name=name,
                return_type=return_type,
                parameters=parameters,
                modifiers=modifiers,
                body=body.strip()
            ))
        return methods

    def extract_method_calls(self, method_body: str) -> set[str]:
        """
        Extrai nomes de métodos chamados dentro de um corpo de método.
        Retorna um conjunto de nomes (heurístico, sem resolução de tipos).
        """
        # Padrão: identificador seguido de '('
        calls = re.findall(r'\b(\w+)\s*\(', method_body)
        # Remove palavras-chave Java
        java_keywords = {
            'if', 'for', 'while', 'switch', 'catch', 'return', 'new',
            'throw', 'assert', 'synchronized', 'super', 'this'
        }
        return {c for c in calls if c not in java_keywords}

    def extract_types_used(self, method_body: str, fields: list[FieldInfo],
                           parameters: str) -> set[str]:
        """
        Extrai os tipos referenciados no método (parâmetros + campos + new X()).
        """
        types = set()

        # Tipos nos parâmetros
        for param in parameters.split(','):
            parts = param.strip().split()
            if len(parts) >= 2:
                types.add(parts[0].strip().replace("[]", ""))

        # Tipos dos campos da classe
        for f in fields:
            base_type = re.sub(r'<.*>', '', f.type_name).replace("[]", "").strip()
            if base_type:
                types.add(base_type)

        # Tipos em `new X(` dentro do método
        for t in re.findall(r'\bnew\s+(\w+)\s*[(<]', method_body):
            types.add(t)

        # Remove tipos primitivos e comuns do Java
        java_primitives = {
            'int', 'long', 'double', 'float', 'boolean', 'char', 'byte', 'short',
            'void', 'String', 'Integer', 'Long', 'Double', 'Float', 'Boolean',
            'Object', 'List', 'Map', 'Set', 'Collection', 'ArrayList', 'HashMap',
            'HashSet', 'Optional', 'Iterator', 'Iterable', 'Comparable',
        }
        return types - java_primitives


# ---------------------------------------------------------------------------
# Index da base de código
# ---------------------------------------------------------------------------

class CodebaseIndex:
    """
    Indexa todos os arquivos .java de um diretório de forma lazy/recursiva.
    """

    def __init__(self, base_path: str):
        self.base_path = Path(base_path)
        self._class_map: dict[str, ClassInfo] = {}   # full_name -> ClassInfo
        self._simple_map: dict[str, ClassInfo] = {}  # class_name -> ClassInfo (último encontrado)
        self._parser = JavaParser()
        self._indexed = False

    def build_index(self, verbose: bool = False):
        """Percorre toda a base e indexa as classes."""
        java_files = list(self.base_path.rglob("*.java"))
        total = len(java_files)
        if verbose:
            print(f"[Index] Encontrados {total} arquivos .java em '{self.base_path}'")

        for i, filepath in enumerate(java_files):
            if verbose and i % 500 == 0:
                print(f"[Index] Processando {i}/{total}...")
            info = self._parser.parse_file(str(filepath))
            if info:
                self._class_map[info.full_name] = info
                self._simple_map[info.class_name] = info

        self._indexed = True
        if verbose:
            print(f"[Index] {len(self._class_map)} classes indexadas.")

    def get_class(self, name: str) -> Optional[ClassInfo]:
        """Busca por nome simples ou nome completo (package.ClassName)."""
        if not self._indexed:
            self.build_index()
        return self._class_map.get(name) or self._simple_map.get(name)

    def find_classes_by_simple_name(self, simple_name: str) -> list[ClassInfo]:
        """Retorna todas as classes com aquele nome simples (pode haver duplicatas em pacotes diferentes)."""
        return [c for c in self._class_map.values() if c.class_name == simple_name]
