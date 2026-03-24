"""
Model Manager — Manages local LLMs for Java test generation.

Usage:
    from model_manager import ModelManager
    manager = ModelManager()
    code = manager.run_from_file("Qwen_Qwen3-0.5B", "output/prompt.txt")
"""

import gc
import json
import os
import re
from pathlib import Path

from transformers import AutoModelForCausalLM, AutoTokenizer
from huggingface_hub import snapshot_download
from dotenv import load_dotenv
from prompt_manager import PromptManager

load_dotenv()

HF_TOKEN = os.getenv("HF_TOKEN")
BASE_DIR = Path(__file__).resolve().parent


class ModelManager:
    """Gerencia modelos locais para geração de testes a partir de prompts do extractor."""

    def __init__(self):
        self.models_dir = BASE_DIR / "models"
        self._loaded_model_name = None
        self._model = None
        self._tokenizer = None

    def download_model(self, hf_model_id: str) -> Path:
        """Baixa um modelo do Hugging Face e salva em models/."""
        if not HF_TOKEN:
            raise ValueError("HF_TOKEN não definido nas variáveis de ambiente.")

        self.models_dir.mkdir(exist_ok=True)
        target_dir = self.models_dir / hf_model_id.replace("/", "_")

        if target_dir.exists():
            print(f"Modelo já existe em {target_dir}")
            return target_dir

        print(f"Baixando modelo {hf_model_id}...")
        snapshot_download(repo_id=hf_model_id, local_dir=target_dir, token=HF_TOKEN)
        return target_dir

    def run_model(self, model_name: str, prompt: str) -> str:
        """Carrega o modelo e gera texto a partir do prompt.

        Args:
            model_name: Nome do diretório do modelo dentro de models/.
            prompt: Texto de entrada para o modelo.

        Returns:
            Texto gerado pelo modelo.
        """
        import torch

        model_path = self.models_dir / model_name

        if not model_path.exists():
            raise ValueError(f"Modelo não encontrado em {model_path}")

        if self._loaded_model_name != model_name:
            self._model = None
            self._tokenizer = None
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

            print(f"Carregando modelo de {model_path}...")
            self._tokenizer = AutoTokenizer.from_pretrained(str(model_path))
            self._model = AutoModelForCausalLM.from_pretrained(
                str(model_path),
                dtype="auto",
                device_map="auto",
            )
            self._loaded_model_name = model_name

        print("Executando modelo...")
        system_prompt = PromptManager().get_system_prompt()
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]
        text = self._tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=False,
        )
        model_inputs = self._tokenizer([text], return_tensors="pt").to(self._model.device)

        generated_ids = self._model.generate(
            **model_inputs,
            max_new_tokens=2048,
        )
        output_ids = generated_ids[0][len(model_inputs.input_ids[0]):]

        content = self._tokenizer.decode(output_ids, skip_special_tokens=True).strip("\n")
        return content

    def extract_java_code(self, raw_output: str) -> str:
        """Extrai apenas o código Java da saída do modelo."""
        fenced = re.search(r"```(?:java)?\s*\n(.*?)```", raw_output, re.DOTALL)
        if fenced:
            return fenced.group(1).strip()

        java_start = re.search(
            r"^(import\s+[\w.]+;|public\s|class\s|interface\s|enum\s|@[\w]+)",
            raw_output,
            re.MULTILINE,
        )
        if java_start:
            return raw_output[java_start.start():].strip()

        return raw_output.strip()

    def run_from_file(self, model_name: str, prompt_file: str, output_file: str = None) -> str:
        """Lê um prompt de um arquivo .txt e executa no modelo.

        Args:
            model_name: Nome do diretório do modelo.
            prompt_file: Caminho do arquivo .txt com o prompt (ex: output/0007_DocumentSet_wordFrequency.txt).
            output_file: Caminho opcional para salvar o código gerado.

        Returns:
            Código Java gerado.
        """
        prompt_path = Path(prompt_file)
        if not prompt_path.exists():
            raise FileNotFoundError(f"Arquivo de prompt não encontrado: {prompt_file}")

        prompt = prompt_path.read_text(encoding="utf-8")
        raw_output = self.run_model(model_name, prompt)
        code = self.extract_java_code(raw_output)

        if output_file:
            out_path = Path(output_file)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(code, encoding="utf-8")
            print(f"Código salvo em {out_path}")

        return code

    def run_batch(self, model_name: str, input_dir: str, output_dir: str, max_files: int = 100):
        """Executa o modelo para todos os prompts .txt de um diretório.

        Args:
            model_name: Nome do diretório do modelo.
            input_dir: Diretório com os arquivos .txt de prompt.
            output_dir: Diretório de saída para os testes gerados.
            max_files: Número máximo de arquivos a processar.
        """
        in_path = Path(input_dir)
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)

        prompt_files = sorted(in_path.glob("*.txt"))[:max_files]
        results = []

        for i, pf in enumerate(prompt_files):
            print(f"\n[{i + 1}/{len(prompt_files)}] Processando {pf.name}...")
            try:
                out_file = out_path / pf.name.replace(".txt", ".java")
                code = self.run_from_file(model_name, str(pf), str(out_file))
                results.append({"file": pf.name, "output": str(out_file), "status": "ok", "length": len(code)})
            except Exception as e:
                print(f"  ERRO: {e}")
                results.append({"file": pf.name, "status": "error", "error": str(e)})

        meta_path = out_path / "batch_results.json"
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)

        ok = sum(1 for r in results if r["status"] == "ok")
        print(f"\n[Batch] {ok}/{len(prompt_files)} testes gerados em '{output_dir}'")
        print(f"[Batch] Metadados: {meta_path}")
