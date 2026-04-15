package extractor;

import com.github.javaparser.StaticJavaParser;
import com.github.javaparser.ast.CompilationUnit;
import com.github.javaparser.ast.ImportDeclaration;
import com.github.javaparser.ast.body.ClassOrInterfaceDeclaration;
import com.github.javaparser.ast.body.ConstructorDeclaration;
import com.github.javaparser.ast.body.FieldDeclaration;
import com.github.javaparser.ast.body.MethodDeclaration;
import com.github.javaparser.ast.body.VariableDeclarator;
import com.github.javaparser.ast.expr.MethodCallExpr;
import com.github.javaparser.ast.type.ClassOrInterfaceType;
import com.github.javaparser.ast.visitor.VoidVisitorAdapter;
import com.google.gson.Gson;
import com.google.gson.GsonBuilder;

import java.io.File;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;

/**
 * Standalone Java file parser that extracts structural information using JavaParser AST.
 * Outputs a JSON object to stdout.
 *
 * Usage: java -jar javaparser-extractor.jar <path-to-java-file>
 */
public class JavaParserExtractor {

    public static void main(String[] args) {
        if (args.length < 1) {
            System.err.println("Usage: java -jar javaparser-extractor.jar <path-to-java-file>");
            System.exit(1);
        }

        String filepath = args[0];
        try {
            Map<String, Object> result = extractInfo(new File(filepath));
            Gson gson = new GsonBuilder().setPrettyPrinting().create();
            System.out.println(gson.toJson(result));
        } catch (Exception e) {
            System.err.println("Error parsing file: " + filepath);
            System.err.println(e.getMessage());
            System.exit(1);
        }
    }

    private static Map<String, Object> extractInfo(File file) throws Exception {
        CompilationUnit cu = StaticJavaParser.parse(file);

        Map<String, Object> result = new LinkedHashMap<>();

        // Package
        String packageName = cu.getPackageDeclaration()
                .map(pd -> pd.getNameAsString())
                .orElse("");
        result.put("package", packageName);

        // Imports
        List<String> imports = cu.getImports().stream()
                .map(ImportDeclaration::getNameAsString)
                .collect(Collectors.toList());
        result.put("imports", imports);

        // Find the first public class, or the first class if none is public
        ClassOrInterfaceDeclaration classDecl = cu.findAll(ClassOrInterfaceDeclaration.class).stream()
                .filter(c -> !c.isInterface())
                .filter(c -> c.isPublic())
                .findFirst()
                .orElseGet(() -> cu.findAll(ClassOrInterfaceDeclaration.class).stream()
                        .filter(c -> !c.isInterface())
                        .findFirst()
                        .orElse(null));

        if (classDecl == null) {
            result.put("className", "");
            result.put("fields", new ArrayList<>());
            result.put("constructors", new ArrayList<>());
            result.put("methods", new ArrayList<>());
            return result;
        }

        result.put("className", classDecl.getNameAsString());

        // Class modifiers (e.g. "public abstract", "public final")
        String classModifiers = classDecl.getModifiers().stream()
                .map(m -> m.getKeyword().asString())
                .collect(Collectors.joining(" "));
        result.put("classModifiers", classModifiers);

        // Whether the class is declared abstract
        result.put("isAbstract", classDecl.isAbstract());

        // Superclass (extends)
        List<String> extendedTypes = classDecl.getExtendedTypes().stream()
                .map(t -> t.getNameAsString())
                .collect(Collectors.toList());
        result.put("extendedTypes", extendedTypes);

        // Implemented interfaces
        List<String> implementedTypes = classDecl.getImplementedTypes().stream()
                .map(t -> t.getNameAsString())
                .collect(Collectors.toList());
        result.put("implementedTypes", implementedTypes);

        // Fields
        List<Map<String, String>> fields = new ArrayList<>();
        for (FieldDeclaration field : classDecl.getFields()) {
            String modifier = field.getModifiers().stream()
                    .map(m -> m.getKeyword().asString())
                    .collect(Collectors.joining(" "));
            String typeName = field.getCommonType().asString();

            for (VariableDeclarator var : field.getVariables()) {
                Map<String, String> fieldMap = new LinkedHashMap<>();
                fieldMap.put("modifier", modifier);
                fieldMap.put("typeName", typeName);
                fieldMap.put("name", var.getNameAsString());
                fieldMap.put("raw", field.toString().trim());
                fields.add(fieldMap);
            }
        }
        result.put("fields", fields);

        // Constructors
        List<Map<String, String>> constructors = new ArrayList<>();
        for (ConstructorDeclaration ctor : classDecl.getConstructors()) {
            Map<String, String> ctorMap = new LinkedHashMap<>();
            ctorMap.put("name", ctor.getNameAsString());
            ctorMap.put("modifiers", ctor.getModifiers().stream()
                    .map(m -> m.getKeyword().asString())
                    .collect(Collectors.joining(" ")));
            ctorMap.put("parameters", ctor.getParameters().stream()
                    .map(p -> p.getTypeAsString() + " " + p.getNameAsString())
                    .collect(Collectors.joining(", ")));
            ctorMap.put("body", stripOuterBraces(ctor.getBody().toString()));
            constructors.add(ctorMap);
        }
        result.put("constructors", constructors);

        // Methods
        List<Map<String, Object>> methods = new ArrayList<>();
        for (MethodDeclaration method : classDecl.getMethods()) {
            Map<String, Object> methodMap = new LinkedHashMap<>();
            methodMap.put("name", method.getNameAsString());
            methodMap.put("returnType", method.getTypeAsString());
            methodMap.put("modifiers", method.getModifiers().stream()
                    .map(m -> m.getKeyword().asString())
                    .collect(Collectors.joining(" ")));
            methodMap.put("parameters", method.getParameters().stream()
                    .map(p -> p.getTypeAsString() + " " + p.getNameAsString())
                    .collect(Collectors.joining(", ")));

            String body = method.getBody()
                    .map(b -> stripOuterBraces(b.toString()))
                    .orElse("");
            methodMap.put("body", body);

            // Extract method calls via visitor
            Set<String> methodCalls = new LinkedHashSet<>();
            method.accept(new VoidVisitorAdapter<Void>() {
                @Override
                public void visit(MethodCallExpr n, Void arg) {
                    methodCalls.add(n.getNameAsString());
                    super.visit(n, arg);
                }
            }, null);
            methodMap.put("methodCalls", new ArrayList<>(methodCalls));

            // Extract types used via visitor
            Set<String> typesUsed = new LinkedHashSet<>();
            method.accept(new VoidVisitorAdapter<Void>() {
                @Override
                public void visit(ClassOrInterfaceType n, Void arg) {
                    typesUsed.add(n.getNameAsString());
                    super.visit(n, arg);
                }
            }, null);
            methodMap.put("typesUsed", new ArrayList<>(typesUsed));

            methods.add(methodMap);
        }
        result.put("methods", methods);

        return result;
    }

    /**
     * Removes the outer braces from a block statement string.
     * E.g., "{\n    x = 1;\n}" becomes "x = 1;"
     */
    private static String stripOuterBraces(String block) {
        if (block == null) return "";
        String trimmed = block.trim();
        if (trimmed.startsWith("{") && trimmed.endsWith("}")) {
            trimmed = trimmed.substring(1, trimmed.length() - 1);
        }
        // Remove common leading indentation
        String[] lines = trimmed.split("\n");
        if (lines.length == 0) return "";

        // Find minimum indentation (ignoring empty lines)
        int minIndent = Integer.MAX_VALUE;
        for (String line : lines) {
            if (line.trim().isEmpty()) continue;
            int indent = 0;
            for (char c : line.toCharArray()) {
                if (c == ' ') indent++;
                else if (c == '\t') indent += 4;
                else break;
            }
            minIndent = Math.min(minIndent, indent);
        }

        if (minIndent == Integer.MAX_VALUE) minIndent = 0;

        StringBuilder sb = new StringBuilder();
        for (String line : lines) {
            if (line.trim().isEmpty()) {
                sb.append("\n");
                continue;
            }
            // Remove minIndent spaces from the beginning
            int removed = 0;
            int idx = 0;
            while (idx < line.length() && removed < minIndent) {
                char c = line.charAt(idx);
                if (c == ' ') { removed++; idx++; }
                else if (c == '\t') { removed += 4; idx++; }
                else break;
            }
            sb.append(line.substring(idx)).append("\n");
        }

        return sb.toString().trim();
    }
}
