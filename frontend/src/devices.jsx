import { useEffect, useState } from "react";

import { Notice, PageHeader, Restricted } from "./components";
import { DECODER_API } from "./api";


// The pattern attribute is anchored by the browser and compiled with the
// "v" flag, where a "-" inside [...] has to be escaped
function htmlPattern(pattern) {
  return pattern.replace(/^\^|\$$/g, "").replaceAll("[:-]", "[:\\-]");
}


function emptyCredentials(type) {
  return Object.fromEntries((type?.fields || []).map((field) => [field.key, ""]));
}


// Inputs for the identifiers / keys of one network type
// (GET /devices/network-types), built from its field list
function CredentialFields({ type, values, onChange, profiles, editing = false }) {
  if (!type) {
    return null;
  }

  return (
    <div className="credential-section">
      <div className="credential-title">
        <span className={`pill pill-type type-${type.value.toLowerCase()}`}>{type.label}</span>
        <p>{type.description}</p>
      </div>

      <div className="form-grid">
        {type.fields.map((field) => {
          const providers = field.provider_type
            ? profiles.filter((profile) => profile.connection_type === field.provider_type)
            : [];

          const value = values[field.key] || "";
          const keepSecret = editing && field.secret;

          return (
            <div className="form-group" key={field.key}>
              <label htmlFor={`credential-${field.key}`}>{field.label}</label>

              {providers.length > 0 ? (
                <select
                  id={`credential-${field.key}`}
                  value={value}
                  onChange={(e) => onChange({ ...values, [field.key]: e.target.value })}
                  required
                >
                  <option value="">Select provider</option>
                  {providers.map((profile) => (
                    <option key={profile.code} value={profile.code}>
                      {profile.name} ({profile.code})
                    </option>
                  ))}
                  {value && !providers.some((profile) => profile.code === value) && (
                    <option value={value}>{value}</option>
                  )}
                </select>
              ) : (
                <input
                  id={`credential-${field.key}`}
                  value={value}
                  type={field.secret ? "password" : "text"}
                  autoComplete="off"
                  spellCheck={false}
                  placeholder={keepSecret ? "Leave empty to keep the stored key" : field.placeholder}
                  pattern={field.pattern ? htmlPattern(field.pattern) : undefined}
                  title={field.hint || undefined}
                  onChange={(e) => onChange({ ...values, [field.key]: e.target.value })}
                  required={!keepSecret}
                />
              )}

              {field.hint && <span className="field-hint">{field.hint}</span>}
            </div>
          );
        })}
      </div>
    </div>
  );
}


function Devices({ api, currentUser, navigate, selectedHeaderApplication = "" }) {
  const permissions = currentUser.permissions;
  const isAdmin = currentUser.role === "admin";

  const canView = permissions.manage_devices;
  const canDelete = permissions.delete_devices;
  const canReadTraffic = permissions.read_application_traffic;

  const [devices, setDevices] = useState([]);
  const [applications, setApplications] = useState([]);
  const [tenants, setTenants] = useState([]);
  const [networkTypes, setNetworkTypes] = useState([]);
  const [profiles, setProfiles] = useState([]);

  const [typeFilter, setTypeFilter] = useState("");
  const [editing, setEditing] = useState(null);

  const [listNotice, setListNotice] = useState(null);

  // Decoder auto-registration test state
  const [testDeviceId, setTestDeviceId] = useState("");
  const [testAppId, setTestAppId] = useState("");
  const [isRegistering, setIsRegistering] = useState(false);
  const [decoderNotice, setDecoderNotice] = useState(null);

  useEffect(() => {
    fetchDevices();
    fetchApplications();

    api.get("/devices/network-types").then(setNetworkTypes).catch(() => setNetworkTypes([]));
    api.get("/connectivity-profiles/").then(setProfiles).catch(() => setProfiles([]));

    if (isAdmin) {
      api.get("/tenants/").then(setTenants).catch(() => setTenants([]));
    }
  }, [api, canView]);

  async function fetchDevices() {
    if (!canView) {
      setDevices([]);
      return;
    }

    try {
      setDevices(await api.get("/devices/"));
    } catch (error) {
      setListNotice({ type: "error", text: error.message });
    }
  }

  async function fetchApplications() {
    if (!canView) {
      return;
    }

    try {
      setApplications(await api.get("/applications/"));
    } catch {
      setApplications([]);
    }
  }

  function applicationName(id) {
    return applications.find((app) => app.id === id)?.name || `Application ${id}`;
  }

  function tenantName(id) {
    if (id === currentUser.tenant_id && currentUser.tenant_name) {
      return currentUser.tenant_name;
    }

    return tenants.find((tenant) => tenant.id === id)?.name || `Organization ${id}`;
  }

  function typeOf(value) {
    return networkTypes.find((type) => type.value === value);
  }

  function providerName(code) {
    if (!code) return "—";
    return profiles.find((p) => p.code === code)?.name || code;
  }

  // The device's main identifier: the first key of its network type, or provider fallback
  function primaryIdentifier(device) {
    const creds = device.credentials || {};

    // 1. Network type specific main key (IMEI, DevEUI, MAC)
    const type = typeOf(device.device_type);
    const field = type?.fields?.[0];
    if (field && creds[field.key]) {
      return { label: field.label, value: creds[field.key] };
    }

    // 2. Provider from device or credentials (satellite_provider_id, sim_provider_id, or provider)
    const provider = device.provider || creds.provider || creds.satellite_provider_id || creds.sim_provider_id || creds.provider_id;
    if (provider) {
      return { label: "Provider", value: providerName(provider) };
    }

    // 3. Any other credential fields (e.g. hardware_serial)
    for (const f of type?.fields || []) {
      if (creds[f.key]) {
        return { label: f.label, value: creds[f.key] };
      }
    }

    if (creds.hardware_serial) {
      return { label: "Serial", value: creds.hardware_serial };
    }

    return null;
  }

  // -------------------------
  // Edit / delete
  // -------------------------

  function startEditing(device) {
    const type = typeOf(device.device_type);

    // Secrets come back masked: left empty, the stored one is kept
    const values = Object.fromEntries(
      (type?.fields || []).map((field) => [
        field.key,
        field.secret ? "" : device.credentials?.[field.key] || "",
      ])
    );

    setEditing({ ...device, credentials: values, original_type: device.device_type });
    setListNotice(null);
    requestAnimationFrame(() =>
      document.getElementById("edit-device-form")?.scrollIntoView({ behavior: "smooth", block: "start" })
    );
  }

  async function saveDevice(event) {
    event.preventDefault();
    setListNotice(null);

    const known = Boolean(typeOf(editing.device_type));

    try {
      await api.put(`/devices/${encodeURIComponent(editing.device_id)}`, {
        name: editing.name,
        device_type: editing.device_type,
        device_type_id: editing.device_type_id ? Number(editing.device_type_id) : undefined,
        application_id: Number(editing.application_id),
        credentials: known ? editing.credentials : undefined,
      });

      setListNotice({ type: "success", text: `Device ${editing.device_id} updated.` });
      setEditing(null);
      fetchDevices();
      fetchApplications();

    } catch (error) {
      setListNotice({ type: "error", text: error.message });
    }
  }

  async function deleteDevice(device) {
    if (!window.confirm(
      `Delete ${device.device_id}? Its telemetry, configuration and commands are deleted too.`
    )) {
      return;
    }

    setListNotice(null);

    try {
      await api.delete(`/devices/${encodeURIComponent(device.device_id)}`);
      setListNotice({ type: "success", text: `Device ${device.device_id} deleted.` });
      fetchDevices();
      fetchApplications();
    } catch (error) {
      setListNotice({ type: "error", text: error.message });
    }
  }

  // -------------------------
  // Automated decoder registration trigger
  // -------------------------

  async function triggerDecoderRegistration(event) {
    if (event) event.preventDefault();
    const id = testDeviceId.trim();
    if (!id) return;

    setIsRegistering(true);
    setDecoderNotice(null);

    const chosenApp = applications.find((a) => String(a.id) === String(testAppId));

    try {
      const res = await fetch(`${DECODER_API}/messages/register-device`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          deviceId: id,
          name: `Device ${id}`,
          deviceType: "NTN",
          applicationId: testAppId ? Number(testAppId) : undefined,
          application: chosenApp ? chosenApp.name : undefined,
        }),
      });

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || data.message || "Failed to register via decoder");
      }

      const assignedName = data.device?.application_name || (chosenApp ? chosenApp.name : "Assigned Application");
      setDecoderNotice({
        type: "success",
        text: `Device '${id}' successfully registered by Decoder into ${assignedName}!`,
      });
      setTestDeviceId("");
      fetchDevices();
      fetchApplications();
    } catch (err) {
      setDecoderNotice({ type: "error", text: err.message });
    } finally {
      setIsRegistering(false);
    }
  }

  const applicationDevices = selectedHeaderApplication
    ? devices.filter((device) => String(device.application_id) === String(selectedHeaderApplication))
    : devices;

  const filteredDevices = typeFilter
    ? applicationDevices.filter((device) =>
        device.device_type === typeFilter ||
        device.device_type?.toLowerCase()?.includes(typeFilter.toLowerCase())
      )
    : applicationDevices;

  const otherCount = applicationDevices.filter((device) => !typeOf(device.device_type)).length;

  return (
    <div className="page">

      <PageHeader
        title="Devices by Types"
        description="Devices registered across NTN, TN, LoRaWAN and BLE networks, automatically provisioned by Decoder microservices."
      >
        <button className="secondary-button" type="button" onClick={() => navigate("connectivity")}>
          Network Profiles
        </button>
        <span
          className="pill pill-type type-ntn"
          style={{ padding: "6px 12px", display: "inline-flex", alignItems: "center", gap: "6px" }}
        >
          <span
            style={{ width: "8px", height: "8px", borderRadius: "50%", background: "#10b981", display: "inline-block" }}
          />
          Decoder Auto-Registration
        </span>
      </PageHeader>

      {canView && (
        <section className="device-metrics" aria-label="Devices by network type">
          <button
            type="button"
            className={`metric-card ${typeFilter === "" ? "active" : ""}`}
            onClick={() => setTypeFilter("")}
            aria-pressed={typeFilter === ""}
          >
            <span>All devices</span>
            <strong>{applicationDevices.length}</strong>
            <small>{selectedHeaderApplication ? applicationName(Number(selectedHeaderApplication)) : "Every application"}</small>
          </button>

          {networkTypes.map((type) => (
            <button
              type="button"
              key={type.value}
              className={`metric-card type-${type.value.toLowerCase()} ${typeFilter === type.value ? "active" : ""}`}
              onClick={() => setTypeFilter(typeFilter === type.value ? "" : type.value)}
              aria-pressed={typeFilter === type.value}
            >
              <span>{type.label}</span>
              <strong>
                {applicationDevices.filter((device) =>
                  device.device_type === type.value ||
                  device.device_type?.toLowerCase()?.includes(type.value.toLowerCase())
                ).length}
              </strong>
              <small>{type.connection_type === "NTN" ? "Satellite" : "Terrestrial"}</small>
            </button>
          ))}

          {otherCount > 0 && (
            <div className="metric-card static">
              <span>Other types</span>
              <strong>{otherCount}</strong>
              <small>Registered before network types</small>
            </div>
          )}
        </section>
      )}

      {/* DEVICE LIST */}

      <section className="card">

        <div className="section-header">
          <div>
            <h2>Registered Devices</h2>
            <p>
              {typeFilter
                ? `${typeOf(typeFilter)?.label || typeFilter} devices accessible to you.`
                : "Devices accessible to you."}
            </p>
          </div>

          {canView && (
            <button className="secondary-button" onClick={fetchDevices}>
              Refresh
            </button>
          )}
        </div>

        {!canView ? (
          <Restricted>
            Viewing devices needs the <strong>Manage Devices</strong> function.
            {canReadTraffic && (
              <>
                {" "}You can read their telemetry on the{" "}
                <button className="link-button" onClick={() => navigate("telemetry")}>
                  Live Data page
                </button>.
              </>
            )}
          </Restricted>
        ) : filteredDevices.length === 0 ? (
          <div className="empty-state">
            <strong>No devices {typeFilter || selectedHeaderApplication ? "match this filter" : "registered yet"}.</strong>
            <p style={{ marginTop: "8px", color: "var(--text-muted)", fontSize: "0.9rem" }}>
              Manual registration is disabled. Devices are automatically provisioned when their first uplink or payload is processed by the Decoder.
            </p>
          </div>
        ) : (
          <div className="table-container">
            <table>
              <thead>
                <tr>
                  <th>Device ID</th>
                  <th>Name</th>
                  <th>Network</th>
                  <th>Identifier</th>
                  <th>Organization</th>
                  <th>Application</th>
                  <th>Actions</th>
                </tr>
              </thead>

              <tbody>
                {filteredDevices.map((device) => {
                  const identifier = primaryIdentifier(device);
                  const type = typeOf(device.device_type);

                  return (
                    <tr key={device.id}>
                      <td><strong>{device.device_id}</strong></td>
                      <td>{device.name}</td>
                      <td>
                        {type
                          ? <span className={`pill pill-type type-${type.value.toLowerCase()}`}>{type.label}</span>
                          : <span className="muted">{device.device_type}</span>}
                      </td>
                      <td>
                        {identifier ? (
                          <div className="identifier">
                            <span>{identifier.label}</span>
                            <code>{identifier.value}</code>
                            {device.provider && identifier.label !== "Provider" && (
                              <div style={{ marginTop: "3px" }}>
                                <span className="muted" style={{ fontSize: "0.72rem" }}>Provider: </span>
                                <span className="tag" style={{ fontSize: "0.72rem", padding: "1px 5px" }}>{providerName(device.provider)}</span>
                              </div>
                            )}
                          </div>
                        ) : device.provider ? (
                          <div className="identifier">
                            <span>Provider</span>
                            <code>{providerName(device.provider)}</code>
                          </div>
                        ) : (
                          <span className="muted">—</span>
                        )}
                      </td>
                      <td>{tenantName(device.tenant_id)}</td>
                      <td>{applicationName(device.application_id)}</td>
                      <td>
                        <div className="table-actions">
                          <button
                            className="secondary-button small"
                            onClick={() => navigate("configuration", { device })}
                          >
                            Configure
                          </button>

                          {canReadTraffic && (
                            <button
                              className="secondary-button small"
                              onClick={() => navigate("telemetry", { deviceId: device.device_id })}
                            >
                              Live Data
                            </button>
                          )}

                          <button
                            className="secondary-button small"
                            onClick={() => startEditing(device)}
                          >
                            Edit
                          </button>

                          {canDelete && (
                            <button
                              className="danger-button small"
                              onClick={() => deleteDevice(device)}
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

      {/* EDIT DEVICE */}

      {editing && (
        <section className="card" id="edit-device-form">
          <div className="section-header">
            <div>
              <h2>Edit {editing.device_id}</h2>
              <p>The device ID cannot change. A device stays in its organization.</p>
            </div>
          </div>

          <form onSubmit={saveDevice}>
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
                <label>Associated Application <span style={{ color: "#ef4444" }}>*</span></label>
                <select
                  value={editing.application_id}
                  onChange={(e) => {
                    const newAppId = Number(e.target.value);
                    const chosenApp = applications.find((a) => a.id === newAppId);
                    const firstType = chosenApp?.device_types?.[0];
                    setEditing({
                      ...editing,
                      application_id: newAppId,
                      device_type: firstType ? firstType.name : editing.device_type,
                      device_type_id: firstType ? firstType.id : null,
                    });
                  }}
                  required
                >
                  <option value="">Select Application</option>
                  {applications
                    .filter((app) => app.tenant_id === editing.tenant_id)
                    .map((app) => (
                      <option key={app.id} value={app.id}>{app.name}</option>
                    ))}
                </select>
              </div>

              <div className="form-group">
                <label>Device Type (Application Defined) <span style={{ color: "#ef4444" }}>*</span></label>
                <select
                  value={editing.device_type_id || editing.device_type}
                  onChange={(e) => {
                    const val = e.target.value;
                    const chosenApp = applications.find((a) => a.id === Number(editing.application_id));
                    const matchedType = chosenApp?.device_types?.find((t) => String(t.id) === val || t.name === val || t.code === val);
                    if (matchedType) {
                      setEditing({
                        ...editing,
                        device_type_id: matchedType.id,
                        device_type: matchedType.name,
                      });
                    } else {
                      setEditing({
                        ...editing,
                        device_type_id: null,
                        device_type: val,
                        credentials: emptyCredentials(typeOf(val)),
                      });
                    }
                  }}
                  required
                >
                  {(() => {
                    const chosenApp = applications.find((a) => a.id === Number(editing.application_id));
                    const appTypes = chosenApp?.device_types || [];
                    return (
                      <>
                        {appTypes.length > 0 && (
                          <optgroup label={`${chosenApp?.name || 'Application'} Device Types`}>
                            {appTypes.map((t) => (
                              <option key={t.id} value={t.id}>
                                {t.name} ({t.decoders?.length || 0} decoders)
                              </option>
                            ))}
                          </optgroup>
                        )}
                        <optgroup label="Standard Network Profiles">
                          {networkTypes.map((type) => (
                            <option key={type.value} value={type.value}>{type.label}</option>
                          ))}
                        </optgroup>
                      </>
                    );
                  })()}
                </select>
              </div>
            </div>

            <CredentialFields
              type={typeOf(editing.device_type)}
              values={editing.credentials}
              onChange={(values) => setEditing({ ...editing, credentials: values })}
              profiles={profiles}
              editing={editing.device_type === editing.original_type}
            />

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

      {/* AUTOMATED DECODER REGISTRATION CARD */}

      <section className="card" id="decoder-registration-info">
        <div className="section-header">
          <div>
            <h2>Automated Device Registration</h2>
            <p>Manual device registration is removed. Devices are dynamically provisioned by the Decoder service upon receiving an uplink.</p>
          </div>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 280px), 1fr))", gap: "16px", marginTop: "16px" }}>
          <div style={{ padding: "16px", background: "var(--surface-sunken, #f8fafc)", borderRadius: "8px", border: "1px solid var(--border-color, #e2e8f0)" }}>
            <h4 style={{ margin: "0 0 8px 0", fontSize: "0.95rem" }}>📡 Provisioning via Special Decoder Keywords</h4>
            <p style={{ margin: "0 0 8px 0", fontSize: "0.85rem", color: "var(--text-secondary, #64748b)", lineHeight: "1.5" }}>
              Your decoder script can return special keywords to provision or update device metadata automatically:
            </p>
            <ul style={{ margin: 0, paddingLeft: "18px", fontSize: "0.82rem", color: "var(--text-secondary, #64748b)", lineHeight: "1.6" }}>
              <li><code>deviceName</code>: Human-friendly name (e.g. <em>"Chiller Sensor 01"</em>)</li>
              <li><code>deviceType</code>: Network profile (<em>"NTN"</em>, <em>"TN"</em>, <em>"LoRaWAN"</em>, <em>"BLE"</em>)</li>
              <li><code>application</code>: Target Application name (e.g. <em>"OtherApp"</em>) or ID (e.g. <em>2</em>)</li>
              <li><code>deviceId</code>: Device ID extracted from raw payload</li>
              <li><code>credentials</code>: Hardware keys (<em>imei</em>, <em>hardware_serial</em>, etc.)</li>
            </ul>
          </div>

          <div style={{ padding: "16px", background: "var(--surface-sunken, #f8fafc)", borderRadius: "8px", border: "1px solid var(--border-color, #e2e8f0)" }}>
            <h4 style={{ margin: "0 0 8px 0", fontSize: "0.95rem" }}>⚡ Quick Decoder Test</h4>
            <p style={{ margin: "0 0 12px 0", fontSize: "0.85rem", color: "var(--text-secondary, #64748b)", lineHeight: "1.5" }}>
              Trigger an automated device registration into a specific application via the Decoder service:
            </p>
            <form onSubmit={triggerDecoderRegistration} style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
              <input
                type="text"
                placeholder="e.g. SENSOR-901"
                value={testDeviceId}
                onChange={(e) => setTestDeviceId(e.target.value)}
                style={{ flex: "1 1 140px", minWidth: 0, padding: "6px 10px", fontSize: "0.85rem" }}
              />
              <select
                value={testAppId}
                onChange={(e) => setTestAppId(e.target.value)}
                style={{ flex: "1 1 150px", minWidth: 0, padding: "6px 10px", fontSize: "0.85rem" }}
              >
                <option value="">Auto (From Decoder / Match)</option>
                {applications.map((app) => (
                  <option key={app.id} value={app.id}>
                    {app.name} (App #{app.id})
                  </option>
                ))}
              </select>
              <button
                type="submit"
                className="primary-button small"
                disabled={isRegistering || !testDeviceId.trim()}
                style={{ whiteSpace: "nowrap" }}
              >
                {isRegistering ? "Registering..." : "Send to Decoder"}
              </button>
            </form>
            {decoderNotice && <div style={{ marginTop: "10px" }}><Notice notice={decoderNotice} /></div>}
          </div>
        </div>
      </section>

    </div>
  );
}

export default Devices;
