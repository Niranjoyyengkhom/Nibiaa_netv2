import { useEffect, useState } from "react";

import { Notice, PageHeader, Restricted } from "./components";


function decoderLabel(decoder) {
  const owner = decoder.tenant_id === null ? " · platform" : "";
  const live = decoder.active_activation_id ? " · live" : "";

  const ver = String(decoder.version || "1").startsWith("v") ? decoder.version : `v${decoder.version || 1}`;
  return `${decoder.name} ${ver}${owner}${live}`;
}


function Applications({ api, currentUser, navigate, activeWorkspace }) {
  const permissions = currentUser.permissions;
  const capabilities = currentUser.capabilities;
  const isAdmin = currentUser.role === "admin";

  const canCreate = capabilities.create_application;
  const canEdit = permissions.manage_application;
  const canDelete = capabilities.delete_application;
  const canReadTraffic = permissions.read_application_traffic;
  const canSeeDecoders = permissions.create_decoder || permissions.manage_decoder;

  const [applications, setApplications] = useState([]);
  const [tenants, setTenants] = useState([]);
  const [decoders, setDecoders] = useState([]);

  // Organization / Individual filter for Registered Applications
  const [filterTenantId, setFilterTenantId] = useState(activeWorkspace?.id ? String(activeWorkspace.id) : "");

  const [name, setName] = useState("");
  const [tenantId, setTenantId] = useState("");
  const [decoderId, setDecoderId] = useState("");
  const [createNotice, setCreateNotice] = useState(null);

  const [editing, setEditing] = useState(null);
  const [listNotice, setListNotice] = useState(null);

  // Device types & decoders state
  const [selectedApp, setSelectedApp] = useState(null);
  const [deviceTypes, setDeviceTypes] = useState([]);
  const [loadingDeviceTypes, setLoadingDeviceTypes] = useState(false);
  const [newTypeName, setNewTypeName] = useState("");
  const [newTypeCode, setNewTypeCode] = useState("");
  const [newTypeNet, setNewTypeNet] = useState("Direct IP");
  const [newTypeDesc, setNewTypeDesc] = useState("");
  const [typeNotice, setTypeNotice] = useState(null);

  // Assign decoder state: maps deviceTypeId -> { schemaId, format, priority }
  const [decoderForms, setDecoderForms] = useState({});

  // Application-level decoders state
  const [appDecoderSchemaId, setAppDecoderSchemaId] = useState("");
  const [appDecoderFormat, setAppDecoderFormat] = useState("");
  const [appDecoderPriority, setAppDecoderPriority] = useState(0);
  const [appDecoderNotice, setAppDecoderNotice] = useState(null);

  useEffect(() => {
    fetchApplications(filterTenantId);

    api.get("/tenants/").then(setTenants).catch(() => setTenants([]));

    if (canSeeDecoders) {
      api.get("/decode-schemas/").then(setDecoders).catch(() => setDecoders([]));
    }
  }, [api]);

  useEffect(() => {
    if (activeWorkspace?.id) {
      setFilterTenantId(String(activeWorkspace.id));
    }
  }, [activeWorkspace]);

  async function fetchApplications(targetTenantId = filterTenantId) {
    try {
      const query = targetTenantId ? { tenant_id: targetTenantId } : undefined;
      const apps = await api.get("/applications/", query);
      setApplications(apps);
      if (selectedApp) {
        const updated = apps.find((a) => a.id === selectedApp.id);
        if (updated) setSelectedApp(updated);
      }
    } catch (error) {
      setListNotice({ type: "error", text: error.message });
      setApplications([]);
    }
  }

  function tenantTypeLabel(tenant) {
    if (!tenant) return "Organization";
    const t = (tenant.type || "").toLowerCase();
    if (t === "individual" || t === "workspace") return "Individual";
    return "Organization";
  }

  function tenantTypeById(id) {
    const t = tenants.find((tenant) => tenant.id === id);
    return tenantTypeLabel(t);
  }

  const filteredApplications = applications.filter((app) => {
    if (filterTenantId && String(app.tenant_id) !== String(filterTenantId)) {
      return false;
    }
    return true;
  });

  // An application can use its organization's decoders and platform decoders
  function decodersFor(organizationId) {
    return decoders.filter(
      (decoder) =>
        decoder.tenant_id === null ||
        decoder.tenant_id === Number(organizationId)
    );
  }

  function tenantName(id) {
    if (id === currentUser.tenant_id && currentUser.tenant_name) {
      return currentUser.tenant_name;
    }

    return tenants.find((tenant) => tenant.id === id)?.name || `Organization ${id}`;
  }

  // -------------------------
  // Device Types & Decoders
  // -------------------------

  async function selectApplicationForDeviceTypes(app) {
    if (selectedApp?.id === app.id) {
      setSelectedApp(null);
      setDeviceTypes([]);
      return;
    }

    setSelectedApp(app);
    setTypeNotice(null);
    setLoadingDeviceTypes(true);
    try {
      const types = await api.get(`/applications/${app.id}/device-types`);
      setDeviceTypes(types);
    } catch (err) {
      setTypeNotice({ type: "error", text: err.message });
      setDeviceTypes([]);
    } finally {
      setLoadingDeviceTypes(false);
    }
  }

  async function refreshDeviceTypes(appId) {
    try {
      const types = await api.get(`/applications/${appId}/device-types`);
      setDeviceTypes(types);
      fetchApplications();
    } catch (err) {
      setTypeNotice({ type: "error", text: err.message });
    }
  }

  // -------------------------
  // Device Types Operations
  // -------------------------

  async function handleCreateDeviceType(event) {
    event.preventDefault();
    if (!selectedApp) return;

    setTypeNotice(null);
    try {
      await api.post(`/applications/${selectedApp.id}/device-types`, {
        name: newTypeName.trim(),
        code: newTypeCode.trim() || undefined,
        network_type: newTypeNet,
        description: newTypeDesc.trim() || undefined,
      });

      setTypeNotice({
        type: "success",
        text: `Device type "${newTypeName.trim()}" created for ${selectedApp.name}.`,
      });
      setNewTypeName("");
      setNewTypeCode("");
      setNewTypeDesc("");
      refreshDeviceTypes(selectedApp.id);
    } catch (err) {
      setTypeNotice({ type: "error", text: err.message });
    }
  }

  async function handleDeleteDeviceType(dt) {
    if (!window.confirm(`Delete device type "${dt.name}"? Assigned devices will have device type unlinked.`)) {
      return;
    }

    setTypeNotice(null);
    try {
      await api.delete(`/device-types/${dt.id}`);
      setTypeNotice({ type: "success", text: `Device type "${dt.name}" deleted.` });
      refreshDeviceTypes(selectedApp.id);
    } catch (err) {
      setTypeNotice({ type: "error", text: err.message });
    }
  }

  async function handleAssignDecoder(event, deviceTypeId) {
    event.preventDefault();
    const form = decoderForms[deviceTypeId] || {};
    if (!form.schemaId) {
      setTypeNotice({ type: "error", text: "Please select a decoder to assign." });
      return;
    }

    setTypeNotice(null);
    try {
      await api.post(`/device-types/${deviceTypeId}/decoders`, {
        decode_schema_id: Number(form.schemaId),
        payload_format: form.format || null,
        priority: Number(form.priority) || 0,
      });

      setTypeNotice({
        type: "success",
        text: `Decoder successfully assigned to device type!`,
      });
      setDecoderForms({ ...decoderForms, [deviceTypeId]: { schemaId: "", format: "", priority: 0 } });
      refreshDeviceTypes(selectedApp.id);
    } catch (err) {
      setTypeNotice({ type: "error", text: err.message });
    }
  }

  async function handleRemoveDecoder(deviceTypeId, assignmentId, schemaName) {
    if (!window.confirm(`Remove decoder "${schemaName}" from this device type?`)) {
      return;
    }

    setTypeNotice(null);
    try {
      await api.delete(`/device-types/${deviceTypeId}/decoders/${assignmentId}`);
      setTypeNotice({ type: "success", text: "Decoder removed from device type." });
      refreshDeviceTypes(selectedApp.id);
    } catch (err) {
      setTypeNotice({ type: "error", text: err.message });
    }
  }

  // -------------------------
  // Application-Level Decoders
  // -------------------------

  async function handleAssignAppDecoder(event) {
    event.preventDefault();
    if (!selectedApp) return;
    if (!appDecoderSchemaId) {
      setAppDecoderNotice({ type: "error", text: "Please select a decoder to assign." });
      return;
    }

    setAppDecoderNotice(null);
    try {
      await api.post(`/applications/${selectedApp.id}/decoders`, {
        decode_schema_id: Number(appDecoderSchemaId),
        payload_format: appDecoderFormat || null,
        priority: Number(appDecoderPriority) || 0,
      });

      setAppDecoderNotice({
        type: "success",
        text: `Decoder successfully assigned to ${selectedApp.name}!`,
      });
      setAppDecoderSchemaId("");
      setAppDecoderFormat("");
      setAppDecoderPriority(0);
      fetchApplications();
    } catch (err) {
      setAppDecoderNotice({ type: "error", text: err.message });
    }
  }

  async function handleRemoveAppDecoder(assignmentId, schemaName) {
    if (!window.confirm(`Remove decoder "${schemaName}" from ${selectedApp.name}?`)) {
      return;
    }

    setAppDecoderNotice(null);
    try {
      await api.delete(`/applications/${selectedApp.id}/decoders/${assignmentId}`);
      setAppDecoderNotice({ type: "success", text: `Decoder removed from ${selectedApp.name}.` });
      fetchApplications();
    } catch (err) {
      setAppDecoderNotice({ type: "error", text: err.message });
    }
  }

  async function handleClearFallbackDecoder(application) {
    if (!window.confirm(`Remove default fallback decoder from ${application.name}? Other applications will NOT be affected.`)) {
      return;
    }

    try {
      await api.put(`/applications/${application.id}`, {
        name: application.name,
        decode_schema_id: null,
      });
      setListNotice({
        type: "success",
        text: `Fallback decoder removed from "${application.name}". All other applications remain unaffected.`,
      });
      fetchApplications();
    } catch (err) {
      setListNotice({ type: "error", text: err.message });
    }
  }

  // -------------------------
  // Create Application
  // -------------------------

  async function createApplication(event) {
    event.preventDefault();
    setCreateNotice(null);

    if (isAdmin && !tenantId) {
      setCreateNotice({ type: "error", text: "Please select an organization." });
      return;
    }

    try {
      const application = await api.post("/applications/", {
        name: name.trim(),
        tenant_id: isAdmin ? Number(tenantId) : null,
        decode_schema_id: decoderId ? Number(decoderId) : null,
      });

      setCreateNotice({
        type: "success",
        text: application.decode_schema_id
          ? `${application.name} created. Its devices decode with ${application.decoder_name} v${application.decoder_version}.`
          : `${application.name} created. You can now define Device Types and assign multiple decoders below.`,
      });

      setName("");
      setTenantId("");
      setDecoderId("");

      fetchApplications();
    } catch (error) {
      setCreateNotice({ type: "error", text: error.message });
    }
  }

  // -------------------------
  // Edit / delete
  // -------------------------

  async function saveApplication(event) {
    event.preventDefault();
    setListNotice(null);

    try {
      await api.put(`/applications/${editing.id}`, {
        name: editing.name.trim(),
        decode_schema_id: editing.decode_schema_id
          ? Number(editing.decode_schema_id)
          : null,
      });

      setListNotice({ type: "success", text: `${editing.name} updated.` });
      setEditing(null);
      fetchApplications();
    } catch (error) {
      setListNotice({ type: "error", text: error.message });
    }
  }

  async function deleteApplication(application) {
    if (!window.confirm(`Delete the application ${application.name}?`)) {
      return;
    }

    setListNotice(null);

    try {
      await api.delete(`/applications/${application.id}`);
      setListNotice({ type: "success", text: `${application.name} deleted.` });
      if (selectedApp?.id === application.id) {
        setSelectedApp(null);
        setDeviceTypes([]);
      }
      fetchApplications();
    } catch (error) {
      setListNotice({ type: "error", text: error.message });
    }
  }

  function editDecoderOptions() {
    const options = decodersFor(editing.tenant_id);

    if (
      editing.original_decoder_id &&
      !options.some((decoder) => decoder.id === editing.original_decoder_id)
    ) {
      options.unshift({
        id: editing.original_decoder_id,
        name: editing.decoder_name,
        version: editing.decoder_version,
        tenant_id: editing.tenant_id,
      });
    }

    return options;
  }

  return (
    <div className="page">

      <PageHeader
        title="Applications & Device Types"
        description="Every device is associated with an application. Each application has multiple device types, and each device type can have multiple decoders (by payload format or message type)."
      />

      {/* CREATE APPLICATION */}

      {canCreate && (
        <section className="card">

          <div className="section-header">
            <div>
              <h2>Create Application</h2>
              <p>
                Every device belongs to an application, and each application manages multiple device types and decoders.
              </p>
            </div>
          </div>

          <form onSubmit={createApplication}>

            <div className="form-grid">

              <div className="form-group">
                <label>Application Name</label>
                <input
                  type="text"
                  placeholder="Smart City Fleet"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  required
                />
              </div>

              {isAdmin && (
                <div className="form-group">
                  <label>Organization / Individual</label>
                  <select
                    value={tenantId}
                    onChange={(e) => {
                      setTenantId(e.target.value);
                      setDecoderId("");
                    }}
                    required
                  >
                    <option value="">Select Organization / Individual</option>
                    {tenants.map((tenant) => (
                      <option key={tenant.id} value={tenant.id}>
                        {tenant.name} ({tenantTypeLabel(tenant)})
                      </option>
                    ))}
                  </select>
                </div>
              )}

              <div className="form-group">
                <label>Default Decoder (Optional Fallback)</label>
                <select
                  value={decoderId}
                  onChange={(e) => setDecoderId(e.target.value)}
                  disabled={isAdmin && !tenantId}
                >
                  <option value="">None — decided by Device Type & match</option>
                  {decodersFor(isAdmin ? tenantId : currentUser.tenant_id).map((decoder) => (
                    <option key={decoder.id} value={decoder.id}>
                      {decoderLabel(decoder)}
                    </option>
                  ))}
                </select>
              </div>

            </div>

            <p className="muted small-text">
              Decoders are created on the{" "}
              <button type="button" className="link-button" onClick={() => navigate("decoders")}>
                Decoders page
              </button>.
            </p>

            <Notice notice={createNotice} />

            <button className="primary-button" type="submit">
              Create Application
            </button>

          </form>

        </section>
      )}

      {/* APPLICATION LIST */}

      <section className="card">

        <div className="section-header">
          <div>
            <h2>
              Registered Applications
              {filteredApplications.length !== applications.length ? (
                <span
                  className="pill"
                  style={{
                    marginLeft: "10px",
                    fontSize: "0.78rem",
                    fontWeight: 500,
                    verticalAlign: "middle",
                  }}
                >
                  {filteredApplications.length} of {applications.length}
                </span>
              ) : (
                applications.length > 0 && (
                  <span
                    className="pill"
                    style={{
                      marginLeft: "10px",
                      fontSize: "0.78rem",
                      fontWeight: 500,
                      verticalAlign: "middle",
                    }}
                  >
                    {applications.length} total
                  </span>
                )
              )}
            </h2>
            <p>Select an application to view and manage its <strong>Device Types</strong> and <strong>Multiple Decoders</strong>.</p>
          </div>

          <div className="header-actions" style={{ display: "flex", alignItems: "center", gap: "10px", flexWrap: "wrap" }}>
            {tenants.length > 0 && (
              <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <label
                  htmlFor="app-tenant-filter"
                  style={{
                    fontSize: "0.82rem",
                    fontWeight: 600,
                    color: "var(--text-muted, var(--text-2))",
                    whiteSpace: "nowrap",
                  }}
                >
                  Organization / Individual:
                </label>
                <select
                  id="app-tenant-filter"
                  value={filterTenantId}
                  onChange={(e) => setFilterTenantId(e.target.value)}
                  style={{
                    padding: "6px 12px",
                    fontSize: "0.85rem",
                    borderRadius: "var(--radius-sm)",
                    border: "1px solid var(--border)",
                    background: "var(--surface)",
                    color: "var(--text)",
                    minWidth: "220px",
                  }}
                >
                  <option value="">All Organizations / Individuals</option>
                  {tenants.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.name} ({tenantTypeLabel(t)})
                    </option>
                  ))}
                </select>
              </div>
            )}

            <button className="secondary-button" onClick={() => fetchApplications(filterTenantId)}>
              Refresh
            </button>
          </div>
        </div>

        {filterTenantId && (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              padding: "8px 14px",
              margin: "6px 0 16px 0",
              background: "rgba(59, 130, 246, 0.1)",
              border: "1px solid rgba(59, 130, 246, 0.25)",
              borderRadius: "var(--radius-sm)",
              fontSize: "0.85rem",
              color: "var(--text)",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <span>Filtered to:</span>
              <strong style={{ color: "var(--primary, #3b82f6)" }}>
                {tenants.find((t) => String(t.id) === String(filterTenantId))?.name || `ID ${filterTenantId}`}
              </strong>
              <span
                className="pill"
                style={{
                  fontSize: "0.72rem",
                  padding: "1px 6px",
                  background:
                    tenantTypeById(Number(filterTenantId)) === "Individual"
                      ? "rgba(139, 92, 246, 0.18)"
                      : "rgba(59, 130, 246, 0.18)",
                  color:
                    tenantTypeById(Number(filterTenantId)) === "Individual"
                      ? "#a78bfa"
                      : "#60a5fa",
                  border: "none",
                }}
              >
                {tenantTypeById(Number(filterTenantId))}
              </span>
            </div>
            <button
              type="button"
              className="link-button"
              style={{ fontSize: "0.82rem", color: "var(--primary, #3b82f6)", fontWeight: 600 }}
              onClick={() => setFilterTenantId("")}
            >
              Show all
            </button>
          </div>
        )}

        {!canEdit && !canCreate && (
          <Restricted title="View only">
            Changing an application needs the <strong>Manage Application</strong> function.
          </Restricted>
        )}

        {applications.length === 0 ? (
          <div className="empty-state">No applications found.</div>
        ) : filteredApplications.length === 0 ? (
          <div className="empty-state">
            <p>
              No registered applications found for{" "}
              <strong>
                {tenants.find((t) => String(t.id) === String(filterTenantId))?.name || "this selection"}
              </strong>.
            </p>
            <button
              type="button"
              className="secondary-button"
              style={{ marginTop: "10px" }}
              onClick={() => setFilterTenantId("")}
            >
              Show All Applications
            </button>
          </div>
        ) : (
          <div className="table-container">
            <table>
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Organization / Individual</th>
                  <th>Assigned Decoders</th>
                  <th>Device Types</th>
                  <th>Devices</th>
                  <th>Actions</th>
                </tr>
              </thead>

              <tbody>
                {filteredApplications.map((application) => {
                  const isSelected = selectedApp?.id === application.id;
                  const appDecs = application.decoders || [];
                  const fmtColors = {
                    json: "#3b82f6",
                    hex: "#8b5cf6",
                    binary: "#10b981",
                    base64: "#f59e0b",
                    any: "#64748b",
                  };

                  return (
                    <tr
                      key={application.id}
                      style={isSelected ? { background: "rgba(59, 130, 246, 0.08)", outline: "1px solid rgba(59, 130, 246, 0.3)" } : {}}
                    >
                      <td>
                        <strong>{application.name}</strong>
                      </td>
                      <td>
                        <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                          <span>{tenantName(application.tenant_id)}</span>
                          <span
                            className="pill"
                            style={{
                              fontSize: "0.72rem",
                              padding: "1px 6px",
                              background:
                                tenantTypeById(application.tenant_id) === "Individual"
                                  ? "rgba(139, 92, 246, 0.15)"
                                  : "rgba(59, 130, 246, 0.15)",
                              color:
                                tenantTypeById(application.tenant_id) === "Individual"
                                  ? "#a78bfa"
                                  : "#60a5fa",
                              border: "none",
                            }}
                          >
                            {tenantTypeById(application.tenant_id)}
                          </span>
                        </div>
                      </td>
                      <td>
                        <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                          {/* Direct assigned Application Decoders */}
                          {appDecs.length > 0 && (
                            <div style={{ display: "flex", flexWrap: "wrap", gap: "4px" }}>
                              {appDecs.map((dec) => {
                                const fmt = dec.payload_format || "any";
                                return (
                                  <span
                                    key={dec.id}
                                    style={{
                                      display: "inline-flex",
                                      alignItems: "center",
                                      gap: "5px",
                                      padding: "3px 8px",
                                      borderRadius: "4px",
                                      fontSize: "0.8rem",
                                      background: "rgba(30, 41, 59, 0.8)",
                                      border: "1px solid var(--border-color, #475569)",
                                    }}
                                  >
                                    <strong>{dec.decode_schema_name}</strong>
                                    <span style={{ color: "#94a3b8" }}>v{dec.decode_schema_version}</span>
                                    <span
                                      style={{
                                        fontSize: "0.7rem",
                                        padding: "1px 5px",
                                        borderRadius: "3px",
                                        fontWeight: 700,
                                        textTransform: "uppercase",
                                        background: `${fmtColors[fmt] || "#64748b"}22`,
                                        color: fmtColors[fmt] || "#94a3b8",
                                        border: `1px solid ${fmtColors[fmt] || "#64748b"}55`,
                                      }}
                                    >
                                      {fmt}
                                    </span>
                                  </span>
                                );
                              })}
                            </div>
                          )}

                          {/* Fallback Decoder */}
                          {application.decode_schema_id ? (
                            <div style={{ display: "inline-flex", alignItems: "center", gap: "6px" }}>
                              <span className="schema-status" style={{ fontSize: "0.8rem" }}>
                                {application.decoder_name} v{application.decoder_version}
                                <span style={{ opacity: 0.7, marginLeft: "4px" }}>(fallback)</span>
                              </span>
                              {canEdit && (
                                <button
                                  type="button"
                                  onClick={() => handleClearFallbackDecoder(application)}
                                  style={{
                                    background: "none",
                                    border: "none",
                                    color: "#ef4444",
                                    cursor: "pointer",
                                    fontSize: "0.9rem",
                                    padding: "0 2px",
                                    lineHeight: 1,
                                  }}
                                  title="Unassign fallback decoder"
                                >
                                  ×
                                </button>
                              )}
                            </div>
                          ) : (
                            appDecs.length === 0 && (
                              <span className="pill pill-warn" style={{ fontSize: "0.75rem", alignSelf: "flex-start" }}>
                                None assigned
                              </span>
                            )
                          )}
                        </div>
                      </td>
                      <td>
                        <button
                          type="button"
                          className="link-button"
                          style={{ fontWeight: 600, display: "inline-flex", alignItems: "center", gap: "6px" }}
                          onClick={() => selectApplicationForDeviceTypes(application)}
                        >
                          <span className="pill pill-type type-direct_ip" style={{ padding: "3px 8px", fontSize: "0.8rem" }}>
                            {application.device_type_count || (application.device_types?.length || 0)} types
                          </span>
                          <span>{isSelected ? "Hide ▲" : "Manage ▼"}</span>
                        </button>
                      </td>
                      <td>{application.device_count}</td>
                      <td>
                        <div className="table-actions">
                          <button
                            className={isSelected ? "primary-button small" : "secondary-button small"}
                            onClick={() => selectApplicationForDeviceTypes(application)}
                          >
                            {isSelected ? "Decoders & Types ▲" : "Decoders & Types ▼"}
                          </button>

                          {canEdit && (
                            <button
                              className="secondary-button small"
                              onClick={() => setEditing({
                                ...application,
                                original_decoder_id: application.decode_schema_id,
                                decode_schema_id: application.decode_schema_id || "",
                              })}
                            >
                              Edit
                            </button>
                          )}

                          {canReadTraffic && (
                            <button
                              className="secondary-button small"
                              onClick={() => navigate("telemetry", { applicationId: application.id })}
                            >
                              Traffic
                            </button>
                          )}

                          {canDelete && (
                            <button
                              className="danger-button small"
                              onClick={() => deleteApplication(application)}
                              title="Only an application without devices can be deleted"
                            >
                              Delete
                            </button>
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

        {!editing && <Notice notice={listNotice} />}

      </section>

      {/* DEVICE TYPES & MULTIPLE DECODERS SECTION FOR SELECTED APPLICATION */}

      {selectedApp && (
        <section className="card" id="device-types-section" style={{ border: "2px solid #3b82f6" }}>
          <div className="section-header">
            <div>
              <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                <span className="pill pill-type type-ntn" style={{ padding: "4px 10px" }}>Active Application</span>
                <h2>Device Types & Decoders — {selectedApp.name}</h2>
              </div>
              <p style={{ marginTop: "6px" }}>
                An application can have <strong>multiple device types</strong>. Each device type can have <strong>multiple decoders</strong> configured for different incoming payload formats (JSON, Hex, Binary, Base64, or Any format).
              </p>
            </div>

            <button className="secondary-button" onClick={() => refreshDeviceTypes(selectedApp.id)}>
              Refresh Types
            </button>
          </div>

          <Notice notice={typeNotice} />

          {/* SECTION 1: APPLICATION DECODERS (DIRECT MULTI-DECODER MAPPING) */}
          <div style={{ padding: "16px", background: "rgba(30, 41, 59, 0.4)", borderRadius: "8px", border: "1px solid var(--border-color, #334155)", marginBottom: "24px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: "10px", marginBottom: "12px" }}>
              <div>
                <h3 style={{ margin: 0, fontSize: "1.1rem", display: "flex", alignItems: "center", gap: "8px" }}>
                  <span>⚡ Decoders for {selectedApp.name}</span>
                  <span className="pill pill-type type-direct_ip" style={{ fontSize: "0.75rem", padding: "2px 8px" }}>
                    {(selectedApp.decoders?.length || 0) + (selectedApp.decode_schema_id ? 1 : 0)} Active
                  </span>
                </h3>
                <p style={{ margin: "4px 0 0 0", fontSize: "0.85rem", color: "var(--text-muted)" }}>
                  Assign multiple decoders directly to <strong>{selectedApp.name}</strong>. Incoming payloads are decoded using matching format decoders (JSON, Hex, Binary, Base64, or Any) in priority order.
                </p>
              </div>
            </div>

            <Notice notice={appDecoderNotice} />

            {/* LIST OF ASSIGNED APPLICATION DECODERS */}
            <div style={{ marginBottom: "16px" }}>
              <div style={{ fontSize: "0.85rem", fontWeight: 600, color: "#94a3b8", marginBottom: "8px" }}>
                Current Assigned Decoders:
              </div>

              {(!selectedApp.decoders || selectedApp.decoders.length === 0) && !selectedApp.decode_schema_id ? (
                <div style={{ padding: "12px", background: "rgba(0,0,0,0.2)", borderRadius: "6px", color: "#f59e0b", fontSize: "0.85rem" }}>
                  No decoders assigned directly to this application yet. Use the form below to assign multiple decoders.
                </div>
              ) : (
                <div style={{ display: "flex", flexWrap: "wrap", gap: "10px" }}>
                  {/* Direct decoders */}
                  {selectedApp.decoders && selectedApp.decoders.map((dec) => {
                    const fmt = dec.payload_format || "any";
                    const fmtColors = {
                      json: "#3b82f6",
                      hex: "#8b5cf6",
                      binary: "#10b981",
                      base64: "#f59e0b",
                      any: "#64748b",
                    };
                    return (
                      <div
                        key={dec.id}
                        style={{
                          display: "inline-flex",
                          alignItems: "center",
                          gap: "8px",
                          padding: "6px 12px",
                          background: "rgba(30, 41, 59, 0.9)",
                          border: "1px solid var(--border-color, #475569)",
                          borderRadius: "6px",
                          fontSize: "0.85rem",
                        }}
                      >
                        <strong>{dec.decode_schema_name}</strong>
                        <span style={{ color: "#94a3b8" }}>v{dec.decode_schema_version}</span>
                        <span
                          style={{
                            fontSize: "0.75rem",
                            padding: "2px 6px",
                            borderRadius: "4px",
                            fontWeight: 700,
                            textTransform: "uppercase",
                            background: `${fmtColors[fmt] || "#64748b"}22`,
                            color: fmtColors[fmt] || "#94a3b8",
                            border: `1px solid ${fmtColors[fmt] || "#64748b"}66`,
                          }}
                        >
                          {fmt === "any" ? "Any Format" : `${fmt} Affinity`}
                        </span>
                        {dec.priority > 0 && (
                          <span style={{ fontSize: "0.75rem", color: "#94a3b8" }}>P{dec.priority}</span>
                        )}
                        {canEdit && (
                          <button
                            type="button"
                            onClick={() => handleRemoveAppDecoder(dec.id, dec.decode_schema_name)}
                            style={{
                              background: "none",
                              border: "none",
                              color: "#ef4444",
                              cursor: "pointer",
                              fontWeight: "bold",
                              padding: "0 2px",
                              fontSize: "1.1rem",
                              lineHeight: "1",
                            }}
                            title="Remove decoder from application"
                          >
                            ×
                          </button>
                        )}
                      </div>
                    );
                  })}

                  {/* Fallback decoder */}
                  {selectedApp.decode_schema_id && (
                    <div
                      style={{
                        display: "inline-flex",
                        alignItems: "center",
                        gap: "8px",
                        padding: "6px 12px",
                        background: "rgba(30, 41, 59, 0.6)",
                        border: "1px dashed var(--border-color, #475569)",
                        borderRadius: "6px",
                        fontSize: "0.85rem",
                      }}
                    >
                      <strong>{selectedApp.decoder_name}</strong>
                      <span style={{ color: "#94a3b8" }}>v{selectedApp.decoder_version}</span>
                      <span className="pill pill-warn" style={{ fontSize: "0.75rem", padding: "2px 6px" }}>
                        Default Fallback
                      </span>
                      {canEdit && (
                        <button
                          type="button"
                          onClick={() => handleClearFallbackDecoder(selectedApp)}
                          style={{
                            background: "none",
                            border: "none",
                            color: "#ef4444",
                            cursor: "pointer",
                            fontWeight: "bold",
                            padding: "0 2px",
                            fontSize: "1.1rem",
                            lineHeight: "1",
                          }}
                          title="Remove fallback decoder"
                        >
                          ×
                        </button>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* FORM TO ADD APPLICATION DECODER */}
            {canEdit && (
              <form
                onSubmit={handleAssignAppDecoder}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "10px",
                  flexWrap: "wrap",
                  padding: "12px",
                  background: "var(--surface-sunken, #0f172a)",
                  borderRadius: "6px",
                }}
              >
                <span style={{ fontSize: "0.85rem", fontWeight: 600, color: "#cbd5e1" }}>
                  ➕ Assign Decoder to {selectedApp.name}:
                </span>

                <select
                  style={{ minWidth: "180px", padding: "6px 10px", fontSize: "0.85rem" }}
                  value={appDecoderSchemaId}
                  onChange={(e) => setAppDecoderSchemaId(e.target.value)}
                  required
                >
                  <option value="">Select Decoder...</option>
                  {decodersFor(selectedApp.tenant_id).map((dec) => (
                    <option key={dec.id} value={dec.id}>
                      {dec.name} v{dec.version} {dec.tenant_id === null ? "(Platform)" : ""}
                    </option>
                  ))}
                </select>

                <select
                  style={{ minWidth: "140px", padding: "6px 10px", fontSize: "0.85rem" }}
                  value={appDecoderFormat}
                  onChange={(e) => setAppDecoderFormat(e.target.value)}
                >
                  <option value="">Any format (Fallback)</option>
                  <option value="json">JSON format</option>
                  <option value="hex">Hex format</option>
                  <option value="binary">Binary format</option>
                  <option value="base64">Base64 format</option>
                </select>

                <div style={{ display: "inline-flex", alignItems: "center", gap: "4px" }}>
                  <label style={{ fontSize: "0.8rem", color: "#94a3b8" }}>Priority:</label>
                  <input
                    type="number"
                    style={{ width: "65px", padding: "6px 8px", fontSize: "0.85rem" }}
                    value={appDecoderPriority}
                    onChange={(e) => setAppDecoderPriority(e.target.value)}
                    title="Higher priority decoders match first"
                  />
                </div>

                <button className="primary-button small" type="submit">
                  Assign Decoder
                </button>
              </form>
            )}
          </div>

          {/* SECTION 2: DEVICE TYPES & DECISIONS */}
          <div style={{ marginBottom: "12px", borderTop: "1px solid var(--border-color, #334155)", paddingTop: "16px" }}>
            <h3 style={{ margin: "0 0 6px 0", fontSize: "1rem" }}>📱 Device Types for {selectedApp.name} (Optional)</h3>
            <p style={{ margin: 0, fontSize: "0.85rem", color: "var(--text-muted)" }}>
              If your devices have distinct models or hardware profiles within this application, you can optionally define Device Types and assign specific decoders to each type.
            </p>
          </div>


          {/* ADD DEVICE TYPE FORM */}
          {canEdit && (
            <div style={{ padding: "16px", background: "var(--surface-sunken, #0f172a)", borderRadius: "8px", marginBottom: "20px" }}>
              <h3 style={{ margin: "0 0 12px 0", fontSize: "1rem" }}>➕ Add New Device Type to {selectedApp.name}</h3>
              <form onSubmit={handleCreateDeviceType}>
                <div className="form-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))" }}>
                  <div className="form-group">
                    <label>Device Type Name</label>
                    <input
                      type="text"
                      placeholder="e.g. Smart Water Meter"
                      value={newTypeName}
                      onChange={(e) => setNewTypeName(e.target.value)}
                      required
                    />
                  </div>

                  <div className="form-group">
                    <label>Code (Identifier)</label>
                    <input
                      type="text"
                      placeholder="e.g. smart_water_meter"
                      value={newTypeCode}
                      onChange={(e) => setNewTypeCode(e.target.value)}
                    />
                  </div>

                  <div className="form-group">
                    <label>Network Profile</label>
                    <select value={newTypeNet} onChange={(e) => setNewTypeNet(e.target.value)}>
                      <option value="Direct IP">Direct IP</option>
                      <option value="NTN">NTN (Satellite)</option>
                      <option value="TN">TN (Cellular)</option>
                      <option value="LoRa">LoRaWAN</option>
                      <option value="BLE">BLE</option>
                    </select>
                  </div>

                  <div className="form-group">
                    <label>Description</label>
                    <input
                      type="text"
                      placeholder="e.g. High precision flow and temperature sensor"
                      value={newTypeDesc}
                      onChange={(e) => setNewTypeDesc(e.target.value)}
                    />
                  </div>
                </div>

                <div style={{ marginTop: "12px", display: "flex", justifyContent: "flex-end" }}>
                  <button className="primary-button small" type="submit">
                    Add Device Type
                  </button>
                </div>
              </form>
            </div>
          )}

          {/* DEVICE TYPES LIST */}
          {loadingDeviceTypes ? (
            <div className="empty-state">Loading device types...</div>
          ) : deviceTypes.length === 0 ? (
            <div className="empty-state">
              No device types defined for this application yet. Use the form above to add the first device type.
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
              {deviceTypes.map((dt) => {
                const formState = decoderForms[dt.id] || { schemaId: "", format: "", priority: 0 };
                const availableDecoders = decodersFor(selectedApp.tenant_id);

                return (
                  <div
                    key={dt.id}
                    style={{
                      border: "1px solid var(--border-color, #334155)",
                      borderRadius: "8px",
                      padding: "16px",
                      background: "rgba(15, 23, 42, 0.4)",
                    }}
                  >
                    {/* Device Type Header */}
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: "10px", marginBottom: "12px" }}>
                      <div>
                        <div style={{ display: "flex", alignItems: "center", gap: "10px", flexWrap: "wrap" }}>
                          <h3 style={{ margin: 0, fontSize: "1.1rem" }}>{dt.name}</h3>
                          <code style={{ fontSize: "0.85rem", padding: "2px 6px", background: "rgba(0,0,0,0.3)", borderRadius: "4px" }}>{dt.code}</code>
                          <span className={`pill pill-type type-${(dt.network_type || "direct_ip").toLowerCase().replace(" ", "_")}`} style={{ fontSize: "0.75rem", padding: "2px 8px" }}>
                            {dt.network_type || "Direct IP"}
                          </span>
                          <span style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>
                            ({dt.device_count} device{dt.device_count === 1 ? "" : "s"})
                          </span>
                        </div>
                        {dt.description && (
                          <p style={{ margin: "4px 0 0 0", fontSize: "0.85rem", color: "var(--text-muted)" }}>
                            {dt.description}
                          </p>
                        )}
                      </div>

                      {canEdit && (
                        <button
                          className="danger-button small"
                          type="button"
                          onClick={() => handleDeleteDeviceType(dt)}
                          title="Delete this device type"
                        >
                          Delete Type
                        </button>
                      )}
                    </div>

                    {/* ASSIGNED DECODERS LIST */}
                    <div style={{ marginTop: "12px" }}>
                      <div style={{ fontSize: "0.85rem", fontWeight: 600, color: "#94a3b8", marginBottom: "8px", display: "flex", alignItems: "center", gap: "6px" }}>
                        <span>⚡ Decoders for this Device Type ({dt.decoders?.length || 0}):</span>
                        {(!dt.decoders || dt.decoders.length === 0) && (
                          <span style={{ color: "#f59e0b", fontWeight: "normal" }}>No decoders assigned yet. Assign decoders below.</span>
                        )}
                      </div>

                      {dt.decoders && dt.decoders.length > 0 && (
                        <div style={{ display: "flex", flexWrap: "wrap", gap: "8px", marginBottom: "12px" }}>
                          {dt.decoders.map((dec) => {
                            const fmt = dec.payload_format || "any";
                            const fmtColors = {
                              json: "#3b82f6",
                              hex: "#8b5cf6",
                              binary: "#10b981",
                              base64: "#f59e0b",
                              any: "#64748b",
                            };
                            return (
                              <div
                                key={dec.id}
                                style={{
                                  display: "inline-flex",
                                  alignItems: "center",
                                  gap: "8px",
                                  padding: "6px 12px",
                                  background: "rgba(30, 41, 59, 0.8)",
                                  border: "1px solid var(--border-color, #475569)",
                                  borderRadius: "6px",
                                  fontSize: "0.85rem",
                                }}
                              >
                                <strong>{dec.decode_schema_name}</strong>
                                <span style={{ color: "#94a3b8" }}>v{dec.decode_schema_version}</span>
                                <span
                                  style={{
                                    fontSize: "0.75rem",
                                    padding: "2px 6px",
                                    borderRadius: "4px",
                                    fontWeight: 700,
                                    textTransform: "uppercase",
                                    background: `${fmtColors[fmt] || "#64748b"}22`,
                                    color: fmtColors[fmt] || "#94a3b8",
                                    border: `1px solid ${fmtColors[fmt] || "#64748b"}66`,
                                  }}
                                >
                                  {fmt === "any" ? "Any Format" : fmt}
                                </span>
                                {dec.priority > 0 && (
                                  <span style={{ fontSize: "0.75rem", color: "#64748b" }}>P{dec.priority}</span>
                                )}
                                {canEdit && (
                                  <button
                                    type="button"
                                    onClick={() => handleRemoveDecoder(dt.id, dec.id, dec.decode_schema_name)}
                                    style={{
                                      background: "none",
                                      border: "none",
                                      color: "#ef4444",
                                      cursor: "pointer",
                                      fontWeight: "bold",
                                      padding: "0 2px",
                                      fontSize: "1rem",
                                      lineHeight: "1",
                                    }}
                                    title="Remove decoder from device type"
                                  >
                                    ×
                                  </button>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      )}

                      {/* ASSIGN DECODER FORM FOR THIS DEVICE TYPE */}
                      {canEdit && (
                        <form
                          onSubmit={(e) => handleAssignDecoder(e, dt.id)}
                          style={{
                            display: "flex",
                            alignItems: "center",
                            gap: "8px",
                            flexWrap: "wrap",
                            padding: "8px 12px",
                            background: "rgba(15, 23, 42, 0.6)",
                            borderRadius: "6px",
                            marginTop: "8px",
                          }}
                        >
                          <span style={{ fontSize: "0.82rem", color: "#cbd5e1" }}>+ Assign Decoder:</span>
                          <select
                            style={{ minWidth: "160px", padding: "4px 8px", fontSize: "0.85rem" }}
                            value={formState.schemaId}
                            onChange={(e) =>
                              setDecoderForms({
                                ...decoderForms,
                                [dt.id]: { ...formState, schemaId: e.target.value },
                              })
                            }
                            required
                          >
                            <option value="">Select Decoder...</option>
                            {availableDecoders.map((dec) => (
                              <option key={dec.id} value={dec.id}>
                                {dec.name} v{dec.version} {dec.tenant_id === null ? "(Platform)" : ""}
                              </option>
                            ))}
                          </select>

                          <select
                            style={{ minWidth: "130px", padding: "4px 8px", fontSize: "0.85rem" }}
                            value={formState.format}
                            onChange={(e) =>
                              setDecoderForms({
                                ...decoderForms,
                                [dt.id]: { ...formState, format: e.target.value },
                              })
                            }
                          >
                            <option value="">Any format (Dynamic)</option>
                            <option value="json">JSON format</option>
                            <option value="hex">Hex format</option>
                            <option value="binary">Binary format</option>
                            <option value="base64">Base64 format</option>
                          </select>

                          <button className="secondary-button small" type="submit">
                            Assign to {dt.name}
                          </button>
                        </form>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </section>
      )}

      {/* EDIT APPLICATION */}

      {editing && (
        <section className="card">
          <div className="section-header">
            <div>
              <h2>Edit {editing.name}</h2>
              <p>
                Update the application name or default fallback decoder.
              </p>
            </div>
          </div>

          <form onSubmit={saveApplication}>
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
                <label>Default Fallback Decoder</label>
                <select
                  value={editing.decode_schema_id || ""}
                  onChange={(e) => setEditing({ ...editing, decode_schema_id: e.target.value })}
                >
                  <option value="">None (Rely on Application Decoders / Dynamic Match)</option>
                  {editDecoderOptions().map((decoder) => (
                    <option key={decoder.id} value={decoder.id}>
                      {decoderLabel(decoder)}
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

export default Applications;
