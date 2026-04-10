"""
CLI for the Java test generation pipeline.

Subcommands:
    example        — Run inline example (no external codebase needed)
    extract        — Extract a prompt for a specific method
    batch          — Extract prompts in batch for all methods in a codebase
    download       — Download a model from Hugging Face
    generate       — Generate a test from a single prompt file using a local LLM
    generate-batch — Generate tests in batch from a directory of prompt files
    evaluate       — Evaluate a single generated test
    evaluate-batch — Evaluate all generated tests in a directory

Usage:
    python run.py example
    python run.py extract --base /path/to/sf110 --class MyClass --method myMethod
    python run.py batch --base /path/to/sf110 --output-dir output --max 100
    python run.py download --model-id Qwen/Qwen3-0.5B
    python run.py generate --model Qwen_Qwen3-0.5B --prompt output/0007_DocumentSet_wordFrequency.txt
    python run.py generate-batch --model Qwen_Qwen3-0.5B --input-dir output --output-dir generated_tests
    python run.py evaluate --test-dir generated_tests/1_tullibee/Foo_calculateTotal_abc123/
    python run.py evaluate-batch --tests-dir generated_tests/ --output-csv evaluation_results.csv
"""

import argparse
import json
import sys
from pathlib import Path

# Ensure the extractor module is on the path
sys.path.insert(0, str(Path(__file__).parent))
from java_parser import JavaParser, CodebaseIndex
from context_extractor import JavaContextExtractor
from model_manager import ModelManager
from evaluator import evaluate_test, evaluate_batch


# ---------------------------------------------------------------------------
# Inline example (for testing without the SF110 codebase)
# ---------------------------------------------------------------------------

EXAMPLE_JAVA = """
package com.example.shop;

import java.util.List;
import java.util.ArrayList;

public class ShoppingCart {

    private List<Item> items;
    private double discount;
    private Customer customer;

    public ShoppingCart(Customer customer) {
        this.customer = customer;
        this.items = new ArrayList<>();
        this.discount = 0.0;
    }

    public void addItem(Item item) {
        if (item == null) {
            throw new IllegalArgumentException("Item cannot be null");
        }
        items.add(item);
    }

    public double calculateTotal() {
        double subtotal = calculateSubtotal();
        return subtotal - (subtotal * discount);
    }

    private double calculateSubtotal() {
        return items.stream()
                    .mapToDouble(i -> i.getPrice() * i.getQuantity())
                    .sum();
    }

    public int getItemCount() {
        return items.size();
    }

    public void applyDiscount(double rate) {
        if (rate < 0 || rate > 1) {
            throw new IllegalArgumentException("Discount rate must be between 0 and 1");
        }
        this.discount = rate;
    }
}
"""

EXAMPLE_ITEM = """
package com.example.shop;

public class Item {
    private String name;
    private double price;
    private int quantity;

    public Item(String name, double price, int quantity) {
        this.name = name;
        this.price = price;
        this.quantity = quantity;
    }

    public double getPrice() { return price; }
    public int getQuantity() { return quantity; }
    public String getName() { return name; }
}
"""


def run_inline_example():
    """Demonstrates the extractor with embedded Java code (no external codebase needed)."""
    import tempfile

    print("=" * 60)
    print("INLINE EXAMPLE (no external database)")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        shop_dir = Path(tmpdir) / "com" / "example" / "shop"
        shop_dir.mkdir(parents=True)

        (shop_dir / "ShoppingCart.java").write_text(EXAMPLE_JAVA)
        (shop_dir / "Item.java").write_text(EXAMPLE_ITEM)

        extractor = JavaContextExtractor(tmpdir, verbose=True)

        print("\n--- Prompt for ShoppingCart.calculateTotal ---\n")
        prompt = extractor.build_prompt(
            class_name="ShoppingCart",
            method_name="calculateTotal",
            max_dependent_classes=2,
        )

        if prompt:
            print(prompt)
        else:
            print("[ERROR] Could not generate prompt.")

        print("\n" + "=" * 60)
        print("BATCH EXTRACTION — all methods from ShoppingCart")
        print("=" * 60)

        class_info = extractor.index.get_class("ShoppingCart")
        if class_info:
            for method in class_info.methods:
                print(f"\n  → Method: {method.signature}")
                p = extractor.build_prompt("ShoppingCart", method.name)
                print(f"    Prompt generated: {len(p)} chars" if p else "    [FAILED]")


def run_sf110(base_path: str, class_name: str, method_name: str,
              output_file: str = None, junit: str = "JUnit 5",
              prompt_type: str = "zero_shot"):
    """Runs the extractor on the real SF110 codebase."""
    print(f"[SF110] Base: {base_path}")
    print(f"[SF110] Class: {class_name} | Method: {method_name}")
    print()

    extractor = JavaContextExtractor(base_path, verbose=True)

    prompt = extractor.build_prompt(
        class_name=class_name,
        method_name=method_name,
        prompt_type=prompt_type,
        junit_version=junit,
    )

    if not prompt:
        print("[ERROR] Prompt not generated. Check class and method names.")
        sys.exit(1)

    if output_file:
        Path(output_file).write_text(prompt, encoding='utf-8')
        print(f"\n[OK] Prompt saved to: {output_file}")
    else:
        print("\n" + "=" * 60)
        print(prompt)


_EVOSUITE_CLASS_SUFFIXES = ("EvoSuiteTest", "EvoSuiteScaffolding")

# GUI Swing event-handler name patterns — these methods receive AWT/Swing event
# objects that are hard to construct correctly and rarely make sense to unit-test.
_GUI_EVENT_HANDLER_PATTERNS = (
    "MouseClicked", "MousePressed", "MouseReleased", "MouseEntered", "MouseExited",
    "KeyTyped", "KeyPressed", "KeyReleased",
    "FocusLost", "FocusGained",
    "ActionPerformed", "StateChanged", "ItemStateChanged",
    "ComponentResized", "WindowClosing", "WindowOpened",
)


def _is_evosuite_class(class_name: str) -> bool:
    return any(class_name.endswith(s) for s in _EVOSUITE_CLASS_SUFFIXES)


def _is_gui_event_handler(method_name: str) -> bool:
    return any(method_name.endswith(p) for p in _GUI_EVENT_HANDLER_PATTERNS)


def batch_extract(base_path: str, output_dir: str, max_methods: int = 100,
                  prompt_type: str = "zero_shot"):
    """
    Extracts prompts in batch for all methods in the codebase.
    Useful for generating the complete experiment dataset.

    Automatically skips:
    - EvoSuite scaffold classes (*EvoSuiteTest, *EvoSuiteScaffolding)
    - GUI Swing event-handler methods (e.g. btnExitMouseClicked, txtTitleFocusLost)
    """
    extractor = JavaContextExtractor(base_path, verbose=True)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    results = []
    count = 0
    skipped_evosuite = 0
    skipped_gui = 0

    for full_name, class_info in extractor.index._class_map.items():
        if _is_evosuite_class(class_info.class_name):
            skipped_evosuite += 1
            continue

        for method in class_info.methods:
            if count >= max_methods:
                break

            if _is_gui_event_handler(method.name):
                skipped_gui += 1
                continue

            prompt = extractor.build_prompt(
                class_name=class_info.class_name,
                method_name=method.name,
                prompt_type=prompt_type,
            )

            if prompt:
                entry = {
                    "id": f"{full_name}#{method.name}",
                    "class": full_name,
                    "method": method.name,
                    "signature": method.signature,
                    "prompt_length": len(prompt),
                    "prompt_file": f"{count:04d}_{class_info.class_name}_{method.name}.txt",
                    "source_path": class_info.source_path,
                    "package": class_info.package,
                    "base_path": base_path,
                }

                (out / entry["prompt_file"]).write_text(prompt, encoding='utf-8')
                results.append(entry)
                count += 1

        if count >= max_methods:
            break

    meta_path = out / "batch_metadata.json"
    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"\n[Batch] {count} prompts generated in '{output_dir}'")
    print(f"[Batch] Skipped: {skipped_evosuite} EvoSuite classes, {skipped_gui} GUI event handlers")
    print(f"[Batch] Metadata: {meta_path}")
    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Java test generation pipeline: extract context and generate tests with local LLMs."
    )
    subparsers = parser.add_subparsers(dest="command")

    # Subcommand: inline example
    subparsers.add_parser("example", help="Run inline example without external codebase")

    # Subcommand: extract single prompt
    single = subparsers.add_parser("extract", help="Extract prompt for a specific method")
    single.add_argument("--base",        required=True, help="Path to Java codebase (e.g. /data/sf110)")
    single.add_argument("--class",       required=True, dest="class_name", help="Class name")
    single.add_argument("--method",      required=True, help="Method name")
    single.add_argument("--output",      default=None,  help="Output file (optional)")
    single.add_argument("--junit",       default="JUnit 5", help="JUnit version (default: JUnit 5)")
    single.add_argument("--prompt-type", default="zero_shot",
                        help="Prompt strategy to use (default: zero_shot)")

    # Subcommand: batch extract prompts
    batch = subparsers.add_parser("batch", help="Extract prompts in batch for the whole codebase")
    batch.add_argument("--base",        required=True, help="Path to Java codebase")
    batch.add_argument("--output-dir",  required=True, help="Output directory")
    batch.add_argument("--max",         type=int, default=100, help="Max methods (default: 100)")
    batch.add_argument("--prompt-type", default="zero_shot",
                       help="Prompt strategy to use (default: zero_shot)")

    # Subcommand: download model
    dl = subparsers.add_parser("download", help="Download model from Hugging Face")
    dl.add_argument("--model-id", required=True, help="HF model ID (e.g. Qwen/Qwen3-0.5B)")

    # Subcommand: generate test from single prompt
    gen = subparsers.add_parser("generate", help="Generate test from a single prompt file using a local LLM")
    gen.add_argument("--model",  required=True, help="Local model name (directory in models/)")
    gen.add_argument("--prompt", required=True, help="Prompt .txt file (e.g. output/0007_DocumentSet_wordFrequency.txt)")
    gen.add_argument("--output", default=None,  help="Output file for generated code")

    # Subcommand: generate tests in batch
    gen_batch = subparsers.add_parser("generate-batch", help="Generate tests in batch from prompt files")
    gen_batch.add_argument("--model",      required=True, help="Local model name")
    gen_batch.add_argument("--input-dir",  default="output", help="Directory with prompt .txt files (default: output)")
    gen_batch.add_argument("--output-dir", required=True, help="Output directory for generated tests")
    gen_batch.add_argument("--max",        type=int, default=100, help="Max files (default: 100)")

    # Subcommand: evaluate a single generated test
    ev = subparsers.add_parser("evaluate", help="Evaluate a single generated test")
    ev.add_argument("--test-dir",  required=True, help="Directory containing test.java and metadata.json")
    ev.add_argument("--keep-temp", action="store_true", help="Keep the temporary Maven project after evaluation")

    # Subcommand: evaluate all generated tests in a directory
    ev_batch = subparsers.add_parser("evaluate-batch", help="Evaluate all generated tests in a directory")
    ev_batch.add_argument("--tests-dir",   required=True, help="Root directory containing generated tests (e.g. generated_tests/)")
    ev_batch.add_argument("--output-csv",  default="evaluation_results.csv", help="Path for consolidated CSV report (default: evaluation_results.csv)")

    args = parser.parse_args()

    if args.command == "example" or args.command is None:
        run_inline_example()
    elif args.command == "extract":
        run_sf110(args.base, args.class_name, args.method, args.output, args.junit,
                  args.prompt_type)
    elif args.command == "batch":
        batch_extract(args.base, args.output_dir, args.max, args.prompt_type)
    elif args.command == "download":
        manager = ModelManager()
        manager.download_model(args.model_id)
    elif args.command == "generate":
        manager = ModelManager()
        code = manager.run_from_file(args.model, args.prompt, args.output)
        if not args.output:
            print("\n" + "=" * 60)
            print(code)
    elif args.command == "generate-batch":
        manager = ModelManager()
        manager.run_batch(args.model, args.input_dir, args.output_dir, args.max)
    elif args.command == "evaluate":
        result = evaluate_test(args.test_dir, keep_temp=args.keep_temp)
        print(f"\nquality_score = {result['quality_score']}")
    elif args.command == "evaluate-batch":
        evaluate_batch(args.tests_dir, args.output_csv)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
