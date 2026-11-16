import ast
import re
import unicodedata
from typing import Tuple, List

FORBIDDEN_PYTHON_MODULES = {
    "os", "sys", "subprocess", "shutil", "socket", "pty", "commands",
    "posix", "nt", "builtins", "signal", "multiprocessing", "threading",
    "ctypes", "inspect", "importlib", "pickle", "marshal", "shelve",
}

FORBIDDEN_PYTHON_ATTRS = {
    "__subclasses__", "__globals__", "__builtins__", "__import__",
    "__code__", "__bases__", "__class__",
}

FORBIDDEN_JS_KEYWORDS = [
    "require", "eval", "Function", "fetch", "XMLHttpRequest", "WebSocket",
    "process", "child_process", "fs", "constructor", "prototype", "__proto__",
]


def is_python_script(code: str) -> bool:
    """
    Determines whether the provided decoder script is Python or JavaScript.
    """
    clean = code.strip()
    if re.search(r"^\s*def\s+(?:decode|transform|decode_payload|parse)\s*\(", clean, re.MULTILINE):
        return True
    if any(clean.startswith(kw) for kw in ("import ", "from ", "def ", "#")):
        return True
    if "function " not in clean and "const " not in clean and "let " not in clean and "var " not in clean:
        try:
            ast.parse(clean)
            return True
        except Exception:
            pass
    return False


def validate_python_script(code: str) -> Tuple[bool, List[str]]:
    errors = []
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, [f"Python Syntax Error (Line {e.lineno}): {e.msg}"]

    # Ensure decode or transform is defined
    has_fn = False
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name in ("decode", "transform", "decode_payload", "parse"):
                has_fn = True

        # Check for forbidden imports
        if isinstance(node, ast.Import):
            for alias in node.names:
                mod = alias.name.split(".")[0]
                if mod in FORBIDDEN_PYTHON_MODULES:
                    errors.append(f"Import of module '{mod}' is not allowed for security")

        if isinstance(node, ast.ImportFrom):
            mod = (node.module or "").split(".")[0]
            if mod in FORBIDDEN_PYTHON_MODULES:
                errors.append(f"Import from module '{mod}' is not allowed for security")

        # Check for forbidden attribute access
        if isinstance(node, ast.Attribute):
            if node.attr in FORBIDDEN_PYTHON_ATTRS:
                errors.append(f"Access to '{node.attr}' is restricted")

        # Check for forbidden function calls
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                if node.func.id in ("eval", "exec", "open", "__import__", "compile"):
                    errors.append(f"Call to '{node.func.id}' is restricted")

    if not has_fn:
        errors.append("Python script must define function 'decode(payload, context=None)' or 'transform(input)'")

    return len(errors) == 0, errors


def validate_js_script(code: str) -> Tuple[bool, List[str]]:
    normalized = unicodedata.normalize("NFKC", code)
    errors = []

    # Must contain transform(input) or decode(input)
    has_fn = re.search(r"function\s+(?:transform|decode)\s*\(", normalized)
    if not has_fn:
        errors.append("JavaScript script must define function decode(input) or transform(input)")

    for kw in FORBIDDEN_JS_KEYWORDS:
        pattern = re.compile(rf"\b{kw}\b")
        if pattern.search(normalized):
            errors.append(f"{kw} is not allowed")

    return len(errors) == 0, errors


def validate_script(code: str) -> Tuple[bool, List[str]]:
    if not code or not code.strip():
        return False, ["Script cannot be empty"]

    if is_python_script(code):
        return validate_python_script(code)
    else:
        return validate_js_script(code)
