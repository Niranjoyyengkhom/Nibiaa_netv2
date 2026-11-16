with open('frontend/src/billing.jsx', 'r', encoding='utf-8') as f:
    code = f.read()

# 1. Admin markup banner
old_overview_top = """      {activeTab === "overview" && (
        <div className="overview-section">
          {/* Active Subscription Banner */}"""

new_overview_top = """      {activeTab === "overview" && (
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

          {/* Active Subscription Banner */}"""

assert old_overview_top in code, "old_overview_top not found"
code = code.replace(old_overview_top, new_overview_top)

# 2. Update usage stat grid
old_stat_start = code.find('{/* Usage Metering Stats */}')
old_stat_end = code.find('{/* Available Plans Catalog */}', old_stat_start)
old_stat_grid = code[old_stat_start:old_stat_end]

new_stat_grid = """{/* Usage Metering Stats */}
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

          """

code = code[:old_stat_start] + new_stat_grid + code[old_stat_end:]

# 3. Update plans display
plan_price_start = code.find('<div style={{ fontSize: "28px", fontWeight: "800"')
plan_price_end = code.find('</ul>', plan_price_start) + len('</ul>')
old_plan_price = code[plan_price_start:plan_price_end]

new_plan_price = """<div style={{ fontSize: "28px", fontWeight: "800", color: "var(--text)" }}>
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
                    </ul>"""

code = code[:plan_price_start] + new_plan_price + code[plan_price_end:]

with open('frontend/src/billing.jsx', 'w', encoding='utf-8') as f:
    f.write(code)

print("Stage 2 updated successfully!")
