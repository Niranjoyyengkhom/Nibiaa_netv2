import { useState } from "react";

import { COLLABORATOR_FUNCTIONS } from "./api";
import { Notice, PageHeader, RoleBadge } from "./components";


// The signed-in user's own profile: everyone may change
// their own name (= login) and password
function Account({ api, currentUser, refreshMe }) {
  const isAdmin = currentUser.role === "admin";
  const [email, setEmail] = useState(currentUser.email || "");
  const [name, setName] = useState(currentUser.name);
  const [currentPassword, setCurrentPassword] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [notice, setNotice] = useState(null);



  async function save(event) {
    event.preventDefault();
    setNotice(null);

    if (password) {
      if (!currentPassword) {
        setNotice({ type: "error", text: "Please enter your current password to set a new password." });
        return;
      }
      if (password !== confirm) {
        setNotice({ type: "error", text: "The two passwords are different." });
        return;
      }
    }

    try {
      await api.put(`/users/${currentUser.id}`, {
        email: email.trim().toLowerCase() || undefined,
        name: name.trim() || undefined,
        password: password || null,
        current_password: currentPassword || null,
      });

      setCurrentPassword("");
      setPassword("");
      setConfirm("");
      setNotice({
        type: "success",
        text: "Account details saved.",
      });
      refreshMe();
    } catch (error) {
      setNotice({ type: "error", text: error.message });
    }
  }

  const functions = COLLABORATOR_FUNCTIONS.filter(
    (fn) => currentUser.permissions[fn.key]
  );

  return (
    <div className="page">

      <PageHeader title="My Account" />

      <section className="profile-card">
        <div>
          <span className="label">Account</span>
          <h2>{currentUser.email || currentUser.name}</h2>
          {currentUser.email && <div className="muted small-text">{currentUser.name}</div>}
          <RoleBadge role={currentUser.role} />
        </div>

        <div>
          <span className="label">Organization / Workspace</span>
          <strong className="block">{isAdmin ? "None (Global Platform Administrator)" : currentUser.tenant_name || "—"}</strong>
          {isAdmin ? (
            <span className="muted small-text">All Workspaces & Tenants</span>
          ) : currentUser.tenant_type ? (
            <span className="muted small-text capitalize">{currentUser.tenant_type}</span>
          ) : null}
        </div>

        <div>
          <span className="label">Functions</span>
          <div className="tag-list">
            {currentUser.role !== "collaborator"
              ? <span className="muted">All ({currentUser.role})</span>
              : functions.length === 0
                ? <span className="muted">None</span>
                : functions.map((fn) => <span className="tag" key={fn.key}>{fn.label}</span>)}
          </div>
        </div>
      </section>

      <section className="card">
        <div className="section-header">
          <div>
            <h2>Edit Profile</h2>
            <p>You can sign in with your email or username.</p>
          </div>
        </div>

        <form onSubmit={save}>
          <div className="form-grid">
            <div className="form-group">
              <label>Email (used to sign in)</label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </div>

            <div className="form-group">
              <label>Display Name</label>
              <input value={name} onChange={(e) => setName(e.target.value)} required />
            </div>

            <div className="form-group">
              <label>Current password</label>
              <input
                type="password"
                placeholder="Required only to change password"
                value={currentPassword}
                onChange={(e) => setCurrentPassword(e.target.value)}
              />
            </div>

            <div className="form-group">
              <label>New password</label>
              <input
                type="password"
                minLength={8}
                placeholder="Leave empty to keep it"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </div>

            <div className="form-group">
              <label>Repeat new password</label>
              <input
                type="password"
                minLength={8}
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
              />
            </div>
          </div>

          <Notice notice={notice} />

          <button className="primary-button" type="submit">Save</button>
        </form>
      </section>

    </div>
  );
}

export default Account;
