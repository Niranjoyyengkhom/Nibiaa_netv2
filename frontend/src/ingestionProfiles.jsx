import { useEffect, useState, useMemo } from "react";
import { API, formatDate } from "./api";
import { Notice, PageHeader } from "./components";
import { Icon } from "./icons";

const PROTOCOL_CONFIG = {
  udp: {
    label: "UDP Datagram",
    shortLabel: "UDP",
    defaultPort: 5001,
    badgeClass: "udp",
    desc: "Low-latency datagram listener for NTN satellite uplinks and LPWAN packets.",
    samplePath: "",
    pathLabel: "Optional Framing / Format",
    pathPlaceholder: "raw_hex | delimited_json",
  },
  mqtt: {
    label: "MQTT 3.1.1 Broker",
    shortLabel: "MQTT",
    defaultPort: 1883,
    badgeClass: "mqtt",
    desc: "Lightweight MQTT 3.1.1 message broker for IoT sensor streams and gateway telemetry.",
    samplePath: "devices/+/up",
    pathLabel: "MQTT Ingestion Topic",
    pathPlaceholder: "devices/+/up or v1/gateway/telemetry",
  },
  tcp: {
    label: "TCP / IP Stream",
    shortLabel: "TCP",
    defaultPort: 1001,
    badgeClass: "tcp",
    desc: "Persistent raw socket stream listener with newline or length-prefix framing.",
    samplePath: "",
    pathLabel: "Stream Delimiter",
    pathPlaceholder: "newline (\\n) | length_prefix",
  },
  webhook: {
    label: "HTTP Webhook REST",
    shortLabel: "Webhook",
    defaultPort: 1002,
    badgeClass: "webhook",
    desc: "REST Webhook receiver for third-party ground segments (Hubble, Skylo, Cellular).",
    samplePath: "/webhooks/custom-stream",
    pathLabel: "Webhook Endpoint Path",
    pathPlaceholder: "/webhooks/provider_name or /ingest/custom",
  },
};

export default function IngestionProfiles({ api, currentUser }) {
  const isAdmin = currentUser?.role === "admin" || currentUser?.role === "owner";
  
  const [profiles, setProfiles] = useState([]);
  const [networkProfiles, setNetworkProfiles] = useState([]);
  const [microserviceStatus, setMicroserviceStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState(null);
  const [activeTab, setActiveTab] = useState("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [copiedId, setCopiedId] = useState(null);
  
  // Modal state for editing an Ingestion Profile
  const [editingProfile, setEditingProfile] = useState(null);
  const [editForm, setEditForm] = useState({
    name: "",
    protocol: "udp",
    network_profile_code: "all",
    use_default: true,
    custom_port: "",
    host: "nibiaanet.nibiaa.com",
    auth_type: "none",
    auth_username: "",
    auth_password: "",
    auth_token: "",
    custom_path: "",
    is_enabled: true,
    description: "",
  });

  // Modal state for adding a new Ingestion Profile / Endpoint
  const [showAddModal, setShowAddModal] = useState(false);
  const [addForm, setAddForm] = useState({
    code: "",
    name: "",
    protocol: "webhook",
    network_profile_code: "all",
    use_default: true,
    custom_port: "",
    host: "nibiaanet.nibiaa.com",
    auth_type: "none",
    auth_username: "",
    auth_password: "",
    auth_token: "",
    custom_path: "/webhooks/custom",
    is_enabled: true,
    description: "",
  });

  // Simulator state
  const [simProtocol, setSimProtocol] = useState("webhook");
  const [simDeviceId, setSimDeviceId] = useState("HUBBLE-DEV-001");
  const [simPayload, setSimPayload] = useState("0102030405060708");
  const [simProvider, setSimProvider] = useState("hubble");
  const [simResult, setSimResult] = useState(null);
  const [simLoading, setSimLoading] = useState(false);

  // Fetch data with independent try/catch so one failure never blocks the others
  const fetchData = async () => {
    setLoading(true);

    // 1. Fetch Ingestion Profiles
    try {
      let profData = null;
      try {
        profData = await api.get("/ingestion-profiles");
      } catch {
        profData = await fetch("/api/ingestion-profiles").then((r) => r.json()).catch(() => null);
      }
      if (profData && Array.isArray(profData.profiles)) {
        setProfiles(profData.profiles);
      }
    } catch (e) {
      console.error("Error fetching ingestion profiles:", e);
    }

    // 2. Fetch Network Profiles
    try {
      const netRes = await api.get("/connectivity/").catch(() => null);
      if (Array.isArray(netRes)) {
        setNetworkProfiles(netRes);
      }
    } catch (e) {
      console.error("Error fetching network profiles:", e);
    }

    // 3. Fetch Microservice Status
    try {
      const statusRes = await fetch("/protocol-ingestion/status")
        .then((r) => r.json())
        .catch(() => null);
      if (statusRes) {
        setMicroserviceStatus(statusRes);
      }
    } catch (e) {
      console.error("Error fetching microservice status:", e);
    }

    setLoading(false);
  };

  useEffect(() => {
    fetchData();
    const interval = setInterval(() => {
      fetch("/protocol-ingestion/status")
        .then((r) => r.json())
        .then((s) => {
          if (s) setMicroserviceStatus(s);
        })
        .catch(() => {});
    }, 6000);
    return () => clearInterval(interval);
  }, []);

  // Quick toggle mode (Default vs Admin-provided)
  const handleToggleMode = async (p) => {
    try {
      const res = await api.post(`/ingestion-profiles/${p.id}/toggle-mode`);
      setNotice({
        type: "info",
        message: `Profile '${p.name}' switched to ${res.use_default ? "Default Port" : "Admin-Provided Custom Port"}.`,
      });
      fetchData();
    } catch (err) {
      setNotice({ type: "error", message: `Toggle failed: ${err.message}` });
    }
  };

  // Open creation modal with a preselected protocol
  const handleOpenAdd = (protocol = "webhook") => {
    const protoCfg = PROTOCOL_CONFIG[protocol] || PROTOCOL_CONFIG.webhook;
    setAddForm({
      code: "",
      name: "",
      protocol,
      network_profile_code: "all",
      use_default: true,
      custom_port: "",
      host: "localhost",
      auth_type: "none",
      auth_username: "",
      auth_password: "",
      custom_path: protoCfg.samplePath,
      is_enabled: true,
      description: "",
    });
    setShowAddModal(true);
  };

  // Open edit modal
  const handleEdit = (p) => {
    setEditingProfile(p);
    setEditForm({
      name: p.name || "",
      protocol: p.protocol || "udp",
      network_profile_code: p.network_profile_code || "all",
      use_default: p.use_default ?? true,
      custom_port: p.custom_port ? String(p.custom_port) : "",
      host: (p.host && p.host !== "localhost" && p.host !== "127.0.0.1" && p.host !== "0.0.0.0") ? p.host : liveHost,
      auth_type: p.auth_type || "none",
      auth_username: p.auth_username || "",
      auth_password: p.has_password ? "***" : "",
      auth_token: p.has_token ? "***" : (p.auth_token || ""),
      custom_path: p.custom_path || "",
      is_enabled: p.is_enabled ?? true,
      description: p.description || "",
    });
  };

  // Save edit
  const handleSaveEdit = async (e) => {
    e.preventDefault();
    if (!editingProfile) return;
    try {
      const targetHost = (editForm.host && editForm.host !== "localhost" && editForm.host !== "127.0.0.1") ? editForm.host : liveHost;
      const payload = {
        name: editForm.name,
        protocol: editForm.protocol,
        network_profile_code: editForm.network_profile_code,
        use_default: Boolean(editForm.use_default),
        custom_port: editForm.custom_port ? parseInt(editForm.custom_port, 10) : null,
        host: targetHost,
        auth_type: editForm.auth_type,
        auth_username: editForm.auth_username || null,
        auth_password: editForm.auth_password || null,
        auth_token: editForm.auth_token || null,
        custom_path: editForm.custom_path || null,
        is_enabled: Boolean(editForm.is_enabled),
        description: editForm.description || null,
      };

      await api.put(`/ingestion-profiles/${editingProfile.id}`, payload);
      setNotice({ type: "info", message: `Ingestion endpoint '${editForm.name}' updated successfully.` });
      setEditingProfile(null);
      fetchData();
    } catch (err) {
      setNotice({ type: "error", message: err.message });
    }
  };

  // Create new profile / endpoint
  const handleCreateProfile = async (e) => {
    e.preventDefault();
    try {
      const codeGen = addForm.code.trim()
        ? addForm.code.trim().toLowerCase().replace(/[^a-z0-9_-]/g, "_")
        : `${addForm.protocol}_${addForm.name.trim().toLowerCase().replace(/[^a-z0-9_-]/g, "_")}`;

      const payload = {
        code: codeGen,
        name: addForm.name.trim(),
        protocol: addForm.protocol,
        network_profile_code: addForm.network_profile_code,
        use_default: Boolean(addForm.use_default),
        custom_port: addForm.custom_port ? parseInt(addForm.custom_port, 10) : null,
        host: addForm.host || "localhost",
        auth_type: addForm.auth_type,
        auth_username: addForm.auth_username || null,
        auth_password: addForm.auth_password || null,
        auth_token: addForm.auth_token || null,
        custom_path: addForm.custom_path || null,
        is_enabled: Boolean(addForm.is_enabled),
        description: addForm.description || null,
      };

      await api.post("/ingestion-profiles", payload);
      setNotice({ type: "info", message: `New ${addForm.protocol.toUpperCase()} endpoint '${payload.name}' created successfully.` });
      setShowAddModal(false);
      fetchData();
    } catch (err) {
      setNotice({ type: "error", message: err.message });
    }
  };

  // Delete profile
  const handleDeleteProfile = async (p) => {
    if (!window.confirm(`Are you sure you want to delete ingestion endpoint '${p.name}' (${p.code})?`)) {
      return;
    }
    try {
      await api.delete(`/ingestion-profiles/${p.id}`);
      setNotice({ type: "info", message: `Ingestion endpoint '${p.name}' removed.` });
      fetchData();
    } catch (err) {
      setNotice({ type: "error", message: `Delete failed: ${err.message}` });
    }
  };

  // Reset all to defaults
  const handleResetDefaults = async () => {
    if (!window.confirm("Reset all Ingestion Profiles to system default values (UDP: 5001, MQTT: 1883, TCP: 1001, Webhook: 1002 on localhost)?")) {
      return;
    }
    try {
      const res = await api.post("/ingestion-profiles/reset-defaults");
      setNotice({ type: "info", message: res.message });
      fetchData();
    } catch (err) {
      setNotice({ type: "error", message: `Reset failed: ${err.message}` });
    }
  };

  // Run simulation
  const handleSimulate = async (e) => {
    e.preventDefault();
    setSimLoading(true);
    setSimResult(null);
    try {
      const res = await fetch("/protocol-ingestion/test/simulate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          protocol: simProtocol,
          device_id: simDeviceId,
          payload: simPayload,
          provider: simProvider,
        }),
      });
      const data = await res.json();
      setSimResult(data);
      // Refresh status after uplink
      const st = await fetch("/protocol-ingestion/status").then((r) => r.json());
      if (st) setMicroserviceStatus(st);
    } catch (err) {
      setSimResult({ error: err.message });
    } finally {
      setSimLoading(false);
    }
  };

  const liveHost = useMemo(() => {
    if (typeof window !== "undefined" && window.location.hostname && window.location.hostname !== "localhost" && window.location.hostname !== "127.0.0.1") {
      return window.location.hostname;
    }
    return "nibiaanet.nibiaa.com";
  }, []);

  const liveOrigin = useMemo(() => {
    if (typeof window !== "undefined" && window.location.origin && !window.location.origin.includes("localhost")) {
      return window.location.origin;
    }
    return "https://nibiaanet.nibiaa.com";
  }, []);

  const getProfileLiveEndpoint = (p) => {
    const host = (p && p.host && p.host !== "localhost" && p.host !== "127.0.0.1" && p.host !== "0.0.0.0") ? p.host : liveHost;
    const path = p?.custom_path || (p?.protocol === "webhook" ? "/webhook" : "");

    if (p?.protocol === "webhook") {
      const isHttps = typeof window !== "undefined" && window.location.protocol === "https:";
      const scheme = isHttps ? "https://" : "http://";
      const cleanPath = path.startsWith("/") ? path : `/${path}`;
      return `${scheme}${host}${cleanPath}`;
    } else if (p?.protocol === "mqtt") {
      return `mqtt://${host}:${p.effective_port || 1883}/${path || "devices/{id}/up"}`;
    } else if (p?.protocol === "tcp") {
      return `tcp://${host}:${p.effective_port || 1001}`;
    } else if (p?.protocol === "udp") {
      return `udp://${host}:${p.effective_port || 5001}`;
    }
    return `${host}:${p?.effective_port}`;
  };

  // Copy connection URI
  const handleCopyUri = (p) => {
    const uri = getProfileLiveEndpoint(p);
    navigator.clipboard.writeText(uri);
    setCopiedId(p.id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  const isMsOnline = microserviceStatus?.status === "online";
  const listeners = microserviceStatus?.listeners || {
    udp: { port: 5001, status: "offline" },
    mqtt: { port: 1883, status: "offline" },
    tcp: { port: 1001, status: "offline" },
    webhook: { port: 1002, status: "offline" },
  };

  // Filter profiles based on activeTab and searchQuery
  const filteredProfiles = useMemo(() => {
    return profiles.filter((p) => {
      const matchesTab = activeTab === "all" || p.protocol.toLowerCase() === activeTab;
      const q = searchQuery.toLowerCase().trim();
      const matchesQuery =
        !q ||
        p.name.toLowerCase().includes(q) ||
        p.code.toLowerCase().includes(q) ||
        p.protocol.toLowerCase().includes(q) ||
        (p.network_profile_name && p.network_profile_name.toLowerCase().includes(q));
      return matchesTab && matchesQuery;
    });
  }, [profiles, activeTab, searchQuery]);

  return (
    <div className="page ingestion-page">
      <PageHeader
        title="Ingestion Profile"
        description="Protocol Ingestion Microservice management. Admins can create and configure UDP, MQTT, TCP/IP, and Webhook endpoints with default or custom ports, hosts, and authentication."
      />

      {/* Top Banner Actions & Service Status */}
      <div className="ingestion-header-row">
        <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
          <span className={`ingestion-status-badge ${isMsOnline ? "online" : "offline"}`}>
            <span className={`ingestion-dot ${isMsOnline ? "online" : "offline"}`} />
            Microservice: {isMsOnline ? "Online (All Listeners Active)" : "Standby"}
          </span>

          <span style={{ fontSize: "12.5px", color: "var(--muted)" }}>
            Uptime: <strong>{microserviceStatus?.uptime_formatted || "Active"}</strong>
          </span>
        </div>

        <div className="button-group">
          <button className="secondary-button small" onClick={fetchData}>
            Refresh Status
          </button>

          {isAdmin && (
            <>
              <button
                className="secondary-button small"
                onClick={handleResetDefaults}
                title="Revert all profiles to microservice defaults"
              >
                Reset to Defaults
              </button>
              <button
                className="primary-button small"
                onClick={() => handleOpenAdd("webhook")}
              >
                + Create New Endpoint
              </button>
            </>
          )}
        </div>
      </div>

      {notice && (
        <Notice
          type={notice.type}
          message={notice.message}
          onDismiss={() => setNotice(null)}
        />
      )}

      {/* 4 Protocol Overview Cards */}
      <section className="ingestion-cards-grid" aria-label="Protocol Listeners">
        {[
          { key: "udp", name: "UDP Listener", defPort: 5001 },
          { key: "mqtt", name: "MQTT Broker", defPort: 1883 },
          { key: "tcp", name: "TCP/IP Stream", defPort: 1001 },
          { key: "webhook", name: "Webhook Gateway", defPort: 1002 },
        ].map((item) => {
          const cfg = PROTOCOL_CONFIG[item.key];
          const lStatus = listeners[item.key] || {};
          const isLActive = lStatus.status === "online" || isMsOnline;
          const assignedProfile = profiles.find((p) => p.protocol === item.key && p.network_profile_code === "all");
          const isDefault = assignedProfile ? assignedProfile.use_default : true;
          const activePort = assignedProfile ? assignedProfile.effective_port : item.defPort;
          const countForProto = profiles.filter((p) => p.protocol === item.key).length;

          return (
            <div key={item.key} className="protocol-card">
              <div>
                <div className="protocol-card-top">
                  <span className={`protocol-badge ${cfg.badgeClass}`}>{cfg.shortLabel}</span>
                  <span
                    className={`tag tag-${isLActive ? "ok" : "muted"}`}
                    style={{ fontSize: "11px", fontWeight: 700 }}
                  >
                    {isLActive ? "Active" : "Offline"}
                  </span>
                </div>

                <h3 className="protocol-card-title">{item.name}</h3>
                <div style={{ fontSize: "11px", color: "var(--muted)", marginBottom: "8px" }}>
                  {countForProto} registered endpoint{countForProto !== 1 ? "s" : ""}
                </div>

                <p className="protocol-card-desc">{cfg.desc}</p>

                <div className="protocol-meta-box">
                  <div className="protocol-meta-row">
                    <span>Default Port:</span>
                    <strong>{activePort}</strong>
                  </div>
                  <div className="protocol-meta-row">
                    <span>Live Host:</span>
                    <strong style={{ color: "var(--primary-text)" }}>{liveHost}</strong>
                  </div>
                  <div className="protocol-meta-row">
                    <span>Port Mode:</span>
                    <strong style={{ color: isDefault ? "var(--ok)" : "var(--primary-text)" }}>
                      {isDefault ? "Default Port" : "Admin Custom"}
                    </strong>
                  </div>
                </div>
              </div>

              {isAdmin && (
                <div className="protocol-card-actions">
                  <button
                    className="primary-button small"
                    style={{ flex: 1 }}
                    onClick={() => handleOpenAdd(item.key)}
                  >
                    + Add {cfg.shortLabel}
                  </button>
                  {assignedProfile && (
                    <button
                      className="secondary-button small"
                      onClick={() => handleEdit(assignedProfile)}
                      title="Configure system default listener"
                    >
                      Config
                    </button>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </section>

      {/* Main Endpoints Management Card & Table */}
      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        {/* Table Toolbar: Filter Tabs + Search + Create Button */}
        <div className="ingestion-toolbar">
          <div className="ingestion-tabs">
            {[
              { id: "all", label: "All Protocols", count: profiles.length },
              { id: "udp", label: "UDP", count: profiles.filter((p) => p.protocol === "udp").length },
              { id: "mqtt", label: "MQTT", count: profiles.filter((p) => p.protocol === "mqtt").length },
              { id: "tcp", label: "TCP / IP", count: profiles.filter((p) => p.protocol === "tcp").length },
              { id: "webhook", label: "Webhook", count: profiles.filter((p) => p.protocol === "webhook").length },
            ].map((tab) => (
              <button
                key={tab.id}
                className={`ingestion-tab-btn ${activeTab === tab.id ? "active" : ""}`}
                onClick={() => setActiveTab(tab.id)}
              >
                <span>{tab.label}</span>
                <span className="ingestion-tab-count">{tab.count}</span>
              </button>
            ))}
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
            <input
              type="text"
              className="ingestion-search-input"
              placeholder="Search endpoints..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
            {isAdmin && (
              <button
                className="primary-button small"
                onClick={() => handleOpenAdd(activeTab === "all" ? "webhook" : activeTab)}
              >
                + New {activeTab !== "all" ? activeTab.toUpperCase() : ""} Endpoint
              </button>
            )}
          </div>
        </div>

        {loading ? (
          <div style={{ padding: "40px", textAlign: "center", color: "var(--muted)", fontSize: "13px" }}>
            Loading ingestion profiles...
          </div>
        ) : filteredProfiles.length === 0 ? (
          <div className="empty-state" style={{ margin: "24px" }}>
            <strong>No ingestion endpoints match your criteria.</strong>
            <p>Click &quot;+ Create New Endpoint&quot; above to add an ingestion endpoint for your network.</p>
          </div>
        ) : (
          <div className="table-container" style={{ margin: 0, border: 0 }}>
            <table className="ingestion-table">
              <thead>
                <tr>
                  <th>Endpoint Name & Code</th>
                  <th>Protocol</th>
                  <th>Target Provider</th>
                  <th>Value Mode</th>
                  <th>Live Gateway Host</th>
                  <th>Path / Live URI</th>
                  <th>Auth</th>
                  <th>Status</th>
                  <th style={{ textAlign: "right" }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {filteredProfiles.map((p) => {
                  const isDef = p.use_default;
                  const isSystemDefault = ["default_udp", "default_mqtt", "default_tcp", "default_webhook"].includes(p.code);
                  const cfg = PROTOCOL_CONFIG[p.protocol] || { label: p.protocol.toUpperCase(), badgeClass: "udp" };

                  return (
                    <tr key={p.id}>
                      <td>
                        <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                          <strong style={{ fontSize: "13.5px", color: "var(--text)" }}>{p.name}</strong>
                          {!isSystemDefault && (
                            <span className="tag" style={{ fontSize: "10px", padding: "1px 6px" }}>
                              Custom
                            </span>
                          )}
                        </div>
                        <div style={{ fontFamily: "var(--mono)", fontSize: "11.5px", color: "var(--muted)", marginTop: "2px" }}>
                          {p.code}
                        </div>
                        {p.description && (
                          <div style={{ fontSize: "11px", color: "var(--muted)", marginTop: "2px", maxWidth: "260px" }}>
                            {p.description}
                          </div>
                        )}
                      </td>

                      <td>
                        <span className={`protocol-badge ${cfg.badgeClass}`}>
                          {p.protocol}
                        </span>
                      </td>

                      <td>
                        <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                          <Icon name="connectivity" size={14} />
                          <span style={{ fontWeight: 600 }}>{p.network_profile_name}</span>
                        </div>
                        <div style={{ fontFamily: "var(--mono)", fontSize: "10.5px", color: "var(--muted)", marginTop: "2px" }}>
                          code: {p.network_profile_code}
                        </div>
                      </td>

                      <td>
                        <span className={`tag tag-${isDef ? "ok" : "warn"}`} style={{ fontSize: "11px" }}>
                          {isDef ? "Default Port" : "Admin Custom"}
                        </span>
                        <div style={{ fontSize: "11px", color: "var(--muted)", marginTop: "2px", fontFamily: "var(--mono)" }}>
                          Port {p.effective_port}
                        </div>
                      </td>

                      <td style={{ fontFamily: "var(--mono)", fontSize: "12px" }}>
                        <div style={{ fontWeight: 600, color: p.protocol === "webhook" ? "#38bdf8" : "var(--text)" }}>
                          {p.protocol === "webhook" ? liveHost : `${liveHost}:${p.effective_port}`}
                        </div>
                        <div style={{ fontSize: "10.5px", color: "var(--muted)", marginTop: "2px" }}>
                          {p.protocol === "webhook" ? "Port 443 (HTTPS Gateway)" : `Port ${p.effective_port}`}
                        </div>
                      </td>

                      <td style={{ fontFamily: "var(--mono)", fontSize: "11.5px" }}>
                        {p.protocol === "webhook" ? (
                          <div>
                            <span
                              style={{
                                padding: "3px 8px",
                                borderRadius: "4px",
                                background: "rgba(56, 189, 248, 0.12)",
                                border: "1px solid rgba(56, 189, 248, 0.3)",
                                color: "#38bdf8",
                                display: "inline-block",
                                wordBreak: "break-all",
                              }}
                            >
                              {p.custom_path || "/webhook"}
                            </span>
                            <div style={{ fontSize: "10px", color: "var(--muted)", marginTop: "3px" }}>
                              {liveOrigin}{p.custom_path || "/webhook"}
                            </div>
                          </div>
                        ) : p.custom_path ? (
                          <span style={{ padding: "2px 6px", borderRadius: "4px", background: "var(--surface-2)", border: "1px solid var(--border)" }}>
                            {p.custom_path}
                          </span>
                        ) : (
                          <span style={{ color: "var(--muted)" }}>
                            {p.protocol === "mqtt" ? "devices/{id}/up" : "Raw socket"}
                          </span>
                        )}
                      </td>

                      <td>
                        {p.auth_type === "none" && !p.has_token ? (
                          <span style={{ color: "var(--muted)", fontSize: "12px" }}>Open (None)</span>
                        ) : (
                          <div>
                            <span className="tag" style={{ fontSize: "11px" }}>
                              {p.auth_type === "hubble_secret" ? "Hubble Secret" : p.auth_type}
                            </span>
                            {p.auth_username && (
                              <div style={{ fontFamily: "var(--mono)", fontSize: "10.5px", color: "var(--muted)", marginTop: "2px" }}>
                                {p.auth_username}
                              </div>
                            )}
                            {p.has_token && (
                              <div style={{ fontFamily: "var(--mono)", fontSize: "10px", color: "#60a5fa", marginTop: "2px" }}>
                                Secret: ••••••••
                              </div>
                            )}
                          </div>
                        )}
                      </td>

                      <td>
                        <span className={`tag tag-${p.is_enabled ? "ok" : "muted"}`} style={{ fontSize: "11px" }}>
                          {p.is_enabled ? "Enabled" : "Disabled"}
                        </span>
                      </td>

                      <td style={{ textAlign: "right" }}>
                        <div className="button-group" style={{ justifyContent: "flex-end" }}>
                          <button
                            className="secondary-button small"
                            onClick={() => handleCopyUri(p)}
                            title="Copy connection URI"
                          >
                            {copiedId === p.id ? "Copied!" : "Copy URI"}
                          </button>

                          {isAdmin && (
                            <>
                              <button
                                className="secondary-button small"
                                onClick={() => handleEdit(p)}
                                title="Edit configuration"
                              >
                                Edit
                              </button>

                              {!isSystemDefault && (
                                <button
                                  className="danger-button small"
                                  onClick={() => handleDeleteProfile(p)}
                                  title="Delete endpoint"
                                >
                                  Delete
                                </button>
                              )}
                            </>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Simulator Section & Reference Endpoints Guide (2 Balanced Columns) */}
      <section className="ingestion-dual-grid" aria-label="Simulator and Endpoints">
        {/* Live Packet Simulator */}
        <div className="simulator-panel">
          <div className="panel-header">
            <div>
              <h3>Live Ingestion Packet Simulator</h3>
              <p>Simulate uplinks via UDP, MQTT, TCP, or Webhook to test end-to-end ingestion and decoding.</p>
            </div>
            <span className="tag tag-ok" style={{ fontSize: "11px" }}>Microservice Test</span>
          </div>

          <form onSubmit={handleSimulate} style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px" }}>
              <div className="field">
                <label>Ingestion Protocol</label>
                <select
                  value={simProtocol}
                  onChange={(e) => setSimProtocol(e.target.value)}
                >
                  <option value="udp">UDP (Port 5001)</option>
                  <option value="mqtt">MQTT (Port 1883)</option>
                  <option value="tcp">TCP/IP (Port 1001)</option>
                  <option value="webhook">Webhook (Port 1002)</option>
                </select>
              </div>

              <div className="field">
                <label>Network Provider</label>
                <select
                  value={simProvider}
                  onChange={(e) => setSimProvider(e.target.value)}
                >
                  <option value="hubble">Hubble Network (NTN)</option>
                  <option value="skylo">Skylo (NTN)</option>
                  <option value="kineis">Kinéis (NTN)</option>
                  <option value="cellular">Cellular (TN)</option>
                  <option value="custom">Custom Provider</option>
                </select>
              </div>
            </div>

            <div className="field">
              <label>Device Identifier (EUI / Serial)</label>
              <input
                type="text"
                value={simDeviceId}
                onChange={(e) => setSimDeviceId(e.target.value)}
                placeholder="HUBBLE-DEV-001"
                required
              />
            </div>

            <div className="field">
              <label>Payload (Hex bytes or JSON string)</label>
              <input
                type="text"
                value={simPayload}
                onChange={(e) => setSimPayload(e.target.value)}
                placeholder="0102030405060708"
                required
              />
            </div>

            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", paddingTop: "6px" }}>
              <span style={{ fontSize: "11.5px", color: "var(--muted)" }}>
                Routes to: <code style={{ fontSize: "11px" }}>/ingest/internal-uplink</code>
              </span>
              <button
                type="submit"
                disabled={simLoading}
                className="primary-button small"
              >
                {simLoading ? "Sending Packet..." : "Send Test Uplink"}
              </button>
            </div>
          </form>

          {simResult && (
            <div style={{ padding: "12px", background: "var(--surface-2)", borderRadius: "var(--radius)", border: "1px solid var(--border)" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "6px" }}>
                <strong style={{ fontSize: "12px" }}>Simulation Result:</strong>
                <span className={`tag tag-${simResult.error ? "warn" : "ok"}`} style={{ fontSize: "10.5px" }}>
                  {simResult.error ? "FAILED" : "SUCCESS (ROUTED)"}
                </span>
              </div>
              <pre style={{ margin: 0, fontSize: "11px", overflowX: "auto", maxHeight: "140px", fontFamily: "var(--mono)" }}>
                {JSON.stringify(simResult, null, 2)}
              </pre>
            </div>
          )}
        </div>

        {/* Microservice Endpoints Reference */}
        <div className="reference-panel">
          <div className="panel-header">
            <div>
              <h3>Live Gateway Ingestion Endpoints ({liveHost})</h3>
              <p>Public connectivity details for third-party gateways and satellite networks (Hubble Network).</p>
            </div>
            <span className="tag tag-ok" style={{ fontSize: "11px", fontFamily: "var(--mono)" }}>
              {liveHost}
            </span>
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
            <div className="guide-item">
              <div className="guide-item-top">
                <strong>1. UDP Datagram Receiver</strong>
                <code>{liveHost}:5001</code>
              </div>
              <p>Target: <code>udp://{liveHost}:5001</code>. Send raw binary datagrams or hex frames.</p>
            </div>

            <div className="guide-item">
              <div className="guide-item-top">
                <strong>2. MQTT 3.1.1 Broker</strong>
                <code>{liveHost}:1883</code>
              </div>
              <p>Target: <code>mqtt://{liveHost}:1883</code>. Publish to: <code>devices/&#123;device_id&#125;/up</code>.</p>
            </div>

            <div className="guide-item">
              <div className="guide-item-top">
                <strong>3. TCP / IP Socket Stream</strong>
                <code>{liveHost}:1001</code>
              </div>
              <p>Target: <code>tcp://{liveHost}:1001</code>. Push newline-delimited JSON or hex strings.</p>
            </div>

            <div className="guide-item">
              <div className="guide-item-top">
                <strong>4. HTTPS Webhook REST Gateway (Hubble Network)</strong>
                <code>Port 443 (HTTPS)</code>
              </div>
              <p style={{ lineHeight: "1.5" }}>
                Hubble Webhook URL: <code>{liveOrigin}/webhooks/hubble</code> (with <code>HTTP-X-HUBBLE-TOKEN</code> secret)
                <br />
                Generic Webhook: <code>{liveOrigin}/webhook</code>
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* CREATE NEW ENDPOINT MODAL */}
      {showAddModal && (
        <div className="modal-backdrop">
          <div className="modal modal-wide">
            <div className="modal-header">
              <div>
                <h2>Create New Protocol Ingestion Endpoint</h2>
                <p>Configure a new UDP, MQTT, TCP/IP, or Webhook entry point for your network.</p>
              </div>
              <button
                type="button"
                className="secondary-button small"
                onClick={() => setShowAddModal(false)}
              >
                ✕
              </button>
            </div>

            <form onSubmit={handleCreateProfile}>
              <div className="modal-body" style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
                {/* Protocol Tabs */}
                <div className="field">
                  <label>Select Protocol</label>
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "10px" }}>
                    {Object.entries(PROTOCOL_CONFIG).map(([pKey, pCfg]) => (
                      <button
                        key={pKey}
                        type="button"
                        className={`secondary-button ${addForm.protocol === pKey ? "primary-button" : ""}`}
                        style={{ padding: "10px 8px", textAlign: "center", display: "flex", flexDirection: "column", gap: "3px" }}
                        onClick={() => {
                          setAddForm({
                            ...addForm,
                            protocol: pKey,
                            custom_path: pCfg.samplePath,
                            custom_port: addForm.use_default ? "" : String(pCfg.defaultPort),
                          });
                        }}
                      >
                        <strong style={{ fontSize: "13px" }}>{pCfg.shortLabel}</strong>
                        <small style={{ fontSize: "10.5px", opacity: 0.8, fontFamily: "var(--mono)" }}>Port {pCfg.defaultPort}</small>
                      </button>
                    ))}
                  </div>
                  <p className="field-hint" style={{ marginTop: "6px" }}>
                    {PROTOCOL_CONFIG[addForm.protocol]?.desc}
                  </p>
                </div>

                {/* Name and Code */}
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px" }}>
                  <div className="field">
                    <label>Endpoint Name</label>
                    <input
                      type="text"
                      value={addForm.name}
                      onChange={(e) => {
                        const val = e.target.value;
                        setAddForm({
                          ...addForm,
                          name: val,
                          code: addForm.code || `${addForm.protocol}_${val.toLowerCase().replace(/[^a-z0-9_-]/g, "_")}`,
                        });
                      }}
                      placeholder={`e.g. My ${PROTOCOL_CONFIG[addForm.protocol]?.shortLabel} Endpoint`}
                      required
                    />
                  </div>

                  <div className="field">
                    <label>Endpoint Code / Identifier</label>
                    <input
                      type="text"
                      value={addForm.code}
                      onChange={(e) => setAddForm({ ...addForm, code: e.target.value })}
                      placeholder="e.g. custom_udp_stream"
                      required
                    />
                  </div>
                </div>

                {/* Provider and Host */}
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px" }}>
                  <div className="field">
                    <label>Target Network Provider</label>
                    <select
                      value={addForm.network_profile_code}
                      onChange={(e) => setAddForm({ ...addForm, network_profile_code: e.target.value })}
                    >
                      <option value="all">Global (All Network Providers)</option>
                      {networkProfiles.map((np) => (
                        <option key={np.code} value={np.code}>
                          {np.name} ({np.code})
                        </option>
                      ))}
                    </select>
                  </div>

                  <div className="field">
                    <label>Host Binding</label>
                    <input
                      type="text"
                      value={addForm.host}
                      onChange={(e) => setAddForm({ ...addForm, host: e.target.value })}
                      placeholder="localhost"
                      required
                    />
                  </div>
                </div>

                {/* Value Mode Toggle */}
                <div className="credential-section" style={{ margin: 0 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
                    <strong style={{ fontSize: "13px" }}>
                      Port Mode: {addForm.use_default ? `Default Port (${PROTOCOL_CONFIG[addForm.protocol]?.defaultPort})` : "Admin-Provided Custom Port"}
                    </strong>
                    <button
                      type="button"
                      className="secondary-button small"
                      onClick={() => setAddForm({ ...addForm, use_default: !addForm.use_default })}
                    >
                      {addForm.use_default ? "Switch to Custom Port" : "Use Default Port"}
                    </button>
                  </div>
                  <p style={{ margin: 0, fontSize: "12px", color: "var(--muted)" }}>
                    {addForm.use_default
                      ? `Binds to protocol standard port ${PROTOCOL_CONFIG[addForm.protocol]?.defaultPort} on localhost.`
                      : "Specify a custom port number for this endpoint."}
                  </p>
                </div>

                {!addForm.use_default && (
                  <div className="field">
                    <label>Custom Port Number</label>
                    <input
                      type="number"
                      placeholder={`e.g. ${PROTOCOL_CONFIG[addForm.protocol]?.defaultPort + 1}`}
                      value={addForm.custom_port}
                      onChange={(e) => setAddForm({ ...addForm, custom_port: e.target.value })}
                      required
                    />
                  </div>
                )}

                {/* Path / Topic */}
                <div className="field">
                  <label>{PROTOCOL_CONFIG[addForm.protocol]?.pathLabel}</label>
                  <input
                    type="text"
                    value={addForm.custom_path}
                    onChange={(e) => setAddForm({ ...addForm, custom_path: e.target.value })}
                    placeholder={PROTOCOL_CONFIG[addForm.protocol]?.pathPlaceholder}
                  />
                </div>

                {/* Auth */}
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "10px" }}>
                  <div className="field">
                    <label>Authentication</label>
                    <select
                      value={addForm.auth_type}
                      onChange={(e) => setAddForm({ ...addForm, auth_type: e.target.value })}
                    >
                      <option value="none">None (Open)</option>
                      <option value="hubble_secret">Hubble Webhook Secret (HTTP-X-HUBBLE-TOKEN)</option>
                      <option value="basic_auth">Basic Auth</option>
                      <option value="token">Bearer Token</option>
                    </select>
                  </div>

                  <div className="field">
                    <label>Username / Key</label>
                    <input
                      type="text"
                      value={addForm.auth_username}
                      onChange={(e) => setAddForm({ ...addForm, auth_username: e.target.value })}
                      placeholder="Optional"
                      disabled={addForm.auth_type === "none" || addForm.auth_type === "hubble_secret"}
                    />
                  </div>

                  <div className="field">
                    <label>Password / Secret</label>
                    <input
                      type="password"
                      value={addForm.auth_password}
                      onChange={(e) => setAddForm({ ...addForm, auth_password: e.target.value })}
                      placeholder="Optional"
                      disabled={addForm.auth_type === "none" || addForm.auth_type === "hubble_secret"}
                    />
                  </div>
                </div>

                {/* Dedicated Hubble Webhook Secret when Webhook is chosen */}
                {(addForm.protocol === "webhook" || addForm.auth_type === "hubble_secret") && (
                  <div
                    className="field"
                    style={{
                      marginTop: "12px",
                      padding: "12px 14px",
                      background: "rgba(59, 130, 246, 0.08)",
                      border: "1px solid rgba(59, 130, 246, 0.25)",
                      borderRadius: "8px",
                    }}
                  >
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "6px" }}>
                      <label style={{ fontWeight: "600", color: "var(--text)", margin: 0 }}>
                        Hubble Webhook Secret
                      </label>
                      <span
                        style={{
                          fontSize: "11px",
                          fontFamily: "var(--mono)",
                          padding: "2px 8px",
                          borderRadius: "4px",
                          background: "rgba(59, 130, 246, 0.2)",
                          color: "#60a5fa",
                        }}
                      >
                        HTTP-X-HUBBLE-TOKEN
                      </span>
                    </div>
                    <input
                      type="text"
                      value={addForm.auth_token}
                      onChange={(e) => setAddForm({ ...addForm, auth_token: e.target.value, auth_type: addForm.auth_type === "none" ? "hubble_secret" : addForm.auth_type })}
                      placeholder="e.g. whsec_... (copied from Hubble Network Portal)"
                    />
                    <small style={{ color: "var(--muted)", fontSize: "11.5px", marginTop: "5px", display: "block", lineHeight: "1.4" }}>
                      Paste the webhook secret generated in your Hubble Network account. NibiaaNet will automatically authenticate incoming satellite packets carrying this secret in the <code>HTTP-X-HUBBLE-TOKEN</code> header.
                    </small>
                  </div>
                )}

                <div className="checkbox-field">
                  <input
                    type="checkbox"
                    id="add_endpoint_enabled"
                    checked={addForm.is_enabled}
                    onChange={(e) => setAddForm({ ...addForm, is_enabled: e.target.checked })}
                  />
                  <label htmlFor="add_endpoint_enabled">
                    Enable this endpoint immediately upon creation
                  </label>
                </div>
              </div>

              <div className="modal-footer">
                <button
                  type="button"
                  className="secondary-button"
                  onClick={() => setShowAddModal(false)}
                >
                  Cancel
                </button>
                <button type="submit" className="primary-button">
                  Create {PROTOCOL_CONFIG[addForm.protocol]?.shortLabel} Endpoint
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* EDIT INGESTION PROFILE MODAL */}
      {editingProfile && (
        <div className="modal-backdrop">
          <div className="modal modal-wide">
            <div className="modal-header">
              <div>
                <h2>Configure Ingestion Profile</h2>
                <p>Update settings for endpoint: <strong>{editingProfile.code}</strong></p>
              </div>
              <button
                type="button"
                className="secondary-button small"
                onClick={() => setEditingProfile(null)}
              >
                ✕
              </button>
            </div>

            <form onSubmit={handleSaveEdit}>
              <div className="modal-body" style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
                <div className="field">
                  <label>Profile Name</label>
                  <input
                    type="text"
                    value={editForm.name}
                    onChange={(e) => setEditForm({ ...editForm, name: e.target.value })}
                    required
                  />
                </div>

                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px" }}>
                  <div className="field">
                    <label>Protocol Type</label>
                    <select
                      value={editForm.protocol}
                      onChange={(e) => setEditForm({ ...editForm, protocol: e.target.value })}
                    >
                      <option value="udp">UDP Datagram</option>
                      <option value="mqtt">MQTT 3.1.1</option>
                      <option value="tcp">TCP/IP Socket</option>
                      <option value="webhook">HTTP Webhook</option>
                    </select>
                  </div>

                  <div className="field">
                    <label>Target Network Provider</label>
                    <select
                      value={editForm.network_profile_code}
                      onChange={(e) => setEditForm({ ...editForm, network_profile_code: e.target.value })}
                    >
                      <option value="all">Global (All Providers)</option>
                      {networkProfiles.map((np) => (
                        <option key={np.code} value={np.code}>
                          {np.name} ({np.code})
                        </option>
                      ))}
                    </select>
                  </div>
                </div>

                <div className="credential-section" style={{ margin: 0 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
                    <strong style={{ fontSize: "13px" }}>
                      Port Mode: {editForm.use_default ? `Default Port (${editingProfile.default_port})` : "Admin-Provided Custom Port"}
                    </strong>
                    <button
                      type="button"
                      className="secondary-button small"
                      onClick={() => setEditForm({ ...editForm, use_default: !editForm.use_default })}
                    >
                      {editForm.use_default ? "Switch to Custom Port" : "Use Default Port"}
                    </button>
                  </div>
                </div>

                {!editForm.use_default && (
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px" }}>
                    <div className="field">
                      <label>Admin Custom Port</label>
                      <input
                        type="number"
                        placeholder={`Default: ${editingProfile.default_port}`}
                        value={editForm.custom_port}
                        onChange={(e) => setEditForm({ ...editForm, custom_port: e.target.value })}
                      />
                    </div>
                    <div className="field">
                      <label>Host Binding</label>
                      <input
                        type="text"
                        value={editForm.host}
                        onChange={(e) => setEditForm({ ...editForm, host: e.target.value })}
                        placeholder="localhost"
                      />
                    </div>
                  </div>
                )}

                <div className="field">
                  <label>Custom Path or MQTT Topic</label>
                  <input
                    type="text"
                    value={editForm.custom_path}
                    onChange={(e) => setEditForm({ ...editForm, custom_path: e.target.value })}
                    placeholder="/webhook or devices/+/up"
                  />
                </div>

                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "10px" }}>
                  <div className="field">
                    <label>Auth Type</label>
                    <select
                      value={editForm.auth_type}
                      onChange={(e) => setEditForm({ ...editForm, auth_type: e.target.value })}
                    >
                      <option value="none">None (Open)</option>
                      <option value="hubble_secret">Hubble Webhook Secret (HTTP-X-HUBBLE-TOKEN)</option>
                      <option value="basic_auth">Basic Auth</option>
                      <option value="token">Bearer Token</option>
                    </select>
                  </div>

                  <div className="field">
                    <label>Auth Username</label>
                    <input
                      type="text"
                      value={editForm.auth_username}
                      onChange={(e) => setEditForm({ ...editForm, auth_username: e.target.value })}
                      placeholder="Optional"
                      disabled={editForm.auth_type === "none" || editForm.auth_type === "hubble_secret"}
                    />
                  </div>

                  <div className="field">
                    <label>Auth Password</label>
                    <input
                      type="password"
                      value={editForm.auth_password}
                      onChange={(e) => setEditForm({ ...editForm, auth_password: e.target.value })}
                      placeholder="Optional"
                      disabled={editForm.auth_type === "none" || editForm.auth_type === "hubble_secret"}
                    />
                  </div>
                </div>

                {/* Dedicated Hubble Webhook Secret when Webhook is chosen */}
                {(editForm.protocol === "webhook" || editForm.auth_type === "hubble_secret") && (
                  <div
                    className="field"
                    style={{
                      marginTop: "12px",
                      padding: "12px 14px",
                      background: "rgba(59, 130, 246, 0.08)",
                      border: "1px solid rgba(59, 130, 246, 0.25)",
                      borderRadius: "8px",
                    }}
                  >
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "6px" }}>
                      <label style={{ fontWeight: "600", color: "var(--text)", margin: 0 }}>
                        Hubble Webhook Secret
                      </label>
                      <span
                        style={{
                          fontSize: "11px",
                          fontFamily: "var(--mono)",
                          padding: "2px 8px",
                          borderRadius: "4px",
                          background: "rgba(59, 130, 246, 0.2)",
                          color: "#60a5fa",
                        }}
                      >
                        HTTP-X-HUBBLE-TOKEN
                      </span>
                    </div>
                    <input
                      type="text"
                      value={editForm.auth_token}
                      onChange={(e) => setEditForm({ ...editForm, auth_token: e.target.value, auth_type: editForm.auth_type === "none" ? "hubble_secret" : editForm.auth_type })}
                      placeholder={editForm.auth_token === "***" ? "•••••••• (unchanged)" : "e.g. whsec_... (copied from Hubble Network Portal)"}
                    />
                    <small style={{ color: "var(--muted)", fontSize: "11.5px", marginTop: "5px", display: "block", lineHeight: "1.4" }}>
                      Paste the webhook secret generated in your Hubble Network account. NibiaaNet will automatically authenticate incoming satellite packets carrying this secret in the <code>HTTP-X-HUBBLE-TOKEN</code> header.
                    </small>
                  </div>
                )}

                <div className="checkbox-field">
                  <input
                    type="checkbox"
                    id="edit_profile_enabled"
                    checked={editForm.is_enabled}
                    onChange={(e) => setEditForm({ ...editForm, is_enabled: e.target.checked })}
                  />
                  <label htmlFor="edit_profile_enabled">
                    Enabled (Allow uplinks through this ingestion endpoint)
                  </label>
                </div>
              </div>

              <div className="modal-footer">
                <button
                  type="button"
                  className="secondary-button"
                  onClick={() => setEditingProfile(null)}
                >
                  Cancel
                </button>
                <button type="submit" className="primary-button">
                  Save Changes
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
