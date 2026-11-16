import { useEffect, useState } from "react";
import { Notice, PageHeader } from "./components";
import { IAM_API, createApi } from "./api";

export default function Attributes({ api, currentUser }) {
  const [activeTab, setActiveTab] = useState("definitions");
  const [definitions, setDefinitions] = useState([]);
  const [policies, setPolicies] = useState([]);
  const [users, setUsers] = useState([]);
  const [notice, setNotice] = useState(null);
  const [loading, setLoading] = useState(false);

  // Dedicated IAM API client
  const iamApi = createApi(api ? api.token : "", null, IAM_API);

  function getAuthHeaders() {
    const token =
      (api && api.token) ||
      sessionStorage.getItem("authToken") ||
      localStorage.getItem("authToken") ||
      "";
    return {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    };
  }

  // --- Definition Form State ---
  const [defForm, setDefForm] = useState({
    key: "",
    name: "",
    description: "",
    entity_type: "user",
    data_type: "string",
    allowed_values: "",
    default_value: "",
    is_required: false,
  });

  // --- User Attribute Assignment State ---
  const [selectedUser, setSelectedUser] = useState("");
  const [userAttributes, setUserAttributes] = useState({});
  const [newAttrKey, setNewAttrKey] = useState("");
  const [newAttrVal, setNewAttrVal] = useState("");

  // --- Policy Simulator State ---
  const [simUser, setSimUser] = useState("");
  const [simAction, setSimAction] = useState("devices:command");
  const [simResType, setSimResType] = useState("device");
  const [simResAttrs, setSimResAttrs] = useState('{"region": "GLOBAL"}');
  const [simCtxAttrs, setSimCtxAttrs] = useState('{"ip": "192.168.1.1"}');
  const [simResult, setSimResult] = useState(null);

  useEffect(() => {
    fetchDefinitions();
    fetchPolicies();
    fetchUsers();
  }, []);

  async function fetchDefinitions() {
    try {
      const res = await fetch(`${IAM_API}/attributes/definitions`, {
        headers: getAuthHeaders(),
      });
      if (res.ok) {
        setDefinitions(await res.json());
      }
    } catch (e) {
      console.warn("Could not fetch definitions from IAM service:", e);
    }
  }

  async function fetchPolicies() {
    try {
      const res = await fetch(`${IAM_API}/abac/policies`, {
        headers: getAuthHeaders(),
      });
      if (res.ok) {
        setPolicies(await res.json());
      }
    } catch (e) {
      console.warn("Could not fetch ABAC policies:", e);
    }
  }

  async function fetchUsers() {
    try {
      const res = await fetch(`${IAM_API}/users/`, {
        headers: getAuthHeaders(),
      });
      if (res.ok) {
        setUsers(await res.json());
      } else {
        const fallback = await api.get("/users/");
        setUsers(fallback || []);
      }
    } catch (e) {
      try {
        const fallback = await api.get("/users/");
        setUsers(fallback || []);
      } catch (err) {}
    }
  }

  async function createDefinition(e) {
    e.preventDefault();
    setNotice(null);
    try {
      const cleanKey = (defForm.key || "")
        .trim()
        .toLowerCase()
        .replace(/\s+/g, "_")
        .replace(/[^a-z0-9_\-\.]/g, "");

      const cleanName = (defForm.name || "").trim();

      if (cleanKey.length < 2) {
        throw new Error("Key Name must be at least 2 characters long (letters, numbers, underscore, dash).");
      }
      if (cleanName.length < 2) {
        throw new Error("Display Name must be at least 2 characters long.");
      }

      let allowed = null;
      if (defForm.data_type === "enum") {
        if (!defForm.allowed_values || !defForm.allowed_values.trim()) {
          throw new Error("Enum data type requires at least one allowed value (comma-separated).");
        }
        allowed = defForm.allowed_values.split(",").map((s) => s.trim()).filter(Boolean);
      }

      const payload = {
        key: cleanKey,
        name: cleanName,
        description: (defForm.description || "").trim() || null,
        entity_type: defForm.entity_type,
        data_type: defForm.data_type,
        allowed_values: allowed,
        default_value: (defForm.default_value || "").trim() || null,
        is_required: Boolean(defForm.is_required),
      };

      const res = await fetch(`${IAM_API}/attributes/definitions`, {
        method: "POST",
        headers: getAuthHeaders(),
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        let errorText = "Failed to create definition";
        try {
          const err = await res.json();
          if (Array.isArray(err.detail)) {
            errorText = err.detail.map((d) => d.msg || JSON.stringify(d)).join(", ");
          } else if (typeof err.detail === "string") {
            errorText = err.detail;
          }
        } catch (_) {
          errorText = res.statusText || errorText;
        }
        throw new Error(errorText);
      }

      setNotice({ type: "success", text: `Attribute definition '${cleanKey}' created successfully.` });
      setDefForm({
        key: "",
        name: "",
        description: "",
        entity_type: "user",
        data_type: "string",
        allowed_values: "",
        default_value: "",
        is_required: false,
      });
      fetchDefinitions();
    } catch (err) {
      setNotice({ type: "error", text: err.message });
    }
  }

  async function deleteDefinition(defId, key) {
    if (!window.confirm(`Delete attribute definition '${key}'?`)) return;
    try {
      const res = await fetch(`${IAM_API}/attributes/definitions/${defId}`, {
        method: "DELETE",
        headers: getAuthHeaders(),
      });
      if (!res.ok) {
        let errorText = "Delete failed";
        try {
          const err = await res.json();
          errorText = typeof err.detail === "string" ? err.detail : JSON.stringify(err.detail);
        } catch (_) {}
        throw new Error(errorText);
      }
      setNotice({ type: "success", text: `Attribute definition '${key}' deleted.` });
      fetchDefinitions();
    } catch (err) {
      setNotice({ type: "error", text: err.message });
    }
  }

  async function loadUserAttributes(userId) {
    setSelectedUser(userId);
    if (!userId) {
      setUserAttributes({});
      return;
    }
    try {
      const res = await fetch(`${IAM_API}/users/${userId}/attributes`, {
        headers: getAuthHeaders(),
      });
      if (res.ok) {
        setUserAttributes(await res.json());
      }
    } catch (err) {
      setUserAttributes({});
    }
  }

  async function saveUserAttribute(e) {
    e.preventDefault();
    if (!selectedUser || !newAttrKey) return;
    try {
      let val = newAttrVal;
      // Auto cast if number or bool
      if (!isNaN(Number(val)) && val.trim() !== "") {
        val = Number(val);
      } else if (val.toLowerCase() === "true") {
        val = true;
      } else if (val.toLowerCase() === "false") {
        val = false;
      }

      const res = await fetch(`${IAM_API}/attributes/entities/user/${selectedUser}`, {
        method: "POST",
        headers: getAuthHeaders(),
        body: JSON.stringify({ key: newAttrKey.trim(), value: val }),
      });
      if (!res.ok) {
        let errorText = "Failed to set attribute";
        try {
          const err = await res.json();
          errorText = typeof err.detail === "string" ? err.detail : JSON.stringify(err.detail);
        } catch (_) {}
        throw new Error(errorText);
      }
      setNotice({ type: "success", text: `Attribute '${newAttrKey}' updated for user #${selectedUser}.` });
      setNewAttrKey("");
      setNewAttrVal("");
      loadUserAttributes(selectedUser);
    } catch (err) {
      setNotice({ type: "error", text: err.message });
    }
  }

  async function deleteUserAttribute(key) {
    try {
      const res = await fetch(`${IAM_API}/attributes/entities/user/${selectedUser}/${key}`, {
        method: "DELETE",
        headers: getAuthHeaders(),
      });
      if (!res.ok) throw new Error("Failed to delete attribute");
      loadUserAttributes(selectedUser);
    } catch (err) {
      setNotice({ type: "error", text: err.message });
    }
  }

  async function runSimulation(e) {
    e.preventDefault();
    setSimResult(null);
    try {
      let parsedResAttrs = {};
      let parsedCtxAttrs = {};
      try {
        if (simResAttrs) parsedResAttrs = JSON.parse(simResAttrs);
        if (simCtxAttrs) parsedCtxAttrs = JSON.parse(simCtxAttrs);
      } catch (jsonErr) {
        throw new Error("Invalid JSON in resource or context attributes");
      }

      const payload = {
        user_id: simUser ? Number(simUser) : undefined,
        action: simAction,
        resource_type: simResType,
        resource_attributes: parsedResAttrs,
        context_attributes: parsedCtxAttrs,
      };

      const res = await fetch(`${IAM_API}/abac/evaluate`, {
        method: "POST",
        headers: getAuthHeaders(),
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      setSimResult(data);
    } catch (err) {
      setNotice({ type: "error", text: err.message });
    }
  }

  return (
    <div className="page">
      <PageHeader
        title="Attribute & ABAC Management"
        description="Fine-grained Attribute-Based Access Control, dynamic metadata schemas, and real-time policy evaluation."
      />

      {notice && (
        <div style={{ marginBottom: "1rem" }}>
          <Notice type={notice.type} message={notice.text} />
        </div>
      )}

      {/* Segmented Control Tabs */}
      <div className="iam-tabs-bar">
        <button
          type="button"
          className={`iam-tab-btn ${activeTab === "definitions" ? "active" : ""}`}
          onClick={() => setActiveTab("definitions")}
        >
          <span className="iam-tab-icon">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z" />
              <line x1="7" y1="7" x2="7.01" y2="7" />
            </svg>
          </span>
          <span>Attribute Schema Catalog</span>
          {definitions.length > 0 && <span className="iam-tab-badge">{definitions.length}</span>}
        </button>

        <button
          type="button"
          className={`iam-tab-btn ${activeTab === "assignments" ? "active" : ""}`}
          onClick={() => setActiveTab("assignments")}
        >
          <span className="iam-tab-icon">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
              <circle cx="12" cy="7" r="4" />
            </svg>
          </span>
          <span>User Attribute Profiles</span>
          {users.length > 0 && <span className="iam-tab-badge">{users.length}</span>}
        </button>

        <button
          type="button"
          className={`iam-tab-btn ${activeTab === "policies" ? "active" : ""}`}
          onClick={() => setActiveTab("policies")}
        >
          <span className="iam-tab-icon">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
            </svg>
          </span>
          <span>ABAC Policies</span>
          {policies.length > 0 && <span className="iam-tab-badge">{policies.length}</span>}
        </button>

        <button
          type="button"
          className={`iam-tab-btn ${activeTab === "simulator" ? "active" : ""}`}
          onClick={() => setActiveTab("simulator")}
        >
          <span className="iam-tab-icon">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polygon points="5 3 19 12 5 21 5 3" />
            </svg>
          </span>
          <span>PDP Policy Simulator</span>
        </button>
      </div>

      {/* ----------------- TAB 1: DEFINITIONS ----------------- */}
      {activeTab === "definitions" && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1.5rem" }}>
          <section className="card">
            <h3 style={{ margin: "0 0 1rem" }}>Registered Attributes ({definitions.length})</h3>
            <div style={{ overflowX: "auto" }}>
              <table className="table" style={{ width: "100%", fontSize: "0.9rem" }}>
                <thead>
                  <tr>
                    <th>Key</th>
                    <th>Name</th>
                    <th>Entity</th>
                    <th>Type</th>
                    <th>Default</th>
                    <th>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {definitions.map((d) => (
                    <tr key={d.id}>
                      <td><code>{d.key}</code></td>
                      <td>{d.name}</td>
                      <td><span className="badge" style={{ textTransform: "uppercase" }}>{d.entity_type}</span></td>
                      <td><code>{d.data_type}</code></td>
                      <td>{d.default_value || "—"}</td>
                      <td>
                        {!d.is_system ? (
                          <button
                            type="button"
                            className="danger-button small"
                            onClick={() => deleteDefinition(d.id, d.key)}
                          >
                            Delete
                          </button>
                        ) : (
                          <span style={{ color: "#94a3b8", fontSize: "0.75rem" }}>System</span>
                        )}
                      </td>
                    </tr>
                  ))}
                  {definitions.length === 0 && (
                    <tr>
                      <td colSpan={6} style={{ textAlign: "center", color: "#64748b" }}>
                        No attribute definitions registered yet.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </section>

          <section className="card">
            <h3 style={{ margin: "0 0 1rem" }}>Register New Attribute</h3>
            <form onSubmit={createDefinition} style={{ display: "flex", flexDirection: "column", gap: "0.8rem" }}>
              <div className="form-group">
                <label>Key Name (lowercase alphanumeric & underscores: e.g. clearance_level)</label>
                <input
                  type="text"
                  required
                  value={defForm.key}
                  onChange={(e) =>
                    setDefForm({
                      ...defForm,
                      key: e.target.value.toLowerCase().replace(/\s+/g, "_").replace(/[^a-z0-9_\-\.]/g, ""),
                    })
                  }
                  placeholder="e.g. clearance_level"
                  className="input"
                />
              </div>

              <div className="form-group">
                <label>Display Name</label>
                <input
                  type="text"
                  required
                  value={defForm.name}
                  onChange={(e) => setDefForm({ ...defForm, name: e.target.value })}
                  placeholder="e.g. Security Clearance Level"
                  className="input"
                />
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.8rem" }}>
                <div className="form-group">
                  <label>Entity Target</label>
                  <select
                    value={defForm.entity_type}
                    onChange={(e) => setDefForm({ ...defForm, entity_type: e.target.value })}
                    className="input"
                  >
                    <option value="user">User</option>
                    <option value="resource">Resource / Device</option>
                    <option value="tenant">Workspace / Tenant</option>
                    <option value="environment">Environment / Context</option>
                  </select>
                </div>

                <div className="form-group">
                  <label>Data Type</label>
                  <select
                    value={defForm.data_type}
                    onChange={(e) => setDefForm({ ...defForm, data_type: e.target.value })}
                    className="input"
                  >
                    <option value="string">String</option>
                    <option value="number">Number</option>
                    <option value="boolean">Boolean</option>
                    <option value="enum">Enum (Allowed list)</option>
                    <option value="json">JSON / List</option>
                  </select>
                </div>
              </div>

              {defForm.data_type === "enum" && (
                <div className="form-group">
                  <label>Allowed Values (comma-separated)</label>
                  <input
                    type="text"
                    value={defForm.allowed_values}
                    onChange={(e) => setDefForm({ ...defForm, allowed_values: e.target.value })}
                    placeholder="e.g. engineering, operations, security"
                    className="input"
                  />
                </div>
              )}

              <div className="form-group">
                <label>Default Value (Optional)</label>
                <input
                  type="text"
                  value={defForm.default_value}
                  onChange={(e) => setDefForm({ ...defForm, default_value: e.target.value })}
                  placeholder="e.g. 1"
                  className="input"
                />
              </div>

              <div className="form-group">
                <label>Description</label>
                <textarea
                  rows={2}
                  value={defForm.description}
                  onChange={(e) => setDefForm({ ...defForm, description: e.target.value })}
                  placeholder="Purpose of this attribute..."
                  className="input"
                />
              </div>

              <button type="submit" className="primary-button" style={{ marginTop: "0.5rem" }}>
                Add Attribute Definition
              </button>
            </form>
          </section>
        </div>
      )}

      {/* ----------------- TAB 2: USER ASSIGNMENTS ----------------- */}
      {activeTab === "assignments" && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1.5rem" }}>
          <section className="card">
            <h3 style={{ margin: "0 0 1rem" }}>Select User Account</h3>
            <div className="form-group" style={{ marginBottom: "1.5rem" }}>
              <select
                className="input"
                value={selectedUser}
                onChange={(e) => loadUserAttributes(e.target.value)}
              >
                <option value="">-- Choose a user to inspect/assign attributes --</option>
                {users.map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.name} ({u.email || "no-email"}) — {u.role}
                  </option>
                ))}
              </select>
            </div>

            {selectedUser && (
              <>
                <h4>Resolved Attributes for User #{selectedUser}</h4>
                <div style={{ marginTop: "0.5rem" }}>
                  {Object.entries(userAttributes).length === 0 ? (
                    <p style={{ color: "#64748b" }}>No custom attributes currently assigned to this user.</p>
                  ) : (
                    <table className="table" style={{ width: "100%", fontSize: "0.9rem" }}>
                      <thead>
                        <tr>
                          <th>Attribute Key</th>
                          <th>Value</th>
                          <th>Action</th>
                        </tr>
                      </thead>
                      <tbody>
                        {Object.entries(userAttributes).map(([k, v]) => (
                          <tr key={k}>
                            <td><code>{k}</code></td>
                            <td><strong>{String(v)}</strong></td>
                            <td>
                              <button
                                type="button"
                                className="danger-button small"
                                onClick={() => deleteUserAttribute(k)}
                              >
                                Remove
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
              </>
            )}
          </section>

          <section className="card">
            <h3 style={{ margin: "0 0 1rem" }}>Assign / Update Attribute</h3>
            {selectedUser ? (
              <form onSubmit={saveUserAttribute} style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
                <div className="form-group">
                  <label>Select Attribute Definition</label>
                  <select
                    className="input"
                    value={newAttrKey}
                    onChange={(e) => {
                      setNewAttrKey(e.target.value);
                      const d = definitions.find((x) => x.key === e.target.value);
                      if (d && d.default_value) setNewAttrVal(d.default_value);
                    }}
                    required
                  >
                    <option value="">-- Choose attribute --</option>
                    {definitions
                      .filter((d) => d.entity_type === "user")
                      .map((d) => (
                        <option key={d.key} value={d.key}>
                          {d.name} ({d.key}) [{d.data_type}]
                        </option>
                      ))}
                  </select>
                </div>

                <div className="form-group">
                  <label>Attribute Value</label>
                  <input
                    type="text"
                    required
                    className="input"
                    value={newAttrVal}
                    onChange={(e) => setNewAttrVal(e.target.value)}
                    placeholder="Enter value (e.g. 2, operations, true)"
                  />
                </div>

                <button type="submit" className="primary-button">
                  Save Attribute Value
                </button>
              </form>
            ) : (
              <p style={{ color: "#64748b" }}>Please select a user account on the left to assign attributes.</p>
            )}
          </section>
        </div>
      )}

      {/* ----------------- TAB 3: ABAC POLICIES ----------------- */}
      {activeTab === "policies" && (
        <section className="card">
          <h3 style={{ margin: "0 0 1rem" }}>Active ABAC Policies ({policies.length})</h3>
          <div style={{ overflowX: "auto" }}>
            <table className="table" style={{ width: "100%", fontSize: "0.88rem" }}>
              <thead>
                <tr>
                  <th>Effect</th>
                  <th>Priority</th>
                  <th>Policy Name</th>
                  <th>Target Actions</th>
                  <th>Target Resources</th>
                  <th>Subject Conditions</th>
                  <th>Resource Conditions</th>
                </tr>
              </thead>
              <tbody>
                {policies.map((p) => (
                  <tr key={p.id}>
                    <td>
                      <span className={`badge ${p.effect === "DENY" ? "badge-danger" : "badge-success"}`}>
                        {p.effect}
                      </span>
                    </td>
                    <td><strong>{p.priority}</strong></td>
                    <td>
                      <div><strong>{p.name}</strong></div>
                      <div style={{ fontSize: "0.75rem", color: "#64748b" }}>{p.description}</div>
                    </td>
                    <td><code>{JSON.stringify(p.target_actions)}</code></td>
                    <td><code>{JSON.stringify(p.target_resource_types)}</code></td>
                    <td><code>{JSON.stringify(p.subject_conditions)}</code></td>
                    <td><code>{JSON.stringify(p.resource_conditions)}</code></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* ----------------- TAB 4: PDP SIMULATOR ----------------- */}
      {activeTab === "simulator" && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1.5rem" }}>
          <section className="card">
            <h3 style={{ margin: "0 0 1rem" }}>Policy Decision Point (PDP) Playground</h3>
            <form onSubmit={runSimulation} style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
              <div className="form-group">
                <label>Evaluate Subject (User)</label>
                <select
                  className="input"
                  value={simUser}
                  onChange={(e) => setSimUser(e.target.value)}
                >
                  <option value="">-- Anonymous / Tokenless --</option>
                  {users.map((u) => (
                    <option key={u.id} value={u.id}>
                      {u.name} ({u.role})
                    </option>
                  ))}
                </select>
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.8rem" }}>
                <div className="form-group">
                  <label>Action Requested</label>
                  <input
                    type="text"
                    required
                    className="input"
                    value={simAction}
                    onChange={(e) => setSimAction(e.target.value)}
                    placeholder="e.g. devices:command"
                  />
                </div>

                <div className="form-group">
                  <label>Resource Type</label>
                  <input
                    type="text"
                    required
                    className="input"
                    value={simResType}
                    onChange={(e) => setSimResType(e.target.value)}
                    placeholder="e.g. device"
                  />
                </div>
              </div>

              <div className="form-group">
                <label>Resource Attributes (JSON)</label>
                <textarea
                  rows={2}
                  className="input"
                  value={simResAttrs}
                  onChange={(e) => setSimResAttrs(e.target.value)}
                />
              </div>

              <div className="form-group">
                <label>Context / Environmental Attributes (JSON)</label>
                <textarea
                  rows={2}
                  className="input"
                  value={simCtxAttrs}
                  onChange={(e) => setSimCtxAttrs(e.target.value)}
                />
              </div>

              <button type="submit" className="primary-button" style={{ background: "linear-gradient(135deg, #10b981 0%, #047857 100%)", boxShadow: "0 4px 14px rgba(16, 185, 129, 0.35)" }}>
                Evaluate Access Decision (PDP)
              </button>
            </form>
          </section>

          <section className="card">
            <h3 style={{ margin: "0 0 1rem" }}>Decision Result</h3>
            {simResult ? (
              <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
                <div
                  style={{
                    padding: "1rem",
                    borderRadius: "8px",
                    background: simResult.allowed ? "#f0fdf4" : "#fef2f2",
                    border: `1px solid ${simResult.allowed ? "#86efac" : "#fca5a5"}`,
                  }}
                >
                  <h4 style={{ margin: 0, color: simResult.allowed ? "#166534" : "#991b1b" }}>
                    Decision: {simResult.effect} ({simResult.allowed ? "Access Granted" : "Access Denied"})
                  </h4>
                  <p style={{ margin: "0.5rem 0 0", fontSize: "0.85rem", color: "#475569" }}>
                    Evaluation Time: {simResult.evaluation_time_ms} ms
                  </p>
                </div>

                <div>
                  <strong>Decision Reasons:</strong>
                  <ul style={{ margin: "0.3rem 0 0 1.2rem", fontSize: "0.9rem", color: "#334155" }}>
                    {simResult.reasons.map((r, i) => (
                      <li key={i}>{r}</li>
                    ))}
                  </ul>
                </div>

                {simResult.matched_policies.length > 0 && (
                  <div>
                    <strong>Matched Policies:</strong>
                    <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap", marginTop: "0.3rem" }}>
                      {simResult.matched_policies.map((p, i) => (
                        <span key={i} className="badge badge-info">{p}</span>
                      ))}
                    </div>
                  </div>
                )}

                <div>
                  <strong>Resolved Subject Attributes:</strong>
                  <pre
                    style={{
                      background: "#0f172a",
                      color: "#38bdf8",
                      padding: "0.8rem",
                      borderRadius: "6px",
                      fontSize: "0.8rem",
                      overflowX: "auto",
                      maxHeight: "150px",
                    }}
                  >
                    {JSON.stringify(simResult.user_attributes, null, 2)}
                  </pre>
                </div>
              </div>
            ) : (
              <p style={{ color: "#64748b" }}>
                Click "Evaluate Access Decision" on the left to simulate dynamic ABAC rule evaluation against subject attributes and policies.
              </p>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
