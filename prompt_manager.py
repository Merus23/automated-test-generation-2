from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from java_parser import ClassInfo, MethodInfo


class PromptManager:

    SYSTEM_PROMPT = (
        "You are an expert Java developer specialized in writing unit tests. "
        "When given Java source code, you must respond with a complete, compilable JUnit test class. "
        "Output only the Java code — no explanations, no markdown fences, no comments outside the code."
    )

    def __init__(self):
        pass

    PROMPT_TYPES = ("zero_shot", "few_shot", "chain_of_thought")

    def get_system_prompt(self) -> str:
        return self.SYSTEM_PROMPT

    def build_prompt(self, prompt_type: str, **kwargs) -> str:
        """Dispatches to the prompt builder selected by *prompt_type*."""
        if prompt_type == "zero_shot":
            return self.get_zero_shot_prompt(**kwargs)
        if prompt_type == "few_shot":
            return self.get_few_shot_prompt(**kwargs)
        if prompt_type == "chain_of_thought":
            return self.get_chain_of_thought_prompt(**kwargs)
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

        test_class_name = f"{class_info.class_name}Test"
        pkg_display = class_info.package or "(default)"
        cls = class_info.class_name

        sections.append(
            f"Task: write a JUnit 4 + Mockito test class for `{cls}` "
            f"(package `{pkg_display}`).\n"
            "Output a SINGLE Java file with these exact parts, in order:\n"
            f"  (1) the FILE HEADER block below, copied verbatim;\n"
            f"  (2) one public class named `{test_class_name}` containing ONLY @Test methods.\n"
            f"Do NOT redeclare `{cls}`, do NOT nest classes, do NOT repeat the package line.\n"
            "All other sections below are REFERENCE ONLY — read them to understand the API, "
            "but do not copy their contents into your output."
        )

        sections.append("----- FILE HEADER START (copy these lines verbatim) -----")
        sections.append(self._build_required_imports(class_info, focal_method, dependent_classes))
        sections.append("----- FILE HEADER END -----\n")

        sections.append(f"----- REFERENCE: how to instantiate `{cls}` -----")
        if class_info.constructors:
            for c in class_info.constructors:
                sections.append(f"  new {c.name}({c.parameters});")
        else:
            sections.append(f"  new {cls}();  // implicit default constructor")
        sections.append("")

        sections.append(f"----- REFERENCE: focal method of `{cls}` (the method under test) -----")
        sections.append(
            f"{focal_method.modifiers} {focal_method.return_type} "
            f"{focal_method.name}({focal_method.parameters}) {{"
        )
        sections.append(focal_method.body)
        sections.append("}\n")

        if called_methods:
            sections.append(f"----- REFERENCE: other methods of `{cls}` callable from the test -----")
            for m in called_methods:
                sections.append(f"  {m.return_type} {m.name}({m.parameters});")
            sections.append("")

        if dependent_classes:
            sections.append("----- REFERENCE: dependent types (method signatures only) -----")
            for dep in dependent_classes:
                sections.append(f"// {dep.full_name}")
                for m in dep.methods:
                    sections.append(f"  {m.return_type} {dep.class_name}.{m.name}({m.parameters});")
            sections.append("")

        sections.append("----- INSTRUCTIONS -----")
        instructions = [
            f"- Write ONE public class `{test_class_name}` (no nested classes, no extra package line).",
            f"- Instantiate with `{cls} sut = new {cls}(...);` before calling instance methods.",
            "- Use ONLY methods shown in the REFERENCE sections. Do not invent APIs.",
            "- For any unknown parameter/dependency type, use `Mockito.mock(Type.class)`.",
            "- Cover happy path, null/empty values, and one edge case.",
            "- Each @Test method name must be unique.",
            "- Test names follow `given_<context>_when_<action>_then_<result>`.",
        ]
        if extra_instructions:
            instructions.append(f"- {extra_instructions}")

        sections.append("\n".join(instructions))
        sections.append("\nOutput only the Java code for the test file. No explanations, no markdown.")

        return "\n".join(sections)

    # ------------------------------------------------------------------ #
    # Few-shot examples embedded in the prompt                            #
    #                                                                     #
    # Each example shows only:                                            #
    #   - the focal method under test (not the full source class)         #
    #   - the test class body only (no package/imports — those come from  #
    #     the FILE HEADER that is already provided verbatim in the prompt) #
    # ------------------------------------------------------------------ #

    # Example 1: method with no external dependencies
    _EXAMPLE_1_FOCAL_METHOD = """\
// Constructor: new StringUtils();
public String reverse(String input) {
    if (input == null) return null;
    return new StringBuilder(input).reverse().toString();
}"""

    _EXAMPLE_1_TEST_BODY = """\
public class StringUtilsTest {

    @Test
    public void given_validString_when_reverse_then_returnsReversedString() {
        StringUtils sut = new StringUtils();
        assertEquals("olleh", sut.reverse("hello"));
    }

    @Test
    public void given_nullInput_when_reverse_then_returnsNull() {
        StringUtils sut = new StringUtils();
        assertNull(sut.reverse(null));
    }

    @Test
    public void given_emptyString_when_reverse_then_returnsEmptyString() {
        StringUtils sut = new StringUtils();
        assertEquals("", sut.reverse(""));
    }
}"""

    # Example 2: method that delegates to a mocked dependency
    _EXAMPLE_2_FOCAL_METHOD = """\
// Constructor: new OrderService(PaymentGateway paymentGateway);
public boolean processOrder(int orderId, double amount) {
    if (amount <= 0) throw new IllegalArgumentException("amount must be positive");
    return paymentGateway.charge(orderId, amount);
}"""

    _EXAMPLE_2_TEST_BODY = """\
public class OrderServiceTest {

    private PaymentGateway mockPaymentGateway;
    private OrderService sut;

    @Before
    public void setUp() {
        mockPaymentGateway = Mockito.mock(PaymentGateway.class);
        sut = new OrderService(mockPaymentGateway);
    }

    @Test
    public void given_validOrder_when_processOrder_then_chargesGatewayAndReturnsTrue() {
        when(mockPaymentGateway.charge(1, 100.0)).thenReturn(true);
        assertTrue(sut.processOrder(1, 100.0));
        verify(mockPaymentGateway).charge(1, 100.0);
    }

    @Test
    public void given_gatewayDeclines_when_processOrder_then_returnsFalse() {
        when(mockPaymentGateway.charge(2, 50.0)).thenReturn(false);
        assertFalse(sut.processOrder(2, 50.0));
    }

    @Test(expected = IllegalArgumentException.class)
    public void given_negativeAmount_when_processOrder_then_throwsIllegalArgumentException() {
        sut.processOrder(1, -10.0);
    }
}"""

    def get_few_shot_prompt(
        self,
        class_info: ClassInfo,
        focal_method: MethodInfo,
        called_methods: list[MethodInfo],
        dependent_classes: list[ClassInfo],
        junit_version: str,
        extra_instructions: str,
    ) -> str:
        sections = []

        test_class_name = f"{class_info.class_name}Test"
        pkg_display = class_info.package or "(default)"
        cls = class_info.class_name

        # 1. Task description
        sections.append(
            f"Task: write a JUnit 4 + Mockito test class for `{cls}` "
            f"(package `{pkg_display}`).\n"
            "Output a SINGLE Java file with these exact parts, in order:\n"
            f"  (1) the FILE HEADER block below, copied verbatim;\n"
            f"  (2) one public class named `{test_class_name}` containing ONLY @Test methods.\n"
            f"Do NOT redeclare `{cls}`, do NOT nest classes, do NOT repeat the package line.\n"
            "All REFERENCE sections are for reading only — do not copy them into your output."
        )

        # 2. Examples — placed early so the model calibrates its output format
        #    before processing the task-specific context.
        sections.append("----- EXAMPLES (output format to follow) -----")
        sections.append(
            "Each example shows: the focal method under test → the expected test class body.\n"
            "Note: package and imports are NOT shown in the examples because they will be\n"
            "provided in the FILE HEADER block below — copy that header verbatim.\n"
        )

        sections.append("## Example 1 — method with no external dependencies")
        sections.append("// Focal method:")
        sections.append(self._EXAMPLE_1_FOCAL_METHOD)
        sections.append("// Test class body:")
        sections.append(self._EXAMPLE_1_TEST_BODY)

        sections.append("\n## Example 2 — method that delegates to a mocked dependency")
        sections.append("// Focal method:")
        sections.append(self._EXAMPLE_2_FOCAL_METHOD)
        sections.append("// Test class body:")
        sections.append(self._EXAMPLE_2_TEST_BODY)

        sections.append("----- END OF EXAMPLES -----\n")

        # 3. FILE HEADER (package + imports to copy verbatim)
        sections.append("----- FILE HEADER START (copy these lines verbatim) -----")
        sections.append(self._build_required_imports(class_info, focal_method, dependent_classes))
        sections.append("----- FILE HEADER END -----\n")

        # 4. Reference sections (read-only context about the class under test)
        sections.append(f"----- REFERENCE: how to instantiate `{cls}` -----")
        if class_info.constructors:
            for c in class_info.constructors:
                sections.append(f"  new {c.name}({c.parameters});")
        else:
            sections.append(f"  new {cls}();  // implicit default constructor")
        sections.append("")

        sections.append(f"----- REFERENCE: focal method of `{cls}` (the method under test) -----")
        sections.append(
            f"{focal_method.modifiers} {focal_method.return_type} "
            f"{focal_method.name}({focal_method.parameters}) {{"
        )
        sections.append(focal_method.body)
        sections.append("}\n")

        if called_methods:
            sections.append(f"----- REFERENCE: other methods of `{cls}` callable from the test -----")
            for m in called_methods:
                sections.append(f"  {m.return_type} {m.name}({m.parameters});")
            sections.append("")

        if dependent_classes:
            sections.append("----- REFERENCE: dependent types (method signatures only) -----")
            for dep in dependent_classes:
                sections.append(f"// {dep.full_name}")
                for m in dep.methods:
                    sections.append(f"  {m.return_type} {dep.class_name}.{m.name}({m.parameters});")
            sections.append("")

        # 5. Instructions
        sections.append("----- INSTRUCTIONS -----")
        instructions = [
            f"- Write ONE public class `{test_class_name}` (no nested classes, no extra package line).",
            f"- Instantiate with `{cls} sut = new {cls}(...);` before calling instance methods.",
            "- Use ONLY methods shown in the REFERENCE sections. Do not invent APIs.",
            "- For any unknown parameter/dependency type, use `Mockito.mock(Type.class)`.",
            "- Cover happy path, null/empty values, and one edge case.",
            "- Each @Test method name must be unique.",
            "- Test names follow `given_<context>_when_<action>_then_<result>`.",
        ]
        if extra_instructions:
            instructions.append(f"- {extra_instructions}")
        sections.append("\n".join(instructions))

        sections.append("\nOutput only the Java code for the test file. No explanations, no markdown.")

        return "\n".join(sections)

    def get_chain_of_thought_prompt(
        self,
        class_info: ClassInfo,
        focal_method: MethodInfo,
        called_methods: list[MethodInfo],
        dependent_classes: list[ClassInfo],
        junit_version: str,
        extra_instructions: str,
    ) -> str:
        sections = []

        test_class_name = f"{class_info.class_name}Test"
        pkg_display = class_info.package or "(default)"
        cls = class_info.class_name

        # ------------------------------------------------------------------ #
        # 1. Task description                                                  #
        # ------------------------------------------------------------------ #
        sections.append(
            f"Task: write a JUnit 4 + Mockito test class for `{cls}` "
            f"(package `{pkg_display}`).\n"
            "You must reason step by step before writing any code.\n"
            "Output a SINGLE Java file with these exact parts, in order:\n"
            f"  (1) the FILE HEADER block below, copied verbatim;\n"
            f"  (2) one public class named `{test_class_name}` containing ONLY @Test methods.\n"
            f"Do NOT redeclare `{cls}`, do NOT nest classes, do NOT repeat the package line.\n"
            "All REFERENCE sections are for reading only — do not copy them into your output."
        )

        # ------------------------------------------------------------------ #
        # 2. FILE HEADER                                                       #
        # ------------------------------------------------------------------ #
        sections.append("----- FILE HEADER START (copy these lines verbatim) -----")
        sections.append(self._build_required_imports(class_info, focal_method, dependent_classes))
        sections.append("----- FILE HEADER END -----\n")

        # ------------------------------------------------------------------ #
        # 3. Reference sections                                                #
        # ------------------------------------------------------------------ #
        sections.append(f"----- REFERENCE: how to instantiate `{cls}` -----")
        if class_info.constructors:
            visible_ctors = [
                c for c in class_info.constructors
                if "private" not in (c.modifiers or "")
            ]
            if visible_ctors:
                for c in visible_ctors:
                    sections.append(f"  new {c.name}({c.parameters});")
            else:
                sections.append(
                    f"  // all constructors are private — use Mockito.mock({cls}.class)"
                )
        else:
            sections.append(f"  new {cls}();  // implicit default constructor")
        sections.append("")

        sections.append(f"----- REFERENCE: focal method of `{cls}` (the method under test) -----")
        sections.append(
            f"{focal_method.modifiers} {focal_method.return_type} "
            f"{focal_method.name}({focal_method.parameters}) {{"
        )
        sections.append(focal_method.body)
        sections.append("}\n")

        if called_methods:
            sections.append(
                f"----- REFERENCE: other methods of `{cls}` callable from the test -----"
            )
            for m in called_methods:
                sections.append(f"  {m.return_type} {m.name}({m.parameters});")
            sections.append("")

        if dependent_classes:
            sections.append("----- REFERENCE: dependent types (method signatures only) -----")
            for dep in dependent_classes:
                sections.append(f"// {dep.full_name}")
                for m in dep.methods[:8]:
                    sections.append(
                        f"  {m.return_type} {dep.class_name}.{m.name}({m.parameters});"
                    )
                if len(dep.methods) > 8:
                    sections.append(f"  // {len(dep.methods) - 8} more method(s) omitted")
            sections.append("")

        # ------------------------------------------------------------------ #
        # 4. Chain-of-Thought reasoning steps                                 #
        #                                                                     #
        # Structured in three tightly-scoped steps based on TestCTRL (TOSEM  #
        # 2025): (1) method intention, (2) concrete test inputs per scenario, #
        # (3) code generation. Steps are bounded to prevent over-generation   #
        # observed by Bodicoat et al. (2025) with unbounded CoT.             #
        # ------------------------------------------------------------------ #
        sections.append("----- CHAIN-OF-THOUGHT: reason before you code -----")
        sections.append(
            "Before writing the test class, reason through the following three steps.\n"
            "Write your reasoning as Java comments (// ...) immediately before the test class.\n"
            "Keep each step concise — 2 to 4 lines maximum per step.\n"
        )

        sections.append(
            "// STEP 1 — METHOD INTENTION\n"
            "// Describe in one or two sentences what the focal method is supposed to do,\n"
            f"// what it returns, and what invariants it must respect.\n"
            "// Example:\n"
            f"// The method `{focal_method.name}` [describe purpose].\n"
            f"// It returns [{focal_method.return_type}] when [condition].\n"
        )

        sections.append(
            "// STEP 2 — TEST SCENARIOS\n"
            "// List the distinct scenarios to be tested, one per line.\n"
            "// For each scenario, state: input values → expected output or behavior.\n"
            "// Cover at minimum:\n"
            "//   (a) happy path — typical valid inputs → expected result;\n"
            "//   (b) boundary or null inputs → expected result or exception;\n"
            "//   (c) one edge case derived from the method body logic.\n"
            "// Example:\n"
            "// Scenario A: input=[...] → returns [...]\n"
            "// Scenario B: input=null  → returns null / throws [...]\n"
            "// Scenario C: input=[...] → [edge case behavior]\n"
        )

        sections.append(
            "// STEP 3 — COMPILATION CHECK\n"
            "// Before finalizing, verify:\n"
            f"//   (a) `{cls}` is instantiated with a visible constructor or Mockito.mock();\n"
            "//   (b) every method call matches the exact signature in the REFERENCE sections;\n"
            "//   (c) every @Test method contains at least one assertion;\n"
            "//   (d) no class, package, or import is declared twice.\n"
        )

        sections.append("----- END OF CHAIN-OF-THOUGHT -----\n")

        # ------------------------------------------------------------------ #
        # 5. Instructions                                                      #
        # ------------------------------------------------------------------ #
        sections.append("----- INSTRUCTIONS -----")
        instructions = [
            "- Write the reasoning (Steps 1–3) as Java comments before the class declaration.",
            f"- Then write ONE public class `{test_class_name}` (no nested classes, no extra package line).",
            f"- Instantiate with `{cls} sut = new {cls}(...);` before calling instance methods.",
            "- Use ONLY methods shown in the REFERENCE sections. Do not invent APIs.",
            "- For any unknown parameter/dependency type, use `Mockito.mock(Type.class)`.",
            "- Each @Test method must correspond to exactly one scenario from Step 2.",
            "- Each @Test method must contain at least one assertion.",
            "- Each @Test method name must be unique.",
            "- Test names follow `given_<context>_when_<action>_then_<result>`.",
        ]
        if extra_instructions:
            instructions.append(f"- {extra_instructions}")

        sections.append("\n".join(instructions))
        sections.append(
            "\nOutput only the Java code for the test file "
            "(reasoning as comments + test class). No explanations, no markdown."
        )

        return "\n".join(sections)

    def _build_required_imports(
        self,
        class_info: ClassInfo,
        focal_method: MethodInfo,
        dependent_classes: list[ClassInfo],
    ) -> str:
        """Builds a deterministic package + imports block for the test file.

        The block is pre-assembled in Python so the model does not have to
        remember which types require which imports. The test file is expected
        to live in the SAME package as the class under test, giving it access
        to package-private members.
        """
        lines: list[str] = []

        if class_info.package:
            lines.append(f"package {class_info.package};")
            lines.append("")

        lines.extend([
            "import org.junit.Test;",
            "import org.junit.Before;",
            "import static org.junit.Assert.*;",
            "import org.mockito.Mock;",
            "import org.mockito.Mockito;",
            "import static org.mockito.Mockito.*;",
        ])

        seen_fqns: set[str] = set()

        for dep in dependent_classes:
            if not dep.full_name or dep.full_name == class_info.full_name:
                continue
            if dep.full_name in seen_fqns:
                continue
            if dep.package and dep.package == class_info.package:
                continue
            lines.append(f"import {dep.full_name};")
            seen_fqns.add(dep.full_name)

        method_text = f"{focal_method.parameters} {focal_method.body or ''}"
        field_types = {f.type_name.split("<")[0] for f in class_info.fields}

        remaining_budget = 25
        for imp in class_info.imports:
            if remaining_budget <= 0:
                break
            if imp in seen_fqns:
                continue
            if imp.endswith(".*"):
                lines.append(f"import {imp};")
                seen_fqns.add(imp)
                remaining_budget -= 1
                continue
            simple = imp.rsplit(".", 1)[-1]
            if (re.search(rf'\b{re.escape(simple)}\b', method_text)
                    or simple in field_types):
                lines.append(f"import {imp};")
                seen_fqns.add(imp)
                remaining_budget -= 1

        return "\n".join(lines)
