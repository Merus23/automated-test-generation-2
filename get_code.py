import os
import re

class GetCode:

    def __init__(self, database_root=None):
        self.database_root = database_root

    def remove_comments(self, code):
        pattern = r'//[^\n]*|/\*.*?\*/|\'(?:\\.|[^\\\'])*\'|"(?:\\.|[^\\"])*"'
        
        def replacer(match):
            s = match.group(0)
            if s.startswith('/'):
                return " "
            else:
                return s
                
        return re.sub(pattern, replacer, code, flags=re.DOTALL)

    def get_code(self, method_path: str) -> str:
        """
        Receves a string like 'ProjectName.relativePath.package.ClassName.methodName' and returns
        the source code of the method.
        
        """
        try:
            parts = method_path.split('.')
            if len(parts) < 3:
                return f"Erro: Caminho inválido '{method_path}'"
            
            project_name = parts[0]
            method_name = parts[-1]
            class_name = parts[-2]
            
            middle_parts = parts[1:-2]
            
            
            if self.database_root:
                db_root_name = os.path.basename(os.path.normpath(self.database_root))
                if project_name == db_root_name:
                  
                    base_path = self.database_root
                else:
                    base_path = os.path.join(self.database_root, project_name)
            else:
                
                current_dir = os.path.dirname(os.path.abspath(__file__))
                workspace_root = os.path.dirname(current_dir)
                base_path = os.path.join(workspace_root, "SF110", project_name)
            
            target_file = None
            
            for i in range(len(middle_parts), -1, -1):
                 rel_path_segments = middle_parts[:i]
                 potential_path = os.path.join(base_path, *rel_path_segments, f"{class_name}.java")
                 if os.path.exists(potential_path):
                     target_file = potential_path
                     break
            
            if not target_file:
                if os.path.exists(base_path):
                    for root, dirs, files in os.walk(base_path):
                        if f"{class_name}.java" in files:
                            target_file = os.path.join(root, f"{class_name}.java")
                            break
            
            if not target_file:
                return f"Erro: Arquivo {class_name}.java não encontrado em {base_path}"

            with open(target_file, "r", encoding="utf-8", errors="ignore") as f:
                code = f.read()

            clean_code = self.remove_comments(code)
            
            return self.extract_method(clean_code, method_name, class_name)

        except Exception as e:
            return f"Erro ao obter código: {str(e)}"

    def extract_method(self, code, method_name, class_name):
        if method_name == class_name:
             # Construtor
             pattern = r"(?:public|protected|private|\s)*\s+" + re.escape(method_name) + r"\s*\("
        else:
             # Método normal (espera tipo de retorno)
             pattern = r"(?:public|protected|private|static|final|synchronized|abstract|native|strictfp|\s)*\s+[\w<>[\]]+\s+" + re.escape(method_name) + r"\s*\("
        
        match = re.search(pattern, code)
        if not match:
            return f"Erro: Método '{method_name}' não encontrado no arquivo."
            
        start_index = match.start()
        
        # Find the start of the method body '{'
        open_brace_index = code.find('{', start_index)
        if open_brace_index == -1:
            # Can be abstract method or interface
            end_index = code.find(';', start_index)
            if end_index != -1:
                return code[start_index:end_index+1]
            return "Erro: Corpo do método não encontrado."
            
        # Count opening and closing braces
        brace_count = 0
        i = open_brace_index
        
        while i < len(code):
            if code[i] == '{':
                brace_count += 1
            elif code[i] == '}':
                brace_count -= 1
                if brace_count == 0:
                    return code[start_index:i+1]
            i += 1
            
        return "Erro: Chaves desbalanceadas."



# if __name__ == "__main__":
#     getCode = GetCode()    
#     print(getCode.get_class_code("1_tullibee.src.main.java.com.ib.client.com.ib.client.Execution.equals")) 
#     pass


