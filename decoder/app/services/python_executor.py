"""
Pure Python Sandboxed Decoder Execution Engine for NibiaaNet.

Executes Python payload decoders natively without external processes,
Node.js dependencies, or pipe overhead.
"""

import base64
import binascii
import datetime
import json
import logging
import math
import re
import struct
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("nibiaanet.decoder.python_executor")

ALLOWED_MODULES = {
    "struct": struct,
    "math": math,
    "binascii": binascii,
    "json": json,
    "datetime": datetime,
    "time": time,
    "re": re,
    "base64": base64,
}


def safe_import(name, globals=None, locals=None, fromlist=(), level=0):
    if name in ALLOWED_MODULES:
        return ALLOWED_MODULES[name]
    raise ImportError(f"Import of module '{name}' is restricted in sandbox")


# Safe built-in functions permitted in the sandbox
SAFE_BUILTINS = {
    "__import__": safe_import,
    "abs": abs,
    "all": all,
    "any": any,
    "bin": bin,
    "bool": bool,
    "bytearray": bytearray,
    "bytes": bytes,
    "chr": chr,
    "dict": dict,
    "divmod": divmod,
    "enumerate": enumerate,
    "filter": filter,
    "float": float,
    "format": format,
    "frozenset": frozenset,
    "hex": hex,
    "int": int,
    "isinstance": isinstance,
    "issubclass": issubclass,
    "iter": iter,
    "len": len,
    "list": list,
    "map": map,
    "max": max,
    "min": min,
    "next": next,
    "oct": oct,
    "ord": ord,
    "pow": pow,
    "range": range,
    "reversed": reversed,
    "round": round,
    "set": set,
    "slice": slice,
    "sorted": sorted,
    "str": str,
    "sum": sum,
    "tuple": tuple,
    "zip": zip,
    "True": True,
    "False": False,
    "None": None,
}


class PythonDecoderEngine:
    """
    Executes Python decoding routines in an isolated, safe namespace.
    Supports functions defined as:
      - def decode(payload: bytes, context: dict = None) -> dict
      - def decode(input: dict) -> dict
      - def transform(input: dict) -> dict
      - def transform(payload: bytes, context: dict = None) -> dict
    """

    def validate_syntax(self, code: str) -> Tuple[bool, Optional[str]]:
        """
        Validates Python code syntax.
        """
        if not code or not code.strip():
            return False, "Code cannot be empty"

        try:
            compile(code, "<decoder>", "exec")
            return True, None
        except SyntaxError as e:
            return False, f"SyntaxError at line {e.lineno}: {e.msg}"

    def execute(
        self,
        code: str,
        raw_bytes: bytes,
        hex_str: str,
        context: Optional[Dict[str, Any]] = None,
        timeout_seconds: float = 2.0,
    ) -> Tuple[bool, Any, List[str], Optional[str]]:
        """
        Executes the Python decoder code.
        Returns: (success, result_dict, logs, error_message)
        """
        ctx = context or {}
        logs: List[str] = []

        def custom_print(*args, **kwargs):
            sep = kwargs.get("sep", " ")
            msg = sep.join(str(a) for a in args)
            logs.append(msg)

        # Build isolated globals
        safe_globals = {
            "__builtins__": {
                **SAFE_BUILTINS,
                "print": custom_print,
            },
            **ALLOWED_MODULES,
            "log": custom_print,
        }

        # Local execution scope
        local_scope: Dict[str, Any] = {}

        try:
            # Compile and execute definitions
            compiled_code = compile(code, "<decoder_script>", "exec")
            exec(compiled_code, safe_globals, local_scope)

            # Locate decode or transform function
            fn = None
            fn_name = None
            for name in ("decode", "transform", "decode_payload", "parse"):
                if name in local_scope and callable(local_scope[name]):
                    fn = local_scope[name]
                    fn_name = name
                    break

            if fn is None:
                return (
                    False,
                    None,
                    logs,
                    "Code must define function 'decode(payload, context=None)' or 'transform(input)'",
                )

            # Build standard input structures
            fmt_type = ctx.get("format") or ctx.get("payload_format") or "hex"
            json_data = ctx.get("json") or ctx.get("data")
            if json_data is None and raw_bytes:
                try:
                    text_content = raw_bytes.decode("utf-8")
                    if (text_content.startswith("{") and text_content.endswith("}")) or (text_content.startswith("[") and text_content.endswith("]")):
                        json_data = json.loads(text_content)
                        fmt_type = "json"
                except Exception:
                    pass

            b64_str = base64.b64encode(raw_bytes).decode("ascii") if raw_bytes else ""
            ctx["format"] = fmt_type
            ctx["json"] = json_data
            ctx["hex"] = hex_str or (raw_bytes.hex() if raw_bytes else "")
            ctx["base64"] = b64_str

            try:
                text_str = raw_bytes.decode("utf-8")
            except Exception:
                text_str = None

            input_dict = {
                "format": fmt_type,
                "bytes": raw_bytes,
                "hex": hex_str or (raw_bytes.hex() if raw_bytes else ""),
                "base64": b64_str,
                "text": text_str,
                "json": json_data,
                "data": json_data,
                "context": ctx,
                "metadata": ctx,
                "payload": raw_bytes,
                "original": hex_str or (raw_bytes.hex() if raw_bytes else ""),
            }

            # Direct variable assignment: if data is JSON, unpack all fields directly onto input_dict and context
            if isinstance(json_data, dict):
                for k, v in json_data.items():
                    if k not in input_dict:
                        input_dict[k] = v
                    if k not in ctx:
                        ctx[k] = v

            # Call function appropriately based on inspect or try/except
            import inspect

            sig = inspect.signature(fn)
            param_count = len(sig.parameters)

            result = None
            if param_count == 1:
                param_name = list(sig.parameters.keys())[0]
                if fmt_type == "json" or json_data is not None or param_name in ("input", "data", "message", "msg", "doc", "obj"):
                    try:
                        result = fn(input_dict)
                    except (TypeError, AttributeError):
                        result = fn(raw_bytes)
                else:
                    try:
                        result = fn(raw_bytes)
                    except (TypeError, AttributeError):
                        result = fn(input_dict)
            elif param_count >= 2:
                first_param = list(sig.parameters.keys())[0]
                if first_param in ("input", "data") or fmt_type == "json":
                    try:
                        result = fn(input_dict, ctx)
                    except (TypeError, AttributeError):
                        result = fn(raw_bytes, ctx)
                else:
                    result = fn(raw_bytes, ctx)
            else:
                result = fn()

            if result is None:
                return False, None, logs, f"Function '{fn_name}' returned None. Must return a dict."

            if not isinstance(result, dict):
                return False, None, logs, f"Decoder must return a dict, got {type(result).__name__}"

            return True, result, logs, None

        except Exception as e:
            logger.warning(f"Python decoder execution error: {e}", exc_info=True)
            return False, None, logs, f"Execution Error: {str(e)}"


python_engine = PythonDecoderEngine()
