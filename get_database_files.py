import os
import re


class GetDatabaseFiles:
    
    def __init__(self):
        pass

    def remove_comments(self, code):
        """
        Remove comments from Java code.
        """
        pattern = r'//[^\n]*|/\*.*?\*/|\'(?:\\.|[^\\\'])*\'|"(?:\\.|[^\\"])*"'
        
        def replacer(match):
            s = match.group(0)
            if s.startswith('/'):
                return " "
            else:
                return s
                
        return re.sub(pattern, replacer, code, flags=re.DOTALL)


    def extract_classes_and_methods_from_file(self, file_path, root_path=None, with_constructors=False):
        """
        Get a specific file path and extract the class and its methods in the format:
        ProjectName.relativePath.package.ClassName.methodName

        Args:
            file_path (str): Path to the Java file.
            root_path (str): Root path of the project to calculate relative path and project name.
            with_constructors (bool): If True, includes constructors in the output.

        Returns:
            list: List of strings in the format ProjectName.relativePath.package.ClassName.methodName

        """

        if not os.path.exists(file_path):
            raise FileNotFoundError("Invalid path!")

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                code = f.read()
        except UnicodeDecodeError:
            # Fallback to latin-1 (common in older Java files) if utf-8 fails
            with open(file_path, "r", encoding="latin-1") as f:
                code = f.read()

        code = self.remove_comments(code)

        results = []

        # Get package (package com.example.service;)
        package_pattern = r"package\s+([a-zA-Z0-9_.]+)\s*;"
        package_match = re.search(package_pattern, code)
        package_name = package_match.group(1) if package_match else None

        # Get all classes
        class_pattern = r"\bclass\s+([A-Za-z_][A-Za-z0-9_]*)"
        classes = re.findall(class_pattern, code)

        # Get all methods. Example: public void doStuff(int x)
        method_pattern = r"(public|protected|private)?\s+(static\s+)?[A-Za-z0-9_<>\[\]]+\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\("
        methods = re.findall(method_pattern, code)
        
        # Base name of the file (e.g., UserService.java -> UserService)
        base_class_name = os.path.splitext(os.path.basename(file_path))[0]

        # Prioritize class from the file name if not found in the code
        if not classes:
            classes = [base_class_name]

        prefix = ""
        if root_path:
            project_name = os.path.basename(os.path.normpath(root_path))
            rel_path = os.path.relpath(file_path, root_path)
            rel_dir = os.path.dirname(rel_path)
            
            prefix = project_name
            if rel_dir and rel_dir != ".":
                prefix += "." + rel_dir.replace(os.sep, ".")

        for cls in classes:
            if with_constructors:
                # Regex for constructor: optional modifier, spaces, NOT preceded by 'new ', class name, open parenthesis
                ctor_pattern = r"(public|protected|private)?\s+(?<!\bnew\s)\b" + re.escape(cls) + r"\s*\("
                ctors = re.findall(ctor_pattern, code)
                for ctor_match in ctors:
                    parts = []
                    if prefix:
                        parts.append(prefix)
                    if package_name:
                        parts.append(package_name)
                    parts.append(cls)
                    parts.append(cls)  # Method name is the class name
                    
                    results.append(".".join(parts))

            for method in methods:
                method_name = method[2]

                if method_name == cls:
                    continue
                
                parts = []
                if prefix:
                    parts.append(prefix)
                if package_name:
                    parts.append(package_name)
                parts.append(cls)
                parts.append(method_name)
                
                results.append(".".join(parts))

        
        return results


    def extract_from_project(self, project_path):
        """
        Traverse the entire project and return a list of all classes and methods in the format:
        Args:
            project_path (str): Path to the root of the Java project.
        Returns:
            list: List of strings in the format -> ProjectName.relativePath.package.Class.method
        """

        final_list = []

        for root, _, files in os.walk(project_path):
            for file in files:
                if "Test" not in file and file.endswith(".java"):
                    full_path = os.path.join(root, file)
                    final_list.extend(
                        self.extract_classes_and_methods_from_file(full_path, root_path=project_path, with_constructors=False)
                    )

        return final_list


# -------------------------
# Example usage:
# -------------------------
if __name__ == "__main__":
    path = "/media/mateus/Backup IC/code/Mateus_dissertacao_implementacao/SF110/1_tullibee" 
    try:
        extractor = GetDatabaseFiles()
        results = extractor.extract_from_project(path)
        for r in results:
            print(r)
    except FileNotFoundError:
        print("Invalid path!")
        exit(1)