import { useEffect, useState } from "react";

import { formatDate } from "./api";
import { Notice, PageHeader, usePersistentState, RawPayloadBlock } from "./components";
import { DecoderRunner } from "./decoderRuntime";


const EMPTY_MATCH = {
  providerId: "",
  protocolId: "",
  deviceTypeId: "",
  messageType: "",
  version: "",
  payloadFormat: "",
};

const MATCH_LABELS = {
  providerId: "Provider",
  protocolId: "Protocol",
  deviceTypeId: "Device type",
  messageType: "Message type",
  version: "Version",
  payloadFormat: "Format Affinity",
};

function matchSummary(match) {
  const parts = Object.entries(match || {})
    .filter(([, value]) => value)
    .map(([key, value]) => `${MATCH_LABELS[key] || key}: ${value}`);

  return parts.length ? parts.join(" · ") : null;
}


const FIELD_DATA_TYPES = [
  { value: "uint8", label: "uint8 (1 byte unsigned)" },
  { value: "int8", label: "int8 (1 byte signed)" },
  { value: "uint16", label: "uint16 (2 bytes unsigned)" },
  { value: "int16", label: "int16 (2 bytes signed)" },
  { value: "uint32", label: "uint32 (4 bytes unsigned)" },
  { value: "int32", label: "int32 (4 bytes signed)" },
  { value: "uint64", label: "uint64 (8 bytes unsigned)" },
  { value: "int64", label: "int64 (8 bytes signed)" },
  { value: "float32", label: "float32 (4 bytes float)" },
  { value: "float64", label: "float64 (8 bytes double)" },
  { value: "bool", label: "bool (1 byte boolean)" },
  { value: "ascii", label: "ascii (String text)" },
  { value: "hex", label: "hex (Hex bytes)" },
  { value: "bitfield", label: "bitfield" },
];


function Decoders({ api, currentUser }) {
  const permissions = currentUser.permissions;
  const isAdmin = currentUser.role === "admin";

  const canManage = Boolean(permissions?.manage_decoder || isAdmin);

  const [decoders, setDecoders] = useState([]);
  const [activations, setActivations] = useState([]);
  const [tenants, setTenants] = useState([]);
  const [profiles, setProfiles] = useState([]);

  // Create decoder state
  const [showCreate, setShowCreate] = useState(false);
  const [createNotice, setCreateNotice] = useState(null);
  const [createName, setCreateName] = useState("");
  const [createTenantId, setCreateTenantId] = useState("");
  const [createKind, setCreateKind] = useState("javascript");
  const [createByteOrder, setCreateByteOrder] = useState("big");
  const [createDescription, setCreateDescription] = useState("");
  const [createCode, setCreateCode] = useState(
    `function decode(input) {\n  // input.payload.bytes contains Uint8Array\n  // input.context has device metadata\n  return {\n    temperature: input.payload.bytes[0],\n    humidity: input.payload.bytes[1]\n  };\n}`
  );
  const [createFields, setCreateFields] = useState([
    {
      field_name: "temperature",
      byte_offset: 0,
      byte_length: 2,
      data_type: "uint16",
      scale_factor: 0.01,
      value_offset: 0,
      unit: "°C",
    },
    {
      field_name: "humidity",
      byte_offset: 2,
      byte_length: 2,
      data_type: "uint16",
      scale_factor: 0.1,
      value_offset: 0,
      unit: "%RH",
    },
  ]);
  const [createMatch, setCreateMatch] = useState({
    protocolId: "",
    payloadFormat: "",
    providerId: "",
    deviceTypeId: "",
    messageType: "",
    version: "",
  });

  const [listNotice, setListNotice] = useState(null);

  // Detail / dry run of one version (kept while switching pages)
  const [selectedId, setSelectedId] = usePersistentState("decoders.selected", null);
  const [payloadHex, setPayloadHex] = usePersistentState("decoders.payloadHex", "09c4026c");
  const [contextJson, setContextJson] = usePersistentState("decoders.context", '{\n  "deviceId": "MAIN-01"\n}');
  const [testResult, setTestResult] = usePersistentState("decoders.testResult", null);

  // "Which decoder matches?"
  const [probe, setProbe] = usePersistentState("decoders.probe", EMPTY_MATCH);
  const [probeResult, setProbeResult] = usePersistentState("decoders.probeResult", null);

  const selected = decoders.find((decoder) => decoder.id === selectedId) || null;

  function setSelected(decoder) {
    setSelectedId(decoder ? decoder.id : null);
  }

  useEffect(() => {
    refresh();
    api.get("/connectivity-profiles/").then(setProfiles).catch(() => setProfiles([]));

    if (isAdmin) {
      api.get("/tenants/").then(setTenants).catch(() => setTenants([]));
    }
  }, [api]);

  async function refresh() {
    try {
      const [decoderList, activationList] = await Promise.all([
        api.get("/decode-schemas/"),
        api.get("/decode-schemas/activations"),
      ]);

      setDecoders(decoderList);
      setActivations(activationList);
    } catch (error) {
      setListNotice({ type: "error", text: error.message });
    }
  }

  function ownerName(tenantId) {
    if (tenantId === null) {
      return "Platform";
    }

    if (tenantId === currentUser.tenant_id && currentUser.tenant_name) {
      return currentUser.tenant_name;
    }

    return tenants.find((tenant) => tenant.id === tenantId)?.name || `Organization ${tenantId}`;
  }

  // Platform decoders are managed by admins only
  function canManageDecoder(decoder) {
    return canManage && (decoder.tenant_id !== null || isAdmin);
  }

  function cleanMatch(values) {
    return Object.fromEntries(
      Object.entries(values).map(([key, value]) => [key, value.trim() || null])
    );
  }

  // -------------------------
  // Test / activate / delete / match
  // -------------------------

  async function testDecoder(event) {
    event.preventDefault();

    let context = {};

    if (selected.kind === "javascript" && contextJson.trim()) {
      try {
        context = JSON.parse(contextJson);
      } catch {
        setTestResult({ ok: false, error: "The context must be valid JSON." });
        return;
      }
    }

    try {
      setTestResult(
        await api.post(`/decode-schemas/${selected.id}/test`, {
          payload_hex: payloadHex.trim(),
          context,
        })
      );
    } catch (error) {
      setTestResult({ ok: false, error: error.message });
    }
  }

  async function activateDecoder(decoder) {
    if (!window.confirm(
      `Make ${decoder.name} v${decoder.version} the live version? Every application using another version of ${decoder.name} moves to it${matchSummary(decoder.match) ? ", and it is used for devices it matches" : ""}.`
    )) {
      return;
    }

    setListNotice(null);

    try {
      const result = await api.post(`/decode-schemas/${decoder.id}/activate`, {
        note: null,
      });

      setListNotice({
        type: "success",
        text: `${decoder.name} v${decoder.version} is live. ${result.applications_updated} application(s) moved to it.`,
      });
      refresh();
    } catch (error) {
      setListNotice({ type: "error", text: error.message });
    }
  }

  async function deleteDecoder(decoder) {
    const appMsg = decoder.application_count > 0
      ? ` It is currently used by ${decoder.application_count} application(s) and will be unlinked automatically.`
      : "";
    if (!window.confirm(`Delete ${decoder.name} v${decoder.version}?${appMsg}`)) {
      return;
    }

    setListNotice(null);

    try {
      await api.delete(`/decode-schemas/${decoder.id}`);
      setListNotice({ type: "success", text: `${decoder.name} v${decoder.version} deleted.` });

      if (selected?.id === decoder.id) {
        setSelected(null);
      }

      refresh();
    } catch (error) {
      setListNotice({ type: "error", text: error.message });
    }
  }

  async function unassignDecoder(decoder) {
    if (!window.confirm(`Unassign ${decoder.name} v${decoder.version} from all ${decoder.application_count} application(s)?`)) {
      return;
    }

    setListNotice(null);

    try {
      const res = await api.post(`/decode-schemas/${decoder.id}/unassign`);
      setListNotice({
        type: "success",
        text: `Unassigned ${decoder.name} v${decoder.version} from ${res.unassigned_applications || 0} application(s).`,
      });
      refresh();
    } catch (error) {
      setListNotice({ type: "error", text: error.message });
    }
  }

  // -------------------------
  // Create New Decoder Format
  // -------------------------

  function handleKindChange(newKind) {
    setCreateKind(newKind);
    if (newKind === "python" && !createCode.includes("def decode")) {
      setCreateCode(
        `def decode(input):\n    # input contains payload (bytes, hex) and context\n    payload = input.get('payload', {})\n    raw_bytes = payload.get('bytes', [])\n    return {\n        'temperature': raw_bytes[0] if len(raw_bytes) > 0 else 0,\n        'humidity': raw_bytes[1] if len(raw_bytes) > 1 else 0\n    }\n`
      );
    } else if (newKind === "javascript" && !createCode.includes("function decode")) {
      setCreateCode(
        `function decode(input) {\n  // input.payload.bytes contains Uint8Array\n  return {\n    temperature: input.payload.bytes[0],\n    humidity: input.payload.bytes[1]\n  };\n}`
      );
    }
  }

  function handleAddField() {
    const lastField = createFields[createFields.length - 1];
    const nextOffset = lastField ? Number(lastField.byte_offset) + Number(lastField.byte_length) : 0;
    setCreateFields([
      ...createFields,
      {
        field_name: `field_${createFields.length + 1}`,
        byte_offset: nextOffset,
        byte_length: 2,
        data_type: "uint16",
        scale_factor: 1,
        value_offset: 0,
        unit: "",
      },
    ]);
  }

  function handleRemoveField(index) {
    if (createFields.length <= 1) {
      alert("A fields decoder must have at least one field.");
      return;
    }
    setCreateFields(createFields.filter((_, i) => i !== index));
  }

  function handleFieldChange(index, key, value) {
    const updated = [...createFields];
    updated[index] = { ...updated[index], [key]: value };
    if (key === "data_type") {
      const sizes = {
        uint8: 1, int8: 1, bool: 1,
        uint16: 2, int16: 2,
        uint32: 4, int32: 4, float32: 4,
        uint64: 8, int64: 8, float64: 8,
      };
      if (sizes[value]) {
        updated[index].byte_length = sizes[value];
      }
    }
    setCreateFields(updated);
  }

  async function handleCreateDecoder(event) {
    event.preventDefault();
    setCreateNotice(null);

    const trimmedName = createName.trim();
    if (!trimmedName) {
      setCreateNotice({ type: "error", text: "Please enter a decoder name." });
      return;
    }

    try {
      const payload = {
        name: trimmedName,
        tenant_id: isAdmin && createTenantId ? Number(createTenantId) : null,
        description: createDescription.trim() || null,
        match: cleanMatch(createMatch),
      };

      if (createKind === "javascript" || createKind === "python") {
        if (!createCode.trim()) {
          setCreateNotice({ type: "error", text: "Decoder code cannot be empty." });
          return;
        }
        payload.code = createCode.trim();
        payload.fields = null;
      } else {
        if (!createFields || createFields.length === 0) {
          setCreateNotice({ type: "error", text: "At least one field definition is required." });
          return;
        }
        payload.code = null;
        payload.byte_order = createByteOrder;
        payload.fields = createFields.map((f) => ({
          field_name: (f.field_name || "").trim().toLowerCase().replace(/[^a-z0-9_]/g, "_") || "field",
          byte_offset: Number(f.byte_offset) || 0,
          byte_length: Number(f.byte_length) || 1,
          data_type: f.data_type || "uint8",
          scale_factor: f.scale_factor !== undefined && f.scale_factor !== "" ? Number(f.scale_factor) : 1,
          value_offset: f.value_offset !== undefined && f.value_offset !== "" ? Number(f.value_offset) : 0,
          unit: f.unit ? f.unit.trim() : null,
        }));
      }

      const created = await api.post("/decode-schemas/", payload);
      setListNotice({
        type: "success",
        text: `Decoder "${created.name} v${created.version}" created successfully!`,
      });
      setShowCreate(false);
      setCreateName("");
      setCreateDescription("");
      refresh();
    } catch (err) {
      setCreateNotice({ type: "error", text: err.message });
    }
  }

  async function explainMatch(event) {
    event.preventDefault();

    try {
      setProbeResult(await api.post("/decode-schemas/match", cleanMatch(probe)));
    } catch (error) {
      setProbeResult({ error: error.message });
    }
  }

  function matchInputs(values, setValues) {
    return (
      <div className="form-grid six" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))" }}>
        <div className="form-group">
          <label>Payload Format</label>
          <select
            value={values.payloadFormat || ""}
            onChange={(e) => setValues({ ...values, payloadFormat: e.target.value })}
          >
            <option value="">Any (Dynamic)</option>
            <option value="json">JSON</option>
            <option value="hex">Hex</option>
            <option value="binary">Binary</option>
            <option value="base64">Base64</option>
          </select>
        </div>
        <div className="form-group">
          <label>Provider</label>
          <select
            value={values.providerId}
            onChange={(e) => setValues({ ...values, providerId: e.target.value })}
          >
            <option value="">Any</option>
            {profiles.map((profile) => (
              <option key={profile.code} value={profile.code}>{profile.name}</option>
            ))}
          </select>
        </div>
        <div className="form-group">
          <label>Protocol</label>
          <select
            value={values.protocolId || ""}
            onChange={(e) => setValues({ ...values, protocolId: e.target.value })}
          >
            <option value="">Any (All Protocols)</option>
            <option value="https">HTTPS</option>
            <option value="mqtt">MQTT</option>
            <option value="tcp">TCP/IP</option>
            <option value="udp">UDP</option>
            <option value="webhook">Webhook</option>
            <option value="custom">Custom</option>
          </select>
        </div>
        {["deviceTypeId", "messageType", "version"].map((key) => (
          <div className="form-group" key={key}>
            <label>{MATCH_LABELS[key]}</label>
            <input
              value={values[key]}
              placeholder={{
                deviceTypeId: "sensor",
                messageType: "status",
                version: "2",
              }[key]}
              onChange={(e) => setValues({ ...values, [key]: e.target.value })}
            />
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className="page">

      <PageHeader
        title="Decoders"
        description="Turn raw uplink bytes into values with JavaScript. A device uses its application's decoder; otherwise the live decoder whose match fits best."
      />

      {/* WRITE AND RUN (TTN Split-Screen Decoder & Live Stream) */}

      <DecoderRunner currentUser={currentUser} api={api} />

      {/* LIST */}

      <section className="card">
        <div className="section-header">
          <div>
            <h2>Decoder Versions</h2>
            <p>
              {isAdmin
                ? "Platform decoders and every organization's decoders."
                : "Your organization's decoders and the platform decoders."}
            </p>
          </div>

          <div style={{ display: "flex", gap: "8px" }}>
            {canManage && (
              <button
                className="primary-button"
                onClick={() => {
                  setShowCreate(!showCreate);
                  setCreateNotice(null);
                }}
              >
                {showCreate ? "Close" : "+ Add Decoder Format"}
              </button>
            )}
            <button className="secondary-button" onClick={refresh}>Refresh</button>
          </div>
        </div>

        {/* ADD DECODER FORMAT FORM */}
        {showCreate && (
          <div
            style={{
              padding: "20px",
              background: "var(--surface-sunken, #0f172a)",
              borderRadius: "8px",
              border: "1px solid var(--border-color, #334155)",
              marginBottom: "24px",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "16px" }}>
              <div>
                <h3 style={{ margin: 0, fontSize: "1.15rem" }}>➕ Add New Decoder Format</h3>
                <p style={{ margin: "4px 0 0 0", fontSize: "0.85rem", color: "var(--text-muted)" }}>
                  Create a new platform or organization decoder format. Choose between JavaScript, Python, or Declarative binary fields.
                </p>
              </div>
              <button
                type="button"
                className="secondary-button small"
                onClick={() => setShowCreate(false)}
              >
                Close
              </button>
            </div>

            <form onSubmit={handleCreateDecoder}>
              <div className="form-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", marginBottom: "16px" }}>
                <div className="form-group">
                  <label>Decoder Name</label>
                  <input
                    type="text"
                    placeholder="e.g. smart_water_meter"
                    value={createName}
                    onChange={(e) => setCreateName(e.target.value)}
                    required
                  />
                  <small style={{ color: "#94a3b8", fontSize: "0.75rem" }}>
                    If this name exists, it will create the next version (v2, v3).
                  </small>
                </div>

                {isAdmin && (
                  <div className="form-group">
                    <label>Scope / Owner</label>
                    <select
                      value={createTenantId}
                      onChange={(e) => setCreateTenantId(e.target.value)}
                    >
                      <option value="">Platform Decoder (All Organizations)</option>
                      {tenants.map((t) => (
                        <option key={t.id} value={t.id}>
                          {t.name} (Organization)
                        </option>
                      ))}
                    </select>
                  </div>
                )}

                <div className="form-group">
                  <label>Decoder Format Type</label>
                  <div style={{ display: "flex", gap: "8px", marginTop: "4px" }}>
                    {[
                      { key: "javascript", label: "JavaScript" },
                      { key: "python", label: "Python" },
                      { key: "fields", label: "Binary Fields" },
                    ].map((fmt) => (
                      <button
                        key={fmt.key}
                        type="button"
                        className={createKind === fmt.key ? "primary-button small" : "secondary-button small"}
                        onClick={() => handleKindChange(fmt.key)}
                        style={{ flex: 1, padding: "6px 12px" }}
                      >
                        {fmt.label}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="form-group">
                  <label>Version Description (Optional)</label>
                  <input
                    type="text"
                    placeholder="e.g. Initial version for pressure and flow"
                    value={createDescription}
                    onChange={(e) => setCreateDescription(e.target.value)}
                  />
                </div>
              </div>

              {/* JAVASCRIPT / PYTHON CODE EDITOR */}
              {(createKind === "javascript" || createKind === "python") && (
                <div style={{ marginBottom: "20px" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "6px" }}>
                    <label style={{ margin: 0, fontWeight: 600 }}>
                      {createKind === "javascript" ? "JavaScript Decoder Function:" : "Python Decoder Function:"}
                    </label>
                    <span style={{ fontSize: "0.78rem", color: "#94a3b8" }}>
                      {createKind === "javascript" ? "ES6 function decode(input)" : "Python def decode(input):"}
                    </span>
                  </div>
                  <textarea
                    className="code-editor"
                    rows={8}
                    value={createCode}
                    onChange={(e) => setCreateCode(e.target.value)}
                    required
                  />
                </div>
              )}

              {/* DECLARATIVE BINARY FIELDS EDITOR */}
              {createKind === "fields" && (
                <div style={{ marginBottom: "20px" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "10px", marginBottom: "12px" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
                      <label style={{ margin: 0, fontWeight: 600 }}>Field Layout:</label>
                      <label style={{ margin: 0, fontSize: "0.85rem", display: "inline-flex", alignItems: "center", gap: "6px" }}>
                        <span>Endianness:</span>
                        <select
                          style={{ padding: "3px 8px", fontSize: "0.82rem" }}
                          value={createByteOrder}
                          onChange={(e) => setCreateByteOrder(e.target.value)}
                        >
                          <option value="big">Big Endian (standard)</option>
                          <option value="little">Little Endian</option>
                        </select>
                      </label>
                    </div>

                    <button
                      type="button"
                      className="secondary-button small"
                      onClick={handleAddField}
                    >
                      + Add Field
                    </button>
                  </div>

                  <div className="table-container" style={{ maxHeight: "300px", overflowY: "auto" }}>
                    <table style={{ width: "100%", fontSize: "0.85rem" }}>
                      <thead>
                        <tr>
                          <th>Field Name</th>
                          <th>Offset</th>
                          <th>Length</th>
                          <th>Data Type</th>
                          <th>Scale</th>
                          <th>Offset</th>
                          <th>Unit</th>
                          <th>Action</th>
                        </tr>
                      </thead>
                      <tbody>
                        {createFields.map((field, idx) => (
                          <tr key={idx}>
                            <td>
                              <input
                                style={{ width: "110px", padding: "4px 6px" }}
                                value={field.field_name}
                                placeholder="name"
                                onChange={(e) => handleFieldChange(idx, "field_name", e.target.value)}
                                required
                              />
                            </td>
                            <td>
                              <input
                                type="number"
                                style={{ width: "60px", padding: "4px 6px" }}
                                value={field.byte_offset}
                                min="0"
                                onChange={(e) => handleFieldChange(idx, "byte_offset", e.target.value)}
                                required
                              />
                            </td>
                            <td>
                              <input
                                type="number"
                                style={{ width: "55px", padding: "4px 6px" }}
                                value={field.byte_length}
                                min="1"
                                onChange={(e) => handleFieldChange(idx, "byte_length", e.target.value)}
                                required
                              />
                            </td>
                            <td>
                              <select
                                style={{ width: "120px", padding: "4px 6px" }}
                                value={field.data_type}
                                onChange={(e) => handleFieldChange(idx, "data_type", e.target.value)}
                              >
                                {FIELD_DATA_TYPES.map((t) => (
                                  <option key={t.value} value={t.value}>{t.label}</option>
                                ))}
                              </select>
                            </td>
                            <td>
                              <input
                                type="number"
                                step="any"
                                style={{ width: "65px", padding: "4px 6px" }}
                                value={field.scale_factor}
                                onChange={(e) => handleFieldChange(idx, "scale_factor", e.target.value)}
                              />
                            </td>
                            <td>
                              <input
                                type="number"
                                step="any"
                                style={{ width: "65px", padding: "4px 6px" }}
                                value={field.value_offset}
                                onChange={(e) => handleFieldChange(idx, "value_offset", e.target.value)}
                              />
                            </td>
                            <td>
                              <input
                                style={{ width: "65px", padding: "4px 6px" }}
                                value={field.unit || ""}
                                placeholder="e.g. °C"
                                onChange={(e) => handleFieldChange(idx, "unit", e.target.value)}
                              />
                            </td>
                            <td>
                              <button
                                type="button"
                                style={{ background: "none", border: "none", color: "#ef4444", cursor: "pointer", fontSize: "1.1rem" }}
                                onClick={() => handleRemoveField(idx)}
                                title="Remove field"
                              >
                                ×
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {/* ROUTING MATCH CRITERIA (OPTIONAL) */}
              <div style={{ padding: "12px", background: "rgba(0,0,0,0.2)", borderRadius: "6px", marginBottom: "16px" }}>
                <div style={{ fontWeight: 600, fontSize: "0.85rem", color: "#cbd5e1", marginBottom: "8px" }}>
                  Routing Match Criteria (Optional — for automatic message matching):
                </div>
                <div className="form-grid six" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))" }}>
                  <div className="form-group">
                    <label>Protocol</label>
                    <select
                      value={createMatch.protocolId}
                      onChange={(e) => setCreateMatch({ ...createMatch, protocolId: e.target.value })}
                    >
                      <option value="">Any Protocol</option>
                      <option value="https">HTTPS</option>
                      <option value="mqtt">MQTT</option>
                      <option value="tcp">TCP/IP</option>
                      <option value="udp">UDP</option>
                      <option value="webhook">Webhook</option>
                      <option value="custom">Custom</option>
                    </select>
                  </div>

                  <div className="form-group">
                    <label>Payload Format</label>
                    <select
                      value={createMatch.payloadFormat}
                      onChange={(e) => setCreateMatch({ ...createMatch, payloadFormat: e.target.value })}
                    >
                      <option value="">Any Format</option>
                      <option value="json">JSON</option>
                      <option value="hex">Hex</option>
                      <option value="binary">Binary</option>
                      <option value="base64">Base64</option>
                    </select>
                  </div>

                  <div className="form-group">
                    <label>Provider</label>
                    <select
                      value={createMatch.providerId}
                      onChange={(e) => setCreateMatch({ ...createMatch, providerId: e.target.value })}
                    >
                      <option value="">Any</option>
                      {profiles.map((p) => (
                        <option key={p.code} value={p.code}>{p.name}</option>
                      ))}
                    </select>
                  </div>

                  <div className="form-group">
                    <label>Device Type</label>
                    <input
                      placeholder="e.g. sensor"
                      value={createMatch.deviceTypeId}
                      onChange={(e) => setCreateMatch({ ...createMatch, deviceTypeId: e.target.value })}
                    />
                  </div>

                  <div className="form-group">
                    <label>Message Type</label>
                    <input
                      placeholder="e.g. status"
                      value={createMatch.messageType}
                      onChange={(e) => setCreateMatch({ ...createMatch, messageType: e.target.value })}
                    />
                  </div>
                </div>
              </div>

              <Notice notice={createNotice} />

              <div style={{ display: "flex", gap: "10px", justifyContent: "flex-end", marginTop: "12px" }}>
                <button
                  type="button"
                  className="secondary-button"
                  onClick={() => setShowCreate(false)}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="primary-button"
                >
                  Save & Register Decoder
                </button>
              </div>
            </form>
          </div>
        )}

        {decoders.length === 0 ? (
          <div className="empty-state">No decoders yet.</div>
        ) : (
          <div className="table-container">
            <table>
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Version</th>
                  <th>Owner</th>
                  <th>Type</th>
                  <th>Match</th>
                  <th>Assigned Apps</th>
                  <th>Status</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {decoders.map((decoder) => (
                  <tr
                    key={decoder.id}
                    className={selected?.id === decoder.id ? "command-row selected" : "command-row"}
                    onClick={() => { setSelected(decoder); setTestResult(null); }}
                  >
                    <td><strong>{decoder.name}</strong></td>
                    <td>{String(decoder.version || "1").startsWith("v") ? decoder.version : `v${decoder.version || 1}`}</td>
                    <td>{ownerName(decoder.tenant_id)}</td>
                    <td>
                      {decoder.kind === "javascript" ? (
                        <span className="pill pill-ok">JavaScript</span>
                      ) : decoder.kind === "python" ? (
                        <span className="pill pill-type type-direct_ip">Python</span>
                      ) : (
                        <span className="pill pill-warn">Fields</span>
                      )}
                    </td>
                    <td className="small-text">
                      {matchSummary(decoder.match) || <span className="muted">application only</span>}
                    </td>
                    <td>{decoder.application_count}</td>
                    <td>
                      {decoder.active_activation_id
                        ? <span className="pill pill-ok">Live</span>
                        : <span className="muted">—</span>}
                    </td>
                    <td onClick={(e) => e.stopPropagation()}>
                      <div className="table-actions">
                        <button
                          className="secondary-button small"
                          onClick={() => { setSelected(decoder); setTestResult(null); }}
                        >
                          Test
                        </button>

                        {canManageDecoder(decoder) && !decoder.active_activation_id && (
                          <button
                            className="secondary-button small"
                            onClick={() => activateDecoder(decoder)}
                          >
                            Activate
                          </button>
                        )}

                        {canManageDecoder(decoder) && (
                          <button
                            className="danger-button small"
                            onClick={() => deleteDecoder(decoder)}
                            title="Delete this decoder (will automatically unbind from any applications)"
                          >
                            Delete
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <Notice notice={listNotice} />
      </section>

      {/* DETAIL + DRY RUN */}

      {selected && (
        <section className="card">
          <div className="section-header">
            <div>
              <h2>{selected.name} {String(selected.version || "1").startsWith("v") ? selected.version : `v${selected.version || 1}`}</h2>
              <p>
                {selected.kind === "javascript" ? "JavaScript decoder" : `Field decoder, ${selected.byte_order} endian`}
                {matchSummary(selected.match) ? ` · match ${matchSummary(selected.match)}` : ""}
                {selected.description ? ` · ${selected.description}` : ""}
              </p>
            </div>
            <div style={{ display: "flex", gap: "8px" }}>
              {canManageDecoder(selected) && (
                <button
                  className="danger-button small"
                  type="button"
                  onClick={() => deleteDecoder(selected)}
                  title="Delete this decoder version"
                >
                  Delete Decoder
                </button>
              )}
              <button
                className="secondary-button"
                type="button"
                onClick={() => setSelected(null)}
              >
                Close
              </button>
            </div>
          </div>

          {selected.kind === "javascript" ? (
            <pre className="code-view">{selected.code}</pre>
          ) : (
            <div className="table-container">
              <table>
                <thead>
                  <tr>
                    <th>Field</th>
                    <th>Bytes</th>
                    <th>Type</th>
                    <th>Scale / offset</th>
                    <th>Unit</th>
                  </tr>
                </thead>
                <tbody>
                  {selected.fields.map((field) => (
                    <tr key={field.field_name}>
                      <td><strong>{field.field_name}</strong></td>
                      <td>
                        {field.byte_offset}..{field.byte_offset + field.byte_length - 1}
                        {field.data_type === "bitfield" &&
                          ` (bits ${field.bit_offset}+${field.bit_length})`}
                      </td>
                      <td>{field.data_type}</td>
                      <td>× {field.scale_factor} + {field.value_offset}</td>
                      <td>{field.unit || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <form onSubmit={testDecoder} className="schema-section">
            <div className="schema-title">
              <div>
                <h3>Dry run</h3>
                <p>Decode a sample payload. Nothing is stored.</p>
              </div>
            </div>

            <div className="inline-form">
              <input
                className="grow"
                value={payloadHex}
                placeholder="Payload as hex, e.g. 09c4026c"
                onChange={(e) => setPayloadHex(e.target.value)}
                required
              />
              <button className="primary-button inline" type="submit">Decode</button>
            </div>

            {selected.kind === "javascript" && (
              <div className="form-group">
                <label>input.context (JSON)</label>
                <textarea
                  className="code-editor"
                  rows={4}
                  value={contextJson}
                  spellCheck={false}
                  onChange={(e) => setContextJson(e.target.value)}
                />
              </div>
            )}

            {testResult && (
              testResult.ok ? (
                <div className="schema-preview">
                  <RawPayloadBlock message={{ payloadHex: payloadHex.trim(), rawPayload: payloadHex.trim() }} />
                  <div className="preview-header">
                    <span>Decoded Output</span>
                    <span className="hardcoded-badge">OK</span>
                  </div>
                  <pre>{JSON.stringify(testResult.decoded, null, 2)}</pre>
                </div>
              ) : (
                <div className="message error">{testResult.error}</div>
              )
            )}
          </form>
        </section>
      )}

      {/* WHICH DECODER MATCHES */}

      <section className="card">
        <div className="section-header">
          <div>
            <h2>Which decoder matches?</h2>
            <p>
              What the pipeline picks for a device whose application has no decoder.
              Protocol defaults to the transport type (udp, tcp, mqtt, webhook).
            </p>
          </div>
        </div>

        <form onSubmit={explainMatch}>
          {matchInputs(probe, setProbe)}

          {probeResult && (
            probeResult.error ? (
              <div className="message error">{probeResult.error}</div>
            ) : probeResult.decoder ? (
              <div className="message success">
                <strong>{probeResult.decoder.name} v{probeResult.decoder.version}</strong>
                {probeResult.candidates.length > 1 &&
                  ` — also fitting: ${probeResult.candidates.slice(1).map((c) => `${c.name} v${c.version}`).join(", ")}`}
              </div>
            ) : (
              <div className="message warning">
                No live decoder matches. The uplink would be kept as NO_ACTIVE_SCHEMA.
              </div>
            )
          )}

          <button className="primary-button" type="submit">Find decoder</button>
        </form>
      </section>

      {/* ACTIVATION HISTORY */}

      <section className="card">
        <div className="section-header">
          <div>
            <h2>Activation History</h2>
            <p>Newest first. Only one version of a decoder is live at a time.</p>
          </div>
        </div>

        {activations.length === 0 ? (
          <div className="empty-state">No activations yet.</div>
        ) : (
          <div className="table-container">
            <table>
              <thead>
                <tr>
                  <th>Decoder</th>
                  <th>Activated</th>
                  <th>Deactivated</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {activations.map((activation) => (
                  <tr key={activation.activation_id}>
                    <td><strong>{activation.schema_name}</strong> v{activation.schema_version}</td>
                    <td>{formatDate(activation.activated_at)}</td>
                    <td>{formatDate(activation.deactivated_at)}</td>
                    <td>
                      {activation.active
                        ? <span className="pill pill-ok">Live</span>
                        : <span className="muted">Replaced</span>}
                    </td>
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

export default Decoders;
