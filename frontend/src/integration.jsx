import { useEffect, useState } from "react";

import { API, formatDate } from "./api";
import { Notice, PageHeader, Restricted, StatusPill } from "./components";
import { Icon } from "./icons";


// Body of every delivery (webhook POST and MQTT message), as built by
// IngestionService.build_event in the backend
const SAMPLE_EVENT = {
  event: "telemetry.uplink",
  telemetry_id: 1842,
  tenant_id: 1,
  device_id: "LORA-01",
  application_id: 3,
  timestamp: "2026-10-26T09:41:07+00:00",
  received_at: "2026-10-26T09:41:09+00:00",
  provider: "skylo",
  connection_type: "NTN",
  decode_activation_id: 12,
  decode_schema_id: 7,
  telemetry: { temperature: 21.4, humidity: 60.2, battery: 3.61 },
  units: { temperature: "°C", humidity: "%RH", battery: "V" },
};

const REST_ENDPOINTS = [
  {
    method: "POST",
    path: "/auth/login",
    description: "Exchange a name and password for a bearer token.",
    query: "",
  },
  {
    method: "GET",
    path: "/telemetry/",
    description: "Decoded uplinks of every device you can see, newest first.",
    query: "application_id, device_id, connection_type (NTN | TN), provider, start, end, limit (≤ 1000)",
  },
  {
    method: "GET",
    path: "/devices/{device_id}/telemetry",
    description: "History of one device.",
    query: "start, end (ISO 8601), connection_type, limit (≤ 1000)",
  },
  {
    method: "GET",
    path: "/devices/{device_id}/latest",
    description: "The latest decoded reading of one device (404 if none yet).",
    query: "",
  },
  {
    method: "GET",
    path: "/decoder-messages/",
    description: "Messages decoded by the decoder runtime, including failures.",
    query: "status (decoded | failed), device_id, limit (≤ 500)",
  },
  {
    method: "GET",
    path: "/devices/",
    description: "Registered devices with their network type and identifiers.",
    query: "",
  },
  {
    method: "GET",
    path: "/usage/",
    description: "Message counts for your organization (owners and admins).",
    query: "tenant_id (admins)",
  },
];

const CHANNELS = [
  {
    key: "webhook",
    icon: "integration",
    title: "Webhooks",
    kind: "Push · HTTPS",
    text: "Every decoded uplink is POSTed as JSON to your URL, signed with HMAC-SHA256. Failed deliveries are retried with back-off.",
  },
  {
    key: "rest",
    icon: "decoders",
    title: "REST API",
    kind: "Pull · HTTPS",
    text: "Query history and the latest values on demand with a bearer token. Best for dashboards and batch jobs.",
  },
  {
    key: "mqtt",
    icon: "connectivity",
    title: "MQTT",
    kind: "Stream · QoS 1",
    text: "Subscribe to your organization's topic tree to receive each uplink the moment it is decoded.",
  },
];


function CodeBlock({ code, label }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard blocked: the code can still be selected
    }
  }

  return (
    <div className="code-block">
      <div className="code-block-header">
        <span>{label}</span>
        <button type="button" className="text-button" onClick={copy}>
          <Icon name={copied ? "check" : "copy"} size={14} />
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre>{code}</pre>
    </div>
  );
}


function Integration({ api, currentUser }) {
  const isAdmin = currentUser.role === "admin";
  const canManageWebhooks = currentUser.capabilities.manage_webhooks;
  const tenantSegment = currentUser.tenant_id ?? "{tenant_id}";

  const [channel, setChannel] = useState("webhook");

  const [webhooks, setWebhooks] = useState([]);
  const [alerts, setAlerts] = useState([]);
  const [tenants, setTenants] = useState([]);
  const [profiles, setProfiles] = useState([]);

  const [form, setForm] = useState({
    name: "",
    url: "",
    tenant_id: "",
    device_ids: "",
    connection_types: [],
    providers: [],
  });
  const [createdSecret, setCreatedSecret] = useState(null);
  const [notice, setNotice] = useState(null);
  const [listNotice, setListNotice] = useState(null);

  // User-configured MQTT Broker state
  const [mqttConfig, setMqttConfig] = useState({
    name: "Default MQTT Broker",
    enabled: true,
    host: "",
    port: 1883,
    client_id: "",
    username: "",
    password: "",
    has_password: false,
    topic_prefix: `nibiaanet/tenants/${tenantSegment}/devices/{device_id}/telemetry`,
    qos: 1,
    use_tls: false,
  });
  const [mqttNotice, setMqttNotice] = useState(null);
  const [mqttTestNotice, setMqttTestNotice] = useState(null);
  const [mqttSaving, setMqttSaving] = useState(false);
  const [mqttTesting, setMqttTesting] = useState(false);

  useEffect(() => {
    api.get("/connectivity-profiles/").then(setProfiles).catch(() => setProfiles([]));

    if (canManageWebhooks) {
      refresh();
    }

    if (isAdmin) {
      api.get("/tenants/").then(setTenants).catch(() => setTenants([]));
    }

    // Load tenant MQTT broker settings
    api.get("/mqtt/config").then((cfg) => {
      if (cfg && cfg.host) {
        setMqttConfig((prev) => ({
          ...prev,
          ...cfg,
          password: "",
        }));
      }
    }).catch(() => {});
  }, [api]);

  async function saveMqttConfig(e) {
    e.preventDefault();
    setMqttNotice(null);
    setMqttTestNotice(null);
    setMqttSaving(true);
    try {
      const payload = {
        name: mqttConfig.name || "Default MQTT Broker",
        enabled: mqttConfig.enabled,
        host: mqttConfig.host.trim(),
        port: parseInt(mqttConfig.port, 10) || 1883,
        client_id: mqttConfig.client_id ? mqttConfig.client_id.trim() : null,
        username: mqttConfig.username ? mqttConfig.username.trim() : null,
        password: mqttConfig.password || null,
        topic_prefix: mqttConfig.topic_prefix || `nibiaanet/tenants/${tenantSegment}/devices/{device_id}/telemetry`,
        qos: parseInt(mqttConfig.qos, 10) || 1,
        use_tls: !!mqttConfig.use_tls,
      };
      const res = await api.post("/mqtt/config", { body: payload });
      setMqttConfig((prev) => ({
        ...prev,
        ...res,
        password: "",
      }));
      setMqttNotice({
        type: "success",
        text: `MQTT broker configuration saved successfully! Telemetry will stream to ${res.host}:${res.port}.`,
      });
    } catch (err) {
      setMqttNotice({ type: "error", text: err.message });
    } finally {
      setMqttSaving(false);
    }
  }

  async function testMqttConnection() {
    if (!mqttConfig.host || !mqttConfig.host.trim()) {
      setMqttTestNotice({ type: "error", text: "Please enter an MQTT broker host to test." });
      return;
    }
    setMqttTestNotice(null);
    setMqttTesting(true);
    try {
      const payload = {
        host: mqttConfig.host.trim(),
        port: parseInt(mqttConfig.port, 10) || 1883,
        client_id: mqttConfig.client_id ? mqttConfig.client_id.trim() : null,
        username: mqttConfig.username ? mqttConfig.username.trim() : null,
        password: mqttConfig.password || null,
        use_tls: !!mqttConfig.use_tls,
        topic: "nibiaanet/test/ping",
      };
      const res = await api.post("/mqtt/test", { body: payload });
      if (res.success) {
        setMqttTestNotice({ type: "success", text: res.message });
      } else {
        setMqttTestNotice({ type: "error", text: res.message });
      }
    } catch (err) {
      setMqttTestNotice({ type: "error", text: err.message });
    } finally {
      setMqttTesting(false);
    }
  }

  async function deleteMqttConfig() {
    if (!window.confirm("Remove custom MQTT broker configuration? Telemetry publishing to this broker will stop.")) return;
    setMqttNotice(null);
    try {
      await api.delete("/mqtt/config");
      setMqttConfig({
        name: "Default MQTT Broker",
        enabled: false,
        host: "",
        port: 1883,
        client_id: "",
        username: "",
        password: "",
        has_password: false,
        topic_prefix: `nibiaanet/tenants/${tenantSegment}/devices/{device_id}/telemetry`,
        qos: 1,
        use_tls: false,
      });
      setMqttNotice({ type: "info", text: "MQTT broker configuration removed." });
    } catch (err) {
      setMqttNotice({ type: "error", text: err.message });
    }
  }

  async function refresh() {
    try {
      const [hooks, failed] = await Promise.all([
        api.get("/webhooks/"),
        api.get("/webhooks/alerts"),
      ]);

      setWebhooks(hooks);
      setAlerts(failed);
    } catch (error) {
      setListNotice({ type: "error", text: error.message });
    }
  }

  function toggleIn(list, value) {
    return list.includes(value) ? list.filter((item) => item !== value) : [...list, value];
  }

  async function createWebhook(event) {
    event.preventDefault();
    setNotice(null);
    setCreatedSecret(null);

    try {
      const webhook = await api.post("/webhooks/", {
        name: form.name.trim(),
        url: form.url.trim(),
        tenant_id: isAdmin ? Number(form.tenant_id) || null : null,
        filters: {
          device_ids: form.device_ids.split(",").map((id) => id.trim()).filter(Boolean),
          connection_types: form.connection_types,
          providers: form.providers,
        },
      });

      setCreatedSecret({ name: webhook.name, secret: webhook.secret });
      setForm({ ...form, name: "", url: "", device_ids: "", connection_types: [], providers: [] });
      refresh();
    } catch (error) {
      setNotice({ type: "error", text: error.message });
    }
  }

  async function toggleWebhook(webhook) {
    setListNotice(null);

    try {
      await api.patch(`/webhooks/${webhook.id}`, { enabled: !webhook.enabled });
      refresh();
    } catch (error) {
      setListNotice({ type: "error", text: error.message });
    }
  }

  async function deleteWebhook(webhook) {
    if (!window.confirm(`Delete the webhook ${webhook.name}? Deliveries stop at once.`)) {
      return;
    }

    setListNotice(null);

    try {
      await api.delete(`/webhooks/${webhook.id}`);
      setListNotice({ type: "success", text: `${webhook.name} deleted.` });
      refresh();
    } catch (error) {
      setListNotice({ type: "error", text: error.message });
    }
  }

  async function redeliver(delivery) {
    setListNotice(null);

    try {
      const result = await api.post(`/webhooks/deliveries/${delivery.id}/redeliver`);
      setListNotice({
        type: result.status === "DELIVERED" ? "success" : "warning",
        text: `Delivery #${delivery.id}: ${result.status}${result.last_error ? ` — ${result.last_error}` : ""}.`,
      });
      refresh();
    } catch (error) {
      setListNotice({ type: "error", text: error.message });
    }
  }

  function filterSummary(filters) {
    const parts = [];

    if (filters.device_ids?.length) parts.push(`devices: ${filters.device_ids.join(", ")}`);
    if (filters.connection_types?.length) parts.push(filters.connection_types.join(" + "));
    if (filters.providers?.length) parts.push(`providers: ${filters.providers.join(", ")}`);

    return parts.length ? parts.join(" · ") : "All uplinks";
  }

  const curlExample = `# 1. Sign in and keep the token
TOKEN=$(curl -s -X POST ${API}/auth/login \\
  -H "Content-Type: application/json" \\
  -d '{"name": "YOUR_NAME", "password": "YOUR_PASSWORD"}' | jq -r .access_token)

# 2. Read the latest 50 uplinks of a device
curl -s "${API}/devices/LORA-01/telemetry?limit=50" \\
  -H "Authorization: Bearer $TOKEN"`;

  const verifyNode = `// Express: verify X-NibiaaNet-Signature before trusting the body
import crypto from "node:crypto";

app.post("/nibiaanet", express.raw({ type: "application/json" }), (req, res) => {
  const expected = "sha256=" + crypto
    .createHmac("sha256", process.env.NIBIAANET_WEBHOOK_SECRET)
    .update(req.body)
    .digest("hex");

  const given = req.get("X-NibiaaNet-Signature") || "";

  if (given.length !== expected.length ||
      !crypto.timingSafeEqual(Buffer.from(given), Buffer.from(expected))) {
    return res.sendStatus(401);
  }

  const event = JSON.parse(req.body);   // telemetry.uplink
  res.sendStatus(200);                  // any 2xx = delivered
});`;

  const verifyPython = `# FastAPI / Flask: verify X-NibiaaNet-Signature
import hashlib, hmac

def is_valid(secret: str, raw_body: bytes, signature: str) -> bool:
    expected = "sha256=" + hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature or "")`;

  const hostVal = mqttConfig.host || "<broker-host>";
  const portVal = mqttConfig.port || 1883;
  const userVal = mqttConfig.username ? `-u "${mqttConfig.username}" ` : "";
  const passVal = mqttConfig.username ? `-P "<password>" ` : "";
  const tlsVal = mqttConfig.use_tls ? `--capath /etc/ssl/certs ` : "";
  const topicVal = (mqttConfig.topic_prefix || `nibiaanet/tenants/${tenantSegment}/devices/{device_id}/telemetry`)
    .replace("{device_id}", "+")
    .replace("{tenant_id}", String(tenantSegment));

  const dynamicMqttExample = `# Subscribe to telemetry from your MQTT broker
mosquitto_sub -h ${hostVal} -p ${portVal} -q ${mqttConfig.qos ?? 1} \\
  ${userVal}${passVal}${tlsVal}-t "${topicVal}"`;

  return (
    <div className="page">

      <PageHeader
        title="Integration Protocol"
        description="How decoded device data is delivered to your systems: push it with webhooks, pull it over the REST API, or stream it over MQTT."
      />

      {/* CHANNELS */}

      <section className="channel-grid" aria-label="Delivery channels">
        {CHANNELS.map((item) => (
          <button
            type="button"
            key={item.key}
            className={`channel-card ${channel === item.key ? "active" : ""}`}
            onClick={() => setChannel(item.key)}
            aria-pressed={channel === item.key}
          >
            <span className="channel-icon"><Icon name={item.icon} size={20} /></span>
            <span className="channel-kind">{item.kind}</span>
            <strong>{item.title}</strong>
            <p>{item.text}</p>
          </button>
        ))}
      </section>

      {/* DATA FLOW + FORMAT */}

      <section className="card">
        <div className="section-header">
          <div>
            <h2>Data flow</h2>
            <p>Every channel carries the same JSON event, once per decoded uplink.</p>
          </div>
        </div>

        <div className="two-column">
          <CodeBlock label="Event body · telemetry.uplink" code={JSON.stringify(SAMPLE_EVENT, null, 2)} />

          <div className="field-list">
            <h3>Fields</h3>
            <dl>
              <dt>event</dt><dd>Always <code>telemetry.uplink</code> for device data.</dd>
              <dt>device_id</dt><dd>The ID the device was registered with.</dd>
              <dt>timestamp</dt><dd>When the device measured (ISO 8601, UTC).</dd>
              <dt>received_at</dt><dd>When NibiaaNet received the uplink.</dd>
              <dt>connection_type</dt><dd><code>NTN</code> (satellite) or <code>TN</code> (terrestrial).</dd>
              <dt>provider</dt><dd>Code of the network profile that carried it.</dd>
              <dt>telemetry</dt><dd>The decoded values, as returned by the decoder.</dd>
              <dt>units</dt><dd>Unit of each value, when the decoder gives one.</dd>
            </dl>
          </div>
        </div>
      </section>

      {/* WEBHOOKS */}

      {channel === "webhook" && (
        <>
          <section className="card">
            <div className="section-header">
              <div>
                <h2>Webhooks</h2>
                <p>
                  NibiaaNet sends <code>POST</code> requests with the event as the body and these headers.
                  Answer with any <code>2xx</code> within 10 s; anything else is retried.
                </p>
              </div>
            </div>

            <div className="table-container">
              <table>
                <thead>
                  <tr><th>Header</th><th>Value</th></tr>
                </thead>
                <tbody>
                  <tr><td><code>Content-Type</code></td><td>application/json</td></tr>
                  <tr><td><code>X-NibiaaNet-Event</code></td><td>telemetry.uplink</td></tr>
                  <tr><td><code>X-NibiaaNet-Delivery</code></td><td>Delivery ID, the same on every retry (use it to de-duplicate)</td></tr>
                  <tr><td><code>X-NibiaaNet-Signature</code></td><td><code>sha256=</code> + HMAC-SHA256 of the raw body with your webhook secret, hex</td></tr>
                </tbody>
              </table>
            </div>

            <div className="two-column spaced">
              <CodeBlock label="Verify the signature · Node.js" code={verifyNode} />
              <CodeBlock label="Verify the signature · Python" code={verifyPython} />
            </div>
          </section>

          <section className="card">
            <div className="section-header">
              <div>
                <h2>Your webhook endpoints</h2>
                <p>Owners and admins register the URLs that receive their organization's data.</p>
              </div>
              {canManageWebhooks && (
                <button className="secondary-button" onClick={refresh}>Refresh</button>
              )}
            </div>

            {!canManageWebhooks ? (
              <Restricted title="Managed by your organization owner">
                Ask your owner to register a webhook. You can still use the REST API with your own sign-in.
              </Restricted>
            ) : (
              <>
                <form onSubmit={createWebhook}>
                  <div className="form-grid">
                    <div className="form-group">
                      <label>Name</label>
                      <input
                        value={form.name}
                        placeholder="Farm dashboard"
                        onChange={(e) => setForm({ ...form, name: e.target.value })}
                        required
                      />
                    </div>

                    <div className="form-group span-2">
                      <label>Endpoint URL</label>
                      <input
                        type="url"
                        value={form.url}
                        placeholder="https://example.com/nibiaanet"
                        onChange={(e) => setForm({ ...form, url: e.target.value })}
                        required
                      />
                    </div>

                    {isAdmin && (
                      <div className="form-group">
                        <label>Organization</label>
                        <select
                          value={form.tenant_id}
                          onChange={(e) => setForm({ ...form, tenant_id: e.target.value })}
                          required
                        >
                          <option value="">Select Organization</option>
                          {tenants.map((tenant) => (
                            <option key={tenant.id} value={tenant.id}>{tenant.name}</option>
                          ))}
                        </select>
                      </div>
                    )}

                    <div className="form-group">
                      <label>Only these devices (optional)</label>
                      <input
                        value={form.device_ids}
                        placeholder="LORA-01, NTN-07"
                        onChange={(e) => setForm({ ...form, device_ids: e.target.value })}
                      />
                    </div>

                    <div className="form-group">
                      <label>Networks</label>
                      <div className="checkbox-inline">
                        {["NTN", "TN"].map((type) => (
                          <label key={type} className="checkbox-row">
                            <input
                              type="checkbox"
                              checked={form.connection_types.includes(type)}
                              onChange={() => setForm({ ...form, connection_types: toggleIn(form.connection_types, type) })}
                            />
                            {type}
                          </label>
                        ))}
                      </div>
                      <span className="field-hint">None checked = both.</span>
                    </div>
                  </div>

                  {profiles.length > 0 && (
                    <div className="form-group">
                      <label>Only these providers (optional)</label>
                      <div className="tag-picker">
                        {profiles.map((profile) => (
                          <button
                            type="button"
                            key={profile.code}
                            className={`tag-option ${form.providers.includes(profile.code) ? "selected" : ""}`}
                            aria-pressed={form.providers.includes(profile.code)}
                            onClick={() => setForm({ ...form, providers: toggleIn(form.providers, profile.code) })}
                          >
                            {profile.name}
                          </button>
                        ))}
                      </div>
                    </div>
                  )}

                  <Notice notice={notice} />

                  {createdSecret && (
                    <div className="secret-callout" role="status">
                      <strong>{createdSecret.name} is registered. Copy its signing secret now — it is shown only once.</strong>
                      <CodeBlock label="Webhook secret" code={createdSecret.secret} />
                    </div>
                  )}

                  <button className="primary-button" type="submit">Register Webhook</button>
                </form>

                <Notice notice={listNotice} />

                {webhooks.length === 0 ? (
                  <div className="empty-state spaced">No webhooks yet.</div>
                ) : (
                  <div className="table-container spaced">
                    <table>
                      <thead>
                        <tr>
                          <th>Name</th>
                          <th>URL</th>
                          <th>Sends</th>
                          <th>State</th>
                          <th>Created</th>
                          <th>Actions</th>
                        </tr>
                      </thead>
                      <tbody>
                        {webhooks.map((webhook) => (
                          <tr key={webhook.id}>
                            <td><strong>{webhook.name}</strong></td>
                            <td className="wrap-anywhere"><code>{webhook.url}</code></td>
                            <td className="small-text">{filterSummary(webhook.filters)}</td>
                            <td>
                              <StatusPill active={webhook.enabled} activeText="Enabled" inactiveText="Paused" />
                            </td>
                            <td>{formatDate(webhook.created_at)}</td>
                            <td>
                              <div className="table-actions">
                                <button className="secondary-button small" onClick={() => toggleWebhook(webhook)}>
                                  {webhook.enabled ? "Pause" : "Resume"}
                                </button>
                                <button className="danger-button small" onClick={() => deleteWebhook(webhook)}>
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

                {alerts.length > 0 && (
                  <div className="schema-section">
                    <div className="schema-title">
                      <div>
                        <h3>Undeliverable</h3>
                        <p>Deliveries that failed every retry. Fix the endpoint, then send them again.</p>
                      </div>
                    </div>

                    <div className="table-container">
                      <table>
                        <thead>
                          <tr>
                            <th>Delivery</th>
                            <th>Device</th>
                            <th>Attempts</th>
                            <th>Last error</th>
                            <th></th>
                          </tr>
                        </thead>
                        <tbody>
                          {alerts.map((delivery) => (
                            <tr key={delivery.id}>
                              <td>#{delivery.id}</td>
                              <td>{delivery.payload?.device_id || "—"}</td>
                              <td>{delivery.attempts}</td>
                              <td className="small-text">
                                {delivery.last_status_code ? `HTTP ${delivery.last_status_code}` : delivery.last_error || "—"}
                              </td>
                              <td>
                                <button className="secondary-button small" onClick={() => redeliver(delivery)}>
                                  Redeliver
                                </button>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}
              </>
            )}
          </section>
        </>
      )}

      {/* REST */}

      {channel === "rest" && (
        <section className="card">
          <div className="section-header">
            <div>
              <h2>REST API</h2>
              <p>
                Base URL <code>{API}</code>. Send <code>Authorization: Bearer &lt;token&gt;</code> on every
                request; you only see your organization's data. Full reference: <a href={`${API}/docs`} target="_blank" rel="noreferrer">{API}/docs</a>.
              </p>
            </div>
          </div>

          <div className="endpoint-list">
            {REST_ENDPOINTS.map((endpoint) => (
              <div className="endpoint" key={`${endpoint.method} ${endpoint.path}`}>
                <div className="endpoint-line">
                  <span className={`method method-${endpoint.method.toLowerCase()}`}>{endpoint.method}</span>
                  <code>{endpoint.path}</code>
                </div>
                <p>{endpoint.description}</p>
                {endpoint.query && <span className="field-hint">Query: {endpoint.query}</span>}
              </div>
            ))}
          </div>

          <CodeBlock label="Example · curl" code={curlExample} />
        </section>
      )}

      {/* MQTT */}

      {channel === "mqtt" && (
        <>
          <section className="card">
            <div className="section-header">
              <div>
                <h2>MQTT Broker Configuration</h2>
                <p>
                  Configure your MQTT broker credentials below. Once configured, NibiaaNet will
                  automatically publish all decoded device uplinks directly to your MQTT broker in real time.
                </p>
              </div>
              <div>
                <span
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: "6px",
                    padding: "4px 12px",
                    borderRadius: "12px",
                    fontSize: "0.82rem",
                    fontWeight: 600,
                    background: mqttConfig.enabled && mqttConfig.host ? "rgba(16, 185, 129, 0.15)" : "rgba(148, 163, 184, 0.15)",
                    color: mqttConfig.enabled && mqttConfig.host ? "#10b981" : "#94a3b8",
                    border: `1px solid ${mqttConfig.enabled && mqttConfig.host ? "rgba(16, 185, 129, 0.3)" : "rgba(148, 163, 184, 0.2)"}`
                  }}
                >
                  <span
                    style={{
                      width: "8px",
                      height: "8px",
                      borderRadius: "50%",
                      background: mqttConfig.enabled && mqttConfig.host ? "#10b981" : "#94a3b8"
                    }}
                  />
                  {mqttConfig.enabled && mqttConfig.host ? "Broker Active" : "Broker Inactive"}
                </span>
              </div>
            </div>

            <form onSubmit={saveMqttConfig}>
              <div className="form-grid">
                <div className="form-group">
                  <label>Broker Host / Address *</label>
                  <input
                    type="text"
                    required
                    placeholder="e.g. broker.emqx.io, mqtt.hivemq.com, or 192.168.1.100"
                    value={mqttConfig.host}
                    onChange={(e) => setMqttConfig({ ...mqttConfig, host: e.target.value })}
                  />
                  <span className="field-hint">Hostname, domain, or IP address of your MQTT broker.</span>
                </div>

                <div className="form-group">
                  <label>Port *</label>
                  <input
                    type="number"
                    required
                    min={1}
                    max={65535}
                    placeholder="1883"
                    value={mqttConfig.port}
                    onChange={(e) => setMqttConfig({ ...mqttConfig, port: e.target.value })}
                  />
                  <span className="field-hint">Standard port: 1883 for TCP, 8883 for SSL/TLS.</span>
                </div>

                <div className="form-group">
                  <label>Broker Name / Label</label>
                  <input
                    type="text"
                    placeholder="Production MQTT Broker"
                    value={mqttConfig.name}
                    onChange={(e) => setMqttConfig({ ...mqttConfig, name: e.target.value })}
                  />
                  <span className="field-hint">Friendly name to identify this broker.</span>
                </div>

                <div className="form-group">
                  <label>Client ID (optional)</label>
                  <input
                    type="text"
                    placeholder="e.g. nibiaanet-telemetry-pub"
                    value={mqttConfig.client_id || ""}
                    onChange={(e) => setMqttConfig({ ...mqttConfig, client_id: e.target.value })}
                  />
                  <span className="field-hint">Leave blank to auto-generate a unique Client ID.</span>
                </div>

                <div className="form-group">
                  <label>Username (optional)</label>
                  <input
                    type="text"
                    placeholder="MQTT username"
                    value={mqttConfig.username || ""}
                    onChange={(e) => setMqttConfig({ ...mqttConfig, username: e.target.value })}
                    autoComplete="off"
                  />
                </div>

                <div className="form-group">
                  <label>Password (optional)</label>
                  <input
                    type="password"
                    placeholder={mqttConfig.has_password ? "•••••••• (Password set — leave blank to keep)" : "MQTT password"}
                    value={mqttConfig.password || ""}
                    onChange={(e) => setMqttConfig({ ...mqttConfig, password: e.target.value })}
                    autoComplete="new-password"
                  />
                  {mqttConfig.has_password && !mqttConfig.password && (
                    <span className="field-hint" style={{ color: "#10b981" }}>Encrypted password is saved.</span>
                  )}
                </div>

                <div className="form-group" style={{ gridColumn: "1 / -1" }}>
                  <label>Topic Template *</label>
                  <input
                    type="text"
                    required
                    value={mqttConfig.topic_prefix}
                    onChange={(e) => setMqttConfig({ ...mqttConfig, topic_prefix: e.target.value })}
                  />
                  <span className="field-hint">
                    Placeholders supported: <code>{"{tenant_id}"}</code> (organization ID), <code>{"{device_id}"}</code> (device identifier).
                  </span>
                </div>

                <div className="form-group">
                  <label>QoS (Quality of Service)</label>
                  <select
                    value={mqttConfig.qos}
                    onChange={(e) => setMqttConfig({ ...mqttConfig, qos: parseInt(e.target.value, 10) })}
                  >
                    <option value={0}>0 — At most once (fire & forget)</option>
                    <option value={1}>1 — At least once (recommended)</option>
                    <option value={2}>2 — Exactly once</option>
                  </select>
                </div>

                <div className="form-group" style={{ display: "flex", flexDirection: "column", justifyContent: "center" }}>
                  <label style={{ display: "flex", alignItems: "center", gap: "8px", cursor: "pointer", marginTop: "16px" }}>
                    <input
                      type="checkbox"
                      checked={mqttConfig.use_tls}
                      onChange={(e) => setMqttConfig({ ...mqttConfig, use_tls: e.target.checked })}
                    />
                    <span><strong>Enable SSL / TLS Encryption</strong> (recommended for port 8883)</span>
                  </label>
                  <label style={{ display: "flex", alignItems: "center", gap: "8px", cursor: "pointer", marginTop: "8px" }}>
                    <input
                      type="checkbox"
                      checked={mqttConfig.enabled}
                      onChange={(e) => setMqttConfig({ ...mqttConfig, enabled: e.target.checked })}
                    />
                    <span><strong>Enable MQTT Telemetry Streaming</strong></span>
                  </label>
                </div>
              </div>

              <Notice notice={mqttNotice} />
              <Notice notice={mqttTestNotice} />

              <div style={{ display: "flex", gap: "10px", marginTop: "20px", flexWrap: "wrap", alignItems: "center" }}>
                <button type="submit" className="primary-button" disabled={mqttSaving}>
                  {mqttSaving ? "Saving..." : "Save Broker Credentials"}
                </button>
                <button
                  type="button"
                  className="secondary-button"
                  onClick={testMqttConnection}
                  disabled={mqttTesting || !mqttConfig.host}
                >
                  {mqttTesting ? "Testing Connection..." : "⚡ Test Broker Connection"}
                </button>
                {mqttConfig.id && (
                  <button
                    type="button"
                    className="danger-button"
                    onClick={deleteMqttConfig}
                    style={{ marginLeft: "auto" }}
                  >
                    Remove Broker Config
                  </button>
                )}
              </div>
            </form>
          </section>

          {/* MQTT SUBSCRIBER REFERENCE & GUIDE */}
          <section className="card">
            <div className="section-header">
              <div>
                <h2>Live Subscription Guide</h2>
                <p>
                  Use your MQTT client (e.g. <code>mosquitto_sub</code>, Node-RED, Telegraf, Grafana, or Home Assistant) to subscribe to telemetry streamed to your broker.
                </p>
              </div>
            </div>

            <div className="table-container">
              <table>
                <thead>
                  <tr><th>Topic Pattern</th><th>Receives</th></tr>
                </thead>
                <tbody>
                  <tr>
                    <td className="wrap-anywhere">
                      <code>{(mqttConfig.topic_prefix || `nibiaanet/tenants/${tenantSegment}/devices/{device_id}/telemetry`).replace("{device_id}", "{device_id}").replace("{tenant_id}", String(tenantSegment))}</code>
                    </td>
                    <td>One specific device telemetry stream</td>
                  </tr>
                  <tr>
                    <td className="wrap-anywhere">
                      <code>{(mqttConfig.topic_prefix || `nibiaanet/tenants/${tenantSegment}/devices/{device_id}/telemetry`).replace("{device_id}", "+").replace("{tenant_id}", String(tenantSegment))}</code>
                    </td>
                    <td>All devices in the organization</td>
                  </tr>
                </tbody>
              </table>
            </div>

            <div className="two-column spaced">
              <CodeBlock label="Live Subscribe Command · mosquitto_sub" code={dynamicMqttExample} />
              <div className="field-list">
                <h3>Delivery Specs</h3>
                <dl>
                  <dt>Payload</dt><dd>Standard JSON event (same schema as Webhooks).</dd>
                  <dt>QoS</dt><dd>Configured to <code>QoS {mqttConfig.qos}</code>.</dd>
                  <dt>Retained</dt><dd>No (real-time stream). Historical data is stored in Cassandra & PostgreSQL.</dd>
                  <dt>Security</dt><dd>{mqttConfig.use_tls ? "TLS / SSL encrypted transport." : "Standard TCP transport."}</dd>
                </dl>
              </div>
            </div>
          </section>
        </>
      )}

    </div>
  );
}

export default Integration;
