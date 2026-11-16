import { useEffect, useState } from "react";

import { COLLABORATOR_FUNCTIONS, NO_FUNCTIONS, functionLabel } from "./api";
import {
  FunctionTags,
  Notice,
  PageHeader,
  RoleBadge,
  StatusPill,
} from "./components";


function Users({ api, currentUser, refreshMe }) {
  const isAdmin = currentUser.role === "admin";

  const [users, setUsers] = useState([]);
  const [tenants, setTenants] = useState([]);
  const [roles, setRoles] = useState([]);

  // Create form
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("collaborator");
  const [tenantId, setTenantId] = useState("");
  const [createNotice, setCreateNotice] = useState(null);

  const [listNotice, setListNotice] = useState(null);

  // Edit name / password
  const [editing, setEditing] = useState(null);

  // Role assignment of one collaborator
  const [selectedCollaborator, setSelectedCollaborator] = useState(null);
  const [assignedRoleId, setAssignedRoleId] = useState("");
  const [permissions, setPermissions] = useState(NO_FUNCTIONS);
  const [roleNotice, setRoleNotice] = useState(null);

  // The form stays disabled until the collaborator's current functions
  // are loaded, so a late answer cannot overwrite the owner's choice
  const [loadingFunctions, setLoadingFunctions] = useState(false);

  useEffect(() => {
    fetchUsers();
    api.get("/tenants/").then(setTenants).catch(() => setTenants([]));
    api.get("/collaborator-roles/").then(setRoles).catch(() => setRoles([]));
  }, [api]);

  async function fetchUsers() {
    try {
      setUsers(await api.get("/users/"));
    } catch (error) {
      setListNotice({ type: "error", text: error.message });
    }
  }

  // Admins manage everyone else; owners manage the collaborators
  // of their own organization (RBAC matrix)
  function canManage(user) {
    if (user.id === currentUser.id) {
      return false;
    }

    if (isAdmin) {
      return true;
    }

    return (
      currentUser.role === "owner" &&
      user.role === "collaborator" &&
      user.tenant_id === currentUser.tenant_id
    );
  }

  // -------------------------
  // Create
  // -------------------------

  async function createUser(event) {
    event.preventDefault();
    setCreateNotice(null);

    try {
      const user = await api.post("/users/", {
        email: email.trim().toLowerCase(),
        name: name.trim() || undefined,
        password,
        role: isAdmin ? role : "collaborator",
        tenant_id: isAdmin && role !== "admin" && tenantId ? Number(tenantId) : null,
      });

      setCreateNotice({
        type: "success",
        text: user.role === "collaborator"
          ? `${user.email || user.name} created. Use "Functions" in the list to give them access.`
          : `${user.email || user.name} created.`,
      });

      setEmail("");
      setName("");
      setPassword("");
      setTenantId("");

      fetchUsers();
    } catch (error) {
      setCreateNotice({ type: "error", text: error.message });
    }
  }

  // -------------------------
  // Edit / revoke / delete
  // -------------------------

  async function saveUser(event) {
    event.preventDefault();
    setListNotice(null);

    try {
      await api.put(`/users/${editing.id}`, {
        email: editing.email ? editing.email.trim().toLowerCase() : undefined,
        name: editing.name ? editing.name.trim() : undefined,
        password: editing.password ? editing.password : null,
      });

      setListNotice({ type: "success", text: `${editing.email || editing.name} updated.` });
      setEditing(null);
      fetchUsers();
    } catch (error) {
      setListNotice({ type: "error", text: error.message });
    }
  }

  async function setActive(user, active) {
    const action = active ? "restore" : "revoke";

    if (!active && !window.confirm(
      `Revoke ${user.name}'s access? They are signed out and cannot sign in until restored.`
    )) {
      return;
    }

    setListNotice(null);

    try {
      await api.post(`/users/${user.id}/${action}`);
      setListNotice({
        type: "success",
        text: active ? `${user.name} can sign in again.` : `${user.name}'s access was revoked.`,
      });
      fetchUsers();
    } catch (error) {
      setListNotice({ type: "error", text: error.message });
    }
  }

  async function deleteUser(user) {
    if (!window.confirm(`Delete ${user.name}? This cannot be undone.`)) {
      return;
    }

    setListNotice(null);

    try {
      await api.delete(`/users/${user.id}`);
      setListNotice({ type: "success", text: `${user.name} deleted.` });

      if (selectedCollaborator?.id === user.id) {
        setSelectedCollaborator(null);
      }

      fetchUsers();
    } catch (error) {
      setListNotice({ type: "error", text: error.message });
    }
  }

  // -------------------------
  // Functions / role assignment
  // -------------------------

  async function openRoleManager(user) {
    setSelectedCollaborator(user);
    setEditing(null);
    setRoleNotice(null);
    setLoadingFunctions(true);

    try {
      const data = await api.get(`/collaborators/${user.id}/permissions`);

      setAssignedRoleId(data.role_id ? String(data.role_id) : "");
      setPermissions(pickFunctions(data));
    } catch (error) {
      setRoleNotice({ type: "error", text: error.message });
      setPermissions(NO_FUNCTIONS);
    } finally {
      setLoadingFunctions(false);
    }
  }

  function pickFunctions(source) {
    return Object.fromEntries(
      COLLABORATOR_FUNCTIONS.map((fn) => [fn.key, Boolean(source[fn.key])])
    );
  }

  function chooseRole(roleId) {
    setAssignedRoleId(roleId);

    // Show the role's functions; "custom" starts from what is shown
    const chosen = roles.find((r) => r.id === Number(roleId));

    if (chosen) {
      setPermissions(pickFunctions(chosen));
    }
  }

  async function savePermissions() {
    setRoleNotice(null);

    try {
      const data = await api.put(
        `/collaborators/${selectedCollaborator.id}/permissions`,
        {
          ...permissions,
          role_id: assignedRoleId ? Number(assignedRoleId) : null,
        }
      );

      setPermissions(pickFunctions(data));

      setRoleNotice({
        type: "success",
        text: data.role_name
          ? `${selectedCollaborator.name} now has the "${data.role_name}" role. It applies on their next action.`
          : `Functions updated for ${selectedCollaborator.name}. They apply on their next action.`,
      });

      fetchUsers();
      api.get("/collaborator-roles/").then(setRoles).catch(() => {});
      refreshMe();
    } catch (error) {
      setRoleNotice({ type: "error", text: error.message });
    }
  }

  const roleLocked = Boolean(assignedRoleId);

  return (
    <div className="page">

      <PageHeader
        title="User Management"
        description={
          isAdmin
            ? "Create and manage users of every organization."
            : `Create and manage the collaborators of ${currentUser.tenant_name}.`
        }
      />

      {/* Create User */}
      <section className="card">
        <div className="section-header">
          <div>
            <h2>{isAdmin ? "Create User" : "Create Collaborator"}</h2>
            <p>
              {isAdmin
                ? "Admins create owners, collaborators and other admins."
                : "Owners create collaborators in their own organization."}
            </p>
          </div>
        </div>

        <form onSubmit={createUser}>
          <div className="form-grid">

            <div className="form-group">
              <label>Email (used to sign in)</label>
              <input
                type="email"
                placeholder="user@nibiaa.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </div>

            <div className="form-group">
              <label>Name / Display Name</label>
              <input
                type="text"
                placeholder="e.g. John Doe (optional)"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </div>

            <div className="form-group">
              <label>Password</label>
              <input
                type="password"
                placeholder="At least 6 characters"
                value={password}
                minLength={6}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </div>

            <div className="form-group">
              <label>Role</label>
              {isAdmin ? (
                <select value={role} onChange={(e) => setRole(e.target.value)}>
                  <option value="collaborator">Collaborator</option>
                  <option value="owner">Owner</option>
                  <option value="admin">Admin</option>
                </select>
              ) : (
                <input value="Collaborator" disabled />
              )}
            </div>

            <div className="form-group">
              <label>Organization</label>
              {isAdmin ? (
                <select
                  value={role === "admin" ? "" : tenantId}
                  onChange={(e) => setTenantId(e.target.value)}
                  disabled={role === "admin"}
                  required={role !== "admin"}
                >
                  <option value="">
                    {role === "admin" ? "Platform (no organization)" : "Select Organization"}
                  </option>
                  {tenants.map((tenant) => (
                    <option key={tenant.id} value={tenant.id}>
                      {tenant.name}
                    </option>
                  ))}
                </select>
              ) : (
                <input value={currentUser.tenant_name || ""} disabled />
              )}
            </div>

          </div>

          <Notice notice={createNotice} />

          <button className="primary-button" type="submit">
            {isAdmin ? "Create User" : "Create Collaborator"}
          </button>
        </form>
      </section>

      {/* Users List */}
      <section className="card">
        <div className="section-header">
          <div>
            <h2>Users</h2>
            <p>Users accessible to the current user.</p>
          </div>
          <button className="secondary-button" onClick={fetchUsers}>
            Refresh
          </button>
        </div>

        {users.length === 0 ? (
          <div className="empty-state">No users found.</div>
        ) : (
          <div className="table-container">
            <table>
              <thead>
                <tr>
                  <th>User / Email</th>
                  <th>Display Name</th>
                  <th>Role</th>
                  <th>Organization</th>
                  <th>Status</th>
                  <th>Functions</th>
                  <th>Actions</th>
                </tr>
              </thead>

              <tbody>
                {users.map((user) => (
                  <tr key={user.id}>
                    <td>
                      <strong>{user.email || user.name}</strong>
                      {user.id === currentUser.id && <span className="muted"> (you)</span>}
                    </td>
                    <td>{user.name}</td>
                    <td><RoleBadge role={user.role} /></td>
                    <td>{user.tenant_name || "Platform"}</td>
                    <td><StatusPill active={user.is_active} /></td>
                    <td>
                      {user.role === "collaborator" ? (
                        <>
                          <div className="muted small-text">
                            {user.collaborator_role_name || "Custom functions"}
                          </div>
                          <FunctionTags keys={user.functions} labels={functionLabel} />
                        </>
                      ) : (
                        <span className="muted">All ({user.role})</span>
                      )}
                    </td>
                    <td>
                      <div className="table-actions">
                        {user.role === "collaborator" && canManage(user) && (
                          <button
                            className="secondary-button small"
                            onClick={() => openRoleManager(user)}
                          >
                            Functions
                          </button>
                        )}

                        {(canManage(user) || user.id === currentUser.id) && (
                          <button
                            className="secondary-button small"
                            onClick={() => {
                              setEditing({ id: user.id, email: user.email || "", name: user.name, password: "" });
                              setSelectedCollaborator(null);
                            }}
                          >
                            Edit
                          </button>
                        )}

                        {canManage(user) && (
                          user.is_active ? (
                            <button
                              className="secondary-button small"
                              onClick={() => setActive(user, false)}
                            >
                              Revoke
                            </button>
                          ) : (
                            <button
                              className="secondary-button small"
                              onClick={() => setActive(user, true)}
                            >
                              Restore
                            </button>
                          )
                        )}

                        {canManage(user) && (
                          <button
                            className="danger-button small"
                            onClick={() => deleteUser(user)}
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

        {!editing && <Notice notice={listNotice} />}
      </section>

      {/* Edit user */}
      {editing && (
        <section className="card">
          <div className="section-header">
            <div>
              <h2>Edit User</h2>
              <p>Leave the password empty to keep the current one.</p>
            </div>
          </div>

          <form onSubmit={saveUser}>
            <div className="form-grid">
              <div className="form-group">
                <label>Email (used to sign in)</label>
                <input
                  type="email"
                  value={editing.email || ""}
                  onChange={(e) => setEditing({ ...editing, email: e.target.value })}
                  required
                />
              </div>

              <div className="form-group">
                <label>Name / Display Name</label>
                <input
                  type="text"
                  value={editing.name || ""}
                  onChange={(e) => setEditing({ ...editing, name: e.target.value })}
                />
              </div>

              <div className="form-group">
                <label>New password</label>
                <input
                  type="password"
                  minLength={6}
                  value={editing.password}
                  onChange={(e) => setEditing({ ...editing, password: e.target.value })}
                />
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

      {/* Role Management */}
      {selectedCollaborator && (
        <section className="card">

          <div className="section-header">
            <div>
              <h2>Functions of {selectedCollaborator.name}</h2>
              <p>
                Assign a collaborator role, or pick custom functions.
                Changes apply on the collaborator's next action.
              </p>
            </div>
          </div>

          <div className="form-grid">
            <div className="form-group">
              <label>Collaborator role</label>
              <select
                value={assignedRoleId}
                disabled={loadingFunctions}
                onChange={(e) => chooseRole(e.target.value)}
              >
                <option value="">Custom functions</option>
                {roles.map((r) => (
                  <option key={r.id} value={r.id}>{r.name}</option>
                ))}
              </select>
              {roles.length === 0 && (
                <span className="muted small-text">
                  No collaborator roles yet{isAdmin ? " — create them on the Collaborator Roles page" : " — the platform admin creates them"}.
                </span>
              )}
            </div>
          </div>

          <div className="permissions-list">
            {COLLABORATOR_FUNCTIONS.map((fn) => (
              <label
                className={`permission-item ${roleLocked ? "locked" : ""}`}
                key={fn.key}
              >
                <input
                  type="checkbox"
                  checked={permissions[fn.key]}
                  disabled={roleLocked || loadingFunctions}
                  onChange={() =>
                    setPermissions((previous) => ({
                      ...previous,
                      [fn.key]: !previous[fn.key],
                    }))
                  }
                />
                <div>
                  <strong>{fn.label}</strong>
                  <p>{fn.description}</p>
                </div>
              </label>
            ))}
          </div>

          {roleLocked && (
            <p className="muted small-text">
              The functions come from the selected role. Choose "Custom
              functions" to pick them one by one.
            </p>
          )}

          <Notice notice={roleNotice} />

          <div className="button-group">
            <button
              className="primary-button"
              onClick={savePermissions}
              disabled={loadingFunctions}
            >
              Save Functions
            </button>
            <button
              className="secondary-button"
              onClick={() => setSelectedCollaborator(null)}
            >
              Close
            </button>
          </div>

        </section>
      )}

    </div>
  );
}

export default Users;
