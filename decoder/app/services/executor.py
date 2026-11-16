import logging
from typing import Dict, Any, Tuple, List, Optional
from app.services.validator import validate_script, is_python_script
from app.services.python_executor import python_engine
from app.services.js_embedded_runtime import embedded_js_engine

logger = logging.getLogger("nibiaanet.decoder.executor")


class DecoderExecutor:
    """
    Unified decoder execution engine for NibiaaNet Decoder Service.
    - Python decoders: Executed natively via sandboxed Python engine.
    - JavaScript decoders: Executed via Google V8 engine embedded directly inside Python (py_mini_racer).
    Zero external Node.js subprocesses required.
    """

    def execute(
        self,
        code: str,
        raw_bytes: bytes,
        hex_str: str,
        context: Optional[dict] = None,
        metadata: Optional[dict] = None,
    ) -> Tuple[bool, Any, List[str], Optional[str]]:
        """
        Executes a decoder script (Python or JavaScript) on raw payload bytes.
        Returns: (success: bool, result_data: dict, logs: list[str], error_msg: Optional[str])
        """
        ctx = context or {}
        if metadata:
            ctx = {**ctx, **metadata}

        # 1. Validate script syntax and security
        valid, errors = validate_script(code)
        if not valid:
            return False, None, [], f"Script validation error: {'; '.join(errors)}"

        # 2. Check language and dispatch
        if is_python_script(code):
            return python_engine.execute(
                code=code,
                raw_bytes=raw_bytes,
                hex_str=hex_str,
                context=ctx,
            )
        else:
            # Embedded V8 JavaScript runtime directly inside Python
            return embedded_js_engine.execute(
                code=code,
                raw_bytes=raw_bytes,
                hex_str=hex_str,
                context=ctx,
            )


decoder_executor = DecoderExecutor()
