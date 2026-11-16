import { useCallback, useEffect, useRef, useState } from "react";

import { Icon } from "./icons";


// How often the unread count is checked while the console is open
const POLL_MS = 30000;

const TYPE_ICON = {
  device: "devices",
  application: "applications",
  decoder: "decoders",
  user: "users",
  organization: "tenants",
  command: "configuration",
};


function timeAgo(value) {
  const seconds = Math.round((Date.now() - new Date(value).getTime()) / 1000);

  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} h ago`;
  if (seconds < 604800) return `${Math.floor(seconds / 86400)} d ago`;

  return new Date(value).toLocaleDateString();
}


// Bell in the header: unread count, and the list in a dropdown
function Notifications({ api }) {
  const [open, setOpen] = useState(false);
  const [unread, setUnread] = useState(0);
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const rootRef = useRef(null);

  const refreshCount = useCallback(async () => {
    try {
      const data = await api.get("/notifications/unread-count");
      setUnread(data.unread_count);
    } catch {
      // Shown when the list is opened
    }
  }, [api]);

  const refreshList = useCallback(async () => {
    setLoading(true);
    setError("");

    try {
      const data = await api.get("/notifications/", { limit: 30 });
      setItems(data);
      setUnread(data.filter((item) => !item.is_read).length);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [api]);

  // Poll the count; also when the tab becomes visible again
  useEffect(() => {
    refreshCount();

    const timer = setInterval(() => {
      if (document.visibilityState === "visible") {
        refreshCount();
      }
    }, POLL_MS);

    const onVisible = () => document.visibilityState === "visible" && refreshCount();
    document.addEventListener("visibilitychange", onVisible);

    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [refreshCount]);

  useEffect(() => {
    if (open) {
      refreshList();
    }
  }, [open, refreshList]);

  // Close on a click outside or Escape
  useEffect(() => {
    if (!open) {
      return undefined;
    }

    function onPointer(event) {
      if (!rootRef.current?.contains(event.target)) {
        setOpen(false);
      }
    }

    function onKey(event) {
      if (event.key === "Escape") {
        setOpen(false);
      }
    }

    document.addEventListener("mousedown", onPointer);
    document.addEventListener("keydown", onKey);

    return () => {
      document.removeEventListener("mousedown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  async function markRead(item) {
    if (item.is_read) {
      return;
    }

    setItems((list) => list.map((n) => (n.id === item.id ? { ...n, is_read: true } : n)));
    setUnread((count) => Math.max(0, count - 1));

    try {
      await api.patch(`/notifications/${item.id}/read`);
    } catch {
      refreshList();
    }
  }

  async function markAllRead() {
    setItems((list) => list.map((n) => ({ ...n, is_read: true })));
    setUnread(0);

    try {
      await api.patch("/notifications/read-all");
    } catch {
      refreshList();
    }
  }

  async function remove(item) {
    setItems((list) => list.filter((n) => n.id !== item.id));

    if (!item.is_read) {
      setUnread((count) => Math.max(0, count - 1));
    }

    try {
      await api.delete(`/notifications/${item.id}`);
    } catch {
      refreshList();
    }
  }

  async function clearAll() {
    setItems([]);
    setUnread(0);

    try {
      await api.delete("/notifications/");
    } catch {
      refreshList();
    }
  }

  return (
    <div className="notifications" ref={rootRef}>
      <button
        type="button"
        className={`icon-button ${open ? "active" : ""}`}
        onClick={() => setOpen((value) => !value)}
        aria-label={unread ? `Notifications, ${unread} unread` : "Notifications"}
        aria-expanded={open}
        title="Notifications"
      >
        <Icon name="bell" size={19} />
        {unread > 0 && (
          <span className="notification-count">{unread > 99 ? "99+" : unread}</span>
        )}
      </button>

      {open && (
        <div className="notifications-panel" role="dialog" aria-label="Notifications">
          <div className="notifications-header">
            <div>
              <strong>Notifications</strong>
              <span>{unread ? `${unread} unread` : "All caught up"}</span>
            </div>

            {items.length > 0 && (
              <div className="notifications-actions">
                <button type="button" className="text-button" onClick={markAllRead} disabled={!unread}>
                  Mark all read
                </button>
                <button type="button" className="text-button danger" onClick={clearAll}>
                  Clear
                </button>
              </div>
            )}
          </div>

          <div className="notifications-list">
            {error ? (
              <div className="notifications-empty">{error}</div>
            ) : loading && items.length === 0 ? (
              <div className="notifications-empty">Loading…</div>
            ) : items.length === 0 ? (
              <div className="notifications-empty">
                <Icon name="bell" size={26} />
                <p>No notifications yet.</p>
                <span>Device, application, decoder and access changes show up here.</span>
              </div>
            ) : (
              items.map((item) => (
                <div
                  key={item.id}
                  className={`notification-item ${item.is_read ? "" : "unread"}`}
                  onClick={() => markRead(item)}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && markRead(item)}
                >
                  <span className={`notification-icon type-${item.notification_type}`}>
                    <Icon name={TYPE_ICON[item.notification_type] || "bell"} size={16} />
                  </span>

                  <div className="notification-copy">
                    <strong>{item.title}</strong>
                    <p>{item.message}</p>
                    <time dateTime={item.created_at} title={new Date(item.created_at).toLocaleString()}>
                      {timeAgo(item.created_at)}
                    </time>
                  </div>

                  <button
                    type="button"
                    className="notification-remove"
                    aria-label="Remove notification"
                    title="Remove"
                    onClick={(e) => {
                      e.stopPropagation();
                      remove(item);
                    }}
                  >
                    ×
                  </button>
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default Notifications;
