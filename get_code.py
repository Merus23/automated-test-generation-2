import os
import re

class GetCode:

    def __init__(self):
        pass

    def remove_comments(self, code):
        pattern = r'//[^\n]*|/\*.*?\*/|\'(?:\\.|[^\\\'])*\'|"(?:\\.|[^\\"])*"'
        
        def replacer(match):
            s = match.group(0)
            if s.startswith('/'):
                return " "
            else:
                return s
                
        return re.sub(pattern, replacer, code, flags=re.DOTALL)

    def get_class_code(self, method_path: str) -> str:
        """
        Recebe uma string como 'ProjectName.relativePath.package.ClassName.methodName' e retorna
        o código-fonte do método.
        """
        try:
            parts = method_path.split('.')
            if len(parts) < 3:
                return f"Erro: Caminho inválido '{method_path}'"
            
            project_name = parts[0]
            method_name = parts[-1]
            class_name = parts[-2]
            
            # O caminho pode conter relativePath e package misturados/duplicados.
            # Ex: 1_tullibee.src.main.java.com.ib.client.com.ib.client.Execution.equals
            # parts[1:-2] = ['src', 'main', 'java', 'com', 'ib', 'client', 'com', 'ib', 'client']
            # O arquivo real está em SF110/1_tullibee/src/main/java/com/ib/client/Execution.java
            
            middle_parts = parts[1:-2]
            
            # Ajuste para encontrar a raiz do projeto independentemente de onde o script é executado
            # O script está em features/get_code.py, então subimos um nível para achar SF110
            current_dir = os.path.dirname(os.path.abspath(__file__))
            workspace_root = os.path.dirname(current_dir)
            base_path = os.path.join(workspace_root, "SF110", project_name)
            
            target_file = None
            
            # Tenta encontrar o arquivo combinando partes do meio como diretórios
            # Começa do maior caminho possível para o menor, priorizando o início da string que é o relativePath
            for i in range(len(middle_parts), -1, -1):
                 rel_path_segments = middle_parts[:i]
                 potential_path = os.path.join(base_path, *rel_path_segments, f"{class_name}.java")
                 if os.path.exists(potential_path):
                     target_file = potential_path
                     break
            
            if not target_file:
                # Fallback: tenta procurar em todo o diretório do projeto se a dedução falhar
                if os.path.exists(base_path):
                    for root, dirs, files in os.walk(base_path):
                        if f"{class_name}.java" in files:
                            target_file = os.path.join(root, f"{class_name}.java")
                            break
            
            if not target_file:
                return f"Erro: Arquivo {class_name}.java não encontrado em {base_path}"

            with open(target_file, "r", encoding="utf-8", errors="ignore") as f:
                code = f.read()

            # Remove comentários para facilitar o parsing
            clean_code = self.remove_comments(code)
            
            return self.extract_method(clean_code, method_name, class_name)

        except Exception as e:
            return f"Erro ao obter código: {str(e)}"

    def extract_method(self, code, method_name, class_name):
        # Regex para encontrar a assinatura do método
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
        
        # Encontrar o início do corpo do método '{'
        open_brace_index = code.find('{', start_index)
        if open_brace_index == -1:
            # Pode ser método abstrato ou interface
            end_index = code.find(';', start_index)
            if end_index != -1:
                return code[start_index:end_index+1]
            return "Erro: Corpo do método não encontrado."
            
        # Contar chaves para achar o fim
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



if __name__ == "__main__":
    getCode = GetCode()    
    print(getCode.get_class_code("1_tullibee.src.main.java.com.ib.client.com.ib.client.Execution.equals")) 
    pass


