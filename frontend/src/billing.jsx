import { useEffect, useState } from "react";
import { formatDate } from "./api";
import { Modal, Notice, PageHeader, StatusPill } from "./components";
import { Icon } from "./icons";


export default function Billing({ api, currentUser, activeWorkspace, onSelectWorkspace }) {
  const [organizations, setOrganizations] = useState([]);
  const [selectedOrgId, setSelectedOrgId] = useState(() => activeWorkspace?.id || 1);
  const isAdmin = currentUser?.role === "admin";
  const [activeTab, setActiveTab] = useState("overview"); // "overview" | "sims" | "invoices" | "providers" | "diagnostics"

  // Data states
  const [plans, setPlans] = useState([]);
  const [subscription, setSubscription] = useState(null);
  const [usage, setUsage] = useState(null);
  const [sims, setSims] = useState([]);
  const [invoices, setInvoices] = useState([]);
  const [providers, setProviders] = useState([]);
  const [providerFilter, setProviderFilter] = useState("all");
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState(null);

  // Modals: Plan Subscription
  const [showSubscribeModal, setShowSubscribeModal] = useState(false);
  const [selectedPlan, setSelectedPlan] = useState(null);
  const [subscribeInterval, setSubscribeInterval] = useState("monthly");

  // Modals: SIM Fleet
  const [topupSim, setTopupSim] = useState(null);
  const [topupVolumeMb, setTopupVolumeMb] = useState(500);
  const [topupCreateInvoice, setTopupCreateInvoice] = useState(true);

  const [smsSim, setSmsSim] = useState(null);
  const [smsPayload, setSmsPayload] = useState("REBOOT#NOW");
  const [smsSource, setSmsSource] = useState("NibiaaNet");

  const [simScope, setSimScope] = useState("workspace"); // "workspace" | "unassigned" | "all"
  const [assignSim, setAssignSim] = useState(null);
  const [assignDeviceId, setAssignDeviceId] = useState("");
  const [assignImei, setAssignImei] = useState("");
  const [assignLabel, setAssignLabel] = useState("");

  // Modals & State: Dynamic Network Providers
  const [showAddProviderModal, setShowAddProviderModal] = useState(false);
  const [editingProvider, setEditingProvider] = useState(null);
  const [providerForm, setProviderForm] = useState({
    name: "Monogoto Global Cellular",
    provider_code: "monogoto",
    provider_type: "monogoto",
    base_url: "https://api.monogoto.io",
    auth_type: "bearer_token",
    api_user: "",
    api_key: "",
    markup_percentage: 20.0,
    cost_per_mb: 0.03,
    cost_per_sim: 1.00,
    cost_per_sms: 0.01,
    is_sandbox: true,
    is_enabled: true,
  });
  const [globalMarkupPct, setGlobalMarkupPct] = useState(20.0);
  const [savingMarkup, setSavingMarkup] = useState(false);
  const [drivers, setDrivers] = useState([]);
  const [providerTestLoading, setProviderTestLoading] = useState({});
  const [providerTestResults, setProviderTestResults] = useState({});

  // Diagnostics State
  const [testResult, setTestResult] = useState(null);
  const [testing, setTesting] = useState(false);

  useEffect(() => {
    if (activeWorkspace?.id) {
      setSelectedOrgId(activeWorkspace.id);
    }
  }, [activeWorkspace?.id]);

  useEffect(() => {
    loadAll(selectedOrgId);
  }, [api, selectedOrgId]);

  async function loadAll(targetOrg, keepNotice = false, forcedSimScope) {
    setLoading(true);
    if (!keepNotice) setNotice(null);
    const effectiveTenantId = isAdmin
      ? (targetOrg || selectedOrgId || activeWorkspace?.id || 1)
      : (currentUser?.tenant_id || activeWorkspace?.id || 1);
    const orgToQuery = effectiveTenantId;
    const activeScope = forcedSimScope || simScope;
    const simUrl = isAdmin
      ? (activeScope === "unassigned"
          ? "/network/sims?unassigned=true"
          : activeScope === "all"
          ? "/network/sims"
          : `/network/sims?tenant_id=${effectiveTenantId}`)
      : `/network/sims?tenant_id=${currentUser?.tenant_id || effectiveTenantId}`;
    try {
      const [plansData, subData, usageData, simsData, invoicesData, providersData, driversData, orgsData] = await Promise.all([
        api.get("/billing/plans").catch(() => []),
        api.get(isAdmin ? `/billing/subscriptions/tenant/${orgToQuery}` : "/billing/subscriptions/me").catch(() => null),
        api.get(isAdmin ? `/billing/usage?tenant_id=${orgToQuery}` : "/billing/usage").catch(() => null),
        api.get(simUrl).catch(() => []),
        api.get(isAdmin ? `/billing/invoices?tenant_id=${orgToQuery}` : "/billing/invoices").catch(() => []),
        api.get("/network/providers").catch(() => []),
        api.get("/network/drivers").catch(() => []),
        isAdmin ? api.get("/tenants").catch(() => []) : Promise.resolve([]),
      ]);

      setPlans(plansData || []);
      setSubscription(subData);
      setUsage(usageData);
      if (usageData?.markup_percentage) {
        setGlobalMarkupPct(usageData.markup_percentage);
      }
      setSims(simsData || []);
      setInvoices(invoicesData || []);
      setProviders(providersData || []);
      setDrivers(driversData || []);
      if (orgsData && orgsData.length > 0) {
        setOrganizations(orgsData);
      }
    } catch (err) {
      setNotice({ type: "error", text: err.message || "Failed to load billing information." });
    } finally {
      setLoading(false);
    }
  }

  // -------------------------------------------------------------------------
  // Subscription Actions
  // -------------------------------------------------------------------------

  async function handleSubscribe(event) {
    event.preventDefault();
    if (!selectedPlan) return;
    const orgId = isAdmin ? (selectedOrgId || activeWorkspace?.id || 1) : (currentUser?.tenant_id || activeWorkspace?.id || 1);
    const orgName = organizations.find((o) => o.id === orgId)?.name || activeWorkspace?.name || "Organization";
    try {
      const updated = await api.post(`/billing/subscriptions/subscribe?tenant_id=${orgId}`, {
        tenant_id: orgId,
        plan_id: selectedPlan.id,
        billing_interval: subscribeInterval,
        auto_renew: true,
      });
      setSubscription(updated);
      setShowSubscribeModal(false);
      setNotice({ type: "success", text: `Successfully subscribed ${orgName} to ${selectedPlan.name}!` });
      loadAll(orgId);
    } catch (err) {
      setNotice({ type: "error", text: err.message });
    }
  }

  async function handleCancelSubscription() {
    const orgId = isAdmin ? (selectedOrgId || activeWorkspace?.id || 1) : (currentUser?.tenant_id || activeWorkspace?.id || 1);
    const orgName = organizations.find((o) => o.id === orgId)?.name || "organization";
    if (!confirm(`Are you sure you want to cancel ${orgName}'s subscription?`)) return;
    try {
      const res = await api.post(`/billing/subscriptions/cancel?immediate=false&tenant_id=${orgId}`);
      setSubscription(res);
      setNotice({ type: "info", text: `Subscription for ${orgName} set to cancel at end of current billing period.` });
      loadAll(orgId);
    } catch (err) {
      setNotice({ type: "error", text: err.message });
    }
  }

  // -------------------------------------------------------------------------
  // Dynamic Network Provider Actions
  // -------------------------------------------------------------------------

  async function handleUpdateGlobalMarkup(event) {
    event.preventDefault();
    setSavingMarkup(true);
    setNotice(null);
    try {
      const res = await api.post("/billing/markup", {
        markup_percentage: Number(globalMarkupPct),
      });
      setNotice({ type: "success", text: res.message || `Pricing markup updated to ${globalMarkupPct}% (No Fixed Amount)!` });
      loadAll();
    } catch (err) {
      setNotice({ type: "error", text: "Failed to update markup %: " + err.message });
    } finally {
      setSavingMarkup(false);
    }
  }

  async function handleCreateProvider(event) {
    event.preventDefault();
    try {
      await api.post("/network/providers", {
        ...providerForm,
        markup_percentage: Number(providerForm.markup_percentage || 20.0),
        cost_per_mb: Number(providerForm.cost_per_mb || 0.03),
        cost_per_sim: Number(providerForm.cost_per_sim || 1.00),
        cost_per_sms: Number(providerForm.cost_per_sms || 0.01),
      });
      setShowAddProviderModal(false);
      setNotice({ type: "success", text: `Network Provider '${providerForm.name}' successfully added with ${providerForm.markup_percentage}% markup!` });
      loadAll();
    } catch (err) {
      setNotice({ type: "error", text: err.message });
    }
  }

  async function handleUpdateProvider(event) {
    event.preventDefault();
    if (!editingProvider) return;
    try {
      await api.put(`/network/providers/${editingProvider.provider_code}`, {
        name: editingProvider.name,
        base_url: editingProvider.base_url,
        auth_type: editingProvider.auth_type,
        api_user: editingProvider.api_user,
        api_key: editingProvider.api_key || undefined,
        markup_percentage: Number(editingProvider.markup_percentage ?? 20.0),
        cost_per_mb: Number(editingProvider.cost_per_mb ?? 0.03),
        cost_per_sim: Number(editingProvider.cost_per_sim ?? 1.00),
        cost_per_sms: Number(editingProvider.cost_per_sms ?? 0.01),
        is_sandbox: editingProvider.is_sandbox,
        is_enabled: editingProvider.is_enabled,
      });
      setEditingProvider(null);
      setNotice({ type: "success", text: `Provider '${editingProvider.name}' updated (+${editingProvider.markup_percentage}% markup)!` });
      loadAll();
    } catch (err) {
      setNotice({ type: "error", text: err.message });
    }
  }

  async function handleDeleteProvider(provider) {
    if (!confirm(`Are you sure you want to remove network provider '${provider.name}' (${provider.provider_code})?`)) return;
    try {
      await api.delete(`/network/providers/${provider.provider_code}`);
      setNotice({ type: "success", text: `Provider '${provider.name}' removed.` });
      loadAll();
    } catch (err) {
      setNotice({ type: "error", text: err.message });
    }
  }

  async function handleTestProvider(providerCode) {
    setProviderTestLoading((prev) => ({ ...prev, [providerCode]: true }));
    try {
      const res = await api.post(`/network/providers/${providerCode}/test`);
      setProviderTestResults((prev) => ({ ...prev, [providerCode]: res }));
      setNotice({
        type: res.success ? "success" : "error",
        text: `${res.provider_name}: ${res.message} (${res.latency_ms} ms)`,
      });
    } catch (err) {
      setNotice({ type: "error", text: `Test failed: ${err.message}` });
    } finally {
      setProviderTestLoading((prev) => ({ ...prev, [providerCode]: false }));
    }
  }

  async function handleSyncProviderSims(providerCode) {
    setNotice(null);
    try {
      const synced = await api.post(`/network/providers/${providerCode}/sync`);
      await loadAll(undefined, true);
      setNotice({ type: "success", text: `Synchronized ${synced.length} SIM cards from ${providerCode.toUpperCase()} API.` });
    } catch (err) {
      setNotice({ type: "error", text: `Sync failed: ${err.message}` });
    }
  }

  // -------------------------------------------------------------------------
  // Cellular IoT SIM Fleet Actions (Provider-Agnostic)
  // -------------------------------------------------------------------------

  async function handleToggleSimStatus(sim) {
    const nextStatus = sim.status === "Active" ? "Suspended" : "Active";
    if (!confirm(`Set network core status of SIM ${sim.iccid} (${(sim.provider || "1nce").toUpperCase()}) to ${nextStatus}?`)) return;

    try {
      await api.post(`/network/sims/${sim.iccid}/status`, { status: nextStatus });
      setNotice({ type: "success", text: `SIM ${sim.iccid} status changed to ${nextStatus}.` });
      loadAll();
    } catch (err) {
      setNotice({ type: "error", text: err.message });
    }
  }

  async function handleResetSim(sim) {
    if (!confirm(`Trigger connectivity reset for SIM ${sim.iccid}? This clears core network session and forces the device to reconnect.`)) return;

    try {
      const res = await api.post(`/network/sims/${sim.iccid}/reset`);
      setNotice({ type: "success", text: res.message || `Reset triggered for SIM ${sim.iccid}.` });
    } catch (err) {
      setNotice({ type: "error", text: err.message });
    }
  }

  async function handleTopupSubmit(event) {
    event.preventDefault();
    if (!topupSim) return;

    try {
      const res = await api.post(`/network/sims/${topupSim.iccid}/topup`, {
        volume_mb: Number(topupVolumeMb),
        create_odoo_invoice: topupCreateInvoice,
      });
      setNotice({ type: "success", text: res.message });
      setTopupSim(null);
      loadAll();
    } catch (err) {
      setNotice({ type: "error", text: err.message });
    }
  }

  async function handleSendSmsSubmit(event) {
    event.preventDefault();
    if (!smsSim) return;

    try {
      const res = await api.post(`/network/sims/${smsSim.iccid}/sms`, {
        payload: smsPayload,
        source_address: smsSource,
      });
      setNotice({ type: "success", text: res.message || "MT-SMS command dispatched." });
      setSmsSim(null);
    } catch (err) {
      setNotice({ type: "error", text: err.message });
    }
  }

  async function handleAssignSimSubmit(event) {
    event.preventDefault();
    if (!assignSim) return;

    const trimmedDevice = assignDeviceId.trim() || null;
    try {
      await api.post(`/network/sims/${assignSim.iccid}/assign`, {
        device_id: trimmedDevice,
        imei: trimmedDevice ? (assignImei.trim() || null) : null,
        label: assignLabel.trim() || null,
      });
      setNotice({ type: "success", text: trimmedDevice ? `SIM ${assignSim.iccid} linked to device ${trimmedDevice}.` : `SIM ${assignSim.iccid} unassigned from device (hardware IMEI cleared).` });
      setAssignSim(null);
      loadAll();
    } catch (err) {
      setNotice({ type: "error", text: err.message });
    }
  }

  // -------------------------------------------------------------------------
  // Invoices & Odoo Synchronisation
  // -------------------------------------------------------------------------

  async function handleProcessRecurringInvoices(force = false) {
    const promptMsg = force
      ? "Force-simulate 30-day recurring auto-billing cycle for testing now?"
      : "Process 30-day auto-billing cycle for subscriptions reaching their 30-day mark?";
    if (!confirm(promptMsg)) return;
    setNotice(null);
    try {
      const orgId = isAdmin ? (selectedOrgId || activeWorkspace?.id || 1) : (currentUser?.tenant_id || activeWorkspace?.id || 1);
      const res = await api.post(`/billing/subscriptions/process-recurring-invoices?force=${force}&tenant_id=${orgId}`);
      await loadAll(undefined, true);
      setNotice({
        type: "success",
        text: res.length > 0
          ? `Auto-generated ${res.length} recurring 30-day invoice(s) successfully!`
          : "No subscriptions currently due for 30-day cycle billing. All active subscriptions are up to date."
      });
    } catch (err) {
      setNotice({ type: "error", text: `Auto-billing process failed: ${err.message}` });
    }
  }

  async function handleGenerateInvoice() {
    try {
      const orgId = isAdmin ? (selectedOrgId || activeWorkspace?.id || 1) : (currentUser?.tenant_id || activeWorkspace?.id || 1);
      const orgName = organizations.find((o) => o.id === orgId)?.name || activeWorkspace?.name || "Organization";
      const inv = await api.post("/billing/invoices/generate", {
        tenant_id: orgId,
        billing_interval: subscription ? subscription.billing_interval : "monthly",
        include_overages: true,
        post_to_odoo: true,
        notes: `Generated via Console for ${orgName}`,
      });
      setNotice({ type: "success", text: `Invoice ${inv.invoice_number} generated for ${orgName} and synced to Odoo ERP!` });
      loadAll(orgId);
    } catch (err) {
      setNotice({ type: "error", text: err.message });
    }
  }

  async function handleSyncOdooInvoice(invoiceId) {
    try {
      const res = await api.post(`/billing/invoices/${invoiceId}/sync-odoo`);
      setNotice({ type: "success", text: `Invoice ${res.invoice_number} state updated from Odoo (${res.odoo_payment_state}).` });
      loadAll();
    } catch (err) {
      setNotice({ type: "error", text: err.message });
    }
  }

  async function handlePayInvoice(invoiceId) {
    if (!confirm("Record payment in Odoo and unlock all cellular SIMs for this organization?")) return;
    try {
      const res = await api.post(`/billing/invoices/${invoiceId}/pay`, {
        payment_method: "odoo_reconcile",
        notes: "Paid via Console",
      });
      setNotice({ type: "success", text: `Invoice ${res.invoice_number} paid! Cellular SIMs reactivated.` });
      loadAll();
    } catch (err) {
      setNotice({ type: "error", text: err.message });
    }
  }

  async function handleDownloadPdf(invoice) {
    try {
      const url = `${import.meta.env.VITE_API_URL || "http://127.0.0.1:3002"}/billing/invoices/${invoice.id}/pdf`;
      window.open(url, "_blank");
    } catch (err) {
      setNotice({ type: "error", text: "Failed to open PDF: " + err.message });
    }
  }

  // -------------------------------------------------------------------------
  // Diagnostics
  // -------------------------------------------------------------------------

  async function runDiagnostic(provider) {
    setTesting(true);
    setTestResult(null);
    try {
      const res = await api.post(`/billing/config/test-${provider}`);
      setTestResult(res);
    } catch (err) {
      setTestResult({
        provider,
        success: false,
        message: err.message,
      });
    } finally {
      setTesting(false);
    }
  }

  return (
    <div className="billing-page">
      <PageHeader
        title="Billing & Subscription"
        description="Manage organization plans, Odoo ERP invoices, and multi-provider cellular IoT connectivity (Monogoto, 1NCE)."
      >
        <div style={{ display: "flex", gap: "8px", alignItems: "center", flexWrap: "wrap" }}>
          {isAdmin && organizations.length > 0 && (
            <div style={{ display: "flex", alignItems: "center", gap: "6px", background: "var(--surface-2)", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)", padding: "4px 10px" }}>
              <span style={{ fontSize: "12px", color: "var(--text-muted)", fontWeight: 600 }}>Active Client:</span>
              <select
                value={selectedOrgId}
                onChange={(e) => {
                  const newId = Number(e.target.value);
                  setSelectedOrgId(newId);
                  const found = organizations.find((o) => o.id === newId);
                  if (found && onSelectWorkspace) {
                    onSelectWorkspace(found);
                  }
                  loadAll(newId);
                }}
                style={{ background: "transparent", border: "none", color: "var(--text)", fontWeight: 700, fontSize: "12px", cursor: "pointer", outline: "none" }}
              >
                {organizations.map((org) => (
                  <option key={org.id} value={org.id} style={{ background: "var(--surface)", color: "var(--text)" }}>
                    {org.name} (ID: {org.id})
                  </option>
                ))}
              </select>
            </div>
          )}
          <button
            type="button"
            className="secondary-button"
            onClick={() => loadAll(selectedOrgId)}
            disabled={loading}
          >
            <Icon name="refresh" size={16} /> Refresh
          </button>
          {isAdmin && (
            <button
              type="button"
              className="primary-button"
              onClick={handleGenerateInvoice}
            >
              <Icon name="billing" size={16} /> Generate Invoice Now
            </button>
          )}
        </div>
      </PageHeader>

      <Notice notice={notice} />

      {/* Tabs Bar */}
      <div className="tabs" style={{ display: "flex", gap: "10px", margin: "20px 0", borderBottom: "1px solid var(--border)", paddingBottom: "8px", flexWrap: "wrap" }}>
        <button
          type="button"
          className={`tab-btn ${activeTab === "overview" ? "active" : ""}`}
          style={{
            padding: "8px 16px",
            borderRadius: "var(--radius-sm)",
            border: "none",
            background: activeTab === "overview" ? "var(--primary)" : "transparent",
            color: activeTab === "overview" ? "#fff" : "var(--text)",
            cursor: "pointer",
            fontWeight: 600,
          }}
          onClick={() => setActiveTab("overview")}
        >
          Overview & Plans
        </button>

        <button
          type="button"
          className={`tab-btn ${activeTab === "sims" ? "active" : ""}`}
          style={{
            padding: "8px 16px",
            borderRadius: "var(--radius-sm)",
            border: "none",
            background: activeTab === "sims" ? "var(--primary)" : "transparent",
            color: activeTab === "sims" ? "#fff" : "var(--text)",
            cursor: "pointer",
            fontWeight: 600,
          }}
          onClick={() => setActiveTab("sims")}
        >
          Cellular IoT Fleet ({sims.length})
        </button>

        <button
          type="button"
          className={`tab-btn ${activeTab === "invoices" ? "active" : ""}`}
          style={{
            padding: "8px 16px",
            borderRadius: "var(--radius-sm)",
            border: "none",
            background: activeTab === "invoices" ? "var(--primary)" : "transparent",
            color: activeTab === "invoices" ? "#fff" : "var(--text)",
            cursor: "pointer",
            fontWeight: 600,
          }}
          onClick={() => setActiveTab("invoices")}
        >
          Odoo Invoices ({invoices.length})
        </button>

        <button
          type="button"
          className={`tab-btn ${activeTab === "providers" ? "active" : ""}`}
          style={{
            padding: "8px 16px",
            borderRadius: "var(--radius-sm)",
            border: "none",
            background: activeTab === "providers" ? "var(--primary)" : "transparent",
            color: activeTab === "providers" ? "#fff" : "var(--text)",
            cursor: "pointer",
            fontWeight: 600,
          }}
          onClick={() => setActiveTab("providers")}
        >
          Network Providers ({providers.length})
        </button>

        {isAdmin && (
          <button
            type="button"
            className={`tab-btn ${activeTab === "diagnostics" ? "active" : ""}`}
            style={{
              padding: "8px 16px",
              borderRadius: "var(--radius-sm)",
              border: "none",
              background: activeTab === "diagnostics" ? "var(--primary)" : "transparent",
              color: activeTab === "diagnostics" ? "#fff" : "var(--text)",
              cursor: "pointer",
              fontWeight: 600,
            }}
            onClick={() => setActiveTab("diagnostics")}
          >
            Diagnostics
          </button>
        )}
      </div>

      {/* ----------------------------------------------------------------- */}
      {/* Tab: Overview & Subscription */}
      {/* ----------------------------------------------------------------- */}
      {activeTab === "overview" && (
        <div className="overview-section">
          {/* Admin Markup % Pricing Control Banner */}
          {isAdmin && (
            <div
              className="card"
              style={{
                marginBottom: "20px",
                background: "linear-gradient(135deg, rgba(37, 99, 235, 0.08) 0%, rgba(124, 58, 237, 0.08) 100%)",
                border: "1px solid rgba(59, 130, 246, 0.35)",
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "16px" }}>
                <div style={{ maxWidth: "580px" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "6px" }}>
                    <span className="pill pill-ok" style={{ fontSize: "11px", fontWeight: 700 }}>DYNAMIC % PRICING ACTIVE</span>
                    <span className="pill" style={{ fontSize: "11px", background: "rgba(255, 255, 255, 0.08)" }}>NO FIXED AMOUNT</span>
                  </div>
                  <h3 style={{ margin: "4px 0" }}>SIM Provider Markup & Profit Margin Control</h3>
                  <p className="muted" style={{ margin: 0, fontSize: "13px" }}>
                    Clients are charged strictly based on SIM usage billed by the network provider (1NCE, Monogoto) + your configured Admin Markup %. There is no fixed recurring fee.
                  </p>
                </div>

                <form onSubmit={handleUpdateGlobalMarkup} style={{ display: "flex", alignItems: "flex-end", gap: "10px" }}>
                  <div>
                    <label style={{ fontSize: "12px", display: "block", marginBottom: "4px", fontWeight: 600 }}>Admin Markup (%)</label>
                    <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                      <input
                        type="number"
                        step="0.5"
                        min="0"
                        max="500"
                        required
                        value={globalMarkupPct}
                        onChange={(e) => setGlobalMarkupPct(e.target.value)}
                        style={{ width: "90px", padding: "8px", fontWeight: 700, fontSize: "15px", textAlign: "center" }}
                      />
                      <span style={{ fontWeight: 700, fontSize: "16px" }}>%</span>
                    </div>
                  </div>
                  <button
                    type="submit"
                    className="primary-button"
                    disabled={savingMarkup}
                    style={{ height: "38px", whiteSpace: "nowrap" }}
                  >
                    {savingMarkup ? "Saving..." : "Save Markup %"}
                  </button>
                </form>
              </div>
            </div>
          )}

          {/* Active Subscription Banner */}
          <div className="card" style={{ marginBottom: "20px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: "16px" }}>
              <div>
                <span className="muted" style={{ fontSize: "12px", textTransform: "uppercase", letterSpacing: "0.5px" }}>Current Subscription</span>
                <h2 style={{ margin: "4px 0 8px 0" }}>
                  {subscription
                    ? subscription.plan?.name
                    : isAdmin
                    ? "Global Platform Admin Scope"
                    : "No Active Subscription"}
                </h2>
                <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
                  <StatusPill
                    active={subscription?.status === "active"}
                    activeText={String(subscription?.status || (isAdmin ? "ACTIVE" : "INACTIVE")).toUpperCase()}
                    inactiveText={String(subscription?.status || "INACTIVE").toUpperCase()}
                  />
                  {subscription?.odoo_partner_id && (
                    <span className="muted" style={{ fontSize: "12px" }}>
                      Odoo Partner #{subscription.odoo_partner_id}
                    </span>
                  )}
                </div>
              </div>

              <div style={{ textAlign: "right" }}>
                {subscription ? (
                  <>
                    <div style={{ fontSize: "24px", fontWeight: "800", color: "var(--primary)" }}>
                      ${subscription.billing_interval === "annually" ? subscription.plan?.annual_price : subscription.plan?.monthly_price}
                      <small style={{ fontSize: "13px", color: "var(--muted)" }}> / {subscription.billing_interval}</small>
                    </div>
                    <div style={{ display: "flex", flexDirection: "column", gap: "3px", marginTop: "6px", fontSize: "12px" }}>
                      <span className="muted">
                        <strong>Subscribed On:</strong> {formatDate(subscription.created_at)}
                      </span>
                      <span className="muted">
                        <strong>Billing Cycle:</strong> Every 30 Days (Auto-recurring)
                      </span>
                      <span className="muted">
                        <strong>Current 30-Day Period:</strong> {formatDate(subscription.current_period_start)} &rarr; {formatDate(subscription.current_period_end)}
                      </span>
                      <span style={{ color: "var(--primary)", fontWeight: "600" }}>
                        <strong>Next Auto-Invoice:</strong> {formatDate(subscription.current_period_end)}
                      </span>
                    </div>
                    <div style={{ display: "flex", gap: "8px", marginTop: "10px", justifyContent: "flex-end", flexWrap: "wrap" }}>
                      <button
                        type="button"
                        className="secondary-button"
                        style={{ padding: "4px 10px", fontSize: "12px" }}
                        title="Evaluate 30-day cycle and generate recurring invoice if due"
                        onClick={() => handleProcessRecurringInvoices(false)}
                      >
                        <Icon name="refresh" size={13} /> Check 30-Day Auto-Bill
                      </button>
                      <button
                        type="button"
                        className="secondary-button"
                        style={{ padding: "4px 10px", fontSize: "12px" }}
                        title="Simulate 30-day recurring billing cycle immediately"
                        onClick={() => handleProcessRecurringInvoices(true)}
                      >
                        Simulate 30-Day Cycle
                      </button>
                    </div>
                    {subscription.status === "active" && (
                      <button
                        type="button"
                        className="danger-button"
                        style={{ marginTop: "12px", padding: "6px 12px", fontSize: "13px" }}
                        onClick={handleCancelSubscription}
                      >
                        Cancel Subscription
                      </button>
                    )}
                  </>
                ) : (
                  <button
                    type="button"
                    className="primary-button"
                    onClick={() => {
                      if (plans.length > 0) {
                        setSelectedPlan(plans[0]);
                        setShowSubscribeModal(true);
                      }
                    }}
                  >
                    Choose a Plan
                  </button>
                )}
              </div>
            </div>
          </div>

          {/* Usage Metering Stats */}
          {usage && (
            <div style={{ marginBottom: "28px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
                <h3 style={{ margin: 0 }}>Cycle Usage & % Billing Metering</h3>
                <span className="pill pill-ok" style={{ fontSize: "11px" }}>Billed by SIM Provider + {usage.markup_percentage || 20}%</span>
              </div>
              <div className="stat-grid">
                <div className="stat-card">
                  <span className="muted">Active Fleet SIMs</span>
                  <strong>{usage.total_active_sims} <small>Active Lines</small></strong>
                  <span style={{ fontSize: "12px", color: "var(--muted)" }}>Billed per active line</span>
                </div>

                <div className="stat-card">
                  <span className="muted">Cellular Data Consumed</span>
                  <strong>{usage.total_data_used_mb} <small>MB Telemetry</small></strong>
                  <span style={{ fontSize: "12px", color: "var(--muted)" }}>1NCE / Monogoto usage</span>
                </div>

                <div className="stat-card">
                  <span className="muted">SIM Provider Wholesale Cost</span>
                  <strong>${(Number(usage.provider_billed_cost) || 0).toFixed(2)}</strong>
                  <span style={{ fontSize: "12px", color: "var(--muted)" }}>Carrier billed base</span>
                </div>

                <div className="stat-card">
                  <span className="muted">Est. Customer Next Invoice</span>
                  <strong style={{ color: "var(--primary)" }}>${(Number(usage.estimated_total_next_invoice) || 0).toFixed(2)}</strong>
                  <span style={{ fontSize: "12px", color: "var(--success)" }}>
                    Includes +{usage.markup_percentage || 20}% (+${(Number(usage.markup_amount) || 0).toFixed(2)}) margin
                  </span>
                </div>
              </div>
            </div>
          )}

          {/* Available Plans Catalog */}
          <h3 style={{ marginBottom: "14px" }}>Available Subscription Tiers</h3>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: "16px" }}>
            {plans.map((plan) => {
              const isCurrent = subscription?.plan_id === plan.id;
              return (
                <div
                  key={plan.id}
                  className="card"
                  style={{
                    display: "flex",
                    flexDirection: "column",
                    justifyContent: "space-between",
                    border: isCurrent ? "2px solid var(--primary)" : "1px solid var(--border)",
                    boxShadow: isCurrent ? "0 4px 16px rgba(37, 99, 235, 0.12)" : "var(--shadow)",
                  }}
                >
                  <div>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                      <h4 style={{ margin: 0 }}>{plan.name}</h4>
                      {isCurrent && (
                        <span className="pill pill-ok" style={{ fontSize: "11px" }}>Current Plan</span>
                      )}
                    </div>

                    <p className="muted" style={{ fontSize: "13px", margin: "8px 0 16px 0", minHeight: "40px" }}>
                      {plan.description}
                    </p>

                    <div style={{ fontSize: "28px", fontWeight: "800", color: "var(--text)" }}>
                      +{plan.markup_percentage || 20}%
                      <small style={{ fontSize: "14px", color: "var(--muted)", fontWeight: "400" }}> on provider cost</small>
                    </div>
                    <div className="muted" style={{ fontSize: "12px", marginTop: "2px" }}>
                      $0.00 Base Fee · Purely % priced by carrier usage (No Fixed Amount)
                    </div>

                    <ul style={{ listStyle: "none", padding: 0, margin: "16px 0", fontSize: "13px", lineHeight: "1.8" }}>
                      <li>✓ <strong>100% Usage-Based</strong>: No fixed recurring plan amount</li>
                      <li>✓ Wholesale SIM Provider Pass-Through (Data + Lines)</li>
                      <li>✓ Configurable Admin Profit Margin (+{plan.markup_percentage || 20}%)</li>
                      <li>✓ Itemized Odoo ERP invoice synchronization</li>
                    </ul>
                  </div>

                  <button
                    type="button"
                    className={isCurrent ? "secondary-button" : "primary-button"}
                    disabled={isCurrent}
                    onClick={() => {
                      setSelectedPlan(plan);
                      setShowSubscribeModal(true);
                    }}
                  >
                    {isCurrent ? "Current Active Tier" : "Select Plan"}
                  </button>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* ----------------------------------------------------------------- */}
      {/* Tab: Cellular Network & SIM Fleet (Provider-Agnostic) */}
      {/* ----------------------------------------------------------------- */}
      {activeTab === "sims" && (
        <div className="sims-section">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px", flexWrap: "wrap", gap: "12px" }}>
            <div>
              <div style={{ display: "flex", alignItems: "center", gap: "10px", flexWrap: "wrap" }}>
                <h3 style={{ margin: 0 }}>Cellular IoT Fleet</h3>
                <span className="pill pill-ok" style={{ fontSize: "11px", padding: "2px 8px" }}>
                  Scope: {isAdmin ? (simScope === "all" ? "All Platform SIMs" : (organizations.find(o => o.id === selectedOrgId)?.name || activeWorkspace?.name || "Selected Workspace")) : (activeWorkspace?.name || currentUser?.tenant_name || "Workspace Fleet")}
                </span>
              </div>
              <p className="muted" style={{ margin: "4px 0 0 0", fontSize: "13px" }}>
                Cellular fleet scoped by workspace. Naked SIMs carry no IMEI until attached to device hardware.
              </p>
              {isAdmin && (
                <div style={{ display: "inline-flex", marginTop: "8px", background: "var(--surface-2)", padding: "2px", borderRadius: "var(--radius-sm)", border: "1px solid var(--border)" }}>
                  <button
                    type="button"
                    style={{
                      border: "none",
                      padding: "4px 10px",
                      borderRadius: "4px",
                      fontSize: "12px",
                      fontWeight: 600,
                      background: simScope === "workspace" ? "var(--primary)" : "transparent",
                      color: simScope === "workspace" ? "#fff" : "var(--text-muted)",
                      cursor: "pointer",
                    }}
                    onClick={() => {
                      setSimScope("workspace");
                      loadAll(selectedOrgId, true, "workspace");
                    }}
                  >
                    Active Workspace Fleet
                  </button>

                  <button
                    type="button"
                    style={{
                      border: "none",
                      padding: "4px 10px",
                      borderRadius: "4px",
                      fontSize: "12px",
                      fontWeight: 600,
                      background: simScope === "all" ? "var(--primary)" : "transparent",
                      color: simScope === "all" ? "#fff" : "var(--text-muted)",
                      cursor: "pointer",
                    }}
                    onClick={() => {
                      setSimScope("all");
                      loadAll(selectedOrgId, true, "all");
                    }}
                  >
                    All Platform SIMs
                  </button>
                </div>
              )}
            </div>

            <div style={{ display: "flex", gap: "8px", alignItems: "center", flexWrap: "wrap" }}>
              <select
                value={providerFilter}
                onChange={(e) => setProviderFilter(e.target.value)}
                style={{ padding: "8px 12px", borderRadius: "var(--radius-sm)", border: "1px solid var(--border)", background: "var(--surface)", color: "var(--text)" }}
              >
                <option value="all">All Providers ({sims.length})</option>
                {providers.map((p) => (
                  <option key={p.provider_code} value={p.provider_code}>
                    {p.name} ({sims.filter((s) => (s.provider || "1nce").toLowerCase() === p.provider_code.toLowerCase()).length})
                  </option>
                ))}
              </select>

              <button
                type="button"
                className="primary-button"
                onClick={() => handleSyncProviderSims(providerFilter === "all" ? (providers[0]?.provider_code || "1nce") : providerFilter)}
              >
                <Icon name="refresh" size={16} /> Sync {providerFilter === "all" ? "Fleet" : providerFilter.toUpperCase()}
              </button>
            </div>
          </div>

          <div className="card table-container">
            <table>
              <thead>
                <tr>
                  <th>Provider / ICCID</th>
                  <th>Device Link</th>
                   <th>Assigned To</th>
                  <th>Radio & Tower</th>
                  <th>Data Quota</th>
                  <th>SMS</th>
                  <th>Status</th>
                  <th style={{ textAlign: "right" }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {sims.filter((s) => providerFilter === "all" || (s.provider || "1nce").toLowerCase() === providerFilter.toLowerCase()).length === 0 ? (
                  <tr>
                    <td colSpan="8" style={{ textAlign: "center", padding: "32px" }} className="muted">
                      No SIM cards found for {providerFilter === "all" ? "any provider" : providerFilter}. Use the Sync button above or add a Network Provider API.
                    </td>
                  </tr>
                ) : (
                  sims
                    .filter((s) => providerFilter === "all" || (s.provider || "1nce").toLowerCase() === providerFilter.toLowerCase())
                    .map((sim) => {
                      const quotaTotal = sim.quota_total_mb || 500.0;
                      const quotaRem = sim.quota_remaining_mb || 0.0;
                      const quotaUsed = sim.quota_used_mb || (quotaTotal - quotaRem);
                      const pct = Math.min(100, Math.round((quotaUsed / quotaTotal) * 100));
                      const pType = (sim.provider || "1nce").toLowerCase();
                      const badgeColors = pType.includes("monogoto")
                        ? { bg: "#ede9fe", color: "#7c3aed" }
                        : pType.includes("1nce")
                        ? { bg: "#dbeafe", color: "#1d4ed8" }
                        : pType.includes("emnify")
                        ? { bg: "#fce7f3", color: "#be185d" }
                        : pType.includes("twilio")
                        ? { bg: "#fee2e2", color: "#b91c1c" }
                        : { bg: "#e0f2fe", color: "#0369a1" };

                      return (
                        <tr key={sim.iccid}>
                          <td>
                            <div style={{ display: "flex", alignItems: "center", gap: "6px", marginBottom: "4px" }}>
                              <span
                                style={{
                                  padding: "2px 8px",
                                  borderRadius: "10px",
                                  fontSize: "11px",
                                  fontWeight: 700,
                                  background: badgeColors.bg,
                                  color: badgeColors.color,
                                }}
                              >
                                {(sim.provider || "1nce").toUpperCase()}
                              </span>
                            </div>
                            <strong>{sim.iccid}</strong>
                            {sim.label && <div className="muted" style={{ fontSize: "12px" }}>{sim.label}</div>}
                          </td>

                          <td>
                            {sim.device_id ? (
                              <div>
                                <code>{sim.device_id}</code>
                                {sim.imei ? (
                                  <div className="muted" style={{ fontSize: "11px", marginTop: "2px", fontFamily: "var(--font-mono, monospace)" }}>
                                    IMEI: {sim.imei}
                                  </div>
                                ) : (
                                  <div className="muted" style={{ fontSize: "11px", marginTop: "2px" }}>
                                    No IMEI reported
                                  </div>
                                )}
                              </div>
                            ) : (
                              <div>
                                <span className="muted" style={{ fontSize: "13px" }}>Unassigned</span>
                                <div className="muted" style={{ fontSize: "11px", color: "var(--text-muted)", marginTop: "2px" }}>
                                  No IMEI (unattached)
                                </div>
                              </div>
                            )}
                          </td>

                          <td>
                            {(() => {
                              const tenantId = sim.tenant_id;
                              const org = organizations.find(o => o.id === tenantId);
                              const tenantName = org
                                ? org.name
                                : tenantId
                                ? `Tenant #${tenantId}`
                                : null;
                              const tenantType = org ? (org.type || "organization") : tenantId ? "unknown" : "unassigned";
                              const isOrg = tenantType === "organization";
                              const isIndiv = tenantType === "individual";
                              const isUnassigned = !tenantId;
                              const displayName = isUnassigned
                                ? "Unassigned Pool"
                                : tenantName || (isOrg ? "Organization" : "Individual");
                              return (
                                <div>
                                  <span style={{
                                    display: "inline-block",
                                    padding: "2px 8px",
                                    borderRadius: "10px",
                                    fontSize: "11px",
                                    fontWeight: 700,
                                    background: isUnassigned ? "var(--surface-3)" : isOrg ? "#dbeafe" : "#dcfce7",
                                    color: isUnassigned ? "var(--text-muted)" : isOrg ? "#1d4ed8" : "#15803d",
                                  }}>
                                    {isOrg ? "🏢 Org" : isIndiv ? "👤 Individual" : "📦 Pool"}
                                  </span>
                                  <div style={{ fontSize: "12px", marginTop: "3px", fontWeight: 500 }}>
                                    {displayName}
                                  </div>
                                </div>
                              );
                            })()}
                          </td>

                          <td>
                            <div>
                              <span className="badge tn" style={{ fontSize: "11px" }}>
                                {sim.last_connectivity_check?.radio_access_technology || "NB-IoT / LTE-M"}
                              </span>
                            </div>
                            {sim.ip_address && (
                              <div className="muted" style={{ fontSize: "12px", marginTop: "2px" }}>
                                IP: {sim.ip_address}
                              </div>
                            )}
                          </td>

                          <td style={{ minWidth: "160px" }}>
                            <div style={{ display: "flex", justifyContent: "space-between", fontSize: "12px", marginBottom: "4px" }}>
                              <span>{(Number(quotaUsed) || 0).toFixed(1)} MB</span>
                              <span className="muted">{(Number(quotaRem) || 0).toFixed(1)} MB left</span>
                            </div>
                            <div style={{ height: "6px", width: "100%", background: "var(--surface-3)", borderRadius: "3px", overflow: "hidden" }}>
                              <div
                                style={{
                                  height: "100%",
                                  width: `${pct}%`,
                                  background: pct > 85 ? "var(--danger)" : pct > 60 ? "var(--warning)" : "var(--primary)",
                                  borderRadius: "3px",
                                }}
                              />
                            </div>
                          </td>

                          <td>
                            <span style={{ fontSize: "13px" }}>{sim.sms_remaining ?? 250}</span>
                            <small className="muted"> / {sim.sms_total ?? 250}</small>
                          </td>

                          <td>
                            <StatusPill
                              active={sim.status === "Active"}
                              activeText="Active"
                              inactiveText={sim.status}
                            />
                          </td>

                          <td style={{ textAlign: "right" }}>
                            <div style={{ display: "flex", gap: "6px", justifyContent: "flex-end" }}>
                              <button
                                type="button"
                                className="secondary-button"
                                style={{ padding: "4px 8px", fontSize: "12px" }}
                                title="Toggle Network Status"
                                onClick={() => handleToggleSimStatus(sim)}
                              >
                                {sim.status === "Active" ? "Suspend" : "Activate"}
                              </button>

                              <button
                                type="button"
                                className="secondary-button"
                                style={{ padding: "4px 8px", fontSize: "12px" }}
                                title="Reset Core Session"
                                onClick={() => handleResetSim(sim)}
                              >
                                Reset
                              </button>

                              <button
                                type="button"
                                className="secondary-button"
                                style={{ padding: "4px 8px", fontSize: "12px" }}
                                title="Top-up Quota (+500MB)"
                                onClick={() => {
                                  setTopupSim(sim);
                                  setTopupVolumeMb(500);
                                }}
                              >
                                Top-Up
                              </button>

                              <button
                                type="button"
                                className="secondary-button"
                                style={{ padding: "4px 8px", fontSize: "12px" }}
                                title="Send MT-SMS Command"
                                onClick={() => {
                                  setSmsSim(sim);
                                  setSmsPayload("CMD#STATUS");
                                }}
                              >
                                SMS
                              </button>

                              <button
                                type="button"
                                className="secondary-button"
                                style={{ padding: "4px 8px", fontSize: "12px" }}
                                title="Assign to Device"
                                onClick={() => {
                                  setAssignSim(sim);
                                  setAssignDeviceId(sim.device_id || "");
                                  setAssignImei(sim.imei || "");
                                  setAssignLabel(sim.label || "");
                                }}
                              >
                                Link
                              </button>
                            </div>
                          </td>
                        </tr>
                      );
                    })
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ----------------------------------------------------------------- */}
      {/* Tab: Odoo Invoices History */}
      {/* ----------------------------------------------------------------- */}
      {activeTab === "invoices" && (
        <div className="invoices-section">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px" }}>
            <div>
              <h3 style={{ margin: 0 }}>Odoo ERP Invoices</h3>
              <p className="muted" style={{ margin: "4px 0 0 0", fontSize: "13px" }}>
                Itemized customer invoices synchronized directly with Odoo ERP (<code>account.move</code>). Automatically generated every 30 days from date of subscription.
              </p>
            </div>
            <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
              <button
                type="button"
                className="secondary-button"
                onClick={() => handleProcessRecurringInvoices(false)}
                title="Runs the 30-day recurring auto-billing cycle across active subscriptions"
              >
                <Icon name="refresh" size={15} /> Process 30-Day Auto-Billing
              </button>
              {isAdmin && (
                <button
                  type="button"
                  className="primary-button"
                  onClick={handleGenerateInvoice}
                >
                  <Icon name="billing" size={16} /> Generate Invoice Now
                </button>
              )}
            </div>
          </div>

          <div className="card table-container">
            <table>
              <thead>
                <tr>
                  <th>Invoice Number</th>
                  <th>Created / Due Date</th>
                  <th>Odoo Move Ref</th>
                  <th>Line Items Breakdown</th>
                  <th>Total Amount</th>
                  <th>Payment State</th>
                  <th style={{ textAlign: "right" }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {invoices.length === 0 ? (
                  <tr>
                    <td colSpan="8" style={{ textAlign: "center", padding: "32px" }} className="muted">
                      No invoices recorded yet. Click "Generate Invoice Now" to generate an itemized invoice.
                    </td>
                  </tr>
                ) : (
                  invoices.map((inv) => (
                    <tr key={inv.id}>
                      <td>
                        <strong>{inv.invoice_number}</strong>
                        {inv.status === "paid" && (
                          <div style={{ fontSize: "11px", color: "var(--success)" }}>
                            Paid on {formatDate(inv.paid_at)}
                          </div>
                        )}
                      </td>

                      <td>
                        <div>{formatDate(inv.created_at)}</div>
                        <div className="muted" style={{ fontSize: "12px" }}>Due: {formatDate(inv.due_date)}</div>
                      </td>

                      <td>
                        {inv.odoo_move_name ? (
                          <code>{inv.odoo_move_name}</code>
                        ) : (
                          <span className="muted">#{inv.odoo_invoice_id || "Draft"}</span>
                        )}
                      </td>

                      <td>
                        <div style={{ fontSize: "12px", lineHeight: "1.6" }}>
                          {inv.line_items?.map((item, idx) => (
                            <div key={idx}>
                              • {item.name}: <strong>${(Number(item.total) || 0).toFixed(2)}</strong>
                            </div>
                          ))}
                        </div>
                      </td>

                      <td>
                        <strong style={{ fontSize: "16px", color: "var(--text)" }}>
                          ${(Number(inv.amount_total) || 0).toFixed(2)}
                        </strong>
                        <div className="muted" style={{ fontSize: "11px" }}>{inv.currency}</div>
                      </td>

                      <td>
                        <span
                          className={`pill ${inv.odoo_payment_state === "paid" || inv.status === "paid" ? "pill-ok" : "pill-off"}`}
                          style={{
                            background: (inv.odoo_payment_state === "paid" || inv.status === "paid") ? "var(--success-soft)" : "var(--warning-soft)",
                            color: (inv.odoo_payment_state === "paid" || inv.status === "paid") ? "var(--success)" : "var(--warning)",
                          }}
                        >
                          {String(inv.odoo_payment_state || inv.status || "draft").toUpperCase()}
                        </span>
                      </td>

                      <td style={{ textAlign: "right" }}>
                        <div style={{ display: "flex", gap: "6px", justifyContent: "flex-end" }}>
                          <button
                            type="button"
                            className="secondary-button"
                            style={{ padding: "4px 8px", fontSize: "12px" }}
                            title="Sync status from Odoo ERP"
                            onClick={() => handleSyncOdooInvoice(inv.id)}
                          >
                            Sync
                          </button>

                          {(inv.status !== "paid" && inv.odoo_payment_state !== "paid") && (
                            <button
                              type="button"
                              className="primary-button"
                              style={{ padding: "4px 8px", fontSize: "12px" }}
                              title="Record payment and reactivate SIMs"
                              onClick={() => handlePayInvoice(inv.id)}
                            >
                              Pay & Unlock
                            </button>
                          )}

                          <button
                            type="button"
                            className="secondary-button"
                            style={{ padding: "4px 8px", fontSize: "12px" }}
                            title="Download PDF report"
                            onClick={() => handleDownloadPdf(inv)}
                          >
                            PDF
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ----------------------------------------------------------------- */}
      {/* Tab: Dynamic Network Providers (Monogoto, 1NCE, Generic) */}
      {/* ----------------------------------------------------------------- */}
      {activeTab === "providers" && (
        <div className="providers-section">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px", flexWrap: "wrap", gap: "12px" }}>
            <div>
              <h3 style={{ margin: 0 }}>Dynamic Network Providers</h3>
              <p className="muted" style={{ margin: "4px 0 0 0", fontSize: "13px" }}>
                Add, edit, remove, and probe cellular & satellite IoT network APIs (Monogoto, 1NCE, generic).
              </p>
            </div>
            {isAdmin && (
              <button
                type="button"
                className="primary-button"
                onClick={() => {
                  setProviderForm({
                    name: "Monogoto Global Cellular",
                    provider_code: "monogoto",
                    provider_type: "monogoto",
                    base_url: "https://api.monogoto.io",
                    auth_type: "bearer_token",
                    api_user: "",
                    api_key: "",
                    is_sandbox: true,
                    is_enabled: true,
                  });
                  setShowAddProviderModal(true);
                }}
              >
                + Add Network Provider
              </button>
            )}
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(340px, 1fr))", gap: "16px" }}>
            {providers.map((p) => {
              const testRes = providerTestResults[p.provider_code];
              const isTesting = providerTestLoading[p.provider_code];
              const pType = (p.provider_type || p.provider_code || "").toLowerCase();
              const badgeColors = pType.includes("monogoto")
                ? { bg: "#ede9fe", color: "#7c3aed", border: "rgba(139, 92, 246, 0.4)" }
                : pType.includes("1nce")
                ? { bg: "#dbeafe", color: "#1d4ed8", border: "rgba(59, 130, 246, 0.4)" }
                : pType.includes("emnify")
                ? { bg: "#fce7f3", color: "#be185d", border: "rgba(236, 72, 153, 0.4)" }
                : pType.includes("twilio")
                ? { bg: "#fee2e2", color: "#b91c1c", border: "rgba(239, 68, 68, 0.4)" }
                : { bg: "#e0f2fe", color: "#0369a1", border: "rgba(14, 165, 233, 0.4)" };

              return (
                <div
                  key={p.provider_code}
                  className="card"
                  style={{
                    display: "flex",
                    flexDirection: "column",
                    justifyContent: "space-between",
                    border: `1px solid ${badgeColors.border}`,
                  }}
                >
                  <div>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "8px" }}>
                      <div>
                        <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                          <span
                            style={{
                              padding: "2px 8px",
                              borderRadius: "10px",
                              fontSize: "11px",
                              fontWeight: 700,
                              background: badgeColors.bg,
                              color: badgeColors.color,
                            }}
                          >
                            {(p.provider_type || p.provider_code || "").toUpperCase()}
                          </span>
                        </div>
                        <h4 style={{ margin: "4px 0 0 0", fontSize: "16px" }}>{p.name}</h4>
                        <div className="muted" style={{ fontSize: "12px", marginTop: "2px" }}>
                          Code: <code>{p.provider_code}</code>
                        </div>
                      </div>

                      <div style={{ display: "flex", gap: "6px" }}>
                        <span
                          className="pill"
                          style={{
                            background: p.is_sandbox ? "#fef3c7" : "#dcfce7",
                            color: p.is_sandbox ? "#d97706" : "#15803d",
                            fontSize: "11px",
                            padding: "2px 8px",
                            borderRadius: "10px",
                            fontWeight: 600,
                          }}
                        >
                          {p.is_sandbox ? "SANDBOX" : "LIVE"}
                        </span>
                        <span
                          className="pill"
                          style={{
                            background: p.is_enabled ? "#dcfce7" : "#f3f4f6",
                            color: p.is_enabled ? "#15803d" : "#6b7280",
                            fontSize: "11px",
                            padding: "2px 8px",
                            borderRadius: "10px",
                            fontWeight: 600,
                          }}
                        >
                          {p.is_enabled ? "ENABLED" : "OFF"}
                        </span>
                      </div>
                    </div>

                    {p.capabilities && p.capabilities.length > 0 && (
                      <div style={{ display: "flex", flexWrap: "wrap", gap: "4px", margin: "8px 0" }}>
                        {p.capabilities.map((cap) => (
                          <span
                            key={cap}
                            style={{
                              fontSize: "10px",
                              padding: "2px 6px",
                              borderRadius: "4px",
                              background: "var(--surface-2)",
                              border: "1px solid var(--border)",
                              color: "var(--text-muted)",
                              textTransform: "uppercase",
                              fontWeight: 600,
                            }}
                          >
                            {cap.replace("_", " ")}
                          </span>
                        ))}
                      </div>
                    )}

                    <div style={{ fontSize: "13px", lineHeight: "1.7", margin: "10px 0", background: "var(--surface-2)", padding: "10px", borderRadius: "var(--radius-sm)" }}>
                      <div>🌐 <strong>Endpoint:</strong> <code>{p.base_url}</code></div>
                      <div>🔑 <strong>Auth:</strong> {p.auth_type} {p.has_api_key ? "• (Encrypted Key Saved)" : "• (No key)"}</div>
                      <div>📶 <strong>Fleet SIMs:</strong> {p.sim_count} registered</div>
                      {p.api_user && <div>👤 <strong>Account User:</strong> {p.api_user}</div>}
                    </div>

                    <div style={{ fontSize: "12px", background: "rgba(59, 130, 246, 0.06)", border: "1px dashed rgba(59, 130, 246, 0.3)", borderRadius: "var(--radius-sm)", padding: "10px", margin: "10px 0" }}>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "6px" }}>
                        <span style={{ fontWeight: 700, color: "var(--primary)" }}>📈 Dynamic % Pricing</span>
                        <span style={{ fontWeight: 700, padding: "2px 8px", borderRadius: "10px", background: "rgba(59, 130, 246, 0.15)", color: "var(--primary)" }}>
                          +{p.markup_percentage != null ? p.markup_percentage : 20}% Admin Margin
                        </span>
                      </div>
                      <div style={{ color: "var(--text-muted)", fontSize: "11px", marginBottom: "4px" }}>
                        Wholesale Billed: ${(p.cost_per_mb ?? 0.03).toFixed(3)}/MB · ${(p.cost_per_sim ?? 1.00).toFixed(2)}/SIM · ${(p.cost_per_sms ?? 0.01).toFixed(3)}/SMS
                      </div>
                      <div style={{ fontWeight: 600, color: "var(--text)" }}>
                        Client Retail: ${(p.effective_customer_mb_rate ?? ((p.cost_per_mb ?? 0.03) * (1 + (p.markup_percentage ?? 20) / 100))).toFixed(3)}/MB · ${(p.effective_customer_sim_rate ?? ((p.cost_per_sim ?? 1.00) * (1 + (p.markup_percentage ?? 20) / 100))).toFixed(2)}/SIM/mo
                      </div>
                    </div>

                    {testRes && (
                      <div
                        style={{
                          margin: "10px 0",
                          padding: "8px 12px",
                          borderRadius: "var(--radius-sm)",
                          fontSize: "12px",
                          background: testRes.success ? "rgba(34, 197, 94, 0.1)" : "rgba(239, 68, 68, 0.1)",
                          color: testRes.success ? "var(--success)" : "var(--danger)",
                          border: `1px solid ${testRes.success ? "rgba(34, 197, 94, 0.3)" : "rgba(239, 68, 68, 0.3)"}`,
                        }}
                      >
                        <strong>{testRes.success ? "✓ Test Passed" : "✕ Test Failed"}</strong>
                        {testRes.latency_ms && ` (${testRes.latency_ms} ms)`}: {testRes.message}
                      </div>
                    )}
                  </div>

                  <div style={{ display: "flex", gap: "8px", marginTop: "16px", flexWrap: "wrap", borderTop: "1px solid var(--border)", paddingTop: "12px" }}>
                    <button
                      type="button"
                      className="primary-button"
                      style={{ padding: "6px 12px", fontSize: "12px" }}
                      disabled={isTesting}
                      onClick={() => handleTestProvider(p.provider_code)}
                    >
                      {isTesting ? "Testing..." : "Test API"}
                    </button>

                    <button
                      type="button"
                      className="secondary-button"
                      style={{ padding: "6px 12px", fontSize: "12px" }}
                      onClick={() => handleSyncProviderSims(p.provider_code)}
                    >
                      <Icon name="refresh" size={14} /> Sync Fleet
                    </button>

                    {isAdmin && (
                      <>
                        <button
                          type="button"
                          className="secondary-button"
                          style={{ padding: "6px 12px", fontSize: "12px" }}
                          onClick={() => setEditingProvider({ ...p, api_key: "" })}
                        >
                          Edit
                        </button>

                        <button
                          type="button"
                          className="danger-button"
                          style={{ padding: "6px 12px", fontSize: "12px" }}
                          onClick={() => handleDeleteProvider(p)}
                        >
                          Delete
                        </button>
                      </>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* ----------------------------------------------------------------- */}
      {/* Tab: Integration Diagnostics (Admin) */}
      {/* ----------------------------------------------------------------- */}
      {activeTab === "diagnostics" && isAdmin && (
        <div className="diagnostics-section">
          <h3>Integration Connectivity Tests</h3>
          <p className="muted" style={{ fontSize: "13px", marginTop: "4px" }}>
            Test live network connections to Monogoto Developer API, 1NCE Management API, and Odoo ERP XML-RPC endpoints.
          </p>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: "16px", marginTop: "16px" }}>
            <div className="card">
              <h4>Monogoto Developer API</h4>
              <p className="muted" style={{ fontSize: "13px" }}>
                Tests OAuth2 Bearer token authentication and Thing fleet query at <code>https://api.monogoto.io</code>.
              </p>
              <button
                type="button"
                className="primary-button"
                disabled={providerTestLoading["monogoto"]}
                onClick={() => handleTestProvider("monogoto")}
              >
                {providerTestLoading["monogoto"] ? "Testing..." : "Test Monogoto Connection"}
              </button>
            </div>

            <div className="card">
              <h4>1NCE Management API</h4>
              <p className="muted" style={{ fontSize: "13px" }}>
                Tests OAuth 2.0 authentication and SIM queries at <code>https://api.1nce.com/management-api</code>.
              </p>
              <button
                type="button"
                className="primary-button"
                disabled={testing}
                onClick={() => runDiagnostic("1nce")}
              >
                {testing ? "Testing..." : "Test 1NCE Connection"}
              </button>
            </div>

            <div className="card">
              <h4>Odoo ERP Invoicing Service</h4>
              <p className="muted" style={{ fontSize: "13px" }}>
                Tests XML-RPC external API authentication and customer partner search.
              </p>
              <button
                type="button"
                className="primary-button"
                disabled={testing}
                onClick={() => runDiagnostic("odoo")}
              >
                {testing ? "Testing..." : "Test Odoo Connection"}
              </button>
            </div>
          </div>

          {testResult && (
            <div className="card" style={{ marginTop: "20px" }}>
              <h4>Diagnostic Result: {(testResult.provider || "").toUpperCase()}</h4>
              <div style={{ margin: "10px 0" }}>
                <StatusPill
                  active={testResult.success}
                  activeText={`SUCCESS (${testResult.mode?.toUpperCase() || "OK"})`}
                  inactiveText="FAILED"
                />
                {testResult.latency_ms && (
                  <span className="muted" style={{ marginLeft: "10px", fontSize: "13px" }}>
                    Latency: {testResult.latency_ms} ms
                  </span>
                )}
              </div>
              <p style={{ fontWeight: 600 }}>{testResult.message}</p>
              {testResult.details && (
                <pre style={{ background: "var(--code-bg)", padding: "12px", borderRadius: "var(--radius-sm)", fontSize: "12px" }}>
                  {JSON.stringify(testResult.details, null, 2)}
                </pre>
              )}
            </div>
          )}
        </div>
      )}

      {/* ----------------------------------------------------------------- */}
      {/* Modals */}
      {/* ----------------------------------------------------------------- */}

      {/* Plan Subscribe Modal */}
      {showSubscribeModal && selectedPlan && (
        <Modal
          title={`Subscribe to ${selectedPlan.name}`}
          subtitle="Confirm organization subscription tier and billing cycle."
          onClose={() => setShowSubscribeModal(false)}
        >
          <form onSubmit={handleSubscribe}>
            {isAdmin && organizations.length > 0 && (
              <div style={{ marginBottom: "16px" }}>
                <label style={{ fontSize: "12px", fontWeight: 600 }}>Target Organization / Client Workspace</label>
                <select
                  value={selectedOrgId}
                  onChange={(e) => setSelectedOrgId(Number(e.target.value))}
                  style={{ width: "100%", padding: "8px", marginTop: "4px" }}
                >
                  {organizations.map((org) => (
                    <option key={org.id} value={org.id}>
                      {org.name} (ID: {org.id})
                    </option>
                  ))}
                </select>
              </div>
            )}
            <div style={{ marginBottom: "16px" }}>
              <label>Billing Interval</label>
              <select
                value={subscribeInterval}
                onChange={(e) => setSubscribeInterval(e.target.value)}
                style={{ width: "100%", padding: "8px", marginTop: "4px" }}
              >
                <option value="monthly">Monthly (${selectedPlan.monthly_price} / month)</option>
                <option value="annually">Annually (${selectedPlan.annual_price} / year)</option>
              </select>
            </div>

            <div className="muted" style={{ fontSize: "13px", lineHeight: "1.6", marginBottom: "20px" }}>
              • Plan includes <strong>{selectedPlan.included_devices} active SIMs</strong> and <strong>{selectedPlan.included_data_mb} MB</strong> pooled data.<br />
              • Customer partner record will be provisioned automatically in Odoo ERP.<br />
              • Recurring invoices will be generated in Odoo at each cycle.
            </div>

            <div style={{ display: "flex", justifyContent: "flex-end", gap: "8px" }}>
              <button type="button" className="secondary-button" onClick={() => setShowSubscribeModal(false)}>
                Cancel
              </button>
              <button type="submit" className="primary-button">
                Confirm & Subscribe
              </button>
            </div>
          </form>
        </Modal>
      )}

      {/* Top-up Modal */}
      {topupSim && (
        <Modal
          title="Top-Up Data Quota"
          subtitle={`Add data volume to SIM ${topupSim.iccid} (${(topupSim.provider || "1nce").toUpperCase()}).`}
          onClose={() => setTopupSim(null)}
        >
          <form onSubmit={handleTopupSubmit}>
            <div style={{ marginBottom: "16px" }}>
              <label>Top-Up Volume (MB)</label>
              <input
                type="number"
                min="50"
                step="50"
                value={topupVolumeMb}
                onChange={(e) => setTopupVolumeMb(e.target.value)}
                style={{ width: "100%", padding: "8px", marginTop: "4px" }}
                required
              />
            </div>

            <div style={{ marginBottom: "20px" }}>
              <label style={{ display: "flex", alignItems: "center", gap: "8px", cursor: "pointer" }}>
                <input
                  type="checkbox"
                  checked={topupCreateInvoice}
                  onChange={(e) => setTopupCreateInvoice(e.target.checked)}
                />
                Generate Odoo Invoice for this top-up (approx. ${(Number(topupVolumeMb) * 0.04).toFixed(2)})
              </label>
            </div>

            <div style={{ display: "flex", justifyContent: "flex-end", gap: "8px" }}>
              <button type="button" className="secondary-button" onClick={() => setTopupSim(null)}>
                Cancel
              </button>
              <button type="submit" className="primary-button">
                Apply Top-Up
              </button>
            </div>
          </form>
        </Modal>
      )}

      {/* MT-SMS Modal */}
      {smsSim && (
        <Modal
          title="Send MT-SMS to Device"
          subtitle={`Dispatches Mobile-Terminated SMS to SIM ${smsSim.iccid} via ${(smsSim.provider || "1nce").toUpperCase()} Gateway.`}
          onClose={() => setSmsSim(null)}
        >
          <form onSubmit={handleSendSmsSubmit}>
            <div style={{ marginBottom: "14px" }}>
              <label>SMS Payload (max 160 chars)</label>
              <input
                type="text"
                value={smsPayload}
                onChange={(e) => setSmsPayload(e.target.value)}
                style={{ width: "100%", padding: "8px", marginTop: "4px" }}
                required
              />
            </div>

            <div style={{ marginBottom: "20px" }}>
              <label>Source Address</label>
              <input
                type="text"
                value={smsSource}
                onChange={(e) => setSmsSource(e.target.value)}
                style={{ width: "100%", padding: "8px", marginTop: "4px" }}
              />
            </div>

            <div style={{ display: "flex", justifyContent: "flex-end", gap: "8px" }}>
              <button type="button" className="secondary-button" onClick={() => setSmsSim(null)}>
                Cancel
              </button>
              <button type="submit" className="primary-button">
                Dispatch SMS
              </button>
            </div>
          </form>
        </Modal>
      )}

      {/* Assign SIM Modal */}
      {assignSim && (
        <Modal
          title="Link SIM to Device"
          subtitle={`Associate SIM ${assignSim.iccid} with a NibiaaNet device ID.`}
          onClose={() => setAssignSim(null)}
        >
          <form onSubmit={handleAssignSimSubmit}>
            <div style={{ marginBottom: "14px" }}>
              <label>Device ID</label>
              <input
                type="text"
                placeholder="e.g. DEVICE001 (leave empty to unassign)"
                value={assignDeviceId}
                onChange={(e) => {
                  setAssignDeviceId(e.target.value);
                  if (!e.target.value.trim()) {
                    setAssignImei("");
                  }
                }}
                style={{ width: "100%", padding: "8px", marginTop: "4px" }}
              />
            </div>

            <div style={{ marginBottom: "14px" }}>
              <label>Device Modem IMEI (Only available when attached)</label>
              <input
                type="text"
                placeholder="e.g. 356938035643801"
                value={assignImei}
                disabled={!assignDeviceId.trim()}
                onChange={(e) => setAssignImei(e.target.value)}
                style={{ width: "100%", padding: "8px", marginTop: "4px", background: !assignDeviceId.trim() ? "var(--surface-2)" : "var(--surface)" }}
              />
              <small className="muted" style={{ fontSize: "11px", display: "block", marginTop: "4px" }}>
                {assignDeviceId.trim() ? "Hardware IMEI reported by device modem." : "Naked SIM cards have no IMEI until attached to a device."}
              </small>
            </div>

            <div style={{ marginBottom: "20px" }}>
              <label>SIM Label</label>
              <input
                type="text"
                placeholder="e.g. Field Cold-Chain Sensor"
                value={assignLabel}
                onChange={(e) => setAssignLabel(e.target.value)}
                style={{ width: "100%", padding: "8px", marginTop: "4px" }}
              />
            </div>

            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "8px" }}>
              {assignSim.device_id && (
                <button
                  type="button"
                  className="secondary-button"
                  style={{ color: "var(--danger)", border: "1px solid var(--danger)", background: "transparent" }}
                  onClick={() => {
                    setAssignDeviceId("");
                    setAssignImei("");
                  }}
                >
                  Detach / Unassign Device
                </button>
              )}
              <div style={{ display: "flex", gap: "8px", marginLeft: "auto" }}>
                <button type="button" className="secondary-button" onClick={() => setAssignSim(null)}>
                  Cancel
                </button>
                <button type="submit" className="primary-button">
                  Save Assignment
                </button>
              </div>
            </div>
          </form>
        </Modal>
      )}

      {/* Add Network Provider Modal */}
      {showAddProviderModal && (
        <Modal
          title="Add Network Provider API"
          subtitle="Register an IoT SIM provider gateway (Monogoto, 1NCE, EMnify, Twilio, or Custom REST)."
          onClose={() => setShowAddProviderModal(false)}
        >
          <form onSubmit={handleCreateProvider}>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px", marginBottom: "14px" }}>
              <div>
                <label>SIM Provider Driver Template</label>
                <select
                  value={providerForm.provider_type}
                  onChange={(e) => {
                    const t = e.target.value;
                    const presets = {
                      monogoto: {
                        name: "Monogoto Global Cellular",
                        provider_code: "monogoto",
                        base_url: "https://api.monogoto.io",
                        auth_type: "bearer_token",
                      },
                      "1nce": {
                        name: "1NCE Cellular IoT",
                        provider_code: "1nce",
                        base_url: "https://api.1nce.com/management-api",
                        auth_type: "oauth2",
                      },
                      emnify: {
                        name: "EMnify Global Cellular IoT",
                        provider_code: "emnify",
                        base_url: "https://cdn.emnify.net/api/v1",
                        auth_type: "bearer_token",
                      },
                      twilio: {
                        name: "Twilio Super SIM",
                        provider_code: "twilio",
                        base_url: "https://supersim.twilio.com/v1",
                        auth_type: "basic_auth",
                      },
                      generic_rest: {
                        name: "Custom REST SIM Provider",
                        provider_code: "custom-sim",
                        base_url: "https://api.mycarrier.com/v1",
                        auth_type: "bearer_token",
                      },
                    };
                    const p = presets[t] || presets.generic_rest;
                    setProviderForm((prev) => ({
                      ...prev,
                      provider_type: t,
                      name: p.name,
                      provider_code: p.provider_code,
                      base_url: p.base_url,
                      auth_type: p.auth_type,
                    }));
                  }}
                  style={{ width: "100%", padding: "8px", marginTop: "4px" }}
                >
                  <option value="monogoto">Monogoto Developer API (developer.monogoto.io)</option>
                  <option value="1nce">1NCE Management API (help.1nce.com)</option>
                  <option value="emnify">EMnify Global Cellular (cdn.emnify.net)</option>
                  <option value="twilio">Twilio Super SIM (twilio.com)</option>
                  <option value="generic_rest">Custom REST SIM Provider (Configurable Gateway)</option>
                </select>
              </div>

              <div>
                <label>Unique Code (Slug)</label>
                <input
                  type="text"
                  required
                  placeholder="e.g. monogoto"
                  value={providerForm.provider_code}
                  onChange={(e) => setProviderForm({ ...providerForm, provider_code: e.target.value })}
                  style={{ width: "100%", padding: "8px", marginTop: "4px" }}
                />
              </div>
            </div>

            <div style={{ marginBottom: "14px" }}>
              <label>Provider Display Name</label>
              <input
                type="text"
                required
                placeholder="e.g. Monogoto Global Cellular"
                value={providerForm.name}
                onChange={(e) => setProviderForm({ ...providerForm, name: e.target.value })}
                style={{ width: "100%", padding: "8px", marginTop: "4px" }}
              />
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: "12px", marginBottom: "14px" }}>
              <div>
                <label>API Base URL</label>
                <input
                  type="url"
                  required
                  placeholder="https://api.monogoto.io"
                  value={providerForm.base_url}
                  onChange={(e) => setProviderForm({ ...providerForm, base_url: e.target.value })}
                  style={{ width: "100%", padding: "8px", marginTop: "4px" }}
                />
              </div>

              <div>
                <label>Auth Type</label>
                <select
                  value={providerForm.auth_type}
                  onChange={(e) => setProviderForm({ ...providerForm, auth_type: e.target.value })}
                  style={{ width: "100%", padding: "8px", marginTop: "4px" }}
                >
                  <option value="bearer_token">Bearer Token (JWT)</option>
                  <option value="oauth2">OAuth 2.0 (Client Secret)</option>
                  <option value="api_key">API Key Header</option>
                  <option value="basic_auth">Basic Auth</option>
                </select>
              </div>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px", marginBottom: "14px" }}>
              <div>
                <label>Username / Client ID / Account Email</label>
                <input
                  type="text"
                  placeholder="e.g. developer@monogoto.io"
                  value={providerForm.api_user}
                  onChange={(e) => setProviderForm({ ...providerForm, api_user: e.target.value })}
                  style={{ width: "100%", padding: "8px", marginTop: "4px" }}
                />
              </div>

              <div>
                <label>Password / Secret / API Key (Encrypted At Rest)</label>
                <input
                  type="password"
                  placeholder="Enter secret or key"
                  value={providerForm.api_key}
                  onChange={(e) => setProviderForm({ ...providerForm, api_key: e.target.value })}
                  style={{ width: "100%", padding: "8px", marginTop: "4px" }}
                />
              </div>
            </div>

            <div style={{ margin: "16px 0", padding: "14px", background: "rgba(59, 130, 246, 0.05)", borderRadius: "var(--radius-md)", border: "1px solid rgba(59, 130, 246, 0.2)" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
                <h4 style={{ margin: 0, fontSize: "14px", color: "var(--primary)" }}>📈 % Pricing & Wholesale Cost Configuration</h4>
                <span style={{ fontSize: "11px", fontWeight: 700, padding: "2px 8px", borderRadius: "10px", background: "rgba(34, 197, 94, 0.15)", color: "var(--success)" }}>
                  NO FIXED BASE AMOUNT
                </span>
              </div>
              <p className="muted" style={{ fontSize: "12px", margin: "0 0 12px 0" }}>
                Clients are charged purely based on carrier wholesale usage + Admin Markup %. Configure wholesale cost billed by this SIM provider:
              </p>

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px", marginBottom: "12px" }}>
                <div>
                  <label style={{ fontSize: "12px", fontWeight: 600 }}>Admin Markup Percentage (%)</label>
                  <div style={{ display: "flex", alignItems: "center", gap: "6px", marginTop: "4px" }}>
                    <input
                      type="number"
                      step="0.5"
                      min="0"
                      max="500"
                      required
                      value={providerForm.markup_percentage ?? 20.0}
                      onChange={(e) => setProviderForm({ ...providerForm, markup_percentage: parseFloat(e.target.value) || 0 })}
                      style={{ width: "100%", padding: "8px" }}
                    />
                    <span style={{ fontWeight: 700, color: "var(--primary)" }}>%</span>
                  </div>
                </div>

                <div>
                  <label style={{ fontSize: "12px", fontWeight: 600 }}>Wholesale Cost per MB ($)</label>
                  <input
                    type="number"
                    step="0.001"
                    min="0"
                    required
                    value={providerForm.cost_per_mb ?? 0.03}
                    onChange={(e) => setProviderForm({ ...providerForm, cost_per_mb: parseFloat(e.target.value) || 0 })}
                    style={{ width: "100%", padding: "8px", marginTop: "4px" }}
                  />
                </div>
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px", marginBottom: "12px" }}>
                <div>
                  <label style={{ fontSize: "12px", fontWeight: 600 }}>Wholesale Cost per Active SIM ($ / mo)</label>
                  <input
                    type="number"
                    step="0.05"
                    min="0"
                    required
                    value={providerForm.cost_per_sim ?? 1.00}
                    onChange={(e) => setProviderForm({ ...providerForm, cost_per_sim: parseFloat(e.target.value) || 0 })}
                    style={{ width: "100%", padding: "8px", marginTop: "4px" }}
                  />
                </div>

                <div>
                  <label style={{ fontSize: "12px", fontWeight: 600 }}>Wholesale Cost per SMS ($)</label>
                  <input
                    type="number"
                    step="0.001"
                    min="0"
                    required
                    value={providerForm.cost_per_sms ?? 0.01}
                    onChange={(e) => setProviderForm({ ...providerForm, cost_per_sms: parseFloat(e.target.value) || 0 })}
                    style={{ width: "100%", padding: "8px", marginTop: "4px" }}
                  />
                </div>
              </div>

              <div style={{ background: "var(--surface)", padding: "10px", borderRadius: "var(--radius-sm)", border: "1px dashed var(--border)", fontSize: "12px" }}>
                <span style={{ fontWeight: 600, color: "var(--text)" }}>Preview Effective Client Rates: </span>
                <span style={{ color: "var(--primary)", fontWeight: 700 }}>
                  ${((providerForm.cost_per_mb ?? 0.03) * (1 + (providerForm.markup_percentage ?? 20) / 100)).toFixed(3)}/MB
                </span>
                {" · "}
                <span style={{ color: "var(--primary)", fontWeight: 700 }}>
                  ${((providerForm.cost_per_sim ?? 1.00) * (1 + (providerForm.markup_percentage ?? 20) / 100)).toFixed(2)}/active SIM
                </span>
                {" · "}
                <span style={{ color: "var(--primary)", fontWeight: 700 }}>
                  ${((providerForm.cost_per_sms ?? 0.01) * (1 + (providerForm.markup_percentage ?? 20) / 100)).toFixed(3)}/SMS
                </span>
              </div>
            </div>

            <div style={{ display: "flex", gap: "20px", margin: "16px 0" }}>
              <label style={{ display: "flex", alignItems: "center", gap: "6px", cursor: "pointer" }}>
                <input
                  type="checkbox"
                  checked={providerForm.is_sandbox}
                  onChange={(e) => setProviderForm({ ...providerForm, is_sandbox: e.target.checked })}
                />
                Sandbox / Simulation Mode
              </label>

              <label style={{ display: "flex", alignItems: "center", gap: "6px", cursor: "pointer" }}>
                <input
                  type="checkbox"
                  checked={providerForm.is_enabled}
                  onChange={(e) => setProviderForm({ ...providerForm, is_enabled: e.target.checked })}
                />
                Enabled
              </label>
            </div>

            <div className="muted" style={{ fontSize: "12px", marginBottom: "16px", background: "var(--surface-2)", padding: "10px", borderRadius: "var(--radius-sm)" }}>
              🔒 <strong>Security Guarantee:</strong> All credentials and API endpoints are saved in the dedicated PostgreSQL <code>billing</code> database with application-level AES-256 authenticated encryption.
            </div>

            <div style={{ display: "flex", justifyContent: "flex-end", gap: "8px" }}>
              <button type="button" className="secondary-button" onClick={() => setShowAddProviderModal(false)}>
                Cancel
              </button>
              <button type="submit" className="primary-button">
                Save Network Provider
              </button>
            </div>
          </form>
        </Modal>
      )}

      {/* Edit Network Provider Modal */}
      {editingProvider && (
        <Modal
          title={`Edit Provider: ${editingProvider.name}`}
          subtitle={`Update API endpoints and encrypted credentials for ${editingProvider.provider_code}.`}
          onClose={() => setEditingProvider(null)}
        >
          <form onSubmit={handleUpdateProvider}>
            <div style={{ marginBottom: "14px" }}>
              <label>Provider Name</label>
              <input
                type="text"
                required
                value={editingProvider.name}
                onChange={(e) => setEditingProvider({ ...editingProvider, name: e.target.value })}
                style={{ width: "100%", padding: "8px", marginTop: "4px" }}
              />
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: "12px", marginBottom: "14px" }}>
              <div>
                <label>API Base URL</label>
                <input
                  type="url"
                  required
                  value={editingProvider.base_url}
                  onChange={(e) => setEditingProvider({ ...editingProvider, base_url: e.target.value })}
                  style={{ width: "100%", padding: "8px", marginTop: "4px" }}
                />
              </div>

              <div>
                <label>Auth Type</label>
                <select
                  value={editingProvider.auth_type}
                  onChange={(e) => setEditingProvider({ ...editingProvider, auth_type: e.target.value })}
                  style={{ width: "100%", padding: "8px", marginTop: "4px" }}
                >
                  <option value="bearer_token">Bearer Token (JWT)</option>
                  <option value="oauth2">OAuth 2.0 (Client Secret)</option>
                  <option value="api_key">API Key Header</option>
                  <option value="basic_auth">Basic Auth</option>
                </select>
              </div>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px", marginBottom: "14px" }}>
              <div>
                <label>Account Username / User</label>
                <input
                  type="text"
                  value={editingProvider.api_user || ""}
                  onChange={(e) => setEditingProvider({ ...editingProvider, api_user: e.target.value })}
                  style={{ width: "100%", padding: "8px", marginTop: "4px" }}
                />
              </div>

              <div>
                <label>Password / Secret (Leave blank to keep current)</label>
                <input
                  type="password"
                  placeholder="••••••••••••"
                  value={editingProvider.api_key || ""}
                  onChange={(e) => setEditingProvider({ ...editingProvider, api_key: e.target.value })}
                  style={{ width: "100%", padding: "8px", marginTop: "4px" }}
                />
              </div>
            </div>

            <div style={{ margin: "16px 0", padding: "14px", background: "rgba(59, 130, 246, 0.05)", borderRadius: "var(--radius-md)", border: "1px solid rgba(59, 130, 246, 0.2)" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
                <h4 style={{ margin: 0, fontSize: "14px", color: "var(--primary)" }}>📈 % Pricing & Wholesale Cost Configuration</h4>
                <span style={{ fontSize: "11px", fontWeight: 700, padding: "2px 8px", borderRadius: "10px", background: "rgba(34, 197, 94, 0.15)", color: "var(--success)" }}>
                  NO FIXED BASE AMOUNT
                </span>
              </div>
              <p className="muted" style={{ fontSize: "12px", margin: "0 0 12px 0" }}>
                Update carrier wholesale rates billed by this provider and the Admin markup margin percentage:
              </p>

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px", marginBottom: "12px" }}>
                <div>
                  <label style={{ fontSize: "12px", fontWeight: 600 }}>Admin Markup Percentage (%)</label>
                  <div style={{ display: "flex", alignItems: "center", gap: "6px", marginTop: "4px" }}>
                    <input
                      type="number"
                      step="0.5"
                      min="0"
                      max="500"
                      required
                      value={editingProvider.markup_percentage ?? 20.0}
                      onChange={(e) => setEditingProvider({ ...editingProvider, markup_percentage: parseFloat(e.target.value) || 0 })}
                      style={{ width: "100%", padding: "8px" }}
                    />
                    <span style={{ fontWeight: 700, color: "var(--primary)" }}>%</span>
                  </div>
                </div>

                <div>
                  <label style={{ fontSize: "12px", fontWeight: 600 }}>Wholesale Cost per MB ($)</label>
                  <input
                    type="number"
                    step="0.001"
                    min="0"
                    required
                    value={editingProvider.cost_per_mb ?? 0.03}
                    onChange={(e) => setEditingProvider({ ...editingProvider, cost_per_mb: parseFloat(e.target.value) || 0 })}
                    style={{ width: "100%", padding: "8px", marginTop: "4px" }}
                  />
                </div>
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px", marginBottom: "12px" }}>
                <div>
                  <label style={{ fontSize: "12px", fontWeight: 600 }}>Wholesale Cost per Active SIM ($ / mo)</label>
                  <input
                    type="number"
                    step="0.05"
                    min="0"
                    required
                    value={editingProvider.cost_per_sim ?? 1.00}
                    onChange={(e) => setEditingProvider({ ...editingProvider, cost_per_sim: parseFloat(e.target.value) || 0 })}
                    style={{ width: "100%", padding: "8px", marginTop: "4px" }}
                  />
                </div>

                <div>
                  <label style={{ fontSize: "12px", fontWeight: 600 }}>Wholesale Cost per SMS ($)</label>
                  <input
                    type="number"
                    step="0.001"
                    min="0"
                    required
                    value={editingProvider.cost_per_sms ?? 0.01}
                    onChange={(e) => setEditingProvider({ ...editingProvider, cost_per_sms: parseFloat(e.target.value) || 0 })}
                    style={{ width: "100%", padding: "8px", marginTop: "4px" }}
                  />
                </div>
              </div>

              <div style={{ background: "var(--surface)", padding: "10px", borderRadius: "var(--radius-sm)", border: "1px dashed var(--border)", fontSize: "12px" }}>
                <span style={{ fontWeight: 600, color: "var(--text)" }}>Preview Effective Client Rates: </span>
                <span style={{ color: "var(--primary)", fontWeight: 700 }}>
                  ${((editingProvider.cost_per_mb ?? 0.03) * (1 + (editingProvider.markup_percentage ?? 20) / 100)).toFixed(3)}/MB
                </span>
                {" · "}
                <span style={{ color: "var(--primary)", fontWeight: 700 }}>
                  ${((editingProvider.cost_per_sim ?? 1.00) * (1 + (editingProvider.markup_percentage ?? 20) / 100)).toFixed(2)}/active SIM
                </span>
                {" · "}
                <span style={{ color: "var(--primary)", fontWeight: 700 }}>
                  ${((editingProvider.cost_per_sms ?? 0.01) * (1 + (editingProvider.markup_percentage ?? 20) / 100)).toFixed(3)}/SMS
                </span>
              </div>
            </div>

            <div style={{ display: "flex", gap: "20px", margin: "16px 0" }}>
              <label style={{ display: "flex", alignItems: "center", gap: "6px", cursor: "pointer" }}>
                <input
                  type="checkbox"
                  checked={editingProvider.is_sandbox}
                  onChange={(e) => setEditingProvider({ ...editingProvider, is_sandbox: e.target.checked })}
                />
                Sandbox Mode
              </label>

              <label style={{ display: "flex", alignItems: "center", gap: "6px", cursor: "pointer" }}>
                <input
                  type="checkbox"
                  checked={editingProvider.is_enabled}
                  onChange={(e) => setEditingProvider({ ...editingProvider, is_enabled: e.target.checked })}
                />
                Enabled
              </label>
            </div>

            <div style={{ display: "flex", justifyContent: "flex-end", gap: "8px" }}>
              <button type="button" className="secondary-button" onClick={() => setEditingProvider(null)}>
                Cancel
              </button>
              <button type="submit" className="primary-button">
                Update Provider
              </button>
            </div>
          </form>
        </Modal>
      )}
    </div>
  );
}
