"""
Java Context Extractor — Construtor de Prompts para LLMs
=========================================================
Monta prompts estruturados para geração de testes unitários com LLMs,
a partir do contexto extraído pelo JavaParser e CodebaseIndex.

Uso:
    extractor = JavaContextExtractor(base_path="/path/to/sf110")
    prompt = extractor.build_prompt("com.example.MyClass", "myMethod")
    print(prompt)
"""

from typing import Optional

from java_parser import (
    ClassInfo,
    CodebaseIndex,
    FieldInfo,
    JavaParser,
    MethodInfo,
)


class JavaContextExtractor:
    """
    Extrai o contexto necessário para geração de testes com LLMs e monta o prompt.

    Exemplo de uso:
        extractor = JavaContextExtractor("/path/to/sf110")
        prompt = extractor.build_prompt("com.example.MyClass", "myMethod")
    """

    def __init__(self, base_path: str, verbose: bool = False):
        self.index = CodebaseIndex(base_path)
        self.index.build_index(verbose=verbose)
        self._parser = JavaParser()

    def build_prompt(
        self,
        class_name: str,
        method_name: str,
        include_field_types: bool = True,
        max_dependent_classes: int = 3,
        junit_version: str = "JUnit 5",
        extra_instructions: str = "",
    ) -> Optional[str]:
        """
        Monta o prompt completo para geração de testes.

        Args:
            class_name:              Nome simples ou completo da classe alvo.
            method_name:             Nome do método focal.
            include_field_types:     Se True, inclui assinaturas de classes de campo.
            max_dependent_classes:   Limite de classes dependentes a incluir.
            junit_version:           Framework de testes a usar.
            extra_instructions:      Instruções adicionais customizadas.

        Returns:
            String com o prompt completo, ou None se classe/método não encontrado.
        """
        class_info = self.index.get_class(class_name)
        if not class_info:
            print(f"[Extractor] Classe '{class_name}' não encontrada no índice.")
            return None

        focal_method = self._find_method(class_info, method_name)
        if not focal_method:
            print(f"[Extractor] Método '{method_name}' não encontrado em '{class_name}'.")
            return None

        # Coleta dependências
        called_methods  = self._get_called_methods(class_info, focal_method)
        dependent_classes = self._get_dependent_classes(
            class_info, focal_method, max_dependent_classes
        )

        return self._assemble_prompt(
            class_info=class_info,
            focal_method=focal_method,
            called_methods=called_methods,
            dependent_classes=dependent_classes,
            junit_version=junit_version,
            extra_instructions=extra_instructions,
        )

    # ------------------------------------------------------------------ #
    #  Extração de dependências                                            #
    # ------------------------------------------------------------------ #

    def _find_method(self, class_info: ClassInfo, method_name: str) -> Optional[MethodInfo]:
        for m in class_info.methods:
            if m.name == method_name:
                return m
        return None

    def _get_called_methods(
        self, class_info: ClassInfo, focal_method: MethodInfo
    ) -> list[MethodInfo]:
        """Retorna os métodos da mesma classe chamados pelo método focal (só assinatura)."""
        calls = self._parser.extract_method_calls(focal_method.body)
        result = []
        for m in class_info.methods:
            if m.name in calls and m.name != focal_method.name:
                # Inclui apenas a assinatura, sem o corpo
                result.append(MethodInfo(
                    name=m.name,
                    return_type=m.return_type,
                    parameters=m.parameters,
                    modifiers=m.modifiers,
                    body="",
                    signature_only=True,
                ))
        return result

    def _get_dependent_classes(
        self,
        class_info: ClassInfo,
        focal_method: MethodInfo,
        max_classes: int,
    ) -> list[ClassInfo]:
        """Resolve e retorna classes dependentes (tipos usados no método e nos campos)."""
        types_used = self._parser.extract_types_used(
            focal_method.body, class_info.fields, focal_method.parameters
        )

        dependent = []
        for type_name in list(types_used)[:max_classes * 2]:  # margem para filtrar
            candidates = self.index.find_classes_by_simple_name(type_name)
            if candidates:
                dependent.append(candidates[0])
            if len(dependent) >= max_classes:
                break

        return dependent

    # ------------------------------------------------------------------ #
    #  Montagem do Prompt                                                  #
    # ------------------------------------------------------------------ #

    def _assemble_prompt(
        self,
        class_info: ClassInfo,
        focal_method: MethodInfo,
        called_methods: list[MethodInfo],
        dependent_classes: list[ClassInfo],
        junit_version: str,
        extra_instructions: str,
    ) -> str:
        sections = []

        # --- Cabeçalho ---
        sections.append(
            f"Gere testes unitários {junit_version} com Mockito para o método abaixo.\n"
            f"A classe alvo é `{class_info.class_name}` do pacote `{class_info.package}`.\n"
        )

        # --- Imports relevantes ---
        relevant_imports = self._filter_relevant_imports(
            class_info.imports, focal_method, class_info.fields
        )
        if relevant_imports:
            sections.append("=== IMPORTS ===")
            sections.append("\n".join(f"import {i};" for i in relevant_imports))

        # --- Pacote e classe ---
        sections.append("=== DECLARAÇÃO DA CLASSE ===")
        sections.append(f"package {class_info.package};\n")
        sections.append(f"public class {class_info.class_name} {{")

        # --- Campos ---
        if class_info.fields:
            sections.append("\n  // Campos")
            for f in class_info.fields:
                sections.append(f"  {f.raw}")

        # --- Construtores ---
        if class_info.constructors:
            sections.append("\n  // Construtores")
            for c in class_info.constructors:
                sections.append(f"  {c.signature} {{")
                # Inclui o corpo do construtor (geralmente curto e informativo)
                for line in c.body.strip().split('\n')[:10]:  # limite de 10 linhas
                    sections.append(f"    {line}")
                sections.append("  }")

        sections.append("}\n")

        # --- Método focal ---
        sections.append("=== MÉTODO FOCAL (a ser testado) ===")
        sections.append(f"{focal_method.modifiers} {focal_method.return_type} "
                        f"{focal_method.name}({focal_method.parameters}) {{")
        sections.append(focal_method.body)
        sections.append("}\n")

        # --- Métodos auxiliares (só assinaturas) ---
        if called_methods:
            sections.append("=== MÉTODOS AUXILIARES CHAMADOS (apenas assinaturas) ===")
            for m in called_methods:
                sections.append(f"{m.signature};")
            sections.append("")

        # --- Classes dependentes ---
        if dependent_classes:
            sections.append("=== CLASSES DEPENDENTES (campos e assinaturas) ===")
            for dep in dependent_classes:
                sections.append(f"// {dep.full_name}")
                sections.append(f"public class {dep.class_name} {{")
                for f in dep.fields:
                    sections.append(f"  {f.raw}")
                for m in dep.methods:
                    sections.append(f"  {m.signature};")
                sections.append("}\n")

        # --- Instruções de geração ---
        sections.append("=== INSTRUÇÕES ===")
        instructions = [
            f"- Use {junit_version} e Mockito",
            "- Cubra: happy path, valores nulos/vazios e casos de borda",
            "- Mocke todas as dependências externas com @Mock / Mockito.mock()",
            "- Use apenas os métodos e campos listados acima; não invente APIs",
            "- Cada teste deve ter um nome descritivo no padrão: "
            "  `dado_<contexto>_quando_<ação>_entao_<resultado>`",
            "- Adicione um comentário explicando o objetivo de cada teste",
        ]
        if extra_instructions:
            instructions.append(f"- {extra_instructions}")

        sections.append("\n".join(instructions))
        sections.append("\nGere apenas o código Java, sem explicações adicionais.")

        return "\n".join(sections)

    def _filter_relevant_imports(
        self,
        imports: list[str],
        focal_method: MethodInfo,
        fields: list[FieldInfo],
    ) -> list[str]:
        """Filtra imports relevantes para o método focal (evita inflar o prompt)."""
        # Coleta tipos mencionados no método
        method_text = f"{focal_method.parameters} {focal_method.body}"
        field_types = {f.type_name.split("<")[0] for f in fields}

        relevant = []
        for imp in imports:
            # Extrai o nome simples do import (última parte)
            simple = imp.split(".")[-1].replace("*", "")
            if (simple in method_text or
                    simple in field_types or
                    simple == "*" or
                    imp.startswith("java.util") or
                    imp.startswith("java.io")):
                relevant.append(imp)

        return relevant[:20]  # limite para não inflar o prompt
