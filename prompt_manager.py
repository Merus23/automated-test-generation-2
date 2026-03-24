from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from java_parser import ClassInfo, FieldInfo, MethodInfo


class PromptManager:

    SYSTEM_PROMPT = (
        "You are an expert Java developer specialized in writing unit tests. "
        "When given Java source code, you must respond with a complete, compilable JUnit test class. "
        "Output only the Java code — no explanations, no markdown fences, no comments outside the code."
    )

    def __init__(self):
        pass

    def get_system_prompt(self) -> str:
        return self.SYSTEM_PROMPT

    # def get_zero_shot_prompt(self, code) -> str:
    #     return f"Write a test case for the following code:\n{code} \n\n Write only the test case code, without explanations."

    def another_prompt_method(self, code) -> str:
        return f"{code}"

    def get_zero_shot_prompt(
        self,
        class_info: ClassInfo,
        focal_method: MethodInfo,
        called_methods: list[MethodInfo],
        dependent_classes: list[ClassInfo],
        junit_version: str,
        extra_instructions: str,
    ) -> str:
        sections = []

        # --- Header ---
        sections.append(
            f"Gere testes unitários {junit_version} com Mockito para o método abaixo.\n"
            f"A classe alvo é `{class_info.class_name}` do pacote `{class_info.package}`.\n"
        )

        # --- Relevant imports ---
        relevant_imports = self._filter_relevant_imports(
            class_info.imports, focal_method, class_info.fields
        )
        if relevant_imports:
            sections.append("=== IMPORTS ===")
            sections.append("\n".join(f"import {i};" for i in relevant_imports))

        # --- Package and class declaration ---
        sections.append("=== DECLARAÇÃO DA CLASSE ===")
        sections.append(f"package {class_info.package};\n")
        sections.append(f"public class {class_info.class_name} {{")

        # --- Fields ---
        if class_info.fields:
            sections.append("\n  // Campos")
            for f in class_info.fields:
                sections.append(f"  {f.raw}")

        # --- Constructors ---
        if class_info.constructors:
            sections.append("\n  // Construtores")
            for c in class_info.constructors:
                sections.append(f"  {c.signature} {{")
                for line in c.body.strip().split('\n')[:10]:
                    sections.append(f"    {line}")
                sections.append("  }")

        sections.append("}\n")

        # --- Focal method ---
        sections.append("=== MÉTODO FOCAL (a ser testado) ===")
        sections.append(f"{focal_method.modifiers} {focal_method.return_type} "
                        f"{focal_method.name}({focal_method.parameters}) {{")
        sections.append(focal_method.body)
        sections.append("}\n")

        # --- Helper methods (signatures only) ---
        if called_methods:
            sections.append("=== MÉTODOS AUXILIARES CHAMADOS (apenas assinaturas) ===")
            for m in called_methods:
                sections.append(f"{m.signature};")
            sections.append("")

        # --- Dependent classes ---
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

        # --- Generation instructions ---
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
        method_text = f"{focal_method.parameters} {focal_method.body}"
        field_types = {f.type_name.split("<")[0] for f in fields}

        relevant = []
        for imp in imports:
            simple = imp.split(".")[-1].replace("*", "")
            if (simple in method_text or
                    simple in field_types or
                    simple == "*" or
                    imp.startswith("java.util") or
                    imp.startswith("java.io")):
                relevant.append(imp)

        return relevant[:20]
