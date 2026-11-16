with open('frontend/src/billing.jsx', 'r', encoding='utf-8') as f:
    code = f.read()

# 1. Update providerForm state and add globalMarkupPct
old_form_state = """  const [providerForm, setProviderForm] = useState({
    name: "Monogoto Global Cellular",
    provider_code: "monogoto",
    provider_type: "monogoto",
    base_url: "https://api.monogoto.io",
    auth_type: "bearer_token",
    api_user: "",
    api_key: "",
    is_sandbox: true,
    is_enabled: true,
  });"""

new_form_state = """  const [providerForm, setProviderForm] = useState({
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
  const [savingMarkup, setSavingMarkup] = useState(false);"""

assert old_form_state in code, "old_form_state not found"
code = code.replace(old_form_state, new_form_state)

# 2. Update loadAll to setGlobalMarkupPct
old_load_all = """      setSubscription(subData);
      setUsage(usageData);"""

new_load_all = """      setSubscription(subData);
      setUsage(usageData);
      if (usageData?.markup_percentage) {
        setGlobalMarkupPct(usageData.markup_percentage);
      }"""

assert old_load_all in code, "old_load_all not found"
code = code.replace(old_load_all, new_load_all)

# 3. Add handleUpdateGlobalMarkup and update handleCreateProvider / handleUpdateProvider
old_create_update = """  async function handleCreateProvider(event) {
    event.preventDefault();
    try {
      await api.post("/network/providers", providerForm);
      setShowAddProviderModal(false);
      setNotice({ type: "success", text: `Network Provider '${providerForm.name}' successfully added!` });
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
        is_sandbox: editingProvider.is_sandbox,
        is_enabled: editingProvider.is_enabled,
      });
      setEditingProvider(null);
      setNotice({ type: "success", text: `Provider '${editingProvider.name}' updated!` });
      loadAll();
    } catch (err) {
      setNotice({ type: "error", text: err.message });
    }
  }"""

new_create_update = """  async function handleUpdateGlobalMarkup(event) {
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
  }"""

assert old_create_update in code, "old_create_update not found"
code = code.replace(old_create_update, new_create_update)

with open('frontend/src/billing.jsx', 'w', encoding='utf-8') as f:
    f.write(code)

print("Stage 1 of billing.jsx updated successfully!")
