"""
CLI for the Java test generation pipeline.

Subcommands:
    example   — Run inline example (no external codebase needed)
    extract   — Extract a prompt for a specific method
    batch     — Extract prompts in batch for all methods in a codebase
    download  — Download a model from Hugging Face
    generate  — Generate a test from a single prompt file using a local LLM
    generate-batch — Generate tests in batch from a directory of prompt files

Usage:
    python run.py example
    python run.py extract --base /path/to/sf110 --class MyClass --method myMethod
    python run.py batch --base /path/to/sf110 --output-dir output --max 100
    python run.py download --model-id Qwen/Qwen3-0.5B
    python run.py generate --model Qwen_Qwen3-0.5B --prompt output/0007_DocumentSet_wordFrequency.txt
    python run.py generate-batch --model Qwen_Qwen3-0.5B --input-dir output --output-dir generated_tests
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
              output_file: str = None, junit: str = "JUnit 5"):
    """Runs the extractor on the real SF110 codebase."""
    print(f"[SF110] Base: {base_path}")
    print(f"[SF110] Class: {class_name} | Method: {method_name}")
    print()

    extractor = JavaContextExtractor(base_path, verbose=True)

    prompt = extractor.build_prompt(
        class_name=class_name,
        method_name=method_name,
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


def batch_extract(base_path: str, output_dir: str, max_methods: int = 100):
    """
    Extracts prompts in batch for all methods in the codebase.
    Useful for generating the complete experiment dataset.
    """
    extractor = JavaContextExtractor(base_path, verbose=True)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    results = []
    count = 0

    for full_name, class_info in extractor.index._class_map.items():
        for method in class_info.methods:
            if count >= max_methods:
                break

            prompt = extractor.build_prompt(
                class_name=class_info.class_name,
                method_name=method.name,
            )

            if prompt:
                entry = {
                    "id": f"{full_name}#{method.name}",
                    "class": full_name,
                    "method": method.name,
                    "signature": method.signature,
                    "prompt_length": len(prompt),
                    "prompt_file": f"{count:04d}_{class_info.class_name}_{method.name}.txt"
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
    single.add_argument("--base",   required=True, help="Path to Java codebase (e.g. /data/sf110)")
    single.add_argument("--class",  required=True, dest="class_name", help="Class name")
    single.add_argument("--method", required=True, help="Method name")
    single.add_argument("--output", default=None,  help="Output file (optional)")
    single.add_argument("--junit",  default="JUnit 5", help="JUnit version (default: JUnit 5)")

    # Subcommand: batch extract prompts
    batch = subparsers.add_parser("batch", help="Extract prompts in batch for the whole codebase")
    batch.add_argument("--base",       required=True, help="Path to Java codebase")
    batch.add_argument("--output-dir", required=True, help="Output directory")
    batch.add_argument("--max",        type=int, default=100, help="Max methods (default: 100)")

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

    args = parser.parse_args()

    if args.command == "example" or args.command is None:
        run_inline_example()
    elif args.command == "extract":
        run_sf110(args.base, args.class_name, args.method, args.output, args.junit)
    elif args.command == "batch":
        batch_extract(args.base, args.output_dir, args.max)
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
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
