from huggingface_hub import HfApi, snapshot_download
import os 
from pathlib import Path
from transformers import AutoModelForCausalLM, AutoTokenizer, pipeline
from dotenv import load_dotenv
load_dotenv()

HF_TOKEN = os.getenv("HF_TOKEN")

class ModelManager:
    """
    Manages the models.
    """
    
    def __init__(self):
         self.BASE_DIR = Path(__file__).resolve().parent

    def list_hf_models(self):
        if not HF_TOKEN:
            raise ValueError("Hugging Face token (HF_TOKEN) is not set in environment variables.")
        
        api = HfApi(token=HF_TOKEN)
        models = api.list_models()
        return [model.modelId for model in models]

    def download_model(self, hf_model_id):
        if not HF_TOKEN:
            raise ValueError("Hugging Face token (HF_TOKEN) is not set in environment variables.")
        
        MODELS_DIR = self.BASE_DIR / "models"
        MODELS_DIR.mkdir(exist_ok=True)

        target_dir = MODELS_DIR / hf_model_id.replace("/", "_")
        
        if target_dir.exists():
            print(f"Model {hf_model_id} already downloaded at {target_dir}")
            return target_dir
        
        print(f"Downloading model {hf_model_id}...")
        snapshot_download(repo_id=hf_model_id, local_dir=target_dir, token=HF_TOKEN)

        return target_dir

    def delete_model(self, model_name):
        MODEL_PATH = os.path.join(self.BASE_DIR, "models", model_name)
        
        if not os.path.exists(MODEL_PATH):
            print(f"Model {model_name} does not exist at {MODEL_PATH}")
            return
        
        os.rmdir(MODEL_PATH)
        print(f"Model {model_name} deleted from {MODEL_PATH}")

    def run_model(self, model_name, prompt) -> str:
        
        MODEL_PATH = os.path.join(self.BASE_DIR, "models", model_name)
        
        if not os.path.exists(MODEL_PATH):
            raise ValueError(f"Model {model_name} does not exist at {MODEL_PATH}")
        
        print(f"Loading model from {MODEL_PATH}...")
        
        tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH)
        model = AutoModelForCausalLM.from_pretrained(MODEL_PATH)

    
        generator = pipeline("text-generation", model=model, tokenizer=tokenizer)

        # print(f"Running model {model_name} with prompt: {prompt}")
        print("Running model...")
        
        # Executa a geração
        # max_new_tokens: limita o tamanho do código gerado
        # temperature: 0.2 para ser mais preciso/determinístico (bom para código)
        output = generator(
            prompt, 
            max_new_tokens=512, 
            do_sample=True, 
            temperature=0.2,
            truncation=True
        )
        
        generated_text = output[0]['generated_text']
        return generated_text


    def prone_code_generated(code) -> str:
        """Most identify the python code and remove any extra text."""
        
        # TODO implement this function
        return code


if __name__ == "__main__":
    manager = ModelManager()
    #models = manager.list_hf_models()
    #manager.download_model("Qwen/Qwen2.5-Coder-0.5B-Instruct")
    
    prompt = "Write a fibonacci function in Python. Returne only the code, without explanations."
    response = manager.run_model("Qwen_Qwen2.5-Coder-0.5B-Instruct", prompt)
    print(response)