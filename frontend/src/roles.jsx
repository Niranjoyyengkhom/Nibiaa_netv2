import { useEffect, useState } from "react";

import { COLLABORATOR_FUNCTIONS, NO_FUNCTIONS, functionLabel } from "./api";
import { FunctionTags, Notice, PageHeader } from "./components";


const EMPTY_ROLE = {
  id: null,
  name: "",
  description: "",
  ...NO_FUNCTIONS,
};


// Admin: named sets of collaborator functions ("Create Collaborator
// Roles"). Owners assign them to collaborators on the Users page.
function CollaboratorRoles({ api }) {
  const [roles, setRoles] = useState([]);
  const [form, setForm] = useState(EMPTY_ROLE);
  const [notice, setNotice] = useState(null);
  const [listNotice, setListNotice] = useState(null);

  useEffect(() => {
    fetchRoles();
  }, [api]);

  async function fetchRoles() {
    try {
      setRoles(await api.get("/collaborator-roles/"));
    } catch (error) {
      setListNotice({ type: "error", text: error.message });
    }
  }

  async function saveRole(event) {
    event.preventDefault();
    setNotice(null);

    const body = {
      name: form.name.trim(),
      description: form.description || null,
      ...Object.fromEntries(
        COLLABORATOR_FUNCTIONS.map((fn) => [fn.key, form[fn.key]])
      ),
    };

    try {
      if (form.id) {
        const role = await api.put(`/collaborator-roles/${form.id}`, body);
        setNotice({
          type: "success",
          text: `${role.name} updated. ${role.collaborator_count} collaborator(s) with this role got the new functions.`,
        });
      } else {
        const role = await api.post("/collaborator-roles/", body);
        setNotice({
          type: "success",
          text: `${role.name} created. Owners can now assign it on the Users page.`,
        });
      }

      setForm(EMPTY_ROLE);
      fetchRoles();
    } catch (error) {
      setNotice({ type: "error", text: error.message });
    }
  }

  async function deleteRole(role) {
    if (!window.confirm(`Delete the role "${role.name}"?`)) {
      return;
    }

    setListNotice(null);

    try {
      await api.delete(`/collaborator-roles/${role.id}`);
      setListNotice({ type: "success", text: `${role.name} deleted.` });

      if (form.id === role.id) {
        setForm(EMPTY_ROLE);
      }

      fetchRoles();
    } catch (error) {
      setListNotice({ type: "error", text: error.message });
    }
  }

  return (
    <div className="page">

      <PageHeader
        title="Collaborator Roles"
        description="Named sets of functions that owners assign to their collaborators."
      />

      <section className="card">
        <div className="section-header">
          <div>
            <h2>{form.id ? `Edit ${form.name || "role"}` : "Create Collaborator Role"}</h2>
            <p>
              Changing a role changes the functions of every collaborator
              that has it.
            </p>
          </div>
        </div>

        <form onSubmit={saveRole}>
          <div className="form-grid">
            <div className="form-group">
              <label>Name</label>
              <input
                placeholder="Field Technician"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                required
              />
            </div>

            <div className="form-group span-2">
              <label>Description</label>
              <input
                placeholder="Installs and maintains devices"
                value={form.description || ""}
                onChange={(e) => setForm({ ...form, description: e.target.value })}
              />
            </div>
          </div>

          <div className="permissions-list">
            {COLLABORATOR_FUNCTIONS.map((fn) => (
              <label className="permission-item" key={fn.key}>
                <input
                  type="checkbox"
                  checked={form[fn.key]}
                  onChange={() => setForm({ ...form, [fn.key]: !form[fn.key] })}
                />
                <div>
                  <strong>{fn.label}</strong>
                  <p>{fn.description}</p>
                </div>
              </label>
            ))}
          </div>

          <Notice notice={notice} />

          <div className="button-group">
            <button className="primary-button" type="submit">
              {form.id ? "Save Role" : "Create Role"}
            </button>

            {form.id && (
              <button
                className="secondary-button"
                type="button"
                onClick={() => { setForm(EMPTY_ROLE); setNotice(null); }}
              >
                Cancel
              </button>
            )}
          </div>
        </form>
      </section>

      <section className="card">
        <div className="section-header">
          <div>
            <h2>Roles</h2>
            <p>A role in use cannot be deleted.</p>
          </div>

          <button className="secondary-button" onClick={fetchRoles}>
            Refresh
          </button>
        </div>

        {roles.length === 0 ? (
          <div className="empty-state">No collaborator roles yet.</div>
        ) : (
          <div className="table-container">
            <table>
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Description</th>
                  <th>Functions</th>
                  <th>Collaborators</th>
                  <th>Actions</th>
                </tr>
              </thead>

              <tbody>
                {roles.map((role) => (
                  <tr key={role.id}>
                    <td><strong>{role.name}</strong></td>
                    <td>{role.description || <span className="muted">—</span>}</td>
                    <td>
                      <FunctionTags
                        keys={COLLABORATOR_FUNCTIONS
                          .filter((fn) => role[fn.key])
                          .map((fn) => fn.key)}
                        labels={functionLabel}
                      />
                    </td>
                    <td>{role.collaborator_count}</td>
                    <td>
                      <div className="table-actions">
                        <button
                          className="secondary-button small"
                          onClick={() => {
                            setForm({ ...role });
                            setNotice(null);
                            window.scrollTo(0, 0);
                          }}
                        >
                          Edit
                        </button>
                        <button
                          className="danger-button small"
                          onClick={() => deleteRole(role)}
                        >
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

        <Notice notice={listNotice} />
      </section>

    </div>
  );
}

export default CollaboratorRoles;
