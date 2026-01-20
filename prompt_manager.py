


class PromptManager:
    
    def __init__(self):
        pass

    def get_zero_shot_prompt(self, code) -> str:
        return f"Write a test case for the following code:\n{code} \n\n Write only the test case code, without explanations."
    
    def another_prompt_method(self, code) -> str:
        return f"{code}"
    
    def load_prompt_from_file(self, file_path) -> str:
        with open(file_path, 'r') as file:
            prompt = file.read()
        return prompt