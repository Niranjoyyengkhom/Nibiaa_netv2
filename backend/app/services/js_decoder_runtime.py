"""
Runs JavaScript decoders (DecoderDefinition.code) in a sandboxed Node.js
process: app/decoder_runtime/runner.js, started with Node's permission
model (no file system, child processes, workers or network) and a memory
limit. Each decode runs in a fresh vm context with a time limit.

One runner process is kept alive and reused; calls are serialised with a
lock. When the runner hangs or dies it is killed and started again, and
the call fails with a DecoderRuntimeError.

Configuration:
    NODE_BINARY            node executable (default "node"; Node 22+)
    DECODER_TIMEOUT_SECONDS  watchdog per call (default 3)
"""

import base64
import json
import logging
import os
import queue
import shutil
import subprocess
import threading
from pathlib import Path
from app.services.js_embedded_runtime import embedded_js_engine


logger = logging.getLogger(__name__)

RUNNER = Path(__file__).resolve().parent.parent / "decoder_runtime" / "runner.js"


class DecoderRuntimeError(Exception):
    """The decoder failed: compile error, exception, time limit, crash."""


class DecoderRuntimeUnavailable(DecoderRuntimeError):
    """Node.js is not installed / cannot be started."""


class JsDecoderRuntime:

    def __init__(self):
        self._lock = threading.Lock()
        self._process = None
        self._answers = None
        self._next_id = 0

    # ================================
    # Public API
    # ================================

    def check(self, code: str):
        """Raises DecoderRuntimeError unless the code defines decode(input) or transform(input)."""
        if embedded_js_engine.is_available():
            ok, err = embedded_js_engine.validate_syntax(code)
            if not ok:
                raise DecoderRuntimeError(err)
            return

        self._call({"op": "check", "code": code})

    def decode(self, code: str, payload: bytes, context: dict):
        """Returns the object returned by decode(input)."""
        if embedded_js_engine.is_available():
            ok, res, logs, err = embedded_js_engine.execute(
                code=code,
                raw_bytes=payload,
                hex_str=payload.hex(),
                context=context,
            )
            if not ok:
                raise DecoderRuntimeError(err or "JavaScript decoder execution failed")
            return res

        return self._call({
            "op": "decode",
            "code": code,
            "bytes": base64.b64encode(payload).decode(),
            "context": context,
        })

    def available(self):
        return embedded_js_engine.is_available() or self._node() is not None

    # ================================
    # Process handling
    # ================================

    def _node(self):
        return shutil.which(os.environ.get("NODE_BINARY", "node"))

    def _start(self):
        node = self._node()

        if node is None:
            raise DecoderRuntimeUnavailable(
                "JavaScript decoders need Node.js 22+ on the server (set NODE_BINARY)"
            )

        # Minimal environment: the decoder never sees server secrets
        env = {"PATH": os.environ.get("PATH", "")}
        for name in ("SYSTEMROOT", "SystemRoot", "TEMP", "TMP"):
            if name in os.environ:
                env[name] = os.environ[name]

        self._process = subprocess.Popen(
            [node, "--permission", "--max-old-space-size=128", str(RUNNER)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=env,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )

        self._answers = queue.Queue()
        stdout, answers = self._process.stdout, self._answers

        def read():
            for line in stdout:
                answers.put(line)
            answers.put(None)  # process ended

        threading.Thread(target=read, daemon=True, name="js-decoder-reader").start()

    def _stop(self):
        if self._process is not None:
            try:
                self._process.kill()
            except OSError:
                pass

        self._process = None
        self._answers = None

    def _call(self, message: dict):
        timeout = float(os.environ.get("DECODER_TIMEOUT_SECONDS", "3"))

        with self._lock:
            if self._process is None or self._process.poll() is not None:
                self._start()

            self._next_id += 1
            message = {**message, "id": self._next_id}

            try:
                self._process.stdin.write(json.dumps(message) + "\n")
                self._process.stdin.flush()
            except OSError:
                self._stop()
                raise DecoderRuntimeError("The decoder runtime stopped; retry")

            while True:
                try:
                    line = self._answers.get(timeout=timeout)
                except queue.Empty:
                    logger.warning("JavaScript decoder did not answer in %ss, restarting the runner", timeout)
                    self._stop()
                    raise DecoderRuntimeError(f"The decoder did not finish within {timeout:g} s")

                if line is None:
                    self._stop()
                    raise DecoderRuntimeError("The decoder crashed (out of memory or killed)")

                try:
                    answer = json.loads(line)
                except ValueError:
                    continue

                # An answer of an earlier, timed-out call is skipped
                if answer.get("id") == message["id"]:
                    break

        if not answer.get("ok"):
            raise DecoderRuntimeError(answer.get("error") or "The decoder failed")

        return answer.get("result")


js_runtime = JsDecoderRuntime()
