import { useEffect, useState } from "react";

import { formatDate } from "./api";


// Next store-and-forward hop for the development simulator
const NEXT_HOP = {
  PENDING: "GROUND_STATION_QUEUED",
  GROUND_STATION_QUEUED: "SATELLITE_QUEUED",
  SATELLITE_QUEUED: "DEVICE_DELIVERED",
};

const HOP_LABEL = {
  GROUND_STATION_QUEUED: "Ground station received",
  SATELLITE_QUEUED: "Satellite received",
  DEVICE_DELIVERED: "Device received",
};

const FINAL_STATUSES = ["ACKNOWLEDGED", "FAILED", "EXPIRED", "CANCELLED"];


function formatValue(value, suffix = "") {
  if (value === null || value === undefined) {
    return "Not set";
  }

  if (typeof value === "boolean") {
    return value ? "Enabled" : "Disabled";
  }

  return `${value}${suffix}`;
}


function DeviceConfiguration({ api, currentUser, device, onBack }) {
  const [configuration, setConfiguration] = useState(null);
  const [commands, setCommands] = useState([]);
  const [selectedCommand, setSelectedCommand] = useState(null);

  const [frequency, setFrequency] = useState("");
  const [enabled, setEnabled] = useState("");

  const [message, setMessage] = useState("");

  // Remote configuration is a device update: admins, owners and
  // collaborators with the Manage Devices function
  const canConfigure = currentUser.permissions.manage_devices;

  const deviceUrl =
    `/devices/${encodeURIComponent(device.device_id)}`;


  // -------------------------
  // Load data
  // -------------------------

  useEffect(() => {
    if (canConfigure) {
      refresh(undefined, true);
    }
  }, [device.device_id, currentUser.id]);


  async function request(url, { method = "GET", body } = {}) {
    if (method === "POST") {
      return api.post(url, body);
    }

    if (method === "PUT") {
      return api.put(url, body);
    }

    return api.get(url);
  }


  async function refresh(
    commandId = selectedCommand?.id,
    prefillForm = false
  ) {
    try {
      const [configurationData, commandsData] =
        await Promise.all([
          request(`${deviceUrl}/configuration`),
          request(`${deviceUrl}/commands`),
        ]);

      setConfiguration(configurationData);
      setCommands(commandsData);

      // Pre-fill the form with the desired values
      if (prefillForm) {
        setFrequency(
          configurationData.desired_wake_frequency_per_day ?? ""
        );
        setEnabled(
          configurationData.desired_enabled === null
            ? ""
            : String(configurationData.desired_enabled)
        );
      }

      if (commandId) {
        setSelectedCommand(
          await request(`${deviceUrl}/commands/${commandId}`)
        );
      }

    } catch (error) {
      console.error(error);
      setMessage(error.message);
    }
  }


  // -------------------------
  // Update desired configuration
  // -------------------------

  async function saveConfiguration(event) {
    event.preventDefault();

    setMessage("");

    const body = {};

    if (frequency !== "") {
      body.wake_frequency_per_day = Number(frequency);
    }

    if (enabled !== "") {
      body.enabled = enabled === "true";
    }

    if (Object.keys(body).length === 0) {
      setMessage("Enter a wake frequency or choose enabled/disabled.");
      return;
    }

    try {
      const data = await request(`${deviceUrl}/configuration`, {
        method: "PUT",
        body,
      });

      const queued = data.queued_commands;

      setMessage(
        queued.length > 0
          ? `Desired configuration saved. ${queued.length} command(s) queued for delivery — the device will apply it when it next connects.`
          : "Desired configuration saved. No new command was needed (already confirmed or already on its way)."
      );

      await refresh(
        queued.length > 0
          ? queued[queued.length - 1].id
          : selectedCommand?.id,
        true
      );

    } catch (error) {
      setMessage(error.message);
    }
  }


  // -------------------------
  // Command details
  // -------------------------

  async function openCommand(commandId) {
    try {
      setSelectedCommand(
        await request(`${deviceUrl}/commands/${commandId}`)
      );
    } catch (error) {
      setMessage(error.message);
    }
  }


  // -------------------------
  // DEVELOPMENT: simulate delivery
  // -------------------------

  async function simulate(status) {
    setMessage("");

    try {
      await request(
        `${deviceUrl}/commands/${selectedCommand.id}/simulate`,
        {
          method: "POST",
          body: { status },
        }
      );

      await refresh(selectedCommand.id);

    } catch (error) {
      setMessage(error.message);
      await refresh(selectedCommand.id);
    }
  }


  async function cancelCommand() {
    setMessage("");

    try {
      await request(
        `${deviceUrl}/commands/${selectedCommand.id}/cancel`,
        {
          method: "POST",
          body: {},
        }
      );

      setMessage("Command cancelled. It will not be delivered to the device.");

      await refresh(selectedCommand.id);

    } catch (error) {
      setMessage(error.message);
      await refresh(selectedCommand.id);
    }
  }


  async function acknowledge(success) {
    setMessage("");

    try {
      await request(
        `${deviceUrl}/commands/${selectedCommand.id}/ack`,
        {
          method: "POST",
          body: {
            success,
            detail: success
              ? null
              : "Device rejected the command",
          },
        }
      );

      setMessage(
        success
          ? "Device acknowledged the command. Confirmed configuration updated."
          : "Device rejected the command. Confirmed configuration unchanged."
      );

      await refresh(selectedCommand.id);

    } catch (error) {
      setMessage(error.message);
      await refresh(selectedCommand.id);
    }
  }


  // -------------------------
  // Render
  // -------------------------

  return (
    <div className="page">

      {/* HEADER */}

      <header className="header">

        <div>

          <h1>
            {device.device_id}
          </h1>

          <p>
            {device.name} · Remote configuration
          </p>

        </div>


        <button
          className="secondary-button"
          onClick={onBack}
        >
          ← Back to Devices
        </button>

      </header>


      {!canConfigure ? (

        <section className="card">

          <div className="access-denied">

            <strong>
              Access restricted
            </strong>

            <p>
              Configuring devices needs the Manage Devices
              function. Ask your organization owner for it.
            </p>

          </div>

        </section>

      ) : (
        <>

          {/* CURRENT CONFIGURATION */}

          <section className="card">

            <div className="section-header">

              <div>

                <h2>
                  Configuration
                </h2>

                <p>
                  Desired is what the server wants. Confirmed is
                  what the device has acknowledged.
                </p>

              </div>


              <div className="config-actions">

                {configuration && (
                  <span
                    className={
                      configuration.in_sync
                        ? "sync-badge in-sync"
                        : "sync-badge out-of-sync"
                    }
                  >
                    {configuration.in_sync
                      ? "In sync"
                      : "Waiting for device"}
                  </span>
                )}

                <button
                  className="secondary-button"
                  onClick={() => refresh()}
                >
                  Refresh
                </button>

              </div>

            </div>


            {configuration && (

              <div className="table-container">

                <table>

                  <thead>
                    <tr>
                      <th>Setting</th>
                      <th>Desired (server)</th>
                      <th>Confirmed (device)</th>
                    </tr>
                  </thead>

                  <tbody>

                    <tr>
                      <td>
                        <strong>Wake frequency</strong>
                      </td>
                      <td>
                        {formatValue(
                          configuration.desired_wake_frequency_per_day,
                          " times/day"
                        )}
                      </td>
                      <td>
                        {formatValue(
                          configuration.confirmed_wake_frequency_per_day,
                          " times/day"
                        )}
                      </td>
                    </tr>

                    <tr>
                      <td>
                        <strong>State</strong>
                      </td>
                      <td>
                        {formatValue(configuration.desired_enabled)}
                      </td>
                      <td>
                        {formatValue(configuration.confirmed_enabled)}
                      </td>
                    </tr>

                    <tr>
                      <td>
                        <strong>Last change</strong>
                      </td>
                      <td>
                        {formatDate(configuration.desired_updated_at)}
                      </td>
                      <td>
                        {formatDate(configuration.confirmed_at)}
                      </td>
                    </tr>

                    <tr>
                      <td>
                        <strong>Command in progress</strong>
                      </td>
                      <td colSpan={2}>
                        {configuration.pending_command_id ? (
                          <>
                            #{configuration.pending_command_id}{" "}
                            <span
                              className={`status-badge status-${configuration.pending_command_status}`}
                            >
                              {configuration.pending_command_status}
                            </span>
                          </>
                        ) : (
                          "None"
                        )}
                      </td>
                    </tr>

                  </tbody>

                </table>

              </div>

            )}


            {/* UPDATE FORM */}

            <form onSubmit={saveConfiguration}>

              <div className="form-grid">

                <div className="form-group">

                  <label>
                    Wake frequency (times per day)
                  </label>

                  <input
                    type="number"
                    min={1}
                    max={24}
                    placeholder="4"
                    value={frequency}
                    onChange={(e) =>
                      setFrequency(e.target.value)
                    }
                  />

                </div>


                <div className="form-group">

                  <label>
                    State
                  </label>

                  <select
                    value={enabled}
                    onChange={(e) =>
                      setEnabled(e.target.value)
                    }
                  >
                    <option value="">
                      No change
                    </option>
                    <option value="true">
                      Enabled
                    </option>
                    <option value="false">
                      Disabled
                    </option>
                  </select>

                </div>

              </div>


              {message && (
                <div className="message">
                  {message}
                </div>
              )}


              <button
                className="primary-button"
                type="submit"
              >
                Send to Device
              </button>

            </form>

          </section>


          {/* COMMANDS */}

          <section className="card">

            <div className="section-header">

              <div>

                <h2>
                  Commands
                </h2>

                <p>
                  Delivered through Server → Ground Station →
                  Satellite → Device. Select a command to see its
                  delivery history.
                </p>

              </div>

            </div>


            {commands.length === 0 ? (

              <div className="empty-state">
                No commands sent to this device yet.
              </div>

            ) : (

              <div className="table-container">

                <table>

                  <thead>
                    <tr>
                      <th>ID</th>
                      <th>Type</th>
                      <th>Payload</th>
                      <th>Status</th>
                      <th>Created</th>
                      <th>Delivered</th>
                      <th>Acknowledged</th>
                    </tr>
                  </thead>

                  <tbody>

                    {commands.map((command) => (

                      <tr
                        key={command.id}
                        className={
                          selectedCommand?.id === command.id
                            ? "command-row selected"
                            : "command-row"
                        }
                        onClick={() => openCommand(command.id)}
                      >
                        <td>
                          <strong>#{command.id}</strong>
                        </td>
                        <td>
                          {command.command_type}
                        </td>
                        <td>
                          <code>
                            {JSON.stringify(command.payload)}
                          </code>
                        </td>
                        <td>
                          <span
                            className={`status-badge status-${command.status}`}
                          >
                            {command.status}
                          </span>
                        </td>
                        <td>
                          {formatDate(command.created_at)}
                        </td>
                        <td>
                          {formatDate(command.delivered_at)}
                        </td>
                        <td>
                          {formatDate(command.acknowledged_at)}
                        </td>
                      </tr>

                    ))}

                  </tbody>

                </table>

              </div>

            )}

          </section>


          {/* COMMAND DETAIL */}

          {selectedCommand && (

            <section className="card">

              <div className="section-header">

                <div>

                  <h2>
                    Command #{selectedCommand.id}
                  </h2>

                  <p>
                    {selectedCommand.command_type}{" "}
                    <code>
                      {JSON.stringify(selectedCommand.payload)}
                    </code>
                    {" · "}expires{" "}
                    {formatDate(selectedCommand.expires_at)}
                  </p>

                </div>

                <div className="config-actions">

                  {/* Possible until the command reaches the device */}
                  {NEXT_HOP[selectedCommand.status] && (
                    <button
                      className="secondary-button"
                      onClick={cancelCommand}
                    >
                      Cancel command
                    </button>
                  )}

                  <span
                    className={`status-badge status-${selectedCommand.status}`}
                  >
                    {selectedCommand.status}
                  </span>

                </div>

              </div>


              {/* DELIVERY HISTORY */}

              <ol className="event-timeline">

                {selectedCommand.events.map((event) => (

                  <li key={event.id}>

                    <div className="event-heading">
                      <strong>{event.location}</strong>
                      <span>→ {event.event}</span>
                    </div>

                    <div className="event-meta">
                      {formatDate(event.created_at)}
                      {event.detail && ` · ${event.detail}`}
                    </div>

                  </li>

                ))}

              </ol>


              {/* DEVELOPMENT SIMULATOR */}

              {!FINAL_STATUSES.includes(selectedCommand.status) && (

                <div className="dev-simulator">

                  <div className="schema-title">

                    <div>

                      <h3>
                        Simulate delivery
                      </h3>

                      <p>
                        The real ground station and satellite
                        integration does not exist yet. These buttons
                        stand in for it.
                      </p>

                    </div>

                    <span className="locked-badge">
                      Development only
                    </span>

                  </div>


                  <div className="test-buttons">

                    {NEXT_HOP[selectedCommand.status] && (
                      <button
                        onClick={() =>
                          simulate(NEXT_HOP[selectedCommand.status])
                        }
                      >
                        {HOP_LABEL[NEXT_HOP[selectedCommand.status]]} →
                      </button>
                    )}

                    {selectedCommand.status === "DEVICE_DELIVERED" && (
                      <>
                        <button
                          onClick={() => acknowledge(true)}
                        >
                          ✓ Device acknowledges
                        </button>

                        <button
                          onClick={() => acknowledge(false)}
                        >
                          ✗ Device rejects
                        </button>
                      </>
                    )}

                    <button
                      onClick={() => simulate("FAILED")}
                    >
                      Mark failed
                    </button>

                    <button
                      onClick={() => simulate("EXPIRED")}
                    >
                      Mark expired
                    </button>

                  </div>

                </div>

              )}

            </section>

          )}

        </>
      )}

    </div>
  );
}


export default DeviceConfiguration;
