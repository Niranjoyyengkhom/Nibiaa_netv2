// Sandboxed runner for JavaScript decoders (DecoderDefinition.code).
//
// Started by app/services/js_decoder_runtime.py as:
//   node --permission --max-old-space-size=128 runner.js
//
// Layers of isolation:
//   1. A separate process with Node's permission model: no file system,
//      child processes, workers, native addons or network.
//   2. Every call runs in a fresh vm context with a null-prototype global:
//      no require, process, Buffer, timers, eval or new Function.
//   3. Data crosses the boundary only as JSON strings, so no object of
//      this realm (and so no route back to `process`) reaches the code.
//   4. A time limit per call; Python kills the process if it hangs.
//
// Protocol: one JSON object per line on stdin, one answer per line on stdout.
//   {"id": 1, "op": "check",  "code": "..."}
//   {"id": 2, "op": "decode", "code": "...", "bytes": "<base64>", "context": {...}}
//   -> {"id": 1, "ok": true, "result": <json>} | {"id": 1, "ok": false, "error": "..."}

"use strict";

const readline = require("readline");
const vm = require("vm");
const crypto = require("crypto");

const TIME_LIMIT_MS = 100;
const MAX_RESULT_CHARS = 64 * 1024;
const MAX_CACHED_SCRIPTS = 200;

const scripts = new Map();

// Runs inside the sandbox after the decoder code: builds DecoderInput
// from the JSON string and returns the result as a JSON string.
const CALL = `
(function () {
  if (typeof decode !== "function") {
    throw new Error("The decoder must define function decode(input)");
  }
  const raw = JSON.parse(__inputJson);
  const input = {
    payload: { bytes: Uint8Array.from(raw.bytes) },
    context: raw.context,
  };
  const result = decode(input);
  if (result === null || typeof result !== "object" || Array.isArray(result)) {
    throw new Error("decode(input) must return an object");
  }
  return JSON.stringify(result);
})()
`;

const callScript = new vm.Script(CALL, { filename: "nibiaanet-call.js" });

function compile(code) {
  const key = crypto.createHash("sha256").update(code).digest("hex");
  let script = scripts.get(key);

  if (!script) {
    script = new vm.Script(code, { filename: "decoder.js" });

    if (scripts.size >= MAX_CACHED_SCRIPTS) {
      scripts.delete(scripts.keys().next().value);
    }
    scripts.set(key, script);
  }

  return script;
}

function sandbox(inputJson) {
  const globals = Object.create(null);
  globals.__inputJson = inputJson;

  return vm.createContext(globals, {
    name: "decoder",
    codeGeneration: { strings: false, wasm: false },
    microtaskMode: "afterEvaluate",
  });
}

function run(message) {
  const script = compile(String(message.code || ""));

  if (message.op === "check") {
    // Defining the decoder must work and must define decode()
    const context = sandbox("{}");
    script.runInContext(context, { timeout: TIME_LIMIT_MS });
    const kind = vm.runInContext("typeof decode", context, { timeout: TIME_LIMIT_MS });

    if (kind !== "function") {
      throw new Error("The decoder must define function decode(input)");
    }

    return true;
  }

  if (message.op === "decode") {
    const bytes = Array.from(Buffer.from(String(message.bytes || ""), "base64"));
    const context = sandbox(JSON.stringify({ bytes, context: message.context || {} }));

    script.runInContext(context, { timeout: TIME_LIMIT_MS });
    const json = callScript.runInContext(context, { timeout: TIME_LIMIT_MS });

    if (typeof json !== "string") {
      throw new Error("decode(input) must return a JSON-serialisable object");
    }

    if (json.length > MAX_RESULT_CHARS) {
      throw new Error(`The decoded result is larger than ${MAX_RESULT_CHARS} characters`);
    }

    return JSON.parse(json);
  }

  throw new Error(`Unknown op ${message.op}`);
}

function describe(error) {
  if (error && error.code === "ERR_SCRIPT_EXECUTION_TIMEOUT") {
    return `The decoder ran longer than ${TIME_LIMIT_MS} ms`;
  }

  // Errors thrown inside the sandbox come from another realm: read the
  // message as a string only
  try {
    const name = String(error && error.name ? error.name : "Error");
    const text = String(error && error.message ? error.message : error);
    return `${name}: ${text}`.slice(0, 500);
  } catch {
    return "The decoder failed";
  }
}

const lines = readline.createInterface({ input: process.stdin });

lines.on("line", (line) => {
  let message;

  try {
    message = JSON.parse(line);
  } catch {
    return;
  }

  let answer;

  try {
    answer = { id: message.id, ok: true, result: run(message) };
  } catch (error) {
    answer = { id: message.id, ok: false, error: describe(error) };
  }

  process.stdout.write(JSON.stringify(answer) + "\n");
});
