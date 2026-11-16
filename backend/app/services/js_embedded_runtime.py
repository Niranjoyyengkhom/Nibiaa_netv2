"""
In-Process Embedded JavaScript Runtime (V8 Engine) inside Python for NibiaaNet Backend.

Uses Google's V8 engine embedded directly into the Python process via py_mini_racer.
Executes JavaScript decoders with high performance, memory isolation, and timeout protection
with ZERO external Node.js binary or subprocess requirements.
"""

import json
import logging
import threading
from typing import Any, Dict, List, Optional, Tuple

try:
    from py_mini_racer import MiniRacer
    from py_mini_racer.py_mini_racer import MiniRacerBaseException, JSTimeoutException, JSEvalException
    V8_AVAILABLE = True
except Exception:
    MiniRacer = None
    MiniRacerBaseException = Exception
    JSTimeoutException = Exception
    JSEvalException = Exception
    V8_AVAILABLE = False

logger = logging.getLogger("nibiaanet.backend.v8_runtime")

JS_PRELUDE = """
var __logs = [];
var console = {
    log: function() {
        var args = Array.prototype.slice.call(arguments);
        __logs.push(args.map(function(a) { return typeof a === 'object' ? JSON.stringify(a) : String(a); }).join(' '));
    },
    warn: function() {
        var args = Array.prototype.slice.call(arguments);
        __logs.push('[WARN] ' + args.map(function(a) { return typeof a === 'object' ? JSON.stringify(a) : String(a); }).join(' '));
    },
    error: function() {
        var args = Array.prototype.slice.call(arguments);
        __logs.push('[ERROR] ' + args.map(function(a) { return typeof a === 'object' ? JSON.stringify(a) : String(a); }).join(' '));
    }
};

function __runDecoderWrapper(fn, input) {
    if (typeof fn !== 'function') {
        throw new Error("Decoder must define function 'decode(input)' or 'transform(input)'");
    }
    // Direct variable assignment for incoming JSON payloads (no byte decoding needed)
    if (input && input.json && typeof input.json === 'object' && !Array.isArray(input.json)) {
        for (var key in input.json) {
            if (input[key] === undefined) {
                input[key] = input.json[key];
            }
        }
    }
    // Expose payload, bytes, and input as fallback globals in sandbox
    if (typeof globalThis !== 'undefined') {
        globalThis.payload = input ? input.payload || input : null;
        globalThis.input = input;
        globalThis.bytes = input ? input.bytes : null;
        globalThis.context = input ? input.context : null;
    }
    var res = fn(input, input ? input.context : {});
    if (res === null || typeof res !== 'object') {
        throw new Error("Decoder must return an object (got " + typeof res + ")");
    }
    return JSON.stringify({
        ok: true,
        result: res,
        logs: __logs
    });
}
"""


class EmbeddedJsEngine:
    """
    Executes JavaScript decoders inside Python using Google's V8 engine.
    """

    def __init__(self):
        self._lock = threading.Lock()

    def is_available(self) -> bool:
        return V8_AVAILABLE

    def validate_syntax(self, code: str) -> Tuple[bool, Optional[str]]:
        if not V8_AVAILABLE:
            return False, "py-mini-racer (V8 engine) is not installed in Python"

        if not code or not code.strip():
            return False, "Code cannot be empty"

        check_script = f"""
        {JS_PRELUDE}
        {code}
        var __fn = (typeof decode === 'function' ? decode : (typeof transform === 'function' ? transform : null));
        if (!__fn) {{
            throw new Error("Code must define function 'decode(input)' or 'transform(input)'");
        }}
        """
        try:
            mr = MiniRacer()
            mr.eval(check_script, timeout=1000)
            return True, None
        except MiniRacerBaseException as e:
            err_msg = str(e)
            if hasattr(e, "message") and e.message:
                err_msg = e.message
            if isinstance(err_msg, bytes):
                err_msg = err_msg.decode("utf-8", errors="replace")
            return False, f"JavaScript Syntax/Definition Error: {err_msg}"
        except Exception as e:
            return False, f"Validation error: {e}"

    def execute(
        self,
        code: str,
        raw_bytes: bytes,
        hex_str: str = "",
        context: Optional[Dict[str, Any]] = None,
        timeout_ms: int = 1500,
        max_memory_bytes: int = 64 * 1024 * 1024,
    ) -> Tuple[bool, Any, List[str], Optional[str]]:
        if not V8_AVAILABLE:
            return (
                False,
                None,
                [],
                "Embedded JavaScript V8 engine is not available. Please install py-mini-racer.",
            )

        ctx = context or {}
        byte_list = list(raw_bytes)

        import base64
        format_type = ctx.get("format") or ctx.get("payload_format") or "hex"
        json_data = ctx.get("json") or ctx.get("data")
        if json_data is None:
            try:
                text_content = raw_bytes.decode("utf-8")
                if (text_content.startswith("{") and text_content.endswith("}")) or (text_content.startswith("[") and text_content.endswith("]")):
                    json_data = json.loads(text_content)
                    format_type = "json"
            except Exception:
                pass

        try:
            text_str = raw_bytes.decode("utf-8")
        except Exception:
            text_str = None

        input_dict = {
            "format": format_type,
            "bytes": byte_list,
            "hex": hex_str or raw_bytes.hex(),
            "base64": base64.b64encode(raw_bytes).decode("ascii"),
            "text": text_str,
            "json": json_data,
            "data": json_data,
            "original": hex_str or raw_bytes.hex(),
            "context": ctx,
            "metadata": ctx,
            "payload": {
                "format": format_type,
                "bytes": byte_list,
                "hex": hex_str or raw_bytes.hex(),
                "base64": base64.b64encode(raw_bytes).decode("ascii"),
                "json": json_data,
                "original": hex_str or raw_bytes.hex(),
            },
        }

        # Direct variable assignment: if data is JSON, unpack all fields directly onto input_dict
        if isinstance(json_data, dict):
            for k, v in json_data.items():
                if k not in input_dict:
                    input_dict[k] = v

        input_json_str = json.dumps(input_dict)

        execution_script = f"""
        {JS_PRELUDE}
        {code}
        var __fn = (typeof decode === 'function' ? decode : (typeof transform === 'function' ? transform : null));
        __runDecoderWrapper(__fn, {input_json_str});
        """

        try:
            mr = MiniRacer()
            raw_output = mr.eval(
                execution_script,
                timeout=timeout_ms,
                max_memory=max_memory_bytes,
            )

            parsed = json.loads(raw_output)
            return True, parsed.get("result"), parsed.get("logs", []), None

        except JSTimeoutException:
            return False, None, [], f"JavaScript execution timed out (limit: {timeout_ms}ms)"
        except MiniRacerBaseException as e:
            err_msg = str(e)
            if hasattr(e, "message") and e.message:
                err_msg = e.message
            if isinstance(err_msg, bytes):
                err_msg = err_msg.decode("utf-8", errors="replace")
            for prefix in ("b'Error: ", "b'", "'", "Error: "):
                if err_msg.startswith(prefix):
                    err_msg = err_msg[len(prefix):]
            if err_msg.endswith("'"):
                err_msg = err_msg[:-1]
            return False, None, [], f"JavaScript Error: {err_msg}"
        except Exception as e:
            logger.warning(f"V8 execution failure: {e}", exc_info=True)
            return False, None, [], f"Execution Error: {str(e)}"


embedded_js_engine = EmbeddedJsEngine()
