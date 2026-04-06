"""
Java Context Extractor — Prompt Builder for LLMs
=================================================
Builds structured prompts for LLM-based unit test generation
from context extracted by JavaParser and CodebaseIndex.

Usage:
    extractor = JavaContextExtractor(base_path="/path/to/sf110")
    prompt = extractor.build_prompt("com.example.MyClass", "myMethod")
    print(prompt)
"""

from typing import Optional

from java_parser import (
    ClassInfo,
    CodebaseIndex,
    JavaParser,
    MethodInfo,
)
from prompt_manager import PromptManager


class JavaContextExtractor:
    """
    Extracts the context required for LLM-based test generation and assembles the prompt.

    Example usage:
        extractor = JavaContextExtractor("/path/to/sf110")
        prompt = extractor.build_prompt("com.example.MyClass", "myMethod")
    """

    def __init__(self, base_path: str, verbose: bool = False):
        self.index = CodebaseIndex(base_path)
        self.index.build_index(verbose=verbose)
        self._parser = JavaParser()
        self._prompt_manager = PromptManager()

    def build_prompt(
        self,
        class_name: str,
        method_name: str,
        prompt_type: str = "zero_shot",
        include_field_types: bool = True,
        max_dependent_classes: int = 3,
        junit_version: str = "JUnit 5",
        extra_instructions: str = "",
    ) -> Optional[str]:
        """
        Builds the complete prompt for test generation.

        Args:
            class_name:              Simple or fully-qualified target class name.
            method_name:             Focal method name.
            prompt_type:             Prompt strategy to use (see PromptManager.PROMPT_TYPES).
            include_field_types:     If True, includes field class signatures.
            max_dependent_classes:   Max number of dependent classes to include.
            junit_version:           Test framework to target.
            extra_instructions:      Optional custom instructions appended to the prompt.

        Returns:
            Complete prompt string, or None if the class/method is not found.
        """
        class_info = self.index.get_class(class_name)
        if not class_info:
            print(f"[Extractor] Class '{class_name}' not found in index.")
            return None

        focal_method = self._find_method(class_info, method_name)
        if not focal_method:
            print(f"[Extractor] Method '{method_name}' not found in '{class_name}'.")
            return None

        # Collect dependencies
        called_methods  = self._get_called_methods(class_info, focal_method)
        dependent_classes = self._get_dependent_classes(
            class_info, focal_method, max_dependent_classes
        )

        return self._prompt_manager.build_prompt(
            prompt_type,
            class_info=class_info,
            focal_method=focal_method,
            called_methods=called_methods,
            dependent_classes=dependent_classes,
            junit_version=junit_version,
            extra_instructions=extra_instructions,
        )

    # ------------------------------------------------------------------ #
    #  Dependency extraction                                               #
    # ------------------------------------------------------------------ #

    def _find_method(self, class_info: ClassInfo, method_name: str) -> Optional[MethodInfo]:
        for m in class_info.methods:
            if m.name == method_name:
                return m
        return None

    def _get_called_methods(
        self, class_info: ClassInfo, focal_method: MethodInfo
    ) -> list[MethodInfo]:
        """Returns methods of the same class called by the focal method (signatures only)."""
        calls = self._parser.extract_method_calls(focal_method.body)
        result = []
        for m in class_info.methods:
            if m.name in calls and m.name != focal_method.name:
                # Include signature only, without the body
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
        """Resolves and returns dependent classes (types used in the method and in fields)."""
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

