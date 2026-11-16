// Sandboxed Node.js runner for Decoder service (Python FastAPI port 3001)
"use strict";

const readline = require("readline");
const vm = require("vm");
const crypto = require("crypto");

const TIME_LIMIT_MS = 200;
const MAX_RESULT_CHARS = 128 * 1024;
const scripts = new Map();

const PRELUDE = `
const __logs = [];
const Console = {
  log: (...args) => { __logs.push(args.map(a => typeof a === 'object' ? JSON.stringify(a) : String(a)).join(' ')); },
  warn: (...args) => { __logs.push('[WARN] ' + args.map(a => typeof a === 'object' ? JSON.stringify(a) : String(a)).join(' ')); },
  error: (...args) => { __logs.push('[ERROR] ' + args.map(a => typeof a === 'object' ? JSON.stringify(a) : String(a)).join(' ')); },
  getLogs: () => __logs
};
`;

const CALL = `
(function () {
  const fn = typeof transform === "function" ? transform : (typeof decode === "function" ? decode : null);
  if (!fn) {
    throw new Error("The decoder must define function decode(input) or transform(input)");
  }
  const raw = JSON.parse(__inputJson);
  const bytes = Uint8Array.from(raw.bytes || []);
  const payloadObj = { bytes: bytes, original: raw.original || null };
  const input = {
    payload: payloadObj,
    bytes: bytes,
    hex: raw.hex || "",
    original: raw.original || null,
    context: raw.context || {},
    metadata: raw.metadata || raw.context || {}
  };
  globalThis.payload = payloadObj;
  globalThis.input = input;
  globalThis.bytes = bytes;
  globalThis.context = input.context;
  const result = fn(input, input.context);
  if (result === null || typeof result !== "object") {
    throw new Error("Decoder must return an object (e.g. { data, units } or key-value object)");
  }
  return JSON.stringify({ result, logs: Console.getLogs() });
})()
`;

function getScript(code) {
  const hash = crypto.createHash("sha256").update(code).digest("hex");
  let script = scripts.get(hash);
  if (!script) {
    script = new vm.Script(PRELUDE + "\n" + code + "\n" + CALL);
    if (scripts.size > 200) {
      scripts.delete(scripts.keys().next().value);
    }
    scripts.set(hash, script);
  }
  return script;
}

const rl = readline.createInterface({ input: process.stdin, terminal: false });

rl.on("line", (line) => {
  if (!line.trim()) return;
  let request;
  try {
    request = JSON.parse(line);
  } catch (err) {
    process.stdout.write(JSON.stringify({ ok: false, error: "Invalid JSON request" }) + "\n");
    return;
  }

  const { id, op, code, bytes, hex, original, context, metadata } = request;

  if (op === "check") {
    try {
      getScript(code);
      process.stdout.write(JSON.stringify({ id, ok: true }) + "\n");
    } catch (err) {
      process.stdout.write(JSON.stringify({ id, ok: false, error: err.message }) + "\n");
    }
    return;
  }

  if (op === "decode" || op === "transform") {
    try {
      const script = getScript(code);
      const rawBytes = bytes ? Buffer.from(bytes, "base64") : (hex ? Buffer.from(hex, "hex") : Buffer.alloc(0));
      const inputJson = JSON.stringify({
        bytes: Array.from(rawBytes),
        hex: hex || rawBytes.toString("hex"),
        original: original || null,
        context: context || {},
        metadata: metadata || context || {}
      });

      const sandbox = {
        __inputJson: inputJson,
        DataView: DataView,
        Uint8Array: Uint8Array,
        Int8Array: Int8Array,
        Uint16Array: Uint16Array,
        Int16Array: Int16Array,
        Uint32Array: Uint32Array,
        Int32Array: Int32Array,
        Float32Array: Float32Array,
        Float64Array: Float64Array,
        Math: Math,
        JSON: JSON,
        String: String,
        Number: Number,
        Boolean: Boolean,
        Array: Array,
        Object: Object,
        parseInt: parseInt,
        parseFloat: parseFloat,
        isNaN: isNaN,
        isFinite: isFinite
      };

      const contextObj = vm.createContext(sandbox);
      const outputJson = script.runInContext(contextObj, { timeout: TIME_LIMIT_MS });
      
      if (outputJson.length > MAX_RESULT_CHARS) {
        throw new Error("Output exceeded maximum allowed size");
      }

      const parsed = JSON.parse(outputJson);
      process.stdout.write(JSON.stringify({ id, ok: true, result: parsed.result, logs: parsed.logs || [] }) + "\n");
    } catch (err) {
      process.stdout.write(JSON.stringify({ id, ok: false, error: err.message }) + "\n");
    }
    return;
  }

  process.stdout.write(JSON.stringify({ id, ok: false, error: "Unknown op: " + op }) + "\n");
});
