import { useCallback, useEffect, useMemo, useState } from "react";
import "./style.css";
import { createRoot } from "react-dom/client";

import { API, createApi, errorMessage } from "./api";
import { clearDrafts, ErrorBoundary, Modal, Notice } from "./components";
import { Icon } from "./icons";
import Notifications from "./notifications";
import Devices from "./devices";
import Users from "./users";
import Tenants from "./tenants";
import CollaboratorRoles from "./roles";
import Attributes from "./attributes";
import Applications from "./applications";
import Decoders from "./decoders";
import Telemetry from "./telemetry";
import Connectivity from "./connectivity";
import Integration from "./integration";
import IngestionProfiles from "./ingestionProfiles";
import DeviceConfiguration from "./configuration";
import Account from "./account";
import AuditLogs from "./auditLogs";
import Billing from "./billing";


// Sidebar: numbered sections, numbered by what the user can see
const NAV_SECTIONS = [
  {
    title: "Application",
    items: [
      { key: "applications", label: "Applications" },
      { key: "devices", label: "Devices (by Types)" },
      { key: "decoders", label: "Decoder" },
      { key: "telemetry", label: "Live Data" },
    ],
  },
  {
    title: "Connectivity Profile",
    items: [
      { key: "connectivity", label: "Network Profiles" },
      { key: "ingestion-profiles", label: "Ingestion Profile" },
      { key: "integration", label: "Integration Protocol" },
    ],
  },
  {
    title: "Users Management",
    items: [
      { key: "users", label: "User Management" },
      { key: "tenants", label: "Workspaces" },
      { key: "roles", label: "Role Management" },
      { key: "attributes", label: "Attribute & ABAC" },
      { key: "audit-logs", label: "Audit & Logs" },
    ],
  },
  {
    title: "Platform",
    items: [
      {
        key: "satellite-pass",
        label: "Satellite Pass Prediction",
        comingSoon: true,
      },
      {
        key: "billing",
        label: "Billing & Subscription",
      },
    ],
  },
];

// Pages available to the global search
const CONSOLE_PAGES = [
  ...NAV_SECTIONS.flatMap((section) => section.items),
  { key: "account", label: "My Account" },
];

// Header breadcrumb and browser tab title of each page
const PAGE_TITLES = {
  devices: "Devices",
  applications: "Applications",
  decoders: "Decoders",
  telemetry: "Live Data",
  connectivity: "Network Profiles",
  "ingestion-profiles": "Ingestion Profile",
  integration: "Integration Protocol",
  users: "User Management",
  tenants: "Workspaces",
  roles: "Role Management",
  attributes: "Attribute & ABAC Management",
  "audit-logs": "Audit & Logs",
  configuration: "Device Configuration",
  account: "My Account",
  billing: "Billing & Subscriptions",
};

function sectionOf(page) {
  return NAV_SECTIONS.find((section) =>
    section.items.some((item) => item.key === page)
  )?.title || (page === "configuration" ? "Application" : "Account");
}


// Which sidebar pages a user can open, based on their permissions.
function visiblePages(user) {
  const p = user.permissions || {};
  const c = user.capabilities || {};

  return {
    devices: true,
    applications:
      c.create_application ||
      p.manage_application ||
      p.read_application_traffic ||
      p.create_devices ||
      p.manage_devices,
    decoders: p.create_decoder || p.manage_decoder,
    telemetry:
      p.read_application_traffic || c.view_usage || c.use_ingestion,
    users: c.manage_users,
    tenants: c.manage_organizations,
    roles: c.manage_collaborator_roles,
    attributes: user.role === "admin" || user.role === "owner" || c.manage_users,
    "audit-logs": user.role === "admin" || user.role === "owner" || c.manage_users,
    connectivity: true,
    "ingestion-profiles": true,
    integration: true,
    account: true,
    billing: true,
  };
}


function ThemeIcon({ theme }) {
  return <Icon name={theme === "dark" ? "sun" : "moon"} size={18} />;
}


function WorkspaceModal({
  api,
  currentUser,
  activeWorkspace,
  onSelectWorkspace,
  onNavigate,
  onClose,
}) {
  const isAdmin = currentUser.role === "admin";
  const [tenants, setTenants] = useState([]);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState(null);

  // Creation form state
  const [showCreate, setShowCreate] = useState(false);
  const [name, setName] = useState("");
  const [type, setType] = useState("workspace");
  const [creating, setCreating] = useState(false);

  const fetchTenants = useCallback(async () => {
    try {
      setLoading(true);
      const res = await api.get("/tenants/");
      setTenants(res);
    } catch (e) {
      setNotice({ type: "error", text: e.message || "Failed to load workspaces" });
    } finally {
      setLoading(false);
    }
  }, [api]);

  useEffect(() => {
    fetchTenants();
  }, [fetchTenants]);

  async function handleCreate(e) {
    e.preventDefault();
    if (!name.trim()) return;
    setCreating(true);
    setNotice(null);
    try {
      const created = await api.post("/tenants/", {
        name: name.trim(),
        type,
      });
      setNotice({ type: "success", text: `Workspace "${created.name}" created successfully!` });
      setName("");
      setShowCreate(false);
      await fetchTenants();
      onSelectWorkspace({ id: created.id, name: created.name });
    } catch (err) {
      setNotice({ type: "error", text: err.message || "Failed to create workspace" });
    } finally {
      setCreating(false);
    }
  }

  return (
    <Modal
      title="Workspaces"
      subtitle="Switch between workspaces or create a new one"
      onClose={onClose}
      wide
      footer={
        <div style={{ display: "flex", justifyContent: "space-between", width: "100%", alignItems: "center" }}>
          {isAdmin && (
            <button
              type="button"
              className="text-button"
              style={{ fontSize: "0.85rem", color: "var(--primary-text)", background: "transparent", border: "none", cursor: "pointer", textDecoration: "underline" }}
              onClick={() => {
                onClose();
                onNavigate("tenants");
              }}
            >
              Open Workspaces Page →
            </button>
          )}
          <button type="button" className="secondary-button" onClick={onClose} style={{ marginLeft: "auto" }}>
            Close
          </button>
        </div>
      }
    >
      <Notice notice={notice} />

      {/* Top Action Bar */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px" }}>
        <span style={{ fontSize: "0.85rem", color: "var(--muted)" }}>
          {loading ? "Loading workspaces..." : `${tenants.length + (isAdmin ? 1 : 0)} workspace(s) available`}
        </span>
        {isAdmin && !showCreate && (
          <button
            type="button"
            className="primary-button small"
            onClick={() => setShowCreate(true)}
            style={{ display: "inline-flex", alignItems: "center", gap: "6px" }}
          >
            <span>+</span> Create Workspace
          </button>
        )}
      </div>

      {/* Create Workspace Inline Form */}
      {showCreate && (
        <form
          onSubmit={handleCreate}
          style={{
            background: "var(--surface-2)",
            border: "1px solid var(--border)",
            borderRadius: "var(--radius)",
            padding: "16px",
            marginBottom: "20px",
          }}
        >
          <h4 style={{ margin: "0 0 12px 0", fontSize: "0.95rem" }}>Create New Workspace</h4>
          <div className="form-grid" style={{ gridTemplateColumns: "1fr 1fr", gap: "12px", marginBottom: "12px" }}>
            <div className="form-group">
              <label>Workspace Name</label>
              <input
                type="text"
                placeholder="e.g. Smart City, Logistics Fleet"
                value={name}
                onChange={(e) => setName(e.target.value)}
                autoFocus
                required
              />
            </div>
            <div className="form-group">
              <label>Workspace Type</label>
              <select value={type} onChange={(e) => setType(e.target.value)}>
                <option value="workspace">Workspace</option>
                <option value="organization">Organization</option>
                <option value="team">Team</option>
                <option value="individual">Individual</option>
              </select>
            </div>
          </div>
          <div style={{ display: "flex", gap: "8px" }}>
            <button type="submit" className="primary-button small" disabled={creating || !name.trim()}>
              {creating ? "Creating..." : "Create Workspace"}
            </button>
            <button
              type="button"
              className="secondary-button small"
              onClick={() => {
                setShowCreate(false);
                setName("");
              }}
            >
              Cancel
            </button>
          </div>
        </form>
      )}

      {/* Workspace List */}
      <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
        {isAdmin && (
          <div
            onClick={() => {
              onSelectWorkspace(null);
              onClose();
            }}
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              padding: "12px 16px",
              borderRadius: "var(--radius)",
              border: activeWorkspace === null ? "1px solid var(--primary)" : "1px solid var(--border)",
              background: activeWorkspace === null ? "var(--primary-soft)" : "var(--surface-2)",
              cursor: "pointer",
              transition: "all 0.15s ease",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
              <span
                style={{
                  width: "10px",
                  height: "10px",
                  borderRadius: "50%",
                  background: activeWorkspace === null ? "var(--primary)" : "var(--muted)",
                }}
              />
              <div>
                <strong style={{ fontSize: "0.95rem", display: "block" }}>Platform (Global Admin)</strong>
                <span style={{ fontSize: "0.78rem", color: "var(--muted)" }}>
                  Global scope across all workspaces, devices, and applications
                </span>
              </div>
            </div>
            {activeWorkspace === null ? (
              <span className="pill pill-ok" style={{ fontSize: "0.75rem" }}>Active</span>
            ) : (
              <button type="button" className="secondary-button small">Select</button>
            )}
          </div>
        )}

        {tenants.map((t) => {
          const isActive = activeWorkspace && activeWorkspace.id === t.id;
          return (
            <div
              key={t.id}
              onClick={() => {
                onSelectWorkspace({ id: t.id, name: t.name });
                onClose();
              }}
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                padding: "12px 16px",
                borderRadius: "var(--radius)",
                border: isActive ? "1px solid var(--primary)" : "1px solid var(--border)",
                background: isActive ? "var(--primary-soft)" : "var(--surface-2)",
                cursor: "pointer",
                transition: "all 0.15s ease",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
                <span
                  style={{
                    width: "10px",
                    height: "10px",
                    borderRadius: "50%",
                    background: isActive ? "var(--success)" : "var(--muted)",
                  }}
                />
                <div>
                  <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                    <strong style={{ fontSize: "0.95rem" }}>{t.name}</strong>
                    <span className="pill" style={{ fontSize: "0.7rem", textTransform: "capitalize" }}>
                      {t.type}
                    </span>
                  </div>
                  <span style={{ fontSize: "0.78rem", color: "var(--muted)" }}>
                    {t.user_count || 0} user(s) · {t.application_count || 0} app(s) · {t.device_count || 0} device(s)
                  </span>
                </div>
              </div>
              {isActive ? (
                <span className="pill pill-ok" style={{ fontSize: "0.75rem" }}>Active</span>
              ) : (
                <button type="button" className="secondary-button small">Select</button>
              )}
            </div>
          );
        })}
      </div>
    </Modal>
  );
}


function App() {
  const [authToken, setAuthToken] = useState(
    () => sessionStorage.getItem("authToken") || localStorage.getItem("authToken")
  );

  const [currentUser, setCurrentUser] = useState(null);

  // Application selector shown in the Devices breadcrumb.
  const [headerApplications, setHeaderApplications] = useState([]);
  const [selectedHeaderApplication, setSelectedHeaderApplication] = useState("");

  // Console preferences.
  const [theme, setTheme] = useState(
    () => localStorage.getItem("nb-theme") || "dark"
  );

  const [navFilter, setNavFilter] = useState("");
  const [globalSearch, setGlobalSearch] = useState("");
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  // Workspace Switcher & Multi-Workspace state
  const [showWorkspaceModal, setShowWorkspaceModal] = useState(false);
  const [selectedWorkspace, setSelectedWorkspaceState] = useState(() => {
    try {
      const saved = localStorage.getItem("nb-workspace");
      return saved ? JSON.parse(saved) : null;
    } catch {
      return null;
    }
  });

  const setSelectedWorkspace = useCallback((ws) => {
    setSelectedWorkspaceState(ws);
    if (ws) {
      localStorage.setItem("nb-workspace", JSON.stringify(ws));
    } else {
      localStorage.removeItem("nb-workspace");
    }
  }, []);

  const [route, setRoute] = useState({
    page: "devices",
    params: {},
  });

  // Login state.
  const [loginName, setLoginName] = useState("");
  const [loginPassword, setLoginPassword] = useState("");
  const [loginError, setLoginError] = useState("");
  const [loginLoading, setLoginLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [authError, setAuthError] = useState("");

  // Auth mode: "login" | "signup" | "activate"
  const [authMode, setAuthMode] = useState("login");

  // Signup state
  const [signupLevel, setSignupLevel] = useState("individual"); // "individual" | "organization"
  const [signupName, setSignupName] = useState("");
  const [signupEmail, setSignupEmail] = useState("");
  const [signupOrgName, setSignupOrgName] = useState("");
  const [signupPassword, setSignupPassword] = useState("");
  const [signupConfirmPassword, setSignupConfirmPassword] = useState("");
  const [signupError, setSignupError] = useState("");
  const [signupLoading, setSignupLoading] = useState(false);
  const [showSignupPassword, setShowSignupPassword] = useState(false);

  // Activation state
  const [activationEmail, setActivationEmail] = useState("");
  const [activationCode, setActivationCode] = useState("");
  const [activationError, setActivationError] = useState("");
  const [activationSuccess, setActivationSuccess] = useState("");
  const [activationLoading, setActivationLoading] = useState(false);
  const [resendLoading, setResendLoading] = useState(false);
  const [resendMessage, setResendMessage] = useState("");
  const [devCodeHint, setDevCodeHint] = useState("");

  // Forgot password & account recovery state
  const [forgotEmail, setForgotEmail] = useState("");
  const [forgotCode, setForgotCode] = useState("");
  const [forgotToken, setForgotToken] = useState("");
  const [forgotNewPassword, setForgotNewPassword] = useState("");
  const [forgotConfirmPassword, setForgotConfirmPassword] = useState("");
  const [showForgotNewPassword, setShowForgotNewPassword] = useState(false);
  const [forgotLoading, setForgotLoading] = useState(false);
  const [forgotError, setForgotError] = useState("");
  const [forgotSuccess, setForgotSuccess] = useState("");
  const [forgotDevCodeHint, setForgotDevCodeHint] = useState("");

  const signOut = useCallback((reason = "") => {
    sessionStorage.removeItem("authToken");
    localStorage.removeItem("authToken");
    clearDrafts();

    setSelectedWorkspace(null);
    setShowWorkspaceModal(false);
    setAuthToken(null);
    setCurrentUser(null);
    setAuthError("");
    setHeaderApplications([]);
    setSelectedHeaderApplication("");
    setLoginPassword("");
    setLoginError(reason);
    setAuthMode("login");
    setSignupError("");
    setActivationError("");
    setActivationSuccess("");
    setResendMessage("");
    setForgotError("");
    setForgotSuccess("");
    setForgotCode("");
    setForgotToken("");
    setForgotNewPassword("");
    setForgotConfirmPassword("");
    setForgotDevCodeHint("");
    setRoute({ page: "devices", params: {} });
    setGlobalSearch("");
    setNavFilter("");
    setMobileNavOpen(false);
  }, [setSelectedWorkspace]);

  const api = useMemo(
    () => (authToken ? createApi(authToken, signOut) : null),
    [authToken, signOut]
  );

  const isAdmin = currentUser?.role === "admin";

  const effectiveCurrentUser = useMemo(() => {
    if (!currentUser) return null;
    // Admin has no org or workspace
    if (currentUser.role === "admin") {
      return currentUser;
    }
    if (!selectedWorkspace) return currentUser;
    return {
      ...currentUser,
      tenant_id: selectedWorkspace.id,
      tenant_name: selectedWorkspace.name,
    };
  }, [currentUser, selectedWorkspace]);

  const activeWorkspaceName = selectedWorkspace
    ? selectedWorkspace.name
    : currentUser?.tenant_name || "";

  const currentOrgName = isAdmin
    ? "NibiaaNet"
    : (effectiveCurrentUser?.tenant_name || currentUser?.tenant_name || "NibiaaNet");

  const currentOrgSubtitle = isAdmin
    ? "Network Management Platform"
    : `${currentOrgName} IoT Platform`;

  // Load the authenticated user from the existing backend.
  const refreshMe = useCallback(async () => {
    if (!api) {
      return;
    }

    try {
      setAuthError("");
      setCurrentUser(await api.get("/auth/me"));
    } catch (error) {
      if (error.status === 401) {
        signOut("Your session has expired. Please sign in again.");
      } else {
        setAuthError(error.message || "Failed to load account.");
        console.error("Failed to load user account:", error);
      }
    }
  }, [api, signOut]);

  useEffect(() => {
    refreshMe();
  }, [refreshMe, route]);

  // Set active UI class on body for UI-specific styling (excluding login screen)
  useEffect(() => {
    if (authToken && currentUser) {
      document.body.classList.add("app-ui-active");
      document.body.classList.remove("login-ui-active");
    } else {
      document.body.classList.add("login-ui-active");
      document.body.classList.remove("app-ui-active");
    }
  }, [authToken, currentUser]);

  // Auto-activation listener on URL query parameters (?activate_token=... or ?activate_email=...)
  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    const token = params.get("activate_token");
    const email = params.get("activate_email");
    const code = params.get("activate_code");

    if (email) {
      setActivationEmail(email);
    }
    if (code) {
      setActivationCode(code);
    }

    if (token) {
      setAuthMode("activate");
      setActivationLoading(true);
      setActivationError("");
      setActivationSuccess("Verifying activation link...");

      fetch(`${API}/auth/activate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token }),
      })
        .then(async (res) => {
          const data = await res.json();
          if (!res.ok) {
            throw new Error(errorMessage(data, "Invalid or expired activation link."));
          }
          if (data.access_token) {
            sessionStorage.setItem("authToken", data.access_token);
            localStorage.removeItem("authToken");
            setAuthToken(data.access_token);
            setRoute({ page: "devices", params: {} });
            window.history.replaceState({}, document.title, window.location.pathname);
          } else {
            setActivationSuccess(data.message || "Account activated! You can now sign in.");
            setAuthMode("login");
          }
        })
        .catch((err) => {
          setActivationError(err.message || "Activation link is invalid or expired.");
          setActivationSuccess("");
        })
        .finally(() => {
          setActivationLoading(false);
        });
    } else if (email || code) {
      setAuthMode("activate");
    }

    // Password reset URL query parameters (?reset_token=... or ?reset_email=... or ?reset_code=...)
    const resetToken = params.get("reset_token");
    const resetEmail = params.get("reset_email");
    const resetCode = params.get("reset_code");

    if (resetEmail) {
      setForgotEmail(resetEmail);
    }
    if (resetToken) {
      setForgotToken(resetToken);
      setAuthMode("forgot_reset");
      setForgotSuccess("Recovery link verified. Please enter your new password below.");
    } else if (resetCode) {
      setForgotCode(resetCode);
      setAuthMode("forgot_reset");
    }
  }, []);



  // Load applications available to the signed-in user for the breadcrumb dropdown.
  useEffect(() => {
    if (!api) {
      setHeaderApplications([]);
      setSelectedHeaderApplication("");
      return;
    }

    api.get("/applications/")
      .then((applications) => setHeaderApplications(applications))
      .catch((error) => {
        console.error("Failed to load applications for the header:", error);
        setHeaderApplications([]);
      });
  }, [api]);

  // Apply and persist the selected theme.
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.documentElement.setAttribute("data-theme", theme);
    document.documentElement.style.colorScheme = theme;
    if (document.body) {
      document.body.dataset.theme = theme;
      document.body.setAttribute("data-theme", theme);
    }
    localStorage.setItem("nb-theme", theme);
  }, [theme]);

  // Browser tab title
  useEffect(() => {
    const org = currentUser?.role === "admin"
      ? "NibiaaNet"
      : (currentUser?.tenant_name || selectedWorkspace?.name || "NibiaaNet");
    const title = !authToken
      ? "Sign in"
      : PAGE_TITLES[route.page] || "Devices";

    document.title = `${title} · ${org} Console`;
  }, [authToken, route.page, currentUser, selectedWorkspace]);

  // The mobile navigation closes when the window grows to desktop width
  useEffect(() => {
    const query = window.matchMedia("(min-width: 1025px)");
    const onChange = () => query.matches && setMobileNavOpen(false);

    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, []);

  function navigate(page, params = {}) {
    setRoute({ page, params });
    window.scrollTo(0, 0);
  }

  // Navigate from search/sidebar and close mobile navigation.
  function navigateToPage(target) {
    navigate(target);
    setGlobalSearch("");
    setNavFilter("");
    setMobileNavOpen(false);
  }

  function toggleTheme() {
    setTheme((current) => (current === "dark" ? "light" : "dark"));
  }

  // -------------------------
  // Login
  // -------------------------

  async function login(event) {
    event.preventDefault();

    setLoginError("");
    setLoginLoading(true);

    try {
      const response = await fetch(`${API}/auth/login`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          name: loginName,
          email: loginName,
          identifier: loginName,
          password: loginPassword,
        }),
      });

      let data = null;
      try {
        data = await response.json();
      } catch {
        data = null;
      }

      if (!response.ok) {
        throw new Error(
          errorMessage(data, "Invalid email, username, or password")
        );
      }

      sessionStorage.setItem("authToken", data.access_token);
      localStorage.removeItem("authToken");

      setLoginPassword("");
      setRoute({ page: "devices", params: {} });
      setAuthToken(data.access_token);
    } catch (error) {
      setLoginError(
        error.message === "Failed to fetch"
          ? `Cannot reach the API at ${API}. Is the backend running?`
          : error.message
      );
    } finally {
      setLoginLoading(false);
    }
  }

  // -------------------------
  // Signup
  // -------------------------

  async function handleSignup(event) {
    event.preventDefault();
    setSignupError("");

    const name = signupName.trim();
    const email = signupEmail.trim().toLowerCase();
    const org = signupOrgName.trim();

    if (!name) {
      setSignupError("Please enter your full name.");
      return;
    }
    if (!email || !email.includes("@")) {
      setSignupError("Please enter a valid email address.");
      return;
    }
    if (signupLevel === "organization" && !org) {
      setSignupError("Please enter your organization name.");
      return;
    }
    if (signupPassword.length < 8) {
      setSignupError("Password must be at least 8 characters long.");
      return;
    }
    if (signupPassword !== signupConfirmPassword) {
      setSignupError("Passwords do not match.");
      return;
    }

    setSignupLoading(true);
    try {
      const response = await fetch(`${API}/auth/signup`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name,
          email,
          password: signupPassword,
          level: signupLevel,
          organization_name: signupLevel === "organization" ? org : null,
        }),
      });

      const data = await response.json();
      if (!response.ok) {
        throw new Error(errorMessage(data, "Registration failed"));
      }

      setActivationEmail(email);
      setActivationCode("");
      if (data.dev_code) {
        setDevCodeHint(data.dev_code);
      }
      setActivationSuccess(data.message || "Account registered! Please enter the activation code sent to your email.");
      setAuthMode("activate");
    } catch (err) {
      setSignupError(
        err.message === "Failed to fetch"
          ? `Cannot reach backend at ${API}. Please ensure the server is running.`
          : err.message
      );
    } finally {
      setSignupLoading(false);
    }
  }

  // -------------------------
  // Activation
  // -------------------------

  async function handleActivate(event) {
    event.preventDefault();
    setActivationError("");
    setResendMessage("");

    const code = activationCode.trim();
    const email = activationEmail.trim().toLowerCase();

    if (!code) {
      setActivationError("Please enter the 6-digit activation code.");
      return;
    }

    setActivationLoading(true);
    try {
      const response = await fetch(`${API}/auth/activate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          code,
          email: email || undefined,
        }),
      });

      const data = await response.json();
      if (!response.ok) {
        throw new Error(errorMessage(data, "Invalid or expired activation code."));
      }

      if (data.access_token) {
        sessionStorage.setItem("authToken", data.access_token);
        localStorage.removeItem("authToken");
        setAuthToken(data.access_token);
        setRoute({ page: "devices", params: {} });
      } else {
        setActivationSuccess("Account activated successfully! Please sign in.");
        setAuthMode("login");
      }
    } catch (err) {
      setActivationError(
        err.message === "Failed to fetch"
          ? `Cannot reach backend at ${API}. Please ensure the server is running.`
          : err.message
      );
    } finally {
      setActivationLoading(false);
    }
  }

  // -------------------------
  // Resend Activation
  // -------------------------

  async function handleResendActivation() {
    const email = activationEmail.trim().toLowerCase();
    if (!email) {
      setActivationError("Please enter your registered email address.");
      return;
    }

    setResendLoading(true);
    setResendMessage("");
    setActivationError("");
    try {
      const response = await fetch(`${API}/auth/resend-activation`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
      });

      const data = await response.json();
      if (!response.ok) {
        throw new Error(errorMessage(data, "Failed to resend activation email."));
      }

      setResendMessage(data.message || "Fresh activation code and link sent to your inbox!");
      if (data.dev_code) {
        setDevCodeHint(data.dev_code);
      }
    } catch (err) {
      setActivationError(err.message || "Failed to resend activation email.");
    } finally {
      setResendLoading(false);
    }
  }

  // -------------------------
  // Forgot / Reset Password
  // -------------------------

  async function handleForgotPasswordRequest(event) {
    if (event) event.preventDefault();
    setForgotError("");
    setForgotSuccess("");
    const email = forgotEmail.trim().toLowerCase();

    if (!email || !email.includes("@")) {
      setForgotError("Please enter a valid registered email address.");
      return;
    }

    setForgotLoading(true);

    try {
      const response = await fetch(`${API}/auth/forgot-password`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
      });

      const data = await response.json();
      if (!response.ok) {
        throw new Error(errorMessage(data, "Failed to send password recovery code."));
      }

      setForgotSuccess(data.message || "A 6-digit recovery code has been sent to your email.");
      if (data.dev_code) {
        setForgotDevCodeHint(data.dev_code);
      }
      setAuthMode("forgot_reset");
    } catch (err) {
      setForgotError(err.message || "Failed to request password reset.");
    } finally {
      setForgotLoading(false);
    }
  }

  async function handleResetPassword(event) {
    event.preventDefault();
    setForgotError("");
    setForgotSuccess("");

    const email = forgotEmail.trim().toLowerCase();
    const code = forgotCode.trim();

    if (!email || !email.includes("@")) {
      setForgotError("Please enter your registered email address.");
      return;
    }
    if (!forgotToken && (!code || code.length < 6)) {
      setForgotError("Please enter the 6-digit verification code sent to your email.");
      return;
    }
    if (forgotNewPassword.length < 8) {
      setForgotError("New password must be at least 8 characters long.");
      return;
    }
    if (forgotNewPassword !== forgotConfirmPassword) {
      setForgotError("Passwords do not match.");
      return;
    }

    setForgotLoading(true);

    try {
      const response = await fetch(`${API}/auth/reset-password`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email,
          code: code || undefined,
          token: forgotToken || undefined,
          new_password: forgotNewPassword,
        }),
      });

      const data = await response.json();
      if (!response.ok) {
        throw new Error(errorMessage(data, "Failed to reset password."));
      }

      // Success! Clear password fields and switch to login with email prefilled
      setLoginName(email);
      setLoginPassword("");
      setLoginError("");
      setForgotNewPassword("");
      setForgotConfirmPassword("");
      setForgotCode("");
      setForgotToken("");
      setForgotDevCodeHint("");
      setAuthMode("login");
      setForgotSuccess("Password reset successfully! Please sign in with your new password.");
    } catch (err) {
      setForgotError(err.message || "Failed to reset password.");
    } finally {
      setForgotLoading(false);
    }
  }

  // -------------------------
  // Login page
  // -------------------------

  if (!authToken) {
    return (
      <div className="login-screen">
        <section className="login-brand-panel">
          <div className="login-brand">
            <img
              src="/nibiaa-logo.png"
              alt="Nibiaa logo"
              className="login-logo"
            />

            <div>
              <h1>NibiaaNet</h1>
              <span>NETWORK CONSOLE</span>
            </div>
          </div>

          <div className="login-brand-content">
            <div className="login-eyebrow">
              <span className="login-status-dot" />
              IOT NETWORK MANAGEMENT
            </div>

            <h2>
              Connect your devices.
              <br />
              <span>Control your network.</span>
            </h2>

            <p>
              Manage devices, applications, connectivity, and live telemetry
              from one unified platform.
            </p>

            <div className="login-feature-list">
              <div className="login-feature">
                <span className="login-feature-icon"><Icon name="devices" size={20} /></span>
                <div>
                  <strong>Device Management</strong>
                  <p>Register NTN, TN, LoRa and BLE devices.</p>
                </div>
              </div>

              <div className="login-feature">
                <span className="login-feature-icon"><Icon name="telemetry" size={20} /></span>
                <div>
                  <strong>Live Telemetry</strong>
                  <p>Decode and monitor incoming device data.</p>
                </div>
              </div>

              <div className="login-feature">
                <span className="login-feature-icon"><Icon name="roles" size={20} /></span>
                <div>
                  <strong>Access Control</strong>
                  <p>Manage users, roles, and permissions.</p>
                </div>
              </div>
            </div>
          </div>

          <div className="login-brand-footer">
            <span>IoT Console</span>
            <span>IoT Network Server</span>
          </div>
        </section>

        <section className="login-form-panel">
          <button
            type="button"
            className="login-theme-toggle"
            onClick={toggleTheme}
            aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
            title={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
          >
            <ThemeIcon theme={theme} />
          </button>

          <div className="login-form-card">
            <div className="login-mobile-brand">
              <img src="/nibiaa-logo.png" alt="Logo" />
              <span>IoT Platform</span>
            </div>

            {/* Segmented Auth Switcher */}
            <div className="auth-mode-switch">
              <button
                type="button"
                className={`auth-mode-btn ${authMode === "login" ? "active" : ""}`}
                onClick={() => {
                  setAuthMode("login");
                  setLoginError("");
                }}
              >
                Sign In
              </button>
              <button
                type="button"
                className={`auth-mode-btn ${authMode === "signup" ? "active" : ""}`}
                onClick={() => {
                  setAuthMode("signup");
                  setSignupError("");
                }}
              >
                Create Account
              </button>
              {authMode === "activate" && (
                <button
                  type="button"
                  className="auth-mode-btn active"
                >
                  Verify Email
                </button>
              )}
              {(authMode === "forgot_request" || authMode === "forgot_reset") && (
                <button
                  type="button"
                  className="auth-mode-btn active"
                >
                  Reset Password
                </button>
              )}
            </div>

            {/* 1. SIGN IN MODE */}
            {authMode === "login" && (
              <>
                <div className="login-form-heading">
                  <span className="login-form-eyebrow">SECURE ACCESS</span>
                  <h2>Welcome back</h2>
                  <p>Sign in to access your organization console.</p>
                </div>

                <form onSubmit={login} className="login-form">
                  <div className="login-field">
                    <label htmlFor="login-name">Email or Username</label>
                    <input
                      id="login-name"
                      type="text"
                      placeholder="Enter your email or username (e.g. admin@nibiaa.com)"
                      value={loginName}
                      onChange={(event) => setLoginName(event.target.value)}
                      autoComplete="username"
                      required
                    />
                  </div>

                  <div className="login-field">
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "6px" }}>
                      <label htmlFor="login-password" style={{ margin: 0 }}>Password</label>
                      <button
                        type="button"
                        className="auth-link-btn"
                        style={{ fontSize: "12px", padding: 0 }}
                        onClick={() => {
                          setAuthMode("forgot_request");
                          setForgotEmail(loginName.includes("@") ? loginName : "");
                          setForgotError("");
                          setForgotSuccess("");
                        }}
                      >
                        Forgot password?
                      </button>
                    </div>
                    <div className="login-password-wrap">
                      <input
                        id="login-password"
                        type={showPassword ? "text" : "password"}
                        placeholder="Enter your password"
                        value={loginPassword}
                        onChange={(event) => setLoginPassword(event.target.value)}
                        autoComplete="current-password"
                        required
                      />
                      <button
                        type="button"
                        className="login-password-toggle"
                        onClick={() => setShowPassword((current) => !current)}
                        aria-label={showPassword ? "Hide password" : "Show password"}
                      >
                        {showPassword ? "Hide" : "Show"}
                      </button>
                    </div>
                  </div>

                  {forgotSuccess && authMode === "login" && (
                    <div className="auth-success-badge" role="status">
                      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <polyline points="20 6 9 17 4 12" />
                      </svg>
                      <p>{forgotSuccess}</p>
                    </div>
                  )}

                  {loginError && (
                    <div className="login-error" role="alert">
                      <span aria-hidden="true">!</span>
                      <p>{loginError}</p>
                    </div>
                  )}

                  <button
                    className="login-submit"
                    type="submit"
                    disabled={loginLoading}
                  >
                    <span>
                      {loginLoading ? "Signing in..." : "Sign in to Console"}
                    </span>
                    {!loginLoading && <span aria-hidden="true">→</span>}
                  </button>

                  <div className="auth-link-row">
                    <span style={{ color: "var(--muted)" }}>Received an activation code?</span>
                    <button
                      type="button"
                      className="auth-link-btn"
                      onClick={() => {
                        setAuthMode("activate");
                        setActivationError("");
                        setActivationSuccess("");
                      }}
                    >
                      Verify Account
                    </button>
                  </div>
                </form>
              </>
            )}
            {/* 2. SIGN UP MODE (Individual & Organization Levels) */}
            {authMode === "signup" && (
              <>
                <div className="login-form-heading">
                  <span className="login-form-eyebrow">SELF-REGISTRATION</span>
                  <h2>Get started</h2>
                  <p>Choose your workspace type to register your account.</p>
                </div>

                <form onSubmit={handleSignup} className="login-form">
                  <div className="login-field">
                    <label>Workspace Level</label>
                    <div className="auth-level-grid">
                      <div
                        className={`auth-level-card ${signupLevel === "individual" ? "selected" : ""}`}
                        onClick={() => setSignupLevel("individual")}
                        role="button"
                        tabIndex={0}
                      >
                        <div className="auth-level-card-title">
                          <span>👤</span> Individual
                        </div>
                        <div className="auth-level-card-desc">
                          Standalone IoT workspace for individual developers.
                        </div>
                      </div>
                      <div
                        className={`auth-level-card ${signupLevel === "organization" ? "selected" : ""}`}
                        onClick={() => setSignupLevel("organization")}
                        role="button"
                        tabIndex={0}
                      >
                        <div className="auth-level-card-title">
                          <span>🏢</span> Organization
                        </div>
                        <div className="auth-level-card-desc">
                          Enterprise team workspace with multi-user fleet access.
                        </div>
                      </div>
                    </div>
                  </div>

                  {signupLevel === "organization" && (
                    <div className="login-field">
                      <label htmlFor="signup-org-name">Organization Name</label>
                      <input
                        id="signup-org-name"
                        type="text"
                        placeholder="e.g. Acme Technologies"
                        value={signupOrgName}
                        onChange={(e) => setSignupOrgName(e.target.value)}
                        required
                      />
                    </div>
                  )}

                  <div className="login-field">
                    <label htmlFor="signup-name">Full Name</label>
                    <input
                      id="signup-name"
                      type="text"
                      placeholder="e.g. Jane Doe"
                      value={signupName}
                      onChange={(e) => setSignupName(e.target.value)}
                      autoComplete="name"
                      required
                    />
                  </div>

                  <div className="login-field">
                    <label htmlFor="signup-email">Work or Personal Email</label>
                    <input
                      id="signup-email"
                      type="email"
                      placeholder="name@company.com"
                      value={signupEmail}
                      onChange={(e) => setSignupEmail(e.target.value)}
                      autoComplete="email"
                      required
                    />
                  </div>

                  <div className="login-field">
                    <label htmlFor="signup-password">Password (min 8 characters)</label>
                    <div className="login-password-wrap">
                      <input
                        id="signup-password"
                        type={showSignupPassword ? "text" : "password"}
                        placeholder="Enter password"
                        value={signupPassword}
                        onChange={(e) => setSignupPassword(e.target.value)}
                        autoComplete="new-password"
                        minLength={8}
                        required
                      />
                      <button
                        type="button"
                        className="login-password-toggle"
                        onClick={() => setShowSignupPassword((prev) => !prev)}
                        aria-label={showSignupPassword ? "Hide password" : "Show password"}
                      >
                        {showSignupPassword ? "Hide" : "Show"}
                      </button>
                    </div>
                  </div>

                  <div className="login-field">
                    <label htmlFor="signup-confirm-password">Confirm Password</label>
                    <input
                      id="signup-confirm-password"
                      type={showSignupPassword ? "text" : "password"}
                      placeholder="Re-enter password"
                      value={signupConfirmPassword}
                      onChange={(e) => setSignupConfirmPassword(e.target.value)}
                      autoComplete="new-password"
                      minLength={8}
                      required
                    />
                  </div>

                  {signupError && (
                    <div className="login-error" role="alert">
                      <span aria-hidden="true">!</span>
                      <p>{signupError}</p>
                    </div>
                  )}

                  <button
                    className="login-submit"
                    type="submit"
                    disabled={signupLoading}
                  >
                    <span>
                      {signupLoading ? "Creating Account..." : "Create Account & Send Code"}
                    </span>
                    {!signupLoading && <span aria-hidden="true">→</span>}
                  </button>

                  <div className="auth-link-row">
                    <span style={{ color: "var(--muted)" }}>Already registered?</span>
                    <button
                      type="button"
                      className="auth-link-btn"
                      onClick={() => {
                        setAuthMode("login");
                        setLoginError("");
                      }}
                    >
                      Sign in here
                    </button>
                  </div>
                </form>
              </>
            )}
            {/* 3. EMAIL ACTIVATION MODE */}
            {authMode === "activate" && (
              <>
                <div className="login-form-heading">
                  <span className="login-form-eyebrow">EMAIL ACTIVATION</span>
                  <h2>Verify your email</h2>
                  <p>
                    Enter the 6-digit code sent to{" "}
                    <strong>{activationEmail || "your email"}</strong> to activate your account.
                  </p>
                </div>

                <form onSubmit={handleActivate} className="login-form">
                  {activationSuccess && (
                    <div className="auth-success-badge" role="status">
                      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
                        <polyline points="22 4 12 14.01 9 11.01" />
                      </svg>
                      <p>{activationSuccess}</p>
                    </div>
                  )}

                  {resendMessage && (
                    <div className="auth-success-badge" role="status">
                      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <polyline points="20 6 9 17 4 12" />
                      </svg>
                      <p>{resendMessage}</p>
                    </div>
                  )}

                  <div className="login-field">
                    <label htmlFor="activate-email">Registered Email</label>
                    <input
                      id="activate-email"
                      type="email"
                      placeholder="name@company.com"
                      value={activationEmail}
                      onChange={(e) => setActivationEmail(e.target.value)}
                      autoComplete="email"
                      required
                    />
                  </div>

                  <div className="login-field">
                    <label htmlFor="activate-code">6-Digit Activation Code</label>
                    <input
                      id="activate-code"
                      type="text"
                      maxLength={6}
                      placeholder="• • • • • •"
                      value={activationCode}
                      onChange={(e) => setActivationCode(e.target.value.replace(/\D/g, ""))}
                      className="auth-code-input"
                      autoFocus
                      required
                    />
                  </div>

                  {devCodeHint && (
                    <div className="auth-code-hint">
                      <span>Dev environment code: <strong>{devCodeHint}</strong></span>
                      <button
                        type="button"
                        className="auth-link-btn"
                        onClick={() => setActivationCode(devCodeHint)}
                      >
                        Auto-fill
                      </button>
                    </div>
                  )}

                  {activationError && (
                    <div className="login-error" role="alert">
                      <span aria-hidden="true">!</span>
                      <p>{activationError}</p>
                    </div>
                  )}

                  <button
                    className="login-submit"
                    type="submit"
                    disabled={activationLoading}
                  >
                    <span>
                      {activationLoading ? "Activating Account..." : "Activate & Enter Console"}
                    </span>
                    {!activationLoading && <span aria-hidden="true">✓</span>}
                  </button>

                  <div className="auth-link-row">
                    <button
                      type="button"
                      className="auth-link-btn"
                      onClick={handleResendActivation}
                      disabled={resendLoading}
                    >
                      {resendLoading ? "Resending..." : "Resend activation email"}
                    </button>
                    <button
                      type="button"
                      className="auth-link-btn"
                      onClick={() => {
                        setAuthMode("login");
                        setLoginError("");
                      }}
                    >
                      Back to Sign In
                    </button>
                  </div>
                </form>
              </>
            )}

            {/* 4. FORGOT PASSWORD - REQUEST CODE */}
            {authMode === "forgot_request" && (
              <>
                <div className="login-form-heading">
                  <span className="login-form-eyebrow">ACCOUNT RECOVERY</span>
                  <h2>Reset password</h2>
                  <p>Enter your registered email address to receive a 6-digit recovery code.</p>
                </div>

                <form onSubmit={handleForgotPasswordRequest} className="login-form">
                  {forgotError && (
                    <div className="login-error" role="alert">
                      <span aria-hidden="true">!</span>
                      <p>{forgotError}</p>
                    </div>
                  )}

                  <div className="login-field">
                    <label htmlFor="forgot-email">Registered Email</label>
                    <input
                      id="forgot-email"
                      type="email"
                      placeholder="name@company.com"
                      value={forgotEmail}
                      onChange={(e) => setForgotEmail(e.target.value)}
                      autoComplete="email"
                      autoFocus
                      required
                    />
                  </div>

                  <button
                    className="login-submit"
                    type="submit"
                    disabled={forgotLoading}
                  >
                    <span>
                      {forgotLoading ? "Sending Recovery Code..." : "Send Recovery Code"}
                    </span>
                    {!forgotLoading && <span aria-hidden="true">→</span>}
                  </button>

                  <div className="auth-link-row">
                    <span style={{ color: "var(--muted)" }}>Remembered your password?</span>
                    <button
                      type="button"
                      className="auth-link-btn"
                      onClick={() => {
                        setAuthMode("login");
                        setForgotError("");
                        setForgotSuccess("");
                      }}
                    >
                      Sign in
                    </button>
                  </div>
                </form>
              </>
            )}

            {/* 5. FORGOT PASSWORD - SET NEW PASSWORD */}
            {authMode === "forgot_reset" && (
              <>
                <div className="login-form-heading">
                  <span className="login-form-eyebrow">ACCOUNT RECOVERY</span>
                  <h2>Set new password</h2>
                  <p>
                    Enter the 6-digit recovery code sent to{" "}
                    <strong>{forgotEmail || "your email"}</strong> and choose a new password.
                  </p>
                </div>

                <form onSubmit={handleResetPassword} className="login-form">
                  {forgotSuccess && (
                    <div className="auth-success-badge" role="status">
                      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <polyline points="20 6 9 17 4 12" />
                      </svg>
                      <p>{forgotSuccess}</p>
                    </div>
                  )}

                  <div className="login-field">
                    <label htmlFor="reset-email">Registered Email</label>
                    <input
                      id="reset-email"
                      type="email"
                      placeholder="name@company.com"
                      value={forgotEmail}
                      onChange={(e) => setForgotEmail(e.target.value)}
                      autoComplete="email"
                      required
                    />
                  </div>

                  {!forgotToken && (
                    <div className="login-field">
                      <label htmlFor="reset-code">6-Digit Recovery Code</label>
                      <input
                        id="reset-code"
                        type="text"
                        maxLength={6}
                        placeholder="• • • • • •"
                        value={forgotCode}
                        onChange={(e) => setForgotCode(e.target.value.replace(/\D/g, ""))}
                        className="auth-code-input"
                        autoFocus
                        required
                      />
                    </div>
                  )}

                  {forgotDevCodeHint && (
                    <div className="auth-code-hint">
                      <span>Dev environment recovery code: <strong>{forgotDevCodeHint}</strong></span>
                      <button
                        type="button"
                        className="auth-link-btn"
                        onClick={() => setForgotCode(forgotDevCodeHint)}
                      >
                        Auto-fill
                      </button>
                    </div>
                  )}

                  <div className="login-field">
                    <label htmlFor="reset-new-password">New Password (min 8 characters)</label>
                    <div className="login-password-wrap">
                      <input
                        id="reset-new-password"
                        type={showForgotNewPassword ? "text" : "password"}
                        placeholder="Enter new password"
                        value={forgotNewPassword}
                        onChange={(e) => setForgotNewPassword(e.target.value)}
                        autoComplete="new-password"
                        minLength={8}
                        required
                      />
                      <button
                        type="button"
                        className="login-password-toggle"
                        onClick={() => setShowForgotNewPassword((prev) => !prev)}
                        aria-label={showForgotNewPassword ? "Hide password" : "Show password"}
                      >
                        {showForgotNewPassword ? "Hide" : "Show"}
                      </button>
                    </div>
                  </div>

                  <div className="login-field">
                    <label htmlFor="reset-confirm-password">Confirm New Password</label>
                    <input
                      id="reset-confirm-password"
                      type={showForgotNewPassword ? "text" : "password"}
                      placeholder="Re-enter new password"
                      value={forgotConfirmPassword}
                      onChange={(e) => setForgotConfirmPassword(e.target.value)}
                      autoComplete="new-password"
                      minLength={8}
                      required
                    />
                  </div>

                  {forgotError && (
                    <div className="login-error" role="alert">
                      <span aria-hidden="true">!</span>
                      <p>{forgotError}</p>
                    </div>
                  )}

                  <button
                    className="login-submit"
                    type="submit"
                    disabled={forgotLoading}
                  >
                    <span>
                      {forgotLoading ? "Resetting Password..." : "Reset Password & Sign In"}
                    </span>
                    {!forgotLoading && <span aria-hidden="true">✓</span>}
                  </button>

                  <div className="auth-link-row">
                    <button
                      type="button"
                      className="auth-link-btn"
                      onClick={handleForgotPasswordRequest}
                      disabled={forgotLoading}
                    >
                      Resend recovery code
                    </button>
                    <button
                      type="button"
                      className="auth-link-btn"
                      onClick={() => {
                        setAuthMode("login");
                        setForgotError("");
                        setForgotSuccess("");
                      }}
                    >
                      Back to Sign In
                    </button>
                  </div>
                </form>
              </>
            )}

          </div>

          <div className="login-copyright">
            IoT Network Server
          </div>
        </section>
      </div>
    );
  }

  // Wait for the authenticated user.
  if (!currentUser) {
    if (authError) {
      return (
        <div className="app-loading" style={{ textAlign: "center", maxWidth: "480px", margin: "auto", padding: "2rem" }}>
          <img src="/nibiaa-logo.png" alt="" style={{ marginBottom: "1.5rem", maxHeight: "48px" }} />
          <div style={{ color: "#ef4444", fontSize: "1.1rem", fontWeight: "600", marginBottom: "0.5rem" }}>
            Failed to Load Account
          </div>
          <div style={{ color: "#94a3b8", fontSize: "0.875rem", marginBottom: "1.5rem", wordBreak: "break-word" }}>
            {authError}
          </div>
          <div style={{ display: "flex", gap: "12px", justifyContent: "center" }}>
            <button
              className="primary-button"
              type="button"
              onClick={() => refreshMe()}
              style={{ padding: "8px 18px", borderRadius: "6px", cursor: "pointer" }}
            >
              Retry
            </button>
            <button
              className="secondary-button"
              type="button"
              onClick={() => signOut()}
              style={{ padding: "8px 18px", borderRadius: "6px", cursor: "pointer" }}
            >
              Sign Out
            </button>
          </div>
        </div>
      );
    }

    return (
      <div className="app-loading">
        <img src="/nibiaa-logo.png" alt="" />
        <span>Loading your account…</span>
      </div>
    );
  }

  // -------------------------
  // Main application
  // -------------------------

  const pages = visiblePages(effectiveCurrentUser);

  const page =
    pages[route.page] === false ? "devices" : route.page;

  const pageProps = {
    api,
    currentUser: effectiveCurrentUser,
    activeWorkspace: selectedWorkspace,
    onSelectWorkspace: setSelectedWorkspace,
    navigate,
    params: route.params,
    refreshMe,
    selectedHeaderApplication,
  };

  const normalizedFilter = navFilter.trim().toLowerCase();

  // Sections with at least one visible (and matching) item, numbered 1, 2, 3 …
  const navSections = NAV_SECTIONS
    .map((section) => ({
      ...section,
      items: section.items.filter(
        (item) =>
          pages[item.key] !== false &&
          (!normalizedFilter || item.label.toLowerCase().includes(normalizedFilter))
      ),
    }))
    .filter((section) => section.items.length > 0);

  // Filter available pages without changing backend permissions.
  const searchResults = CONSOLE_PAGES.filter((item) => {
    const matches =
      item.label.toLowerCase().includes(globalSearch.trim().toLowerCase());

    const isAvailable = pages[item.key] !== false;

    return globalSearch.trim() && matches && isAvailable;
  });

  const initial = (currentUser.name || "U").slice(0, 1).toUpperCase();

  return (
    <div
      className={`app-layout ${
        mobileNavOpen ? "mobile-nav-open" : ""
      }`}
    >
      {/* Mobile navigation backdrop */}
      {mobileNavOpen && (
        <button
          type="button"
          className="mobile-nav-backdrop"
          aria-label="Close navigation"
          onClick={() => setMobileNavOpen(false)}
        />
      )}

      {/* Sidebar */}
      <aside className="sidebar" aria-label="Main navigation">
        <div className="sidebar-brand">
          <img
            src="/nibiaa-logo.png"
            alt="Nibiaa logo"
            className="brand-logo"
          />

          <div className="brand-copy">
            <div className="brand-title">
              <span className="brand-name">{currentOrgName}</span>
              <b>CONSOLE</b>
            </div>

            <p>{currentOrgSubtitle}</p>
          </div>
        </div>

        {/* Workspace switcher: only shown for tenant/workspace users with a tenant assigned (Admin has no org or workspace) */}
        {!isAdmin && currentUser && (currentUser.tenant_id || selectedWorkspace) && (
          <div
            className="workspace-chip"
            onClick={() => setShowWorkspaceModal(true)}
            role="button"
            tabIndex={0}
            title="Click to switch or create workspaces"
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                setShowWorkspaceModal(true);
              }
            }}
          >
            <span
              className="workspace-dot"
              style={selectedWorkspace ? { background: "var(--primary)", boxShadow: "0 0 0 3px var(--primary-soft)" } : {}}
            />
            <div style={{ display: "flex", flexDirection: "column", minWidth: 0, flex: 1, overflow: "hidden" }}>
              <span className="workspace-label">WORKSPACE</span>
              <strong>{activeWorkspaceName}</strong>
            </div>
            <span style={{ fontSize: "0.8rem", color: "var(--muted)", marginLeft: "4px" }}>
              ▾
            </span>
          </div>
        )}

        {/* Sidebar navigation filter */}
        <div className="sidebar-search-wrap">
          <Icon name="search" size={15} />

          <input
            type="search"
            placeholder="Filter navigation..."
            value={navFilter}
            onChange={(event) => setNavFilter(event.target.value)}
            aria-label="Filter navigation"
          />

          {navFilter && (
            <button
              type="button"
              onClick={() => setNavFilter("")}
              aria-label="Clear navigation filter"
            >
              ×
            </button>
          )}
        </div>

        <nav className="sidebar-nav">
          {navSections.map((section, index) => (
            <div className="sidebar-section" key={section.title}>
              <div className="sidebar-section-title">
                <span>{index + 1}</span> {section.title}
              </div>

              {section.items.map((item) => (
                <button
                  key={item.key}
                  type="button"
                  className={`sidebar-item ${page === item.key ? "active" : ""}`}
                  aria-current={page === item.key ? "page" : undefined}
                  onClick={() => {
                    if (!item.comingSoon) navigateToPage(item.key);
                  }}
                  disabled={item.comingSoon}
                >
                  <Icon
                    name={item.comingSoon ? "connectivity" : item.key}
                    size={17}
                    className="nav-glyph"
                  />

                  <span className="sidebar-item-copy">
                    <span>{item.label}</span>

                    {item.comingSoon && (
                      <span className="sidebar-coming-soon">COMING SOON</span>
                    )}
                  </span>
                </button>
              ))}
            </div>
          ))}

          {navSections.length === 0 && (
            <div className="sidebar-filter-empty">
              No matching navigation items
            </div>
          )}
        </nav>

        <div className="sidebar-bottom">
          <button
            type="button"
            className={`sidebar-user ${
              page === "account" ? "active" : ""
            }`}
            onClick={() => navigateToPage("account")}
            title="My account"
          >
            <span className="avatar">{initial}</span>

            <span className="sidebar-user-copy">
              <strong>{currentUser.email || currentUser.name}</strong>

              <span>
                {currentUser.email && currentUser.name ? `${currentUser.name} · ` : ""}
                {currentUser.role}
                {currentUser.collaborator_role_name
                  ? ` · ${currentUser.collaborator_role_name}`
                  : ""}
              </span>
            </span>
          </button>

          <button
            type="button"
            className="sidebar-item logout-item"
            onClick={() => signOut()}
          >
            <Icon name="logout" size={17} className="nav-glyph" />
            <span>Sign out</span>
          </button>
        </div>
      </aside>

      {/* Main content */}
      <main className="main-content">
        <header className="topbar">
          {/* Mobile menu */}
          <button
            type="button"
            className="icon-button mobile-menu-button"
            onClick={() => setMobileNavOpen((open) => !open)}
            aria-label={
              mobileNavOpen ? "Close navigation" : "Open navigation"
            }
            aria-expanded={mobileNavOpen}
          >
            <Icon name="menu" size={20} />
          </button>

          {/* Breadcrumb */}
          <div className="breadcrumb">
            <span className="breadcrumb-root">{currentOrgName}</span>
            <span className="breadcrumb-separator">/</span>
            <span className="breadcrumb-muted">{sectionOf(page)}</span>

            {page === "devices" && (
              <>
                <span className="breadcrumb-separator">/</span>
                <select
                  className="breadcrumb-application-select"
                  value={selectedHeaderApplication}
                  onChange={(event) => setSelectedHeaderApplication(event.target.value)}
                  aria-label="Filter devices by application"
                >
                  <option value="">All Applications</option>
                  {headerApplications.map((application) => (
                    <option key={application.id} value={application.id}>
                      {application.name}
                    </option>
                  ))}
                </select>
              </>
            )}
            <span className="breadcrumb-separator">/</span>
            <strong>{PAGE_TITLES[page] || "Devices"}</strong>
          </div>

          <div className="topbar-actions">
            {/* Global page search */}
            <div className="global-search">
              <Icon name="search" size={15} />

              <input
                type="search"
                placeholder="Search pages..."
                value={globalSearch}
                onChange={(event) => setGlobalSearch(event.target.value)}
                aria-label="Search console pages"
                onKeyDown={(event) => {
                  if (event.key === "Escape") {
                    setGlobalSearch("");
                  }

                  if (event.key === "Enter" && searchResults.length > 0) {
                    navigateToPage(searchResults[0].key);
                  }
                }}
              />

              {globalSearch.trim() && (
                <div className="global-search-results">
                  {searchResults.map((item) => (
                    <button
                      type="button"
                      key={item.key}
                      onClick={() => navigateToPage(item.key)}
                    >
                      <Icon name={item.key} size={15} />
                      {item.label}
                    </button>
                  ))}

                  {searchResults.length === 0 && (
                    <div className="global-search-empty">
                      No matching pages
                    </div>
                  )}
                </div>
              )}
            </div>

            <Notifications api={api} />

            {/* Dark/light theme toggle */}
            <button
              type="button"
              className="icon-button"
              onClick={toggleTheme}
              aria-label={`Switch to ${
                theme === "dark" ? "light" : "dark"
              } theme`}
              title={`Switch to ${
                theme === "dark" ? "light" : "dark"
              } theme`}
            >
              <ThemeIcon theme={theme} />
            </button>

            {/* Current user */}
            <button
              type="button"
              className="topbar-user"
              onClick={() => navigateToPage("account")}
              title="My account"
            >
              <span className="topbar-avatar">{initial}</span>
              <span className="topbar-user-name">{currentUser.email || currentUser.name}</span>
            </button>
          </div>
        </header>

        <div className="content-container">
          <ErrorBoundary>
            {page === "users" ? (
              <Users {...pageProps} />
            ) : page === "tenants" ? (
              <Tenants {...pageProps} />
            ) : page === "roles" ? (
              <CollaboratorRoles {...pageProps} />
            ) : page === "attributes" ? (
              <Attributes {...pageProps} />
            ) : page === "audit-logs" ? (
              <AuditLogs {...pageProps} />
            ) : page === "applications" ? (
              <Applications {...pageProps} />
            ) : page === "decoders" ? (
              <Decoders {...pageProps} />
            ) : page === "telemetry" ? (
              <Telemetry key={route.params?.deviceId || "telemetry-all"} {...pageProps} />
            ) : page === "connectivity" ? (
              <Connectivity {...pageProps} />
            ) : page === "ingestion-profiles" ? (
              <IngestionProfiles {...pageProps} />
            ) : page === "billing" ? (
              <Billing {...pageProps} />
            ) : page === "integration" ? (
              <Integration {...pageProps} />
            ) : page === "account" ? (
              <Account {...pageProps} />
            ) : page === "configuration" && route.params.device ? (
              <DeviceConfiguration
                {...pageProps}
                device={route.params.device}
                onBack={() => navigate("devices")}
              />
            ) : (
              <Devices {...pageProps} />
            )}
          </ErrorBoundary>
        </div>
      </main>

      {showWorkspaceModal && (
        <WorkspaceModal
          api={api}
          currentUser={currentUser}
          activeWorkspace={selectedWorkspace}
          onSelectWorkspace={setSelectedWorkspace}
          onNavigate={(target) => navigateToPage(target)}
          onClose={() => setShowWorkspaceModal(false)}
        />
      )}
    </div>
  );
}

createRoot(document.getElementById("root")).render(
  <ErrorBoundary>
    <App />
  </ErrorBoundary>
);
