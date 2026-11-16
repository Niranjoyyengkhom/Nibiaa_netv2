import { useEffect, useState } from "react";

import { formatDate } from "./api";
import { Notice, PageHeader, StatusPill } from "./components";


const EMPTY_PROFILE = {
  id: null,
  code: "",
  name: "",
  connection_type: "NTN",
  integration_status: "planned",
  enabled: true,
  transport: "",
  max_payload_bytes: "",
  description: "",
};

const TRANSPORTS = [
  { value: "https", label: "HTTPS" },
  { value: "mqtt", label: "MQTT" },
  { value: "tcp", label: "TCP/IP" },
  { value: "udp", label: "UDP" },
  { value: "webhook", label: "Webhook" },
  { value: "custom", label: "Custom" },
];


function profileBody(form) {
  return {
    name: form.name.trim(),
    connection_type: form.connection_type,
    integration_status: form.integration_status,
    enabled: form.enabled,
    transport: form.transport || null,
    max_payload_bytes: form.max_payload_bytes ? Number(form.max_payload_bytes) : null,
    description: form.description || null,
  };
}


// Connectivity Profile -> Network Profiles: the satellite / terrestrial providers.
// A new provider is added here by an admin, no code change needed.
function Connectivity({ api, currentUser }) {
  const canManage = currentUser.capabilities.manage_connectivity_profiles;

  const [profiles, setProfiles] = useState([]);
  const [form, setForm] = useState(EMPTY_PROFILE);
  const [formNotice, setFormNotice] = useState(null);
  const [listNotice, setListNotice] = useState(null);

  // Source mappings of one profile
  const [sourcesOf, setSourcesOf] = useState(null);
  const [sources, setSources] = useState([]);
  const [sourceTransport, setSourceTransport] = useState("udp");
  const [sourceIdentity, setSourceIdentity] = useState("");
  const [sourceNotice, setSourceNotice] = useState(null);

  useEffect(() => {
    fetchProfiles();
  }, [api]);

  async function fetchProfiles() {
    try {
      setProfiles(await api.get("/connectivity-profiles/"));
    } catch (error) {
      setListNotice({ type: "error", text: error.message });
    }
  }

  // -------------------------
  // Add / manage profile
  // -------------------------

  async function saveProfile(event) {
    event.preventDefault();
    setFormNotice(null);

    try {
      if (form.id) {
        const profile = await api.put(`/connectivity-profiles/${form.id}`, profileBody(form));
        setFormNotice({ type: "success", text: `${profile.name} updated.` });
      } else {
        const profile = await api.post("/connectivity-profiles/", {
          code: form.code.trim(),
          ...profileBody(form),
        });
        setFormNotice({
          type: "success",
          text: `${profile.name} added. Map its ground-segment IP or client ID under "Sources" so uplinks are recognised.`,
        });
      }

      setForm(EMPTY_PROFILE);
      fetchProfiles();
    } catch (error) {
      setFormNotice({ type: "error", text: error.message });
    }
  }

  async function toggleEnabled(profile) {
    setListNotice(null);

    try {
      await api.put(`/connectivity-profiles/${profile.id}`, {
        ...profileBody({
          ...profile,
          transport: profile.transport || "",
          max_payload_bytes: profile.max_payload_bytes || "",
          description: profile.description || "",
        }),
        enabled: !profile.enabled,
      });

      setListNotice({
        type: "success",
        text: profile.enabled
          ? `${profile.name} disabled: its uplinks are refused until it is enabled again.`
          : `${profile.name} enabled.`,
      });
      fetchProfiles();
    } catch (error) {
      setListNotice({ type: "error", text: error.message });
    }
  }

  async function deleteProfile(profile) {
    if (!window.confirm(`Delete the network profile ${profile.name}?`)) {
      return;
    }

    setListNotice(null);

    try {
      await api.delete(`/connectivity-profiles/${profile.id}`);
      setListNotice({ type: "success", text: `${profile.name} deleted.` });

      if (sourcesOf?.id === profile.id) {
        setSourcesOf(null);
      }

      fetchProfiles();
    } catch (error) {
      setListNotice({ type: "error", text: error.message });
    }
  }

  // -------------------------
  // Sources
  // -------------------------

  async function openSources(profile) {
    setSourcesOf(profile);
    setSourceNotice(null);
    setSourceTransport(
      TRANSPORTS.map((t) => t.value).includes(profile.transport)
        ? profile.transport
        : "udp"
    );

    try {
      setSources(await api.get(`/connectivity-profiles/${profile.id}/sources`));
    } catch (error) {
      setSourceNotice({ type: "error", text: error.message });
    }
  }

  async function addSource(event) {
    event.preventDefault();
    setSourceNotice(null);

    try {
      await api.post(`/connectivity-profiles/${sourcesOf.id}/sources`, {
        transport: sourceTransport,
        identity: sourceIdentity.trim(),
      });

      setSourceIdentity("");
      setSources(await api.get(`/connectivity-profiles/${sourcesOf.id}/sources`));
      fetchProfiles();
    } catch (error) {
      setSourceNotice({ type: "error", text: error.message });
    }
  }

  async function removeSource(source) {
    setSourceNotice(null);

    try {
      await api.delete(`/connectivity-profiles/sources/${source.id}`);
      setSources(sources.filter((row) => row.id !== source.id));
      fetchProfiles();
    } catch (error) {
      setSourceNotice({ type: "error", text: error.message });
    }
  }

  const addressTransport = ["udp"].includes(sourceTransport);

  return (
    <div className="page">

      <PageHeader
        title="Network Profiles"
        description="Satellite (NTN) and terrestrial (TN) networks that carry device uplinks."
      />

      {/* ADD / EDIT PROFILE */}

      {canManage && (
        <section className="card">
          <div className="section-header">
            <div>
              <h2>{form.id ? `Manage ${form.name}` : "Add Network Profile"}</h2>
              <p>
                A new satellite or terrestrial network is added here, without a code change.
                The code is stored with every uplink and cannot change later.
              </p>
            </div>
          </div>

          <form onSubmit={saveProfile}>
            <div className="form-grid">
              <div className="form-group">
                <label>Code</label>
                <input
                  value={form.code}
                  placeholder="astrocast"
                  pattern="[a-z][a-z0-9_]*"
                  title="lower_snake_case, starting with a letter"
                  disabled={Boolean(form.id)}
                  onChange={(e) => setForm({ ...form, code: e.target.value })}
                  required
                />
              </div>

              <div className="form-group">
                <label>Name</label>
                <input
                  value={form.name}
                  placeholder="Astrocast"
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  required
                />
              </div>

              <div className="form-group">
                <label>Network</label>
                <select
                  value={form.connection_type}
                  onChange={(e) => setForm({ ...form, connection_type: e.target.value })}
                >
                  <option value="NTN">NTN (satellite)</option>
                  <option value="TN">TN (terrestrial)</option>
                </select>
              </div>

              <div className="form-group">
                <label>Integration status</label>
                <select
                  value={form.integration_status}
                  onChange={(e) => setForm({ ...form, integration_status: e.target.value })}
                >
                  <option value="planned">Planned</option>
                  <option value="available">Available</option>
                </select>
              </div>

              <div className="form-group">
                <label>Uplink transport</label>
                <select
                  value={form.transport || ""}
                  onChange={(e) => setForm({ ...form, transport: e.target.value })}
                >
                  <option value="">Not set</option>
                  {TRANSPORTS.map((t) => (
                    <option key={t.value} value={t.value}>{t.label}</option>
                  ))}
                </select>
              </div>

              <div className="form-group">
                <label>Max payload (bytes)</label>
                <input
                  type="number"
                  min={1}
                  max={65535}
                  placeholder="No limit"
                  value={form.max_payload_bytes || ""}
                  onChange={(e) => setForm({ ...form, max_payload_bytes: e.target.value })}
                />
              </div>
            </div>

            <div className="form-group spaced">
              <label>Description</label>
              <input
                value={form.description || ""}
                placeholder="LEO IoT constellation, ground segment in ..."
                onChange={(e) => setForm({ ...form, description: e.target.value })}
              />
            </div>

            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={form.enabled}
                onChange={(e) => setForm({ ...form, enabled: e.target.checked })}
              />
              Enabled (uplinks of a disabled provider are refused)
            </label>

            <Notice notice={formNotice} />

            <div className="button-group">
              <button className="primary-button" type="submit">
                {form.id ? "Save Profile" : "Add Profile"}
              </button>
              {form.id && (
                <button
                  className="secondary-button"
                  type="button"
                  onClick={() => { setForm(EMPTY_PROFILE); setFormNotice(null); }}
                >
                  Cancel
                </button>
              )}
            </div>
          </form>
        </section>
      )}

      {/* PROFILE LIST */}

      <section className="card">
        <div className="section-header">
          <div>
            <h2>Network Profiles</h2>
            <p>
              {canManage
                ? "A used profile cannot be deleted: disable it to keep its history."
                : "Managed by the platform admin."}
            </p>
          </div>

          <button className="secondary-button" onClick={fetchProfiles}>Refresh</button>
        </div>

        {profiles.length === 0 ? (
          <div className="empty-state">No network profiles.</div>
        ) : (
          <div className="table-container">
            <table>
              <thead>
                <tr>
                  <th>Provider</th>
                  <th>Network</th>
                  <th>Integration</th>
                  <th>Transport</th>
                  <th>Max payload</th>
                  <th>Uplinks</th>
                  <th>State</th>
                  {canManage && <th>Actions</th>}
                </tr>
              </thead>
              <tbody>
                {profiles.map((profile) => (
                  <tr key={profile.id}>
                    <td>
                      <strong>{profile.name}</strong>
                      <div className="muted small-text"><code>{profile.code}</code></div>
                    </td>
                    <td>
                      <span className={`pill ${profile.connection_type === "NTN" ? "pill-ntn" : "pill-tn"}`}>
                        {profile.connection_type}
                      </span>
                    </td>
                    <td className="capitalize">{profile.integration_status}</td>
                    <td>{profile.transport ? profile.transport.toUpperCase() : "—"}</td>
                    <td>{profile.max_payload_bytes ? `${profile.max_payload_bytes} B` : "—"}</td>
                    <td>{profile.uplink_count}</td>
                    <td>
                      <StatusPill
                        active={profile.enabled}
                        activeText="Enabled"
                        inactiveText="Disabled"
                      />
                    </td>
                    {canManage && (
                      <td>
                        <div className="table-actions">
                          <button
                            className="secondary-button small"
                            onClick={() => {
                              setForm({ ...profile });
                              setFormNotice(null);
                              window.scrollTo(0, 0);
                            }}
                          >
                            Edit
                          </button>
                          <button
                            className="secondary-button small"
                            onClick={() => openSources(profile)}
                          >
                            Sources ({profile.source_count})
                          </button>
                          <button
                            className="secondary-button small"
                            onClick={() => toggleEnabled(profile)}
                          >
                            {profile.enabled ? "Disable" : "Enable"}
                          </button>
                          <button
                            className="danger-button small"
                            onClick={() => deleteProfile(profile)}
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

        <Notice notice={listNotice} />
      </section>

      {/* SOURCES */}

      {sourcesOf && (
        <section className="card">
          <div className="section-header">
            <div>
              <h2>Sources of {sourcesOf.name}</h2>
              <p>
                How an uplink is recognised as coming from {sourcesOf.name}:
                the source IP of its ground segment (UDP / satellite), or its
                client ID (TCP / MQTT).
              </p>
            </div>
            <button className="secondary-button" onClick={() => setSourcesOf(null)}>Close</button>
          </div>

          <form onSubmit={addSource} className="inline-form">
            <select
              value={sourceTransport}
              onChange={(e) => setSourceTransport(e.target.value)}
            >
              {TRANSPORTS.map((t) => (
                <option key={t.value} value={t.value}>{t.label}</option>
              ))}
            </select>
            <input
              className="grow"
              value={sourceIdentity}
              placeholder={
                sourceTransport === "webhook"
                  ? "Webhook URL or Path, e.g. /api/webhook/provider"
                  : addressTransport
                  ? "Source IP, e.g. 203.0.113.5"
                  : "Client ID, e.g. gw-cell-01"
              }
              onChange={(e) => setSourceIdentity(e.target.value)}
              required
            />
            <button className="primary-button inline" type="submit">Add Source</button>
          </form>

          <Notice notice={sourceNotice} />

          {sources.length === 0 ? (
            <div className="empty-state">
              No sources yet. Uplinks can still name this provider explicitly.
            </div>
          ) : (
            <div className="table-container">
              <table>
                <thead>
                  <tr>
                    <th>Transport</th>
                    <th>Identity</th>
                    <th>Added</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {sources.map((source) => (
                    <tr key={source.id}>
                      <td>{source.transport.toUpperCase()}</td>
                      <td><code>{source.identity}</code></td>
                      <td>{formatDate(source.created_at)}</td>
                      <td>
                        <button
                          className="danger-button small"
                          onClick={() => removeSource(source)}
                        >
                          Remove
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}

    </div>
  );
}

export default Connectivity;
