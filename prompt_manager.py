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

    PROMPT_TYPES = ("zero_shot",)

    def get_system_prompt(self) -> str:
        return self.SYSTEM_PROMPT

    def build_prompt(self, prompt_type: str, **kwargs) -> str:
        """Dispatches to the prompt builder selected by *prompt_type*."""
        if prompt_type == "zero_shot":
            return self.get_zero_shot_prompt(**kwargs)
        raise ValueError(
            f"Unknown prompt type '{prompt_type}'. "
            f"Available: {', '.join(self.PROMPT_TYPES)}"
        )

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
            f"Generate unit tests with Mockito for the method below.\n"
            f"Use JUnit 4 (org.junit) or JUnit 5 (org.junit.jupiter.api) — whichever you know best.\n"
            f"The target class is `{class_info.class_name}` from package `{class_info.package}`.\n"
        )

        # --- Relevant imports ---
        relevant_imports = self._filter_relevant_imports(
            class_info.imports, focal_method, class_info.fields
        )
        if relevant_imports:
            sections.append("=== IMPORTS ===")
            sections.append("\n".join(f"import {i};" for i in relevant_imports))

        # --- Package and class declaration ---
        sections.append("=== CLASS DECLARATION ===")
        sections.append(f"package {class_info.package};\n")
        sections.append(f"public class {class_info.class_name} {{")

        # --- Fields ---
        if class_info.fields:
            sections.append("\n  // Fields")
            for f in class_info.fields:
                sections.append(f"  {f.raw}")

        # --- Constructors ---
        if class_info.constructors:
            sections.append("\n  // Constructors")
            for c in class_info.constructors:
                sections.append(f"  {c.signature} {{")
                for line in c.body.strip().split('\n')[:10]:
                    sections.append(f"    {line}")
                sections.append("  }")

        sections.append("}\n")

        # --- Focal method ---
        sections.append("=== FOCAL METHOD (to be tested) ===")
        sections.append(f"{focal_method.modifiers} {focal_method.return_type} "
                        f"{focal_method.name}({focal_method.parameters}) {{")
        sections.append(focal_method.body)
        sections.append("}\n")

        # --- Helper methods (signatures only) ---
        if called_methods:
            sections.append("=== HELPER METHODS CALLED (signatures only) ===")
            for m in called_methods:
                sections.append(f"{m.signature};")
            sections.append("")

        # --- Dependent classes ---
        if dependent_classes:
            sections.append("=== DEPENDENT CLASSES (fields and signatures) ===")
            for dep in dependent_classes:
                sections.append(f"// {dep.full_name}")
                sections.append(f"public class {dep.class_name} {{")
                for f in dep.fields:
                    sections.append(f"  {f.raw}")
                for m in dep.methods:
                    sections.append(f"  {m.signature};")
                sections.append("}\n")

        # --- Generation instructions ---
        sections.append("=== INSTRUCTIONS ===")
        instructions = [
            "- Use JUnit 4 or JUnit 5 (your choice) with Mockito",
            "- Cover: happy path, null/empty values, and edge cases",
            "- Mock all external dependencies with @Mock / Mockito.mock()",
            "- Use only the methods and fields listed above; do not invent APIs",
            "- Each test must have a descriptive name following the pattern: "
            "  `given_<context>_when_<action>_then_<result>`",
            "- Add a comment explaining the purpose of each test",
        ]
        if extra_instructions:
            instructions.append(f"- {extra_instructions}")

        sections.append("\n".join(instructions))
        sections.append("\nGenerate only the Java code, without any additional explanations.")

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
