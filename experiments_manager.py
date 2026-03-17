import os

from get_database_files import GetDatabaseFiles
from get_code import GetCode
from prompt_manager import PromptManager
from model_manager import ModelManager


class ExperimentsManager:
    def __init__(self):
        self.model_name = None
        self.project_path = None
        self.project_output_path = None
        self.prompt = None

    def create_test_generation_experiment(self):
        """
        Generate tests for the given project using the specified model and prompt.

        Iterates over all methods in the project at self.project_path, builds a
        zero-shot prompt for each method, runs the model (self.model_name), prunes
        the output, and saves the generated test to self.project_output_path.
        """
        db_files = GetDatabaseFiles()
        get_code = GetCode(database_root=self.project_path)
        prompt_manager = PromptManager()
        model_manager = ModelManager()

        methods = db_files.extract_from_project(self.project_path)

        class_tests = {}

        for method_path in methods:
            code = get_code.get_code(method_path)

            if code.startswith("Erro"):
                print(f"Skipping {method_path}: {code}")
                continue

            prompt = prompt_manager.get_zero_shot_prompt(code)
            generated_text = model_manager.run_model(self.model_name, prompt)
            proned_code = model_manager.prone_code_generated(generated_text)

            parts = method_path.split(".")
            project_name = parts[0]
            class_name = parts[-2]
            method_name = parts[-1]

            key = (project_name, class_name)
            if key not in class_tests:
                class_tests[key] = []
            class_tests[key].append(f"// {method_name}\n{proned_code}")

        for (project_name, class_name), tests in class_tests.items():
            output_file = os.path.join(
                self.project_output_path,
                project_name,
                f"{class_name}Test.java"
            )
            model_manager.save_code_to_file("\n\n".join(tests), output_file)

    def execute_test_smell_detection(self, project_path: str) -> str:
        """
        Execute test smell detection on the given project path.
        """
        # Placeholder for actual implementation
        return f"Executed test smell detection on {project_path}"


    def execute_legibility_analysis(self, project_path: str) -> str:
        """
        Execute legibility analysis on the given project path.
        """
        # Placeholder for actual implementation
        return f"Executed legibility analysis on {project_path}"
    

if __name__ == "__main__":
    exp = ExperimentsManager()
    exp.model_name = "Qwen_Qwen2.5-Coder-0.5B-Instruct"
    exp.project_path = "/home/mateus-silva/Documents/MasterDegree/files/localLLM/SF110"
    exp.project_output_path = "output"
    exp.create_test_generation_experiment()