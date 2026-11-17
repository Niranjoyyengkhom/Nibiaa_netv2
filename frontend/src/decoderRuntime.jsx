import { useEffect, useState, useMemo } from "react";

import { formatDate, formatUtcDate } from "./api";
import { Modal, Notice, Restricted, usePersistentState, RawPayloadCell, RawPayloadBlock, RawPayloadBadge, Pagination } from "./components";


// Decoder server (decoder/server). It runs the code written here and stores
// the decoded result in the platform database, where the backend reads it
// (GET /decoder-messages/).
export const DECODER_API =
  import.meta.env.VITE_DECODER_API_URL ||
  import.meta.env.VITE_DECODER_API ||
  (typeof window !== "undefined" && (window.location.port === "8080" || window.location.protocol === "https:" || window.location.hostname !== "localhost")
    ? "/decoder"
    : "http://127.0.0.1:3001");


export const TTN_TEMPLATE = `function decodeUplink(input) {
  // TTN (The Things Network) Standard Payload Formatter
  // input.bytes: Uint8Array of raw payload bytes
  // input.fPort: LoRaWAN port number
  const bytes = input.bytes;

  if (!bytes || bytes.length < 2) {
    return {
      errors: ["Payload must contain at least 2 bytes"]
    };
  }

  // Example decoder for 4-byte payload (temp + hum)
  const temp = bytes.length >= 2 ? (bytes[0] << 8 | bytes[1]) / 100 : bytes[0];
  const hum = bytes.length >= 4 ? (bytes[2] << 8 | bytes[3]) / 10 : 50;

  return {
    data: {
      temperature: temp,
      humidity: hum,
    },
    warnings: []
  };
}
`;

export const PYTHON_TEMPLATE = `def decode(payload: bytes, context: dict = None) -> dict:
    """
    Python Decoder for NibiaaNet (FastAPI Native).
    Special keywords like deviceName, deviceType, credentials auto-provision the device.
    """
    if len(payload) < 4:
        raise ValueError("Payload must contain at least 4 bytes")

    temp_raw, hum_raw = struct.unpack(">hH", payload[0:4])

    return {
        # Special keywords for device provisioning:
        "deviceName": "Cold Storage Sensor 01",
        "deviceType": "NTN",
        "application": "OtherApp",  # Target application name or ID (routes device to this app)

        # Telemetry sensor data:
        "data": {
            "temperature": round(temp_raw / 100.0, 2),
            "humidity": round(hum_raw / 10.0, 1),
        },
        "units": {
            "temperature": "°C",
            "humidity": "%"
        }
    }
`;

export const JS_TEMPLATE = `function transform(input) {
  const bytes = input.bytes;

  if (bytes.length < 4) {
    throw new Error("Payload must contain at least 4 bytes.");
  }

  return {
    // Special keywords for device provisioning:
    deviceName: "Cold Storage Sensor 01",
    deviceType: "NTN", // "NTN", "TN", "LoRaWAN", "BLE", "Direct IP"
    application: "OtherApp", // Target application name or ID (routes device to this app)

    // Telemetry measurements:
    data: {
      temperature: (bytes[0] << 8 | bytes[1]) / 100,
      humidity: (bytes[2] << 8 | bytes[3]) / 10,
    },
    units: {
      temperature: "°C",
      humidity: "%",
    }
  };
}
`;

export const JSON_DIRECT_TEMPLATE = `function transform(input) {
  // If data is in JSON, no byte or bit decoding is needed!
  // Assign variables directly from incoming JSON data:
  const temperature = input.temperature || input.temp;
  const humidity = input.humidity || input.hum;
  const battery = input.battery || input.batt;

  return {
    deviceName: input.deviceName || "Cold Storage Sensor 01",
    deviceType: input.deviceType || "Direct IP",
    data: {
      temperature,
      humidity,
      battery,
    },
    units: {
      temperature: "°C",
      humidity: "%",
      battery: "%",
    }
  };
}
`;

export const PYTHON_JSON_TEMPLATE = `def decode(input: dict) -> dict:
    """
    Direct variable assignment for incoming JSON payloads.
    No byte or hex decoding required - just map variables to incoming data!
    """
    temperature = input.get("temperature") or input.get("temp")
    humidity = input.get("humidity") or input.get("hum")
    battery = input.get("battery") or input.get("batt")

    return {
        "deviceName": input.get("deviceName") or "Cold Storage Sensor 01",
        "deviceType": input.get("deviceType") or "Direct IP",
        "application": input.get("application") or "OtherApp",
        "data": {
            "temperature": temperature,
            "humidity": humidity,
            "battery": battery,
        },
        "units": {
            "temperature": "°C",
            "humidity": "%",
            "battery": "%"
        }
    }
`;

export const JSON_DYNAMIC_TEMPLATE = `function transform(input) {
  // If data is in JSON, no byte decoding is needed!
  // Variables are directly accessible on input:
  if (input.format === "json" || input.json) {
    const temperature = input.temperature ?? input.temp;
    const humidity = input.humidity ?? input.hum;
    const battery = input.battery ?? input.batt;

    return {
      deviceName: input.deviceName || "Smart Environmental Sensor",
      deviceType: input.deviceType || "Direct IP",
      application: input.application || "OtherApp",
      data: {
        temperature,
        humidity,
        battery,
      },
      units: {
        temperature: "°C",
        humidity: "%",
        battery: "%",
      }
    };
  }

  // Fallback for Hex / Binary / Base64 payload bytes:
  const bytes = input.bytes;
  if (bytes && bytes.length >= 4) {
    return {
      deviceName: "Sensor " + (input.context?.deviceId || "01"),
      deviceType: "NTN",
      data: {
        temperature: (bytes[0] << 8 | bytes[1]) / 100,
        humidity: (bytes[2] << 8 | bytes[3]) / 10,
      },
      units: {
        temperature: "°C",
        humidity: "%"
      }
    };
  }

  return { data: { raw: input.hex } };
}
`;

const TEMPLATE = JS_TEMPLATE;


function messageTimestamp(message) {
  if (!message) return null;
  return (
    message.receivedAt ||
    message.received_at ||
    message.stored_at ||
    message.processed_at ||
    message.timestamp ||
    message.created_at ||
    message.time ||
    null
  );
}


function formatValue(value) {
  return typeof value === "object" && value !== null
    ? JSON.stringify(value)
    : String(value);
}


function formatValues(values) {
  return Object.entries(values || {})
    .map(([key, value]) => `${key}: ${formatValue(value)}`)
    .join(" · ");
}


// Which received messages a live decoder decodes (DecoderMatch)
const PROTOCOL_OPTIONS = [
  { value: "", label: "Any Protocol (All)" },
  { value: "https", label: "HTTPS" },
  { value: "mqtt", label: "MQTT" },
  { value: "tcp", label: "TCP/IP" },
  { value: "udp", label: "UDP" },
  { value: "webhook", label: "Webhook" },
  { value: "custom", label: "Custom" },
];

const MATCH_FIELDS = [
  {
    key: "protocolId",
    label: "Protocol",
    type: "select",
    options: PROTOCOL_OPTIONS,
  },
  {
    key: "payloadFormat",
    label: "Payload Format",
    type: "select",
    options: [
      { value: "", label: "Any format (All)" },
      { value: "json", label: "JSON" },
      { value: "hex", label: "Hex" },
      { value: "binary", label: "Binary" },
      { value: "base64", label: "Base64" },
    ],
  },
  { key: "providerId", label: "Provider", placeholder: "" },
  { key: "deviceTypeId", label: "Device type", placeholder: "" },
  { key: "messageType", label: "Message type", placeholder: "" },
  { key: "protocolVersion", label: "Protocol version", placeholder: "" },
];

const EMPTY_MATCH = Object.fromEntries(MATCH_FIELDS.map((field) => [field.key, ""]));

function matchText(match) {
  const entries = Object.entries(match || {}).filter(([_, value]) => value && String(value).trim());
  if (!entries.length) return "All messages";
  return entries
    .map(([key, value]) => `${MATCH_FIELDS.find((f) => f.key === key)?.label || key}: ${value}`)
    .join(" · ");
}


// Calls the decoder server with the signed-in user's token
async function decoderRequest(path, { method = "GET", body } = {}) {
  let response;

  try {
    response = await fetch(`${DECODER_API}${path}`, {
      method,
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${localStorage.getItem("authToken")}`,
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new Error(`Cannot reach the decoder server at ${DECODER_API}. Is it running?`);
  }

  const data = await response.json().catch(() => null);

  if (!response.ok) {
    throw new Error(data?.error || `The decoder server answered ${response.status}.`);
  }

  return data;
}


// -------------------------
// Decoders page: write and run (TTN Split-Screen Layout)
// -------------------------

function hexToAsciiStr(hex) {
  if (!hex) return "";
  const clean = String(hex).replace(/\s+/g, "");
  let str = "";
  for (let i = 0; i < clean.length; i += 2) {
    const code = parseInt(clean.substring(i, i + 2), 16);
    if (code >= 32 && code <= 126) {
      str += String.fromCharCode(code);
    }
  }
  return str;
}

function formatRelativeTime(dateStr) {
  if (!dateStr) return "Just now";
  try {
    const date = new Date(dateStr);
    const diff = Math.floor((Date.now() - date.getTime()) / 1000);
    if (isNaN(diff) || diff < 3) return "Just now";
    if (diff < 60) return `${diff}s ago`;
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    return `${Math.floor(diff / 3600)}h ago`;
  } catch {
    return "Recent";
  }
}

function InboundPayloadView({ hex }) {
  const [copied, setCopied] = useState(false);

  // Parse hex into all formats
  const parsed = useMemo(() => {
    if (!hex || typeof hex !== "string") {
      return { isEmpty: true };
    }
    const cleanHex = hex.trim().replace(/^0x/i, "").replace(/\s+/g, "");
    if (!cleanHex || cleanHex.length < 2) {
      return { isEmpty: true };
    }

    const bytes = [];
    for (let i = 0; i < cleanHex.length; i += 2) {
      bytes.push(parseInt(cleanHex.substring(i, i + 2), 16));
    }

    // 1. UTF-8 Text / JSON
    let text = "";
    let isUtf8 = false;
    let isJson = false;
    let formattedJson = null;

    try {
      const uint8 = new Uint8Array(bytes);
      text = new TextDecoder("utf-8", { fatal: true }).decode(uint8);
      isUtf8 = true;
    } catch {
      // Fallback: check printable ASCII
      let printable = 0;
      for (const b of bytes) {
        if ((b >= 32 && b <= 126) || b === 10 || b === 13 || b === 9) printable++;
      }
      if (bytes.length > 0 && printable / bytes.length >= 0.8) {
        text = bytes.map((b) => ((b >= 32 && b <= 126) || b === 10 || b === 13 || b === 9 ? String.fromCharCode(b) : ".")).join("");
        isUtf8 = true;
      }
    }

    if (isUtf8 && text) {
      const trimmed = text.trim();
      if ((trimmed.startsWith("{") && trimmed.endsWith("}")) || (trimmed.startsWith("[") && trimmed.endsWith("]"))) {
        try {
          const obj = JSON.parse(trimmed);
          formattedJson = JSON.stringify(obj, null, 2);
          isJson = true;
        } catch {}
      }
    }

    // 2. Base64
    let b64 = "";
    try {
      let bin = "";
      for (const b of bytes) bin += String.fromCharCode(b);
      b64 = btoa(bin);
    } catch {}

    // 3. Formatted Hex (spaced)
    const spacedHex = cleanHex.match(/.{1,2}/g)?.join(" ") || cleanHex;

    // 4. Byte array string
    const byteArrStr = "[" + bytes.join(", ") + "]";

    const defaultMode = isJson ? "json" : isUtf8 ? "text" : "hex";

    return {
      isEmpty: false,
      bytesCount: bytes.length,
      isJson,
      isUtf8,
      defaultMode,
      json: formattedJson,
      text: text,
      hex: spacedHex,
      rawHex: cleanHex,
      base64: b64,
      bytesArray: byteArrStr,
    };
  }, [hex]);

  const [mode, setMode] = useState(parsed.defaultMode || "json");

  // Keep mode in sync if payload changes
  useEffect(() => {
    if (parsed.defaultMode) {
      setMode(parsed.defaultMode);
    }
  }, [parsed.defaultMode]);

  if (parsed.isEmpty) {
    return (
      <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", fontStyle: "italic", marginTop: "6px" }}>
        No payload bytes
      </div>
    );
  }

  const currentContent =
    mode === "json"
      ? parsed.json || parsed.text
      : mode === "text"
      ? parsed.text
      : mode === "base64"
      ? parsed.base64
      : mode === "bytes"
      ? parsed.bytesArray
      : parsed.hex;

  const handleCopy = () => {
    navigator.clipboard.writeText(currentContent);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div style={{ marginTop: "8px" }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: "4px",
          gap: "6px",
          flexWrap: "wrap",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
          <span style={{ fontSize: "0.72rem", color: "var(--text-muted, #94a3b8)", fontWeight: 600 }}>
            Raw Data ({parsed.bytesCount} B):
          </span>
          {parsed.isJson && (
            <span
              style={{
                fontSize: "0.65rem",
                padding: "1px 5px",
                borderRadius: "3px",
                background: "rgba(52, 211, 153, 0.15)",
                color: "#34d399",
                border: "1px solid rgba(52, 211, 153, 0.3)",
                fontWeight: 600,
              }}
            >
              JSON
            </span>
          )}
        </div>

        {/* Format Selector Tabs */}
        <div style={{ display: "flex", gap: "3px", alignItems: "center" }}>
          {parsed.isJson && (
            <button
              type="button"
              onClick={() => setMode("json")}
              style={{
                fontSize: "0.68rem",
                padding: "2px 6px",
                borderRadius: "4px",
                border: mode === "json" ? "1px solid #38bdf8" : "1px solid rgba(255,255,255,0.1)",
                background: mode === "json" ? "rgba(56, 189, 248, 0.2)" : "rgba(0,0,0,0.2)",
                color: mode === "json" ? "#38bdf8" : "var(--text-muted, #94a3b8)",
                cursor: "pointer",
                fontWeight: mode === "json" ? 600 : 400,
              }}
            >
              JSON
            </button>
          )}
          {parsed.isUtf8 && (
            <button
              type="button"
              onClick={() => setMode("text")}
              style={{
                fontSize: "0.68rem",
                padding: "2px 6px",
                borderRadius: "4px",
                border: mode === "text" ? "1px solid #38bdf8" : "1px solid rgba(255,255,255,0.1)",
                background: mode === "text" ? "rgba(56, 189, 248, 0.2)" : "rgba(0,0,0,0.2)",
                color: mode === "text" ? "#38bdf8" : "var(--text-muted, #94a3b8)",
                cursor: "pointer",
                fontWeight: mode === "text" ? 600 : 400,
              }}
            >
              Text
            </button>
          )}
          <button
            type="button"
            onClick={() => setMode("hex")}
            style={{
              fontSize: "0.68rem",
              padding: "2px 6px",
              borderRadius: "4px",
              border: mode === "hex" ? "1px solid #38bdf8" : "1px solid rgba(255,255,255,0.1)",
              background: mode === "hex" ? "rgba(56, 189, 248, 0.2)" : "rgba(0,0,0,0.2)",
              color: mode === "hex" ? "#38bdf8" : "var(--text-muted, #94a3b8)",
              cursor: "pointer",
              fontWeight: mode === "hex" ? 600 : 400,
            }}
          >
            Hex
          </button>
          <button
            type="button"
            onClick={() => setMode("base64")}
            style={{
              fontSize: "0.68rem",
              padding: "2px 6px",
              borderRadius: "4px",
              border: mode === "base64" ? "1px solid #38bdf8" : "1px solid rgba(255,255,255,0.1)",
              background: mode === "base64" ? "rgba(56, 189, 248, 0.2)" : "rgba(0,0,0,0.2)",
              color: mode === "base64" ? "#38bdf8" : "var(--text-muted, #94a3b8)",
              cursor: "pointer",
              fontWeight: mode === "base64" ? 600 : 400,
            }}
          >
            Base64
          </button>
          <button
            type="button"
            onClick={() => setMode("bytes")}
            style={{
              fontSize: "0.68rem",
              padding: "2px 6px",
              borderRadius: "4px",
              border: mode === "bytes" ? "1px solid #38bdf8" : "1px solid rgba(255,255,255,0.1)",
              background: mode === "bytes" ? "rgba(56, 189, 248, 0.2)" : "rgba(0,0,0,0.2)",
              color: mode === "bytes" ? "#38bdf8" : "var(--text-muted, #94a3b8)",
              cursor: "pointer",
              fontWeight: mode === "bytes" ? 600 : 400,
            }}
          >
            Bytes
          </button>
          <button
            type="button"
            onClick={handleCopy}
            style={{
              fontSize: "0.68rem",
              padding: "2px 6px",
              borderRadius: "4px",
              border: "1px solid rgba(255,255,255,0.15)",
              background: "rgba(255,255,255,0.06)",
              color: copied ? "#34d399" : "var(--text-muted, #94a3b8)",
              cursor: "pointer",
              marginLeft: "3px",
            }}
            title="Copy current format to clipboard"
          >
            {copied ? "✓ Copied" : "📋 Copy"}
          </button>
        </div>
      </div>

      <pre
        style={{
          fontSize: "0.75rem",
          background: "rgba(0,0,0,0.35)",
          border: "1px solid rgba(255,255,255,0.07)",
          padding: "8px 10px",
          borderRadius: "6px",
          color: mode === "json" ? "#38bdf8" : "#cbd5e1",
          wordBreak: "break-all",
          whiteSpace: mode === "json" ? "pre" : "pre-wrap",
          maxHeight: "160px",
          overflowY: "auto",
          fontFamily: "var(--mono, monospace)",
          margin: 0,
        }}
      >
        {currentContent}
      </pre>
    </div>
  );
}

export function DecoderRunner({ currentUser, api }) {
  // Live decoders apply to every matching message, so only admins save them
  const isAdmin = currentUser?.role === "admin";

  // Kept while switching pages (until sign out)
  const [code, setCode] = usePersistentState("decoder.code", TEMPLATE);
  const [payload, setPayload] = usePersistentState("decoder.payload", "0A280258");
  const [format, setFormat] = usePersistentState("decoder.format", "auto");
  const [deviceId, setDeviceId] = usePersistentState("decoder.deviceId", "");

  const [running, setRunning] = useState(false);
  const [result, setResult] = usePersistentState("decoder.result", null);
  const [notice, setNotice] = useState(null);

  // Live Uplink Stream state (Right Panel - TTN style)
  const [liveStreamMessages, setLiveStreamMessages] = useState([]);
  const [liveStreamLoading, setLiveStreamLoading] = useState(false);
  const [liveStreamFilter, setLiveStreamFilter] = useState("");
  const [autoRefreshLive, setAutoRefreshLive] = useState(true);
  const [inspectMessage, setInspectMessage] = useState(null);
  const [loadHint, setLoadHint] = useState(null);

  // Save as live decoder
  const [name, setName] = usePersistentState("decoder.name", "UDP Sensor");
  const [match, setMatch] = usePersistentState("decoder.match", { ...EMPTY_MATCH, protocolId: "udp" });
  const [saveNotice, setSaveNotice] = useState(null);
  const [liveDecoders, setLiveDecoders] = useState([]);

  // Normalize legacy protocol IDs if loaded from persistent storage
  useEffect(() => {
    if (match.protocolId && !PROTOCOL_OPTIONS.some((p) => p.value === match.protocolId)) {
      setMatch((prev) => ({
        ...prev,
        protocolId:
          prev.protocolId === "udp-sensor"
            ? "udp"
            : prev.protocolId === "http"
            ? "https"
            : "",
      }));
    }
  }, [match.protocolId, setMatch]);

  useEffect(() => {
    refreshDecoders();
  }, []);

  async function refreshDecoders() {
    try {
      setLiveDecoders(await decoderRequest("/decoders"));
    } catch {
      // The run form reports an unreachable server
      setLiveDecoders([]);
    }
  }

  // Fetch real-time live uplinks for the TTN Right Panel
  async function refreshLiveStream() {
    if (!api) return;
    try {
      setLiveStreamLoading(true);
      const [stagedRes, telemetryRes] = await Promise.allSettled([
        api.get("/ingest/messages", { limit: 50 }),
        api.get("/telemetry/", { limit: 50 }),
      ]);

      const staged = stagedRes.status === "fulfilled" && Array.isArray(stagedRes.value) ? stagedRes.value : [];
      const telemetry = telemetryRes.status === "fulfilled" && Array.isArray(telemetryRes.value) ? telemetryRes.value : [];

      const seen = new Set();
      const combined = [];

      // 1. Process staged messages (have raw bytes, format, provider)
      for (const m of staged) {
        const key = `msg-${m.id}`;
        if (!seen.has(key)) {
          seen.add(key);
          combined.push({
            id: m.id,
            source: "staged",
            deviceId: m.device_id || m.device_identifier || "Unknown",
            deviceName: m.originator_device || m.device_id || m.device_identifier,
            status: m.status || "ROUTED",
            provider: m.provider || "hubble",
            connectionType: m.connection_type || "NTN",
            transport: m.transport || "webhook",
            rawPayloadHex: m.raw_payload_hex || "",
            payloadFormat: m.payload_format || "hex",
            decoded: m.decoded || null,
            receivedAt: m.received_at || m.processed_at || new Date().toISOString(),
            error: m.error || null,
            details: m,
          });
        }
      }

      // 2. Add telemetry records
      for (const t of telemetry) {
        const key = `tel-${t.id}`;
        if (!seen.has(key)) {
          seen.add(key);
          combined.push({
            id: t.id,
            source: "telemetry",
            deviceId: t.device_id || "Unknown",
            deviceName: t.device_name || t.device_id,
            status: "ROUTED",
            provider: t.provider || "hubble",
            connectionType: t.connection_type || "NTN",
            transport: "telemetry",
            rawPayloadHex: t.raw_payload_hex || "",
            payloadFormat: "hex",
            decoded: t.telemetry || null,
            receivedAt: t.received_at || t.timestamp || new Date().toISOString(),
            details: t,
          });
        }
      }

      // Sort newest first
      combined.sort((a, b) => new Date(b.receivedAt) - new Date(a.receivedAt));
      setLiveStreamMessages(combined);
    } catch (e) {
      console.debug("Live stream fetch:", e);
    } finally {
      setLiveStreamLoading(false);
    }
  }

  // Periodic polling for live uplink stream
  useEffect(() => {
    refreshLiveStream();
    if (!autoRefreshLive) return;
    const interval = setInterval(refreshLiveStream, 3000);
    return () => clearInterval(interval);
  }, [api, autoRefreshLive]);

  // Load a live packet from the right panel into the left coding screen
  function loadIntoDecoder(msg) {
    if (msg.rawPayloadHex) {
      const cleanHex = msg.rawPayloadHex.trim();
      let utf8Text = "";
      try {
        const bytes = cleanHex.match(/.{1,2}/g)?.map((b) => parseInt(b, 16)) || [];
        utf8Text = new TextDecoder("utf-8", { fatal: true }).decode(new Uint8Array(bytes));
      } catch {
        utf8Text = hexToAsciiStr(cleanHex);
      }

      const trimmed = utf8Text.trim();
      if ((trimmed.startsWith("{") && trimmed.endsWith("}")) || (trimmed.startsWith("[") && trimmed.endsWith("]"))) {
        try {
          const parsed = JSON.parse(trimmed);
          setPayload(JSON.stringify(parsed, null, 2));
          setFormat("json");
        } catch {
          setPayload(cleanHex);
          setFormat("hex");
        }
      } else {
        setPayload(cleanHex);
        setFormat("hex");
      }
    } else if (msg.decoded) {
      setPayload(JSON.stringify(msg.decoded, null, 2));
      setFormat("json");
    }

    if (msg.deviceId && msg.deviceId !== "Unknown") {
      setDeviceId(msg.deviceId);
    }

    setLoadHint(`⚡ Loaded uplink payload from ${msg.deviceId || "device"} into Decoder!`);
    setTimeout(() => setLoadHint(null), 4000);
  }

  async function save(event) {
    event.preventDefault();
    setSaveNotice(null);

    try {
      const saved = await decoderRequest("/decoders", {
        method: "POST",
        body: { name: name.trim(), code, match },
      });

      const verLabel = String(saved.version || "1").startsWith("v") ? saved.version : `v${saved.version || 1}`;
      setSaveNotice({
        type: "success",
        text: `${name.trim()} ${verLabel} is live. New messages matching ${matchText(saved.match)} are decoded with it.`,
      });

      refreshDecoders();
    } catch (error) {
      setSaveNotice({ type: "error", text: error.message });
    }
  }

  // Puts a live decoder's code in the editor, to change it and save the next version
  function load(decoder) {
    setCode(decoder.code);
    setName(decoder.name);
    setMatch({ ...EMPTY_MATCH, ...decoder.match });
    const verLabel = String(decoder.version || "1").startsWith("v") ? decoder.version : `v${decoder.version || 1}`;
    setSaveNotice({
      type: "info",
      text: `Editing ${decoder.name} ${verLabel}. Saving creates the next version.`,
    });
  }

  async function deleteLiveDecoder(decoder) {
    const verLabel = String(decoder.version || "1").startsWith("v") ? decoder.version : `v${decoder.version || 1}`;
    if (!window.confirm(`Delete live decoder "${decoder.name} ${verLabel}"?`)) {
      return;
    }

    setSaveNotice(null);

    try {
      await decoderRequest(`/decoders/${decoder.id}`, { method: "DELETE" });
      setSaveNotice({
        type: "success",
        text: `Decoder "${decoder.name}" deleted.`,
      });
      refreshDecoders();
    } catch (error) {
      setSaveNotice({ type: "error", text: error.message });
    }
  }

  async function run(event) {
    event.preventDefault();
    setRunning(true);
    setNotice(null);
    setResult(null);

    try {
      setResult(await decoderRequest("/decode/run", {
        method: "POST",
        body: {
          code,
          payload: payload.trim(),
          format,
          deviceId: deviceId.trim() || undefined,
        },
      }));
    } catch (error) {
      setNotice({ type: "error", text: error.message });
    } finally {
      setRunning(false);
    }
  }

  // Filter messages in the live stream
  const filteredLiveMessages = liveStreamMessages.filter((msg) => {
    if (!liveStreamFilter.trim()) return true;
    const term = liveStreamFilter.toLowerCase();
    return (
      (msg.deviceId && msg.deviceId.toLowerCase().includes(term)) ||
      (msg.deviceName && msg.deviceName.toLowerCase().includes(term)) ||
      (msg.status && msg.status.toLowerCase().includes(term)) ||
      (msg.provider && msg.provider.toLowerCase().includes(term))
    );
  });

  return (
    <div className="page-section">
      {/* TTN SPLIT-SCREEN WORKSPACE */}
      <div className="ttn-workspace-grid">

        {/* LEFT COLUMN: DECODER CODING SCREEN */}
        <section className="ttn-pane-card">
          <div className="section-header" style={{ marginBottom: "14px" }}>
            <div>
              <h2 style={{ fontSize: "1.2rem", margin: 0 }}>Payload Decoder (Coding Screen)</h2>
              <p style={{ margin: "4px 0 0 0", fontSize: "0.82rem", color: "var(--text-muted, #94a3b8)" }}>
                Write custom code in JavaScript (TTN <code>decodeUplink</code> / ES6) or Python.
              </p>
            </div>

            <div style={{ display: "flex", gap: "6px", flexWrap: "wrap" }}>
              <button
                type="button"
                className="secondary-button small"
                onClick={() => {
                  setCode(TTN_TEMPLATE);
                  setPayload("09C4026C");
                  setFormat("hex");
                  setResult(null);
                }}
                title="TTN standard decodeUplink(input)"
              >
                📦 TTN decodeUplink
              </button>
              <button
                type="button"
                className="secondary-button small"
                onClick={() => {
                  setCode(JSON_DIRECT_TEMPLATE);
                  setPayload('{"deviceName": "Cold Storage Sensor 01", "deviceType": "Direct IP", "temperature": 24.5, "humidity": 62.0, "battery": 95}');
                  setFormat("json");
                  setResult(null);
                }}
              >
                ⚡ JSON Direct
              </button>
              <button
                type="button"
                className="secondary-button small"
                onClick={() => {
                  setCode(PYTHON_JSON_TEMPLATE);
                  setPayload('{"deviceName": "xiao-69s-MG24", "deviceType": "NTN", "latitude": 17.4354, "longitude": 78.3782, "rssi": -44}');
                  setFormat("json");
                  setResult(null);
                }}
              >
                🐍 Python JSON
              </button>
              <button
                type="button"
                className="secondary-button small"
                onClick={() => {
                  setCode(JSON_DYNAMIC_TEMPLATE);
                  setPayload('{"deviceName": "Smart Temp Sensor", "deviceType": "Direct IP", "data": {"temperature": 23.4, "humidity": 55.2}}');
                  setFormat("json");
                  setResult(null);
                }}
              >
                📋 Multi-Format
              </button>
              <button
                type="button"
                className="secondary-button small"
                onClick={() => {
                  setCode(JS_TEMPLATE);
                  setPayload("0A280258");
                  setFormat("hex");
                  setResult(null);
                }}
              >
                🔧 JS Binary
              </button>
            </div>
          </div>

          <form onSubmit={run}>
            <div className="form-group" style={{ marginBottom: "14px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "4px" }}>
                <label style={{ margin: 0, fontWeight: 600 }}>Decoder Script</label>
                <span style={{ fontSize: "0.75rem", color: "var(--text-muted, #94a3b8)" }}>
                  Supports <code>decodeUplink(input)</code>, <code>transform(input)</code>, or Python <code>decode(input)</code>
                </span>
              </div>
              <textarea
                className="code-editor"
                value={code}
                rows={16}
                spellCheck={false}
                onChange={(e) => setCode(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Tab") {
                    e.preventDefault();
                    const { selectionStart, selectionEnd } = e.target;
                    setCode(code.slice(0, selectionStart) + "  " + code.slice(selectionEnd));
                    requestAnimationFrame(() => {
                      e.target.selectionStart = e.target.selectionEnd = selectionStart + 2;
                    });
                  }
                }}
                required
              />
            </div>

            {/* TEST RUNNER INPUTS */}
            <div
              style={{
                background: "var(--surface-sunken, #080d1a)",
                padding: "14px",
                borderRadius: "8px",
                border: "1px solid var(--border-color, #1e293b)",
                marginBottom: "14px",
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
                <span style={{ fontWeight: 600, fontSize: "0.85rem" }}>🧪 Test Simulation Input</span>
                {loadHint && (
                  <span
                    className="pill pill-ok"
                    style={{ fontSize: "0.72rem", padding: "2px 8px", animation: "fadein 0.3s" }}
                  >
                    {loadHint}
                  </span>
                )}
              </div>

              <div className="form-grid" style={{ gridTemplateColumns: "2fr 1fr 1fr", gap: "10px", marginBottom: "10px" }}>
                <div className="form-group" style={{ margin: 0 }}>
                  <label style={{ fontSize: "0.75rem" }}>Payload (Hex, JSON, Base64)</label>
                  <input
                    value={payload}
                    placeholder="e.g. 0A280258 or JSON"
                    onChange={(e) => setPayload(e.target.value)}
                    required
                  />
                </div>

                <div className="form-group" style={{ margin: 0 }}>
                  <label style={{ fontSize: "0.75rem" }}>Payload Format</label>
                  <select value={format} onChange={(e) => setFormat(e.target.value)}>
                    <option value="auto">Auto-detect</option>
                    <option value="hex">Hexadecimal</option>
                    <option value="json">JSON</option>
                    <option value="base64">Base64</option>
                    <option value="binary">Binary</option>
                    <option value="text">UTF-8 Text</option>
                  </select>
                </div>

                <div className="form-group" style={{ margin: 0 }}>
                  <label style={{ fontSize: "0.75rem" }}>Device ID (Context)</label>
                  <input
                    value={deviceId}
                    placeholder="e.g. xiao-69s-MG24"
                    onChange={(e) => setDeviceId(e.target.value)}
                  />
                </div>
              </div>

              <div style={{ display: "flex", gap: "10px", alignItems: "center" }}>
                <button className="primary-button" type="submit" disabled={running}>
                  {running ? "Testing Decoder…" : "⚡ Test Decoder"}
                </button>
                <span style={{ fontSize: "0.75rem", color: "var(--text-muted, #94a3b8)" }}>
                  Dry run sandbox: runs isolated in V8/Python without mutating database
                </span>
              </div>
            </div>

            <Notice notice={notice} />
          </form>

          {/* TEST RESULTS */}
          {result && <RunResult result={result} />}
        </section>

        {/* RIGHT COLUMN: LIVE DATA SCREEN (INBOUND UPLINK STREAM) */}
        <section className="ttn-pane-card">
          <div className="section-header" style={{ marginBottom: "14px" }}>
            <div>
              <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <span className="ttn-pulse-dot" />
                <h2 style={{ fontSize: "1.2rem", margin: 0 }}>Live Data (Inbound Stream)</h2>
                <span
                  className="pill pill-ok"
                  style={{ fontSize: "0.72rem", padding: "2px 6px", fontWeight: 700 }}
                >
                  LIVE
                </span>
              </div>
              <p style={{ margin: "4px 0 0 0", fontSize: "0.82rem", color: "var(--text-muted, #94a3b8)" }}>
                Incoming packets from Hubble Network, MQTT, UDP, and Webhooks.
              </p>
            </div>

            <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
              <label
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "6px",
                  fontSize: "0.78rem",
                  cursor: "pointer",
                  color: "var(--text-muted, #94a3b8)",
                  userSelect: "none",
                }}
              >
                <input
                  type="checkbox"
                  checked={autoRefreshLive}
                  onChange={(e) => setAutoRefreshLive(e.target.checked)}
                />
                Auto-poll (3s)
              </label>

              <button
                type="button"
                className="secondary-button small"
                onClick={refreshLiveStream}
                disabled={liveStreamLoading}
              >
                {liveStreamLoading ? "Refreshing…" : "↻ Refresh"}
              </button>
            </div>
          </div>

          {/* STREAM CONTROLS & FILTER */}
          <div style={{ display: "flex", gap: "8px", marginBottom: "12px", alignItems: "center" }}>
            <input
              type="text"
              placeholder="🔍 Filter by device ID, name, or provider..."
              value={liveStreamFilter}
              onChange={(e) => setLiveStreamFilter(e.target.value)}
              style={{ fontSize: "0.8rem", padding: "6px 10px" }}
            />
            {liveStreamFilter && (
              <button
                type="button"
                className="secondary-button small"
                onClick={() => setLiveStreamFilter("")}
              >
                Clear
              </button>
            )}
            <span
              style={{
                fontSize: "0.75rem",
                color: "var(--text-muted, #94a3b8)",
                whiteSpace: "nowrap",
              }}
            >
              {filteredLiveMessages.length} uplinks
            </span>
          </div>

          {/* REAL-TIME PACKET CARDS */}
          <div
            style={{
              maxHeight: "680px",
              overflowY: "auto",
              paddingRight: "4px",
              scrollbarWidth: "thin",
            }}
          >
            {filteredLiveMessages.length === 0 ? (
              <div
                style={{
                  textAlign: "center",
                  padding: "40px 20px",
                  background: "var(--surface-sunken, #080d1a)",
                  borderRadius: "8px",
                  border: "1px dashed var(--border-color, #1e293b)",
                  color: "var(--text-muted, #94a3b8)",
                }}
              >
                <div style={{ fontSize: "1.8rem", marginBottom: "8px" }}>📡</div>
                <strong style={{ display: "block", color: "var(--text)", marginBottom: "4px" }}>
                  Waiting for incoming uplinks…
                </strong>
                <p style={{ margin: 0, fontSize: "0.82rem" }}>
                  When your device (e.g. <code>xiao-69s-MG24</code>) transmits through Hubble Network or webhooks,
                  its live packets, raw payload, and decoded data appear here automatically.
                </p>
              </div>
            ) : (
              filteredLiveMessages.map((msg) => {
                const isRouted = msg.status === "ROUTED";
                const hasDecoded = msg.decoded && typeof msg.decoded === "object" && Object.keys(msg.decoded).length > 0;
                const locLat = msg.decoded?.latitude ?? msg.details?.latitude;
                const locLon = msg.decoded?.longitude ?? msg.details?.longitude;
                const alt = msg.decoded?.altitude ?? msg.details?.altitude;
                const rssi = msg.decoded?.rssi ?? msg.details?.rssi;
                const counter = msg.decoded?.counter ?? msg.details?.counter ?? msg.details?.sequence_number;

                return (
                  <div key={`${msg.source}-${msg.id}`} className="ttn-live-card">
                    {/* CARD HEADER */}
                    <div className="ttn-live-card-header">
                      <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                        <span className={`pill ${isRouted ? "pill-ok" : "pill-off"}`} style={{ fontSize: "0.72rem", padding: "1px 7px" }}>
                          {isRouted ? "ROUTED" : (msg.status || "DECODE_FAILED")}
                        </span>
                        <strong style={{ fontSize: "0.85rem", color: "var(--text, #f8fafc)" }}>
                          {msg.deviceName || msg.deviceId}
                        </strong>
                        {msg.deviceName && msg.deviceName !== msg.deviceId && (
                          <span style={{ fontSize: "0.75rem", color: "var(--text-muted, #94a3b8)" }}>
                            ({msg.deviceId})
                          </span>
                        )}
                      </div>

                      <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                        <span
                          className="ttn-mini-badge"
                          style={{
                            background: "rgba(59, 130, 246, 0.15)",
                            color: "#60a5fa",
                            borderColor: "rgba(59, 130, 246, 0.3)",
                          }}
                        >
                          🛰️ {msg.provider || "Hubble Network"}
                        </span>
                        <span style={{ fontSize: "0.72rem", color: "var(--text-muted, #94a3b8)" }}>
                          {formatRelativeTime(msg.receivedAt)}
                        </span>
                      </div>
                    </div>

                    {/* METADATA BADGES */}
                    <div className="ttn-badge-row">
                      {rssi !== undefined && (
                        <span className="ttn-mini-badge">
                          📶 RSSI: {rssi} dBm
                        </span>
                      )}
                      {counter !== undefined && (
                        <span className="ttn-mini-badge">
                          # Count: {counter}
                        </span>
                      )}
                      {locLat !== undefined && locLon !== undefined && (
                        <span className="ttn-mini-badge" style={{ color: "#34d399", borderColor: "rgba(52, 211, 153, 0.3)" }}>
                          📍 {Number(locLat).toFixed(4)}, {Number(locLon).toFixed(4)} {alt ? `(${Math.round(alt)}m)` : ""}
                        </span>
                      )}
                      <span className="ttn-mini-badge">
                        {msg.connectionType || "NTN"} · {msg.transport || "webhook"}
                      </span>
                    </div>

                    {/* MULTI-FORMAT RAW PAYLOAD DISPLAY (JSON / TEXT / HEX / BASE64 / BYTES) */}
                    <InboundPayloadView hex={msg.rawPayloadHex} />

                    {/* DECODED OUTPUT JSON */}
                    <div style={{ marginTop: "8px" }}>
                      <span style={{ fontSize: "0.72rem", color: "#38bdf8", fontWeight: 600, display: "block", marginBottom: "2px" }}>
                        Decoded Output JSON:
                      </span>
                      {hasDecoded ? (
                        <pre className="ttn-json-block">
                          {JSON.stringify(msg.decoded, null, 2)}
                        </pre>
                      ) : (
                        <div
                          style={{
                            fontSize: "0.75rem",
                            color: "var(--text-muted, #94a3b8)",
                            background: "rgba(0,0,0,0.2)",
                            padding: "6px 8px",
                            borderRadius: "4px",
                            fontStyle: "italic",
                          }}
                        >
                          {msg.error || "No decoded fields. Load into Decoder above to write decoder."}
                        </div>
                      )}
                    </div>

                    {/* ACTIONS */}
                    <div style={{ display: "flex", gap: "8px", marginTop: "10px", justifyContent: "flex-end" }}>
                      <button
                        type="button"
                        className="primary-button small"
                        style={{ padding: "4px 10px", fontSize: "0.75rem" }}
                        onClick={() => loadIntoDecoder(msg)}
                        title="Load this packet's payload and device ID into the code editor above"
                      >
                        ⚡ Load into Decoder
                      </button>
                      <button
                        type="button"
                        className="secondary-button small"
                        style={{ padding: "4px 10px", fontSize: "0.75rem" }}
                        onClick={() => setInspectMessage(msg.details || msg)}
                      >
                        🔍 Inspect
                      </button>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </section>
      </div>

      {/* INSPECT MODAL */}
      {inspectMessage && (
        <MessageModal
          message={inspectMessage}
          onClose={() => setInspectMessage(null)}
        />
      )}

      {/* SAVE AS LIVE DECODER CONFIGURATION */}
      <section className="card" style={{ marginTop: "24px" }}>
        <div className="schema-title">
          <div>
            <h3>Live Decoder Version Registry</h3>
            <p>
              Save the code written in the left editor as a permanent live decoder version. It will automatically decode
              incoming packets (HTTPS, MQTT, TCP/IP, UDP, Webhook) matching the configured criteria.
            </p>
          </div>
        </div>

        {isAdmin ? (
          <form onSubmit={save}>
            <div className="form-grid">
              <div className="form-group">
                <label>Decoder Name</label>
                <input value={name} onChange={(e) => setName(e.target.value)} required />
              </div>

              {MATCH_FIELDS.map((field) => (
                <div className="form-group" key={field.key}>
                  <label>{field.label}</label>
                  {field.type === "select" ? (
                    <>
                      <select
                        value={
                          field.options.some((opt) => opt.value === (match[field.key] || ""))
                            ? (match[field.key] || "")
                            : (match[field.key] ? "custom" : "")
                        }
                        onChange={(e) => {
                          const val = e.target.value;
                          if (val === "custom") {
                            setMatch({ ...match, [field.key]: match[field.key] && !field.options.some((o) => o.value === match[field.key]) ? match[field.key] : "" });
                          } else {
                            setMatch({ ...match, [field.key]: val });
                          }
                        }}
                      >
                        {field.options.map((opt) => (
                          <option key={opt.value} value={opt.value}>
                            {opt.label}
                          </option>
                        ))}
                        {match[field.key] && !field.options.some((opt) => opt.value === match[field.key]) && match[field.key] !== "custom" && (
                          <option value={match[field.key]}>{match[field.key]} (Custom)</option>
                        )}
                      </select>
                      {(match[field.key] === "custom" || (match[field.key] && !field.options.some((opt) => opt.value === match[field.key]))) && (
                        <input
                          style={{ marginTop: "6px" }}
                          placeholder={`Enter custom ${field.label.toLowerCase()}...`}
                          value={match[field.key] === "custom" ? "" : match[field.key]}
                          onChange={(e) => setMatch({ ...match, [field.key]: e.target.value })}
                        />
                      )}
                    </>
                  ) : (
                    <input
                      value={match[field.key]}
                      placeholder={field.placeholder}
                      onChange={(e) => setMatch({ ...match, [field.key]: e.target.value })}
                    />
                  )}
                </div>
              ))}
            </div>

            <Notice notice={saveNotice} />

            <button className="primary-button" type="submit">
              Save as Live Decoder
            </button>
          </form>
        ) : (
          <Restricted>
            Only admins can save live decoders. You can still test code in the editor above.
          </Restricted>
        )}

        {liveDecoders.length > 0 && (
          <div className="table-container spaced">
            <table>
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Version</th>
                  <th>Match</th>
                  <th>Updated</th>
                  {isAdmin && <th>Actions</th>}
                </tr>
              </thead>
              <tbody>
                {liveDecoders.map((decoder) => (
                  <tr key={decoder.id}>
                    <td><strong>{decoder.name}</strong></td>
                    <td>{String(decoder.version || "1").startsWith("v") ? decoder.version : `v${decoder.version || 1}`}</td>
                    <td className="small-text">{matchText(decoder.match)}</td>
                    <td>{formatDate(decoder.updatedAt || decoder.updated_at || decoder.createdAt || decoder.created_at)}</td>
                    {isAdmin && (
                      <td>
                        <div style={{ display: "flex", gap: "6px" }}>
                          <button
                            type="button"
                            className="secondary-button small"
                            onClick={() => load(decoder)}
                            title="Load into editor"
                          >
                            Load
                          </button>
                          <button
                            type="button"
                            className="danger-button small"
                            onClick={() => deleteLiveDecoder(decoder)}
                            title="Delete this decoder"
                          >
                            Delete
                          </button>
                        </div>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}


function RunResult({ result }) {
  if (!result || typeof result !== "object") return null;

  const isSuccess = Boolean(result.success);
  const message = result.message || (isSuccess ? result : null);
  const failure = result.failure || (!isSuccess ? result : null);

  const payloadHex = String(
    result.payloadHex || message?.payloadHex || failure?.payloadHex || ""
  ).toUpperCase();

  const rawPayload =
    result.rawPayload ||
    result.payload ||
    message?.rawPayload ||
    message?.payload ||
    payloadHex;

  const detectedFormat =
    result.detectedFormat ||
    result.format ||
    message?.detectedFormat ||
    message?.format ||
    "hex";

  const logs =
    result.logs ||
    message?.decoded?.logs ||
    message?.logs ||
    failure?.logs ||
    [];

  const error =
    result.error ||
    failure?.error ||
    message?.error ||
    "Decoding execution failed";

  // Data can come from result.data or message.decoded.data or output
  const rawData =
    result.data ||
    message?.decoded?.data ||
    (typeof result.output === "object" && !Array.isArray(result.output) ? result.output : null) ||
    {};

  const units = result.units || message?.decoded?.units || {};
  const device = result.device || message?.device;
  const isProvisioned = Boolean(result.deviceProvisioned || device);
  const messageId = result.messageId || message?.messageId || failure?.messageId;

  return (
    <div className="spaced">
      <div style={{ display: "flex", alignItems: "center", gap: "10px", flexWrap: "wrap", marginBottom: "8px" }}>
        <h3 style={{ margin: 0 }}>Result</h3>
        <span className={`pill ${isSuccess ? "pill-ok" : "pill-off"}`}>
          {isSuccess ? "Decoded" : "Failed"}
        </span>
        <span
          className="pill"
          style={{
            background: "rgba(59, 130, 246, 0.15)",
            color: "#60a5fa",
            border: "1px solid rgba(59, 130, 246, 0.3)",
            fontWeight: 600,
            fontSize: "0.75rem",
          }}
        >
          Format: {String(result.detectedFormat || result.format || message?.detectedFormat || "binary").toUpperCase()}
        </span>
        <span
          className="pill"
          style={{
            background: "rgba(168, 85, 247, 0.12)",
            color: "#a855f7",
            border: "1px solid rgba(168, 85, 247, 0.25)",
            fontWeight: 600,
            fontSize: "0.75rem",
          }}
        >
          🧪 Test Mode (Isolated · No DB / MQTT / Webhook / REST emission)
        </span>
      </div>

      {result.detectedMetadata?.name && (
        <div
          style={{
            padding: "10px 14px",
            marginBottom: "14px",
            background: "rgba(59, 130, 246, 0.08)",
            border: "1px solid rgba(59, 130, 246, 0.2)",
            borderRadius: "8px",
            fontSize: "0.85rem",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
            <span style={{ fontSize: "1rem" }}>🔍</span>
            <strong>Detected Device Metadata (Preview):</strong>
            <span>
              Device: <strong>{result.detectedMetadata.name}</strong> ({result.detectedMetadata.device_type || "NTN"})
            </span>
            <span style={{ color: "var(--text-secondary, #64748b)", marginLeft: "auto", fontSize: "0.8rem" }}>
              (Dry-run: device was not saved to database)
            </span>
          </div>
        </div>
      )}

      {isProvisioned && device && !result.isTest && (
        <div
          style={{
            padding: "12px 16px",
            marginBottom: "14px",
            background: "rgba(16, 185, 129, 0.1)",
            border: "1px solid rgba(16, 185, 129, 0.3)",
            borderRadius: "8px",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "4px" }}>
            <span style={{ fontSize: "1.1rem" }}>⚡</span>
            <strong>Automated Device Provisioning Triggered</strong>
            <span className="pill pill-type type-ntn" style={{ fontSize: "0.75rem", padding: "2px 8px" }}>
              {device.device_type || device.deviceType || "NTN"}
            </span>
          </div>
          <p style={{ margin: "4px 0 0 0", fontSize: "0.85rem", color: "var(--text-secondary, #64748b)" }}>
            Device <strong>{device.name || device.deviceId || device.dev_id}</strong> (ID: <code>{device.device_id || device.deviceId}</code>) is registered and linked to this decoder.
          </p>
        </div>
      )}

      {(payloadHex || result.output) && (
        <div
          style={{
            marginBottom: "14px",
            padding: "12px 14px",
            background: "var(--surface-2, #f8fafc)",
            borderRadius: "8px",
            border: "1px solid var(--border, #e2e8f0)",
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "6px" }}>
            <span style={{ fontSize: "0.85rem", fontWeight: "600", color: "var(--text, #0f172a)" }}>
              📡 Raw Payload
            </span>
          </div>
          <RawPayloadBlock message={{ payloadHex, rawPayload, payloadFormat: detectedFormat }} />
        </div>
      )}

      {isSuccess ? (
        <div className="table-container">
          <table>
            <thead>
              <tr>
                <th>Field</th>
                <th>Decoded Value</th>
                <th>Unit</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(rawData).length > 0 ? (
                Object.entries(rawData).map(([field, value]) => (
                  <tr key={field}>
                    <td><strong>{field}</strong></td>
                    <td>{formatValue(value)}</td>
                    <td>{units[field] || "—"}</td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={3} className="muted">Decoder returned an empty data object.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      ) : (
        <Notice notice={{ type: "error", text: error }} />
      )}

      {logs?.length > 0 && (
        <div style={{ marginTop: "12px" }}>
          <label>Console Logs</label>
          <pre className="code-view">{logs.join("\n")}</pre>
        </div>
      )}

      {result.output && (
        <details className="raw-json" style={{ marginTop: "12px" }}>
          <summary>Raw JSON Output</summary>
          <pre className="code-view">{JSON.stringify(result.output, null, 2)}</pre>
        </details>
      )}

      {messageId && (
        <p className="muted small-text" style={{ marginTop: "10px" }}>
          Message ID: <code>{messageId}</code>
        </p>
      )}
    </div>
  );
}


// -------------------------
// Live Data page: stored results
// -------------------------

export function DecoderMessages({ api, canRead, deviceId = "", onClearDevice }) {
  const [messages, setMessages] = useState([]);
  const [status, setStatus] = useState("");
  const [filterDevice, setFilterDevice] = useState(deviceId || "");
  const [notice, setNotice] = useState(null);
  const [opened, setOpened] = useState(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [totalCount, setTotalCount] = useState(0);
  const [totalPages, setTotalPages] = useState(1);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setFilterDevice(deviceId || "");
    setPage(1);
  }, [deviceId]);

  async function refresh(nextStatus = status, nextDev = filterDevice, nextPage = page, nextLimit = pageSize) {
    try {
      setLoading(true);
      const query = { limit: nextLimit, page: nextPage };
      if (nextStatus) query.status = nextStatus;
      if (nextDev && nextDev.trim()) query.device_id = nextDev.trim();

      const res = await api.get("/decoder-messages/", query);
      const items = Array.isArray(res) ? res : (res?.items || []);
      const total = typeof res?.total === "number" ? res.total : items.length;
      const pages = typeof res?.pages === "number" ? res.pages : Math.max(1, Math.ceil(total / nextLimit));

      setMessages(items);
      setTotalCount(total);
      setTotalPages(pages);
      setNotice(null);
    } catch (error) {
      setNotice({ type: "error", text: error.message });
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (canRead) {
      refresh(status, deviceId, page, pageSize);
    }
  }, [api, canRead, deviceId, page, pageSize]);

  return (
    <section className="card">
      <div className="section-header">
        <div>
          <h2>
            Decoder Runtime Messages
            {totalCount > 0 && (
              <span
                className="pill"
                style={{
                  marginLeft: "10px",
                  fontSize: "0.78rem",
                  fontWeight: 500,
                  verticalAlign: "middle",
                }}
              >
                {totalCount.toLocaleString()} total
              </span>
            )}
          </h2>
          <p>
            {filterDevice
              ? `Decoded messages for device ${filterDevice}. Newest first.`
              : "Decoded by the decoder runtime, from devices and from Decoder page runs. Newest first. Select a message to see it in full."}
          </p>
        </div>

        {canRead && (
          <div className="header-actions" style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
            {filterDevice ? (
              <span className="pill pill-primary" style={{ display: "inline-flex", alignItems: "center", gap: "6px", fontSize: "0.82rem", padding: "4px 10px" }}>
                <span>Device: <strong>{filterDevice}</strong></span>
                <button
                  type="button"
                  style={{ background: "transparent", border: "none", color: "inherit", cursor: "pointer", padding: "0 2px", fontWeight: "bold", fontSize: "1rem", lineHeight: 1 }}
                  onClick={() => {
                    setFilterDevice("");
                    setPage(1);
                    refresh(status, "", 1, pageSize);
                    if (onClearDevice) onClearDevice();
                  }}
                  title="Clear device filter"
                >
                  ×
                </button>
              </span>
            ) : (
              <input
                type="text"
                placeholder="Filter by device ID..."
                value={filterDevice}
                onChange={(e) => setFilterDevice(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    setPage(1);
                    refresh(status, filterDevice, 1, pageSize);
                  }
                }}
                style={{ maxWidth: "160px", padding: "4px 8px", fontSize: "0.85rem" }}
              />
            )}

            <select
              value={status}
              onChange={(e) => {
                setStatus(e.target.value);
                setPage(1);
                refresh(e.target.value, filterDevice, 1, pageSize);
              }}
            >
              <option value="">All Status</option>
              <option value="decoded">Decoded</option>
              <option value="failed">Failed</option>
            </select>

            <button
              className="secondary-button"
              disabled={loading}
              onClick={() => refresh(status, filterDevice, page, pageSize)}
            >
              {loading ? "Loading..." : "Refresh"}
            </button>
          </div>
        )}
      </div>

      <Notice notice={notice} />

      {!canRead ? (
        <Restricted>
          Reading decoded messages needs the <strong>Read Application Traffic</strong> function.
        </Restricted>
      ) : messages.length === 0 ? (
        <div className="empty-state">
          {filterDevice
            ? `No decoder messages recorded for device "${filterDevice}".`
            : "No decoded messages yet. Run a decoder on the Decoders page."}
        </div>
      ) : (
        <div className="table-container">
          <table>
            <thead>
              <tr>
                <th>Received</th>
                <th>Device</th>
                <th>Source</th>
                <th>Status</th>
                <th>Decoder</th>
                <th>Payload</th>
                <th>Values</th>
              </tr>
            </thead>
            <tbody>
              {messages.map((message, idx) => (
                <tr
                  key={message.messageId || message.message_id || `msg-${idx}`}
                  className="clickable-row"
                  tabIndex={0}
                  onClick={() => setOpened(message)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      setOpened(message);
                    }
                  }}
                >
                  <td>{formatUtcDate(messageTimestamp(message))}</td>
                  <td>{message.deviceId || message.device_id || <span className="muted">—</span>}</td>
                  <td><span className="tag">{message.transport || "udp"}</span></td>
                  <td>
                    <span className={`pill ${message.status === "decoded" ? "pill-ok" : "pill-off"}`}>
                      {message.status === "decoded" ? "Decoded" : "Failed"}
                    </span>
                  </td>
                  <td className="small-text">
                    {decoderLabel(message) !== "—" ? (
                      <span style={{
                        display: "inline-flex",
                        alignItems: "center",
                        gap: "4px",
                        padding: "2px 8px",
                        borderRadius: "4px",
                        backgroundColor: "rgba(99, 102, 241, 0.12)",
                        color: "#818cf8",
                        fontWeight: 500,
                        fontSize: "0.82rem"
                      }}>
                        {decoderLabel(message)}
                      </span>
                    ) : (
                      <span className="muted">—</span>
                    )}
                  </td>
                  <td className="small-text"><RawPayloadCell message={message} /></td>
                  <td className="small-text values-cell">
                    {message.status === "decoded"
                      ? formatValues(message.decoded?.data || message.data || {})
                      : <span className="error-text">{message.error}</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {messages.length > 0 && (
            <Pagination
              page={page}
              totalPages={totalPages}
              totalItems={totalCount}
              pageSize={pageSize}
              onPageChange={(p) => setPage(p)}
              onPageSizeChange={(sz) => {
                setPageSize(sz);
                setPage(1);
              }}
              pageSizeOptions={[10, 25, 50, 100]}
              loading={loading}
              itemLabel="messages"
            />
          )}
        </div>
      )}

      {opened && <MessageDetail message={opened} onClose={() => setOpened(null)} />}
    </section>
  );
}


// Popup with one stored message: values, payload, routing and the raw record
function MessageDetail({ message, onClose }) {
  const decoded = message.status === "decoded";
  const data = message.decoded?.data || {};
  const units = message.decoded?.units || {};
  const metadata = message.decoded?.metadata || {};
  const logs = message.decoded?.logs || message.logs || [];
  const hex = (message.payloadHex || "").toUpperCase();

  const details = [
    ["Message ID", message.messageId || message.message_id],
    ["Received", formatUtcDate(messageTimestamp(message))],
    ["Device", message.deviceId || message.device_id || "—"],
    ["Source", message.transport],
    ["Decoder", decoderLabel(message)],
    ["Decoder ID", message.decoder?.id || metadata.decoderId],
    ["Protocol", metadata.protocolId || message.decoder?.protocol || message.protocol || message.transport],
    ["Provider", metadata.providerId || message.provider],
    ["Message type", metadata.messageType || message.messageType],
  ].filter(([, value]) => value !== undefined && value !== null && value !== "");

  return (
    <Modal
      title={decoded ? "Decoded message" : "Failed message"}
      subtitle={`${message.deviceId || message.device_id || "No device"} · ${formatUtcDate(messageTimestamp(message))}`}
      onClose={onClose}
      wide
      footer={<button type="button" className="secondary-button" onClick={onClose}>Close</button>}
    >
      <div className="detail-status">
        <span className={`pill ${decoded ? "pill-ok" : "pill-off"}`}>
          {decoded ? "Decoded" : "Failed"}
        </span>
      </div>

      <h3 className="detail-heading">Payload</h3>
      <RawPayloadBlock message={message} />

      <h3 className="detail-heading">{decoded ? "Values" : "Error"}</h3>
      {decoded ? (
        Object.keys(data).length === 0 ? (
          <p className="muted">The decoder returned no values.</p>
        ) : (
          <div className="value-grid">
            {Object.entries(data).map(([field, value]) => (
              <div className="value-tile" key={field}>
                <span>{field}</span>
                <strong>
                  {formatValue(value)}
                  {units[field] && <small> {units[field]}</small>}
                </strong>
              </div>
            ))}
          </div>
        )
      ) : (
        <Notice notice={{ type: "error", text: message.error }} />
      )}

      <h3 className="detail-heading">Details</h3>
      <dl className="detail-list">
        {details.map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>

      {logs.length > 0 && (
        <>
          <h3 className="detail-heading">Console</h3>
          <pre className="code-view">{logs.join("\n")}</pre>
        </>
      )}

      <details className="raw-json">
        <summary>Raw message (JSON)</summary>
        <pre className="code-view">{JSON.stringify(message, null, 2)}</pre>
      </details>
    </Modal>
  );
}


export function decoderLabel(message) {
  if (!message) return "—";

  if (message.transport === "editor") {
    return "Editor run";
  }

  // 1. Direct decoder object on message (e.g. { id, name, version })
  const dec = message.decoder;
  if (dec) {
    if (typeof dec === "object") {
      const name = dec.name || dec.title || dec.id;
      const ver = dec.version;
      if (name && ver) {
        const formattedVer = String(ver).startsWith("v") ? ver : `v${ver}`;
        return `${name} ${formattedVer}`;
      }
      if (name) return name;
    } else if (typeof dec === "string" && dec.trim()) {
      return dec.trim();
    }
  }

  // 2. Metadata inside message.decoded (legacy decoder server format)
  const metadata = message.decoded?.metadata;
  if (metadata) {
    const name = metadata.decoderName || metadata.decoder_name || metadata.decoderId;
    const ver = metadata.decoderVersion || metadata.decoder_version;
    if (name && ver) {
      const formattedVer = String(ver).startsWith("v") ? ver : `v${ver}`;
      return `${name} ${formattedVer}`;
    }
    if (name) return name;
  }

  // 3. Top-level direct properties
  const topName = message.decoderName || message.decoder_name || message.decodeSchemaName || message.decode_schema_name;
  const topVer = message.decoderVersion || message.decoder_version || message.schema_version;
  if (topName) {
    if (topVer) {
      const formattedVer = String(topVer).startsWith("v") ? topVer : `v${topVer}`;
      return `${topName} ${formattedVer}`;
    }
    return topName;
  }

  // 4. Schema ID fallback if available
  if (message.decodeSchemaId || message.decode_schema_id) {
    return `Decoder #${message.decodeSchemaId || message.decode_schema_id}`;
  }

  return "—";
}
