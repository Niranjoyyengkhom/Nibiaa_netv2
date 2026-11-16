import { useEffect, useState, useMemo } from "react";

import { formatDate } from "./api";
import { Modal, Notice, PageHeader, Restricted, RawPayloadCell, RawPayloadBlock, RawPayloadBadge, Pagination } from "./components";
import { DecoderMessages } from "./decoderRuntime";


const STATUSES = [
  "ROUTED",
  "UNKNOWN_PROVIDER",
  "NO_ACTIVE_SCHEMA",
  "DECODE_FAILED",
  "UNKNOWN_DEVICE",
];


function hexToAscii(hex) {
  if (!hex) return "—";
  const clean = hex.replace(/\s+/g, "");
  let str = "";
  for (let i = 0; i < clean.length; i += 2) {
    const code = parseInt(clean.substring(i, i + 2), 16);
    str += code >= 32 && code <= 126 ? String.fromCharCode(code) : "·";
  }
  return str;
}


function formatPayloadForIngest(input) {
  if (typeof input !== "string") {
    return input;
  }
  return input.trim();
}

function hexToBase64(hex) {
  if (typeof hex !== "string") return hex;
  const clean = hex.trim();

  // If JSON or binary bitstring, return as-is
  if ((clean.startsWith("{") && clean.endsWith("}")) || (clean.startsWith("[") && clean.endsWith("]"))) {
    return clean;
  }
  const bits = clean.replace(/\s+/g, "");
  if (/^[01]+$/.test(bits) && bits.length >= 8 && bits.length % 8 === 0) {
    return clean;
  }

  const cleanHex = clean.replace(/\s+/g, "").replace(/^0x/i, "");
  if (/^([0-9a-fA-F]{2})+$/.test(cleanHex)) {
    return cleanHex;
  }

  return clean;
}


function formatValues(values) {
  return Object.entries(values || {})
    .map(([key, value]) => `${key}: ${value}`)
    .join(" · ");
}


function Telemetry({ api, currentUser, params }) {
  const permissions = currentUser.permissions;
  const capabilities = currentUser.capabilities;
  const isAdmin = currentUser.role === "admin";

  const canRead = permissions.read_application_traffic;

  const [records, setRecords] = useState([]);
  const [applications, setApplications] = useState([]);
  const [tenants, setTenants] = useState([]);
  const [profiles, setProfiles] = useState([]);
  const [usage, setUsage] = useState(null);
  const [trafficPage, setTrafficPage] = useState(1);
  const [trafficPageSize, setTrafficPageSize] = useState(25);

  const paginatedRecords = useMemo(() => {
    const start = (trafficPage - 1) * trafficPageSize;
    return records.slice(start, start + trafficPageSize);
  }, [records, trafficPage, trafficPageSize]);

  const [filters, setFilters] = useState({
    tenant_id: "",
    application_id: params?.applicationId ? String(params.applicationId) : "",
    device_id: params?.deviceId || "",
    connection_type: "",
    provider: "",
    limit: 100,
  });

  const [notice, setNotice] = useState(null);

  useEffect(() => {
    if (params?.deviceId !== undefined || params?.applicationId !== undefined) {
      const nextFilters = {
        ...filters,
        device_id: params?.deviceId || "",
        application_id: params?.applicationId ? String(params.applicationId) : filters.application_id,
      };
      setFilters(nextFilters);
      fetchTelemetry(nextFilters);
    }
  }, [params?.deviceId, params?.applicationId]);

  useEffect(() => {
    api.get("/connectivity-profiles/").then(setProfiles).catch(() => setProfiles([]));
    api.get("/applications/").then(setApplications).catch(() => setApplications([]));

    if (isAdmin) {
      api.get("/tenants/").then(setTenants).catch(() => setTenants([]));
    }

    fetchTelemetry();
    fetchUsage();
  }, [api]);

  async function fetchTelemetry(activeFilters = filters) {
    if (!canRead) {
      return;
    }

    setNotice(null);

    try {
      setRecords(await api.get("/telemetry/", activeFilters));
    } catch (error) {
      setNotice({ type: "error", text: error.message });
    }
  }

  async function fetchUsage(tenantId = filters.tenant_id) {
    if (!capabilities.view_usage) {
      return;
    }

    try {
      setUsage(await api.get("/usage/", { tenant_id: tenantId }));
    } catch {
      setUsage(null);
    }
  }

  function applyFilters(event) {
    event.preventDefault();
    fetchTelemetry();
    fetchUsage();
  }

  function clearFilters() {
    const cleared = {
      tenant_id: "",
      application_id: "",
      device_id: "",
      connection_type: "",
      provider: "",
      limit: 100,
    };

    setFilters(cleared);
    fetchTelemetry(cleared);
    fetchUsage("");
  }

  function applicationName(id) {
    return applications.find((app) => app.id === id)?.name || `Application ${id}`;
  }

  function providerName(code) {
    if (!code) {
      return "Unknown";
    }

    return profiles.find((profile) => profile.code === code)?.name || code;
  }

  return (
    <div className="page">

      <PageHeader
        title={filters.device_id ? `Live Data — ${filters.device_id}` : "Live Data"}
        description={
          filters.device_id
            ? `Displaying real-time telemetry and decoder runtime messages exclusively for device ${filters.device_id}.`
            : "Uplinks received from devices, decoded and routed to their organization."
        }
      />

      {filters.device_id && (
        <div style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "12px 18px",
          marginBottom: "16px",
          background: "rgba(59, 130, 246, 0.12)",
          border: "1px solid rgba(59, 130, 246, 0.3)",
          borderRadius: "8px",
          color: "#93c5fd"
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
            <span style={{ fontSize: "1.2rem" }}>🎯</span>
            <span>
              Device Filter Active: <strong>{filters.device_id}</strong>
            </span>
          </div>
          <button
            type="button"
            className="secondary-button small"
            onClick={clearFilters}
          >
            Show All Devices
          </button>
        </div>
      )}

      {/* USAGE */}

      {usage && (
        <section className="stat-grid">
          <div className="stat-card">
            <span className="label">Devices</span>
            <strong>{usage.devices}</strong>
          </div>
          <div className="stat-card">
            <span className="label">Applications</span>
            <strong>{usage.applications}</strong>
          </div>
          <div className="stat-card">
            <span className="label">Uplink messages</span>
            <strong>{usage.uplink_messages}</strong>
          </div>
          <div className="stat-card">
            <span className="label">Downlink commands</span>
            <strong>
              {usage.downlink_commands}
              <small> ({usage.downlink_commands_acknowledged} acknowledged)</small>
            </strong>
          </div>
          <div className="stat-card wide">
            <span className="label">Uplinks by provider</span>
            <div className="tag-list">
              {Object.keys(usage.uplink_messages_by_provider).length === 0
                ? <span className="muted">None yet</span>
                : Object.entries(usage.uplink_messages_by_provider).map(([code, count]) => (
                  <span className="tag" key={code}>{providerName(code === "unknown" ? null : code)}: {count}</span>
                ))}
            </div>
          </div>
        </section>
      )}

      {/* DECODER RUNTIME (decoder server, stored in the platform database) */}

      <DecoderMessages
        api={api}
        canRead={canRead}
        deviceId={filters.device_id}
        onClearDevice={() => {
          const updated = { ...filters, device_id: "" };
          setFilters(updated);
          fetchTelemetry(updated);
        }}
      />

      {/* TRAFFIC */}

      <section className="card">
        <div className="section-header">
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: "10px", flexWrap: "wrap" }}>
              <h2>Application Traffic</h2>
              <span className="pill" style={{ background: "rgba(16, 185, 129, 0.15)", color: "#10b981", border: "1px solid rgba(16, 185, 129, 0.3)", fontSize: "0.75rem", padding: "2px 8px", borderRadius: "12px" }}>
                ⏱ 24h Auto-Retention Active
              </span>
            </div>
            <p>Newest first. Telemetry older than 24 hours is automatically pruned.</p>
          </div>
          {canRead && (
            <button className="secondary-button" onClick={() => fetchTelemetry()}>
              Refresh
            </button>
          )}
        </div>

        {!canRead ? (
          <Restricted>
            Reading telemetry needs the <strong>Read Application Traffic</strong> function.
          </Restricted>
        ) : (
          <>
            <form onSubmit={applyFilters} className="filters">
              {isAdmin && (
                <div className="form-group">
                  <label>Organization</label>
                  <select
                    value={filters.tenant_id}
                    onChange={(e) => setFilters({ ...filters, tenant_id: e.target.value, application_id: "" })}
                  >
                    <option value="">All</option>
                    {tenants.map((tenant) => (
                      <option key={tenant.id} value={tenant.id}>{tenant.name}</option>
                    ))}
                  </select>
                </div>
              )}

              <div className="form-group">
                <label>Application</label>
                <select
                  value={filters.application_id}
                  onChange={(e) => setFilters({ ...filters, application_id: e.target.value })}
                >
                  <option value="">All</option>
                  {applications
                    .filter((app) => !filters.tenant_id || app.tenant_id === Number(filters.tenant_id))
                    .map((app) => (
                      <option key={app.id} value={app.id}>{app.name}</option>
                    ))}
                </select>
              </div>

              <div className="form-group">
                <label>Device ID</label>
                <input
                  value={filters.device_id}
                  placeholder="Any"
                  onChange={(e) => setFilters({ ...filters, device_id: e.target.value })}
                />
              </div>

              <div className="form-group">
                <label>Network</label>
                <select
                  value={filters.connection_type}
                  onChange={(e) => setFilters({ ...filters, connection_type: e.target.value })}
                >
                  <option value="">NTN + TN</option>
                  <option value="NTN">NTN (satellite)</option>
                  <option value="TN">TN (terrestrial)</option>
                </select>
              </div>

              <div className="form-group">
                <label>Provider</label>
                <select
                  value={filters.provider}
                  onChange={(e) => setFilters({ ...filters, provider: e.target.value })}
                >
                  <option value="">All</option>
                  {profiles.map((profile) => (
                    <option key={profile.code} value={profile.code}>{profile.name}</option>
                  ))}
                </select>
              </div>

              <div className="form-group">
                <label>Limit</label>
                <input
                  type="number"
                  min={1}
                  max={1000}
                  value={filters.limit}
                  onChange={(e) => setFilters({ ...filters, limit: e.target.value })}
                />
              </div>

              <div className="filter-buttons">
                <button className="primary-button inline" type="submit">Apply</button>
                <button className="secondary-button" type="button" onClick={clearFilters}>Clear</button>
              </div>
            </form>

            <Notice notice={notice} />

            {records.length === 0 ? (
              <div className="empty-state">No telemetry for these filters.</div>
            ) : (
              <div className="table-container">
                <table>
                  <thead>
                    <tr>
                      <th>Measured</th>
                      <th>Received</th>
                      <th>Data Originator</th>
                      <th>Application</th>
                      <th>Decoder</th>
                      <th>Provider</th>
                      <th>Raw Payload</th>
                      <th>Decoded Values</th>
                    </tr>
                  </thead>
                  <tbody>
                    {paginatedRecords.map((record) => (
                      <tr key={record.id}>
                        <td>{formatDate(record.timestamp)}</td>
                        <td>{formatDate(record.received_at)}</td>
                        <td>
                          <div style={{ fontWeight: 600 }}>{record.data_originator || record.device_name || record.device_id}</div>
                          {record.device_id && record.device_name && record.device_id !== record.device_name && (
                            <span className="muted small-text" style={{ fontSize: "0.75rem", display: "block" }}>
                              ID: {record.device_id}
                            </span>
                          )}
                        </td>
                        <td>{applicationName(record.application_id)}</td>
                        <td className="small-text">
                          {record.decoder_name ? (
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
                              {record.decoder_name} {record.decoder_version ? (String(record.decoder_version).startsWith("v") ? record.decoder_version : `v${record.decoder_version}`) : ""}
                            </span>
                          ) : record.decode_schema_id ? (
                            <span className="muted">Decoder #{record.decode_schema_id}</span>
                          ) : (
                            <span className="muted">—</span>
                          )}
                        </td>
                        <td>
                          {providerName(record.provider)}
                          {record.connection_type && (
                            <span className={`pill ${record.connection_type === "NTN" ? "pill-ntn" : "pill-tn"}`}>
                              {record.connection_type}
                            </span>
                          )}
                        </td>
                        <td>
                          <RawPayloadCell message={{ raw_payload_hex: record.raw_payload_hex }} />
                        </td>
                        <td className="values-cell">{formatValues(record.telemetry)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>

                {records.length > 0 && (
                  <Pagination
                    page={trafficPage}
                    totalPages={Math.max(1, Math.ceil(records.length / trafficPageSize))}
                    totalItems={records.length}
                    pageSize={trafficPageSize}
                    onPageChange={(p) => setTrafficPage(p)}
                    onPageSizeChange={(sz) => {
                      setTrafficPageSize(sz);
                      setTrafficPage(1);
                    }}
                    pageSizeOptions={[10, 25, 50, 100]}
                    itemLabel="records"
                  />
                )}
              </div>
            )}
          </>
        )}
      </section>

      {capabilities.use_ingestion && (
        <IngestionConsole api={api} profiles={profiles} onIngested={() => { fetchTelemetry(); fetchUsage(); }} />
      )}

    </div>
  );
}


// -------------------------
// Admin: ingestion console
// -------------------------

function IngestionConsole({ api, profiles, onIngested }) {
  const [deviceId, setDeviceId] = useState("");
  const [payloadHex, setPayloadHex] = useState("09c4026c");
  const [transport, setTransport] = useState("udp");
  const [remoteAddress, setRemoteAddress] = useState("");
  const [connectionId, setConnectionId] = useState("");
  const [provider, setProvider] = useState("");
  const [messageType, setMessageType] = useState("");
  const [payloadVersion, setPayloadVersion] = useState("");

  const [result, setResult] = useState(null);
  const [notice, setNotice] = useState(null);

  const [messages, setMessages] = useState([]);
  const [statusFilter, setStatusFilter] = useState("");
  const [logNotice, setLogNotice] = useState(null);
  const [openedMessage, setOpenedMessage] = useState(null);

  useEffect(() => {
    fetchMessages();
  }, [api]);

  async function fetchMessages(status = statusFilter) {
    try {
      setMessages(await api.get("/ingest/messages", { status, limit: 50 }));
    } catch (error) {
      setLogNotice({ type: "error", text: error.message });
    }
  }

  async function sendUplink(event) {
    event.preventDefault();
    setNotice(null);
    setResult(null);

    try {
      const message = await api.post("/ingest/uplinks", {
        id: `console-${Date.now()}`,
        received_at: new Date().toISOString(),
        transport: {
          type: transport,
          remote_address: remoteAddress || null,
          connection_id: connectionId || null,
          provider: provider || null,
        },
        source: {
          device_id: deviceId.trim() || null,
          message_type: messageType.trim() || null,
          version: payloadVersion.trim() || null,
        },
        payload: { data: hexToBase64(payloadHex) },
      });

      setResult(message);
      fetchMessages();

      if (message.status === "ROUTED") {
        onIngested();
      }
    } catch (error) {
      setNotice({ type: "error", text: error.message });
    }
  }

  async function sendViaRedisQueue() {
    setNotice(null);
    setResult(null);

    try {
      const outcome = await api.post("/ingest/queue", {
        id: `redis-${Date.now()}`,
        received_at: new Date().toISOString(),
        transport: {
          type: transport,
          remote_address: remoteAddress || null,
          connection_id: connectionId || null,
          provider: provider || null,
        },
        source: {
          device_id: deviceId.trim() || null,
          message_type: messageType.trim() || null,
          version: payloadVersion.trim() || null,
        },
        payload: { data: hexToBase64(payloadHex) },
      });

      setNotice({
        type: "success",
        text: `⚡ Telemetry queued in Redis unprocessed queue (ID: ${outcome.message_id}, Queue Depth: ${outcome.queue_length}). Background worker is decoding...`,
      });
      setTimeout(() => {
        fetchMessages();
        if (onIngested) onIngested();
      }, 800);
    } catch (error) {
      setNotice({ type: "error", text: error.message });
    }
  }

  async function reprocess() {
    setLogNotice(null);

    try {
      const outcome = await api.post("/ingest/reprocess", {});
      setLogNotice({
        type: "success",
        text: `Reprocessed ${outcome.processed} message(s), ${outcome.routed} now routed.`,
      });
      fetchMessages();

      if (outcome.routed) {
        onIngested();
      }
    } catch (error) {
      setLogNotice({ type: "error", text: error.message });
    }
  }

  async function purge() {
    if (!window.confirm(
      "Purge telemetry and staged uplinks older than 24 hours (24-Hour Auto-Retention Policy)?"
    )) {
      return;
    }

    try {
      const outcome = await api.post("/ingest/purge", {});
      setLogNotice({ type: "success", text: `Purged ${outcome.deleted} record(s) older than 24 hours.` });
      fetchMessages();
      if (onIngested) onIngested();
    } catch (error) {
      setLogNotice({ type: "error", text: error.message });
    }
  }

  return (
    <>
      <section className="card">
        <div className="section-header">
          <div>
            <h2>Send Test Uplink</h2>
            <p>
              Admin only. Plays the role of a provider adapter: the uplink goes
              through provider resolution, routing, decoding and delivery.
            </p>
          </div>
          <span className="locked-badge">Admin</span>
        </div>

        <form onSubmit={sendUplink}>
          <div className="form-grid">
            <div className="form-group">
              <label>Device ID</label>
              <input
                value={deviceId}
                placeholder="MAIN-01"
                onChange={(e) => setDeviceId(e.target.value)}
              />
            </div>

            <div className="form-group">
              <label>Payload (Hex, Binary, Base64, or JSON)</label>
              <input
                value={payloadHex}
                placeholder="Hex: 09c4026c · JSON: {'temp':25} · Bits: 00001001..."
                onChange={(e) => setPayloadHex(e.target.value)}
                required
              />
            </div>

            <div className="form-group">
              <label>Protocol</label>
              <select value={transport} onChange={(e) => setTransport(e.target.value)}>
                <option value="https">HTTPS</option>
                <option value="mqtt">MQTT</option>
                <option value="tcp">TCP/IP</option>
                <option value="udp">UDP</option>
                <option value="webhook">Webhook</option>
                <option value="custom">Custom</option>
              </select>
            </div>

            <div className="form-group">
              <label>Source address (UDP / satellite)</label>
              <input
                value={remoteAddress}
                placeholder="203.0.113.5:4000"
                onChange={(e) => setRemoteAddress(e.target.value)}
              />
            </div>

            <div className="form-group">
              <label>Client ID (TCP / MQTT)</label>
              <input
                value={connectionId}
                placeholder="gw-cell-01"
                onChange={(e) => setConnectionId(e.target.value)}
              />
            </div>

            <div className="form-group">
              <label>Provider (optional)</label>
              <select value={provider} onChange={(e) => setProvider(e.target.value)}>
                <option value="">Resolve from source mappings</option>
                {profiles.map((profile) => (
                  <option key={profile.code} value={profile.code}>{profile.name}</option>
                ))}
              </select>
            </div>

            <div className="form-group">
              <label>Message type (optional, for decoder match)</label>
              <input
                value={messageType}
                placeholder="status"
                onChange={(e) => setMessageType(e.target.value)}
              />
            </div>

            <div className="form-group">
              <label>Version (optional, for decoder match)</label>
              <input
                value={payloadVersion}
                placeholder="2"
                onChange={(e) => setPayloadVersion(e.target.value)}
              />
            </div>
          </div>

          <Notice notice={notice} />

          {result && (
            <div className={`message ${result.status === "ROUTED" ? "success" : "warning"}`}>
              <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "6px" }}>
                <span className={`pill ${result.status === "ROUTED" ? "pill-ok" : "pill-off"}`}>
                  {result.status}
                </span>
                <strong>{result.status === "ROUTED" ? "Uplink Ingested & Decoded" : "Ingest Processing Incomplete"}</strong>
              </div>

              {result.raw_payload_hex && (
                <div style={{ marginBottom: "6px" }}>
                  <strong>Raw Payload:</strong>{" "}
                  <code className="hex">{result.raw_payload_hex.match(/.{1,2}/g)?.join(" ") || result.raw_payload_hex}</code>
                  {" "}<span className="muted small-text">({result.raw_payload_hex.length / 2} bytes)</span>
                </div>
              )}

              <div>
                <strong>{result.status === "ROUTED" ? "Decoded Data:" : "Detail:"}</strong>{" "}
                {result.status === "ROUTED"
                  ? `${formatValues(result.decoded)} (provider: ${result.provider || "unknown"}, decoder #${result.decode_schema_id} by ${result.decoder_selection})`
                  : result.error || "Uplink staged without active decoder match"}
              </div>
            </div>
          )}

          <div style={{ display: "flex", gap: "10px", marginTop: "12px", flexWrap: "wrap" }}>
            <button className="primary-button" type="submit">Send Uplink (Direct)</button>
            <button
              type="button"
              className="secondary-button"
              style={{ borderColor: "var(--accent, #3b82f6)", color: "var(--accent, #3b82f6)" }}
              onClick={sendViaRedisQueue}
            >
              ⚡ Enqueue in Redis (Unprocessed)
            </button>
          </div>
        </form>
      </section>

      <section className="card">
        <div className="section-header">
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: "10px", flexWrap: "wrap" }}>
              <h2>Staged Uplinks</h2>
              <span className="pill" style={{ background: "rgba(59, 130, 246, 0.15)", color: "var(--accent, #3b82f6)", border: "1px solid rgba(59, 130, 246, 0.3)", fontSize: "0.75rem", padding: "2px 8px", borderRadius: "12px" }}>
                ⏱ 24h Auto-Retention Active
              </span>
            </div>
            <p>
              Every uplink lands here first. Failed ones can be reprocessed
              after the device, decoder or provider is fixed. Staged messages and telemetry automatically prune after 24 hours.
            </p>
          </div>

          <div className="table-actions">
            <select
              value={statusFilter}
              onChange={(e) => { setStatusFilter(e.target.value); fetchMessages(e.target.value); }}
            >
              <option value="">All statuses</option>
              {STATUSES.map((status) => (
                <option key={status} value={status}>{status}</option>
              ))}
            </select>
            <button className="secondary-button" onClick={() => fetchMessages()}>Refresh</button>
            <button className="secondary-button" onClick={reprocess}>Reprocess failed</button>
            <button className="danger-button" onClick={purge}>Purge (&gt;24h)</button>
          </div>
        </div>

        <Notice notice={logNotice} />

        {messages.length === 0 ? (
          <div className="empty-state">No staged uplinks.</div>
        ) : (
          <div className="table-container">
            <table>
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Received</th>
                  <th>Data Originator</th>
                  <th>Provider</th>
                  <th>Raw Payload</th>
                  <th>Status</th>
                  <th>Decoder</th>
                  <th>Decoded / Detail</th>
                  <th>Attempts</th>
                </tr>
              </thead>
              <tbody>
                {messages.map((message) => (
                  <tr
                    key={message.id}
                    className="clickable-row"
                    tabIndex={0}
                    onClick={() => setOpenedMessage(message)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        setOpenedMessage(message);
                      }
                    }}
                    style={{ cursor: "pointer" }}
                  >
                    <td>#{message.id}</td>
                    <td>{formatDate(message.received_at)}</td>
                    <td>
                      <div style={{ fontWeight: 600 }}>{message.data_originator || message.device_identifier || "—"}</div>
                      {message.source_address && (
                        <span className="muted small-text" style={{ fontSize: "0.75rem", display: "block" }}>
                          {message.transport?.toUpperCase() || "UDP"} · {message.source_address}
                        </span>
                      )}
                    </td>
                    <td>{message.provider || "unknown"}</td>
                    <td>
                      <RawPayloadCell message={message} />
                    </td>
                    <td>
                      <span className={`pill ${message.status === "ROUTED" ? "pill-ok" : "pill-off"}`}>
                        {message.status}
                      </span>
                    </td>
                    <td className="small-text">
                      {message.decode_schema_id
                        ? `#${message.decode_schema_id} (${message.decoder_selection})`
                        : "—"}
                    </td>
                    <td className="small-text values-cell">
                      {message.error || formatValues(message.decoded)}
                    </td>
                    <td>{message.attempts}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {openedMessage && (
        <StagedMessageModal
          message={openedMessage}
          onClose={() => setOpenedMessage(null)}
        />
      )}
    </>
  );
}


function StagedMessageModal({ message, onClose }) {
  if (!message) return null;

  const hex = (message.raw_payload_hex || "").toUpperCase();
  const isRouted = message.status === "ROUTED";
  const decoded = message.decoded || {};

  const details = [
    ["Message ID", `#${message.id}`],
    ["Received", formatDate(message.received_at)],
    ["Data Originator", message.data_originator || (message.device_identifier ? `${message.device_identifier} via ${message.transport?.toUpperCase() || "UDP"}${message.source_address ? " [" + message.source_address + "]" : ""}` : "—")],
    ["Device Identifier", message.device_identifier || "—"],
    ["Device ID", message.device_id || "—"],
    ["Transport", message.transport],
    ["Provider", message.provider || "unknown"],
    ["Connection Type", message.connection_type || "—"],
    ["Source Address", message.source_address || "—"],
    ["Decoder", message.decode_schema_id ? `#${message.decode_schema_id} (${message.decoder_selection})` : "—"],
    ["Protocol ID", message.protocol_id || "—"],
    ["Message Type", message.message_type || "—"],
    ["Payload Version", message.payload_version || "—"],
    ["Attempts", message.attempts],
  ].filter(([, val]) => val !== undefined && val !== null && val !== "");

  return (
    <Modal
      title={`Staged Uplink #${message.id}`}
      subtitle={`${message.data_originator || message.device_identifier || "Unknown device"} · ${formatDate(message.received_at)}`}
      onClose={onClose}
      wide
      footer={<button type="button" className="secondary-button" onClick={onClose}>Close</button>}
    >
      <div className="detail-status" style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "16px" }}>
        <span className={`pill ${isRouted ? "pill-ok" : "pill-off"}`}>
          {message.status}
        </span>
        <span className="muted small-text">
          {hex.length / 2} byte{hex.length === 2 ? "" : "s"} · Transport: {message.transport?.toUpperCase() || "UDP"}
        </span>
      </div>

      {/* RAW PAYLOAD VIEW */}
      <h4 className="detail-heading" style={{ margin: "16px 0 6px 0" }}>Payload</h4>
      <RawPayloadBlock message={message} />

      {/* DECODED RESULT OR FAILURE DETAIL */}
      <h4 className="detail-heading" style={{ margin: "0 0 8px 0" }}>
        {isRouted ? "Decoded Output" : "Processing Status Detail"}
      </h4>
      {isRouted ? (
        Object.keys(decoded).length === 0 ? (
          <p className="muted">The decoder returned no values.</p>
        ) : (
          <div className="table-container" style={{ marginBottom: "16px" }}>
            <table>
              <thead>
                <tr>
                  <th>Field</th>
                  <th>Value</th>
                  <th>Unit</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(decoded).map(([key, val]) => (
                  <tr key={key}>
                    <td><strong>{key}</strong></td>
                    <td>{typeof val === "object" ? JSON.stringify(val) : String(val)}</td>
                    <td>{message.units?.[key] || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      ) : (
        <div className="message error" style={{ marginBottom: "16px" }}>
          {message.error || "No active decoder schema matched this message context."}
        </div>
      )}

      {/* METADATA DETAILS */}
      <h4 className="detail-heading" style={{ margin: "16px 0 8px 0" }}>Routing Details</h4>
      <dl className="detail-list">
        {details.map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
    </Modal>
  );
}

export default Telemetry;
