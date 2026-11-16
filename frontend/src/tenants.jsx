import { useEffect, useState } from "react";

import { Notice, PageHeader, StatusPill } from "./components";


const TYPES = [
  { value: "workspace", label: "Workspace" },
  { value: "organization", label: "Organization" },
  { value: "team", label: "Team" },
  { value: "individual", label: "Individual" },
];


function Tenants({ api, currentUser, activeWorkspace, onSelectWorkspace }) {
  const [tenants, setTenants] = useState([]);

  const [name, setName] = useState("");
  const [type, setType] = useState("workspace");
  const [createNotice, setCreateNotice] = useState(null);

  const [editing, setEditing] = useState(null);
  const [listNotice, setListNotice] = useState(null);

  useEffect(() => {
    fetchTenants();
  }, [api]);

  async function fetchTenants() {
    try {
      setTenants(await api.get("/tenants/"));
    } catch (error) {
      setListNotice({ type: "error", text: error.message });
    }
  }

  async function createTenant(event) {
    event.preventDefault();
    setCreateNotice(null);

    try {
      const tenant = await api.post("/tenants/", { name: name.trim(), type });

      setCreateNotice({
        type: "success",
        text: `Workspace "${tenant.name}" created successfully.`,
      });
      setName("");
      setType("workspace");

      fetchTenants();
      if (onSelectWorkspace) {
        onSelectWorkspace({ id: tenant.id, name: tenant.name });
      }
    } catch (error) {
      setCreateNotice({ type: "error", text: error.message });
    }
  }

  async function saveTenant(event) {
    event.preventDefault();
    setListNotice(null);

    try {
      await api.put(`/tenants/${editing.id}`, {
        name: editing.name.trim(),
        type: editing.type,
      });

      setListNotice({ type: "success", text: `${editing.name} updated.` });
      setEditing(null);
      fetchTenants();
    } catch (error) {
      setListNotice({ type: "error", text: error.message });
    }
  }

  async function setAccess(tenant, active) {
    if (!active && !window.confirm(
      `Revoke the access of ${tenant.name}? Its ${tenant.user_count} user(s) are signed out and cannot sign in until it is restored. No data is deleted.`
    )) {
      return;
    }

    setListNotice(null);

    try {
      await api.post(`/tenants/${tenant.id}/${active ? "restore" : "revoke"}`);
      setListNotice({
        type: "success",
        text: active
          ? `${tenant.name}'s access was restored.`
          : `${tenant.name}'s access was revoked.`,
      });
      fetchTenants();
    } catch (error) {
      setListNotice({ type: "error", text: error.message });
    }
  }

  async function deleteTenant(tenant) {
    if (!window.confirm(`Delete workspace "${tenant.name}"? This will delete all its applications, decoders, webhooks, and associated configurations. This cannot be undone.`)) {
      return;
    }

    setListNotice(null);

    try {
      await api.delete(`/tenants/${tenant.id}`);
      if (activeWorkspace?.id === tenant.id && onSelectWorkspace) {
        onSelectWorkspace(null);
      }
      setListNotice({ type: "success", text: `Workspace "${tenant.name}" deleted.` });
      fetchTenants();
    } catch (error) {
      setListNotice({ type: "error", text: error.message });
    }
  }

  return (
    <div className="page">

      <PageHeader
        title="Workspaces & Organizations"
        description="Create, configure, and isolate multiple workspaces, organizations, and environments."
      />

      {activeWorkspace && (
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
            <span style={{ fontSize: "1.2rem" }}>🏢</span>
            <span>
              Active Workspace Filter: <strong>{activeWorkspace.name}</strong>
            </span>
          </div>
          <button
            type="button"
            className="secondary-button small"
            onClick={() => onSelectWorkspace && onSelectWorkspace(null)}
          >
            Switch to Platform (Global)
          </button>
        </div>
      )}

      {/* CREATE WORKSPACE */}

      <section className="card">

        <div className="section-header">
          <div>
            <h2>Create Workspace</h2>
            <p>Create a new isolated workspace or organization for your teams, devices, and applications.</p>
          </div>
        </div>

        <form onSubmit={createTenant}>
          <div className="form-grid">
            <div className="form-group">
              <label>Workspace Name</label>
              <input
                type="text"
                placeholder="e.g. Smart City, Logistics Fleet, Acme Corp"
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
              />
            </div>

            <div className="form-group">
              <label>Workspace Type</label>
              <select value={type} onChange={(e) => setType(e.target.value)}>
                {TYPES.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <Notice notice={createNotice} />

          <button className="primary-button" type="submit">
            Create Workspace
          </button>
        </form>

      </section>

      {/* WORKSPACES LIST */}

      <section className="card">

        <div className="section-header">
          <div>
            <h2>Registered Workspaces</h2>
            <p>
              Switch between workspaces, edit settings, or manage access.
            </p>
          </div>

          <button className="secondary-button" onClick={fetchTenants}>
            Refresh
          </button>
        </div>

        {tenants.length === 0 ? (
          <div className="empty-state">No workspaces found.</div>
        ) : (
          <div className="table-container">
            <table>
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Workspace Name</th>
                  <th>Type</th>
                  <th>Users</th>
                  <th>Applications</th>
                  <th>Devices</th>
                  <th>Access</th>
                  <th>Actions</th>
                </tr>
              </thead>

              <tbody>
                {tenants.map((tenant) => (
                  <tr key={tenant.id}>
                    <td>{tenant.id}</td>
                    <td><strong>{tenant.name}</strong></td>
                    <td className="capitalize">{tenant.type}</td>
                    <td>{tenant.user_count}</td>
                    <td>{tenant.application_count}</td>
                    <td>{tenant.device_count}</td>
                    <td><StatusPill active={tenant.is_active} /></td>
                    <td>
                      <div className="table-actions">
                        {onSelectWorkspace && (
                          <button
                            type="button"
                            className={`small ${activeWorkspace?.id === tenant.id ? "primary-button" : "secondary-button"}`}
                            onClick={() => onSelectWorkspace(activeWorkspace?.id === tenant.id ? null : { id: tenant.id, name: tenant.name })}
                          >
                            {activeWorkspace?.id === tenant.id ? "✓ Active" : "Switch"}
                          </button>
                        )}

                        <button
                          className="secondary-button small"
                          onClick={() => setEditing({ ...tenant })}
                        >
                          Edit
                        </button>

                        {tenant.is_active ? (
                          <button
                            className="secondary-button small"
                            onClick={() => setAccess(tenant, false)}
                          >
                            Revoke Access
                          </button>
                        ) : (
                          <button
                            className="secondary-button small"
                            onClick={() => setAccess(tenant, true)}
                          >
                            Restore Access
                          </button>
                        )}

                        <button
                          className="danger-button small"
                          onClick={() => deleteTenant(tenant)}
                          title="Delete workspace and associated configurations"
                        >
                          Delete
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {!editing && <Notice notice={listNotice} />}

      </section>

      {/* EDIT ORGANIZATION */}

      {editing && (
        <section className="card">
          <div className="section-header">
            <div>
              <h2>Edit {editing.name}</h2>
            </div>
          </div>

          <form onSubmit={saveTenant}>
            <div className="form-grid">
              <div className="form-group">
                <label>Name</label>
                <input
                  value={editing.name}
                  onChange={(e) => setEditing({ ...editing, name: e.target.value })}
                  required
                />
              </div>

              <div className="form-group">
                <label>Type</label>
                <select
                  value={editing.type}
                  onChange={(e) => setEditing({ ...editing, type: e.target.value })}
                >
                  {TYPES.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <Notice notice={listNotice} />

            <div className="button-group">
              <button className="primary-button" type="submit">Save</button>
              <button
                className="secondary-button"
                type="button"
                onClick={() => { setEditing(null); setListNotice(null); }}
              >
                Cancel
              </button>
            </div>
          </form>
        </section>
      )}

    </div>
  );
}

export default Tenants;
