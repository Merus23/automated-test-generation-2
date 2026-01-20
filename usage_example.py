from model_manager import ModelManager
from prompt_manager import PromptManager
from get_code import GetCode
from get_database_files import GetDatabaseFiles


if __name__ == "__main__":
    # Usage example

    DB_PATH = "/home/mateus-silva/Documents/MasterDegree/files/Mateus_dissertacao_implementacao/SF110"
    MODEL_NAME = "Qwen_Qwen2.5-Coder-0.5B-Instruct"

    manager = ModelManager()
    prompt_manager = PromptManager()
    code_getter = GetCode(database_root=DB_PATH)
    db_files_getter = GetDatabaseFiles()
    
    files_path = db_files_getter.extract_from_project(DB_PATH)        
    print(f"First extracted file: {files_path[0]} \n\n")

    example_file_code = code_getter.get_code(files_path[0])
    print(f"Example file code:\n{example_file_code}\n\n")




    # If you have a local model downloaded, download it first
    # manager.download_model("Qwen/Qwen2.5-Coder-0.5B-Instruct")
    
    # response = manager.run_model(MODEL_NAME, prompt_manager.get_zero_shot_prompt(example_file_code))
    # print(f"response: {response}")
    
