import { useState, useEffect, useMemo } from "react";
import { PageHeader, Notice, Modal } from "./components";
import { formatDate } from "./api";

const CATEGORY_COLORS = {
  AUTH: { bg: "rgba(168, 85, 247, 0.15)", text: "#c084fc", border: "rgba(168, 85, 247, 0.3)" },
  SECURITY: { bg: "rgba(239, 68, 68, 0.15)", text: "#f87171", border: "rgba(239, 68, 68, 0.3)" },
  USER_MANAGEMENT: { bg: "rgba(59, 130, 246, 0.15)", text: "#60a5fa", border: "rgba(59, 130, 246, 0.3)" },
  ORGANIZATION: { bg: "rgba(6, 182, 212, 0.15)", text: "#22d3ee", border: "rgba(6, 182, 212, 0.3)" },
  APPLICATION: { bg: "rgba(99, 102, 241, 0.15)", text: "#818cf8", border: "rgba(99, 102, 241, 0.3)" },
  DEVICE: { bg: "rgba(16, 185, 129, 0.15)", text: "#34d399", border: "rgba(16, 185, 129, 0.3)" },
  DECODER: { bg: "rgba(245, 158, 11, 0.15)", text: "#fbbf24", border: "rgba(245, 158, 11, 0.3)" },
  TELEMETRY: { bg: "rgba(20, 184, 166, 0.15)", text: "#2dd4bf", border: "rgba(20, 184, 166, 0.3)" },
  SYSTEM: { bg: "rgba(148, 163, 184, 0.15)", text: "#94a3b8", border: "rgba(148, 163, 184, 0.3)" },
  GENERAL: { bg: "rgba(100, 116, 139, 0.15)", text: "#cbd5e1", border: "rgba(100, 116, 139, 0.3)" },
};

function CategoryBadge({ category }) {
  const cat = (category || "GENERAL").toUpperCase();
  const theme = CATEGORY_COLORS[cat] || CATEGORY_COLORS.GENERAL;
  return (
    <span
      style={{
        display: "inline-block",
        padding: "2px 8px",
        borderRadius: "4px",
        fontSize: "0.72rem",
        fontWeight: 700,
        letterSpacing: "0.03em",
        background: theme.bg,
        color: theme.text,
        border: `1px solid ${theme.border}`,
        whiteSpace: "nowrap",
      }}
    >
      {cat}
    </span>
  );
}

function StatusBadge({ status }) {
  const isOk = status?.toUpperCase() === "SUCCESS";
  const isFailed = status?.toUpperCase() === "FAILED";
  return (
    <span
      className={`pill ${isOk ? "pill-ok" : isFailed ? "pill-off" : "pill-warn"}`}
      style={{ fontSize: "0.75rem", padding: "2px 8px" }}
    >
      {status || "UNKNOWN"}
    </span>
  );
}

function AuditLogs({ api, currentUser }) {
  const [logs, setLogs] = useState([]);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState(null);

  // Filters
  const [category, setCategory] = useState("ALL");
  const [status, setStatus] = useState("ALL");
  const [search, setSearch] = useState("");
  const [limit, setLimit] = useState(100);

  // Selected Log for detail modal
  const [selectedLog, setSelectedLog] = useState(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    fetchLogs();
    fetchStats();
  }, [category, status, limit]);

  async function fetchLogs() {
    setLoading(true);
    setNotice(null);
    try {
      const params = new URLSearchParams();
      if (category && category !== "ALL") params.append("category", category);
      if (status && status !== "ALL") params.append("status", status);
      if (search.trim()) params.append("search", search.trim());
      params.append("limit", limit.toString());

      const res = await api.get(`/audit-logs/?${params.toString()}`);
      setLogs(res || []);
    } catch (err) {
      setNotice({ type: "error", text: err.message || "Failed to load audit logs" });
      setLogs([]);
    } finally {
      setLoading(false);
    }
  }

  async function fetchStats() {
    try {
      const s = await api.get("/audit-logs/stats");
      setStats(s);
    } catch {
      // stats failure is non-blocking
    }
  }

  function handleSearchSubmit(e) {
    e.preventDefault();
    fetchLogs();
  }

  function handleExportCsv() {
    const params = new URLSearchParams();
    if (category && category !== "ALL") params.append("category", category);
    if (status && status !== "ALL") params.append("status", status);
    if (search.trim()) params.append("search", search.trim());

    const token = localStorage.getItem("authToken");
    const url = `/api/audit-logs/export?${params.toString()}`;
    
    // Download through browser fetch with bearer token
    fetch(url, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((res) => {
        if (!res.ok) throw new Error("Export failed");
        return res.blob();
      })
      .then((blob) => {
        const downloadUrl = window.URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = downloadUrl;
        a.download = `nibiaanet_audit_logs_${new Date().toISOString().slice(0, 10)}.csv`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        window.URL.revokeObjectURL(downloadUrl);
      })
      .catch((err) => {
        setNotice({ type: "error", text: `Export failed: ${err.message}` });
      });
  }

  function formatDetailsJson(details) {
    if (!details) return "None";
    try {
      const parsed = typeof details === "string" ? JSON.parse(details) : details;
      return JSON.stringify(parsed, null, 2);
    } catch {
      return String(details);
    }
  }

  function copyDetailsToClipboard(text) {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <div className="page">
      <PageHeader
        title="Audit & Logs"
        description="Comprehensive audit trail recording all user authentication, system operations, resource creations, modifications, and security events."
      />

      <Notice notice={notice} />

      {/* METRIC CARDS */}
      <div className="stat-cards" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "14px", marginBottom: "20px" }}>
        <div className="card" style={{ padding: "16px", display: "flex", flexDirection: "column", gap: "4px" }}>
          <span style={{ fontSize: "0.8rem", color: "var(--text-muted, #94a3b8)", textTransform: "uppercase", fontWeight: 600 }}>Total Audit Events</span>
          <span style={{ fontSize: "1.8rem", fontWeight: 700, color: "var(--text, #f8fafc)" }}>
            {stats ? stats.total_logs : logs.length}
          </span>
          <span style={{ fontSize: "0.75rem", color: "var(--text-secondary, #64748b)" }}>Recorded in platform audit ledger</span>
        </div>

        <div className="card" style={{ padding: "16px", display: "flex", flexDirection: "column", gap: "4px" }}>
          <span style={{ fontSize: "0.8rem", color: "#34d399", textTransform: "uppercase", fontWeight: 600 }}>Successful Operations</span>
          <span style={{ fontSize: "1.8rem", fontWeight: 700, color: "#34d399" }}>
            {stats ? stats.success_count : logs.filter((l) => l.status === "SUCCESS").length}
          </span>
          <span style={{ fontSize: "0.75rem", color: "var(--text-secondary, #64748b)" }}>Authorized state changes</span>
        </div>

        <div className="card" style={{ padding: "16px", display: "flex", flexDirection: "column", gap: "4px" }}>
          <span style={{ fontSize: "0.8rem", color: "#f87171", textTransform: "uppercase", fontWeight: 600 }}>Security / Failed</span>
          <span style={{ fontSize: "1.8rem", fontWeight: 700, color: "#f87171" }}>
            {stats ? stats.failed_count : logs.filter((l) => l.status === "FAILED").length}
          </span>
          <span style={{ fontSize: "0.75rem", color: "var(--text-secondary, #64748b)" }}>Failed logins & denied requests</span>
        </div>

        <div className="card" style={{ padding: "16px", display: "flex", flexDirection: "column", gap: "4px" }}>
          <span style={{ fontSize: "0.8rem", color: "#60a5fa", textTransform: "uppercase", fontWeight: 600 }}>Past 24 Hours</span>
          <span style={{ fontSize: "1.8rem", fontWeight: 700, color: "#60a5fa" }}>
            {stats ? stats.actions_today : "-"}
          </span>
          <span style={{ fontSize: "0.75rem", color: "var(--text-secondary, #64748b)" }}>Recent activity in ledger</span>
        </div>
      </div>

      {/* FILTER CONTROLS */}
      <section className="card" style={{ marginBottom: "20px" }}>
        <div style={{ display: "flex", flexWrap: "wrap", gap: "12px", alignItems: "center", justifyContent: "space-between" }}>
          {/* Search Form */}
          <form onSubmit={handleSearchSubmit} style={{ display: "flex", gap: "8px", flex: "1 1 280px", minWidth: "220px" }}>
            <input
              type="text"
              placeholder="Search user, action, resource, details, IP..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              style={{ flex: 1, padding: "8px 12px", fontSize: "0.85rem" }}
            />
            <button type="submit" className="primary-button small">
              Search
            </button>
            {search && (
              <button
                type="button"
                className="secondary-button small"
                onClick={() => { setSearch(""); fetchLogs(); }}
              >
                Clear
              </button>
            )}
          </form>

          {/* Dropdown Filters */}
          <div style={{ display: "flex", gap: "10px", flexWrap: "wrap", alignItems: "center" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
              <label style={{ fontSize: "0.8rem", color: "var(--text-muted, #94a3b8)", whiteSpace: "nowrap" }}>Category:</label>
              <select
                value={category}
                onChange={(e) => setCategory(e.target.value)}
                style={{ padding: "6px 10px", fontSize: "0.85rem", width: "auto" }}
              >
                <option value="ALL">All Categories</option>
                <option value="AUTH">Authentication (AUTH)</option>
                <option value="SECURITY">Security (SECURITY)</option>
                <option value="USER_MANAGEMENT">User Management</option>
                <option value="ORGANIZATION">Organization</option>
                <option value="APPLICATION">Application</option>
                <option value="DEVICE">Device</option>
                <option value="DECODER">Decoder</option>
                <option value="TELEMETRY">Telemetry</option>
                <option value="SYSTEM">System</option>
              </select>
            </div>

            <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
              <label style={{ fontSize: "0.8rem", color: "var(--text-muted, #94a3b8)", whiteSpace: "nowrap" }}>Status:</label>
              <select
                value={status}
                onChange={(e) => setStatus(e.target.value)}
                style={{ padding: "6px 10px", fontSize: "0.85rem", width: "auto" }}
              >
                <option value="ALL">All Statuses</option>
                <option value="SUCCESS">Success</option>
                <option value="FAILED">Failed</option>
              </select>
            </div>

            <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
              <label style={{ fontSize: "0.8rem", color: "var(--text-muted, #94a3b8)", whiteSpace: "nowrap" }}>Limit:</label>
              <select
                value={limit}
                onChange={(e) => setLimit(Number(e.target.value))}
                style={{ padding: "6px 10px", fontSize: "0.85rem", width: "auto" }}
              >
                <option value={50}>50</option>
                <option value={100}>100</option>
                <option value={250}>250</option>
                <option value={500}>500</option>
              </select>
            </div>

            <button
              type="button"
              className="secondary-button small"
              onClick={() => { fetchLogs(); fetchStats(); }}
              disabled={loading}
              title="Refresh audit logs"
            >
              {loading ? "Refreshing..." : "↻ Refresh"}
            </button>

            <button
              type="button"
              className="secondary-button small"
              onClick={handleExportCsv}
              title="Export current audit logs to CSV"
            >
              📥 Export CSV
            </button>
          </div>
        </div>
      </section>

      {/* AUDIT LOGS TABLE */}
      <section className="card">
        <div className="section-header" style={{ marginBottom: "12px" }}>
          <div>
            <h2 style={{ fontSize: "1.1rem", margin: 0 }}>Audit Activity Ledger</h2>
            <p style={{ margin: "4px 0 0 0", fontSize: "0.8rem", color: "var(--text-muted, #94a3b8)" }}>
              Displaying {logs.length} audit record(s) ordered by timestamp (newest first).
            </p>
          </div>
        </div>

        {loading && logs.length === 0 ? (
          <div className="empty-state">Loading audit logs...</div>
        ) : logs.length === 0 ? (
          <div className="empty-state">No audit logs matching the selected filters.</div>
        ) : (
          <div className="table-container">
            <table>
              <thead>
                <tr>
                  <th>Timestamp</th>
                  <th>User / Actor</th>
                  <th>Category</th>
                  <th>Action</th>
                  <th>Resource</th>
                  <th>Status</th>
                  <th>IP Address</th>
                  <th>Details</th>
                </tr>
              </thead>
              <tbody>
                {logs.map((log) => (
                  <tr
                    key={log.id}
                    onClick={() => setSelectedLog(log)}
                    style={{ cursor: "pointer" }}
                    title="Click to view complete audit details"
                  >
                    <td style={{ whiteSpace: "nowrap", fontSize: "0.82rem", color: "#cbd5e1" }}>
                      {formatDate(log.timestamp)}
                    </td>
                    <td>
                      <div style={{ display: "flex", flexDirection: "column" }}>
                        <strong>{log.user_name || "System"}</strong>
                        {log.tenant_name && (
                          <span style={{ fontSize: "0.72rem", color: "var(--text-muted, #94a3b8)" }}>
                            {log.tenant_name}
                          </span>
                        )}
                      </div>
                    </td>
                    <td>
                      <CategoryBadge category={log.category} />
                    </td>
                    <td>
                      <code style={{ fontSize: "0.8rem", fontWeight: 600 }}>{log.action}</code>
                    </td>
                    <td>
                      {log.resource_type ? (
                        <span style={{ fontSize: "0.82rem" }}>
                          <span style={{ color: "var(--text-muted, #94a3b8)" }}>{log.resource_type}: </span>
                          <strong>{log.resource_id || "-"}</strong>
                        </span>
                      ) : (
                        <span className="muted">—</span>
                      )}
                    </td>
                    <td>
                      <StatusBadge status={log.status} />
                    </td>
                    <td style={{ fontSize: "0.8rem", fontFamily: "monospace", color: "#94a3b8" }}>
                      {log.ip_address || "—"}
                    </td>
                    <td>
                      <button
                        type="button"
                        className="secondary-button small"
                        style={{ padding: "2px 8px", fontSize: "0.75rem" }}
                        onClick={(e) => {
                          e.stopPropagation();
                          setSelectedLog(log);
                        }}
                      >
                        Inspect
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* DETAIL MODAL */}
      {selectedLog && (
        <Modal
          title={`Audit Event #${selectedLog.id} — ${selectedLog.action}`}
          onClose={() => setSelectedLog(null)}
        >
          <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: "10px", padding: "12px", background: "var(--surface-2, rgba(255,255,255,0.03))", borderRadius: "8px" }}>
              <div>
                <span className="small-text muted">Timestamp (UTC):</span>
                <div style={{ fontWeight: 600, fontSize: "0.85rem" }}>{formatDate(selectedLog.timestamp)}</div>
              </div>
              <div>
                <span className="small-text muted">Status:</span>
                <div><StatusBadge status={selectedLog.status} /></div>
              </div>
              <div>
                <span className="small-text muted">Category:</span>
                <div><CategoryBadge category={selectedLog.category} /></div>
              </div>
              <div>
                <span className="small-text muted">Actor / User:</span>
                <div style={{ fontWeight: 600, fontSize: "0.85rem" }}>
                  {selectedLog.user_name || "System"} {selectedLog.user_id ? `(ID: ${selectedLog.user_id})` : ""}
                </div>
              </div>
              <div>
                <span className="small-text muted">Organization:</span>
                <div style={{ fontWeight: 600, fontSize: "0.85rem" }}>
                  {selectedLog.tenant_name || (selectedLog.tenant_id ? `Tenant ${selectedLog.tenant_id}` : "Global / System")}
                </div>
              </div>
              <div>
                <span className="small-text muted">IP Address:</span>
                <div style={{ fontFamily: "monospace", fontSize: "0.85rem" }}>{selectedLog.ip_address || "Not recorded"}</div>
              </div>
              <div>
                <span className="small-text muted">Target Resource:</span>
                <div style={{ fontWeight: 600, fontSize: "0.85rem" }}>
                  {selectedLog.resource_type || "N/A"} {selectedLog.resource_id ? `(${selectedLog.resource_id})` : ""}
                </div>
              </div>
            </div>

            <div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "6px" }}>
                <span style={{ fontSize: "0.85rem", fontWeight: 600 }}>Event Payload / Context Details</span>
                {selectedLog.details && (
                  <button
                    type="button"
                    className="secondary-button small"
                    onClick={() => copyDetailsToClipboard(formatDetailsJson(selectedLog.details))}
                    style={{ fontSize: "0.75rem", padding: "2px 8px" }}
                  >
                    {copied ? "✓ Copied" : "Copy JSON"}
                  </button>
                )}
              </div>
              <pre
                className="code-view"
                style={{
                  maxHeight: "260px",
                  overflowY: "auto",
                  padding: "12px",
                  fontSize: "0.82rem",
                  background: "#0f172a",
                  borderRadius: "6px",
                  border: "1px solid var(--border-color, #334155)",
                }}
              >
                {formatDetailsJson(selectedLog.details)}
              </pre>
            </div>

            <div style={{ display: "flex", justifyContent: "flex-end" }}>
              <button
                type="button"
                className="secondary-button"
                onClick={() => setSelectedLog(null)}
              >
                Close
              </button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}

export default AuditLogs;
