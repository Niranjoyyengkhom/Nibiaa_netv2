// Small building blocks shared by the pages

import React, { Component, useEffect, useRef, useState } from "react";


// Drafts (decoder code, test payloads, ...) are kept per browser tab, so
// switching pages does not lose them. Cleared on sign out.
const DRAFT_PREFIX = "nb-draft:";

function readDraft(key, initial) {
  try {
    const stored = sessionStorage.getItem(DRAFT_PREFIX + key);
    return stored === null ? initial : JSON.parse(stored);
  } catch {
    return initial;
  }
}

export function usePersistentState(key, initial) {
  const [value, setValue] = useState(() => readDraft(key, initial));

  useEffect(() => {
    try {
      sessionStorage.setItem(DRAFT_PREFIX + key, JSON.stringify(value));
    } catch {
      // Storage full or blocked: the draft lives until the page changes
    }
  }, [key, value]);

  return [value, setValue];
}

export function clearDrafts() {
  try {
    Object.keys(sessionStorage)
      .filter((key) => key.startsWith(DRAFT_PREFIX))
      .forEach((key) => sessionStorage.removeItem(key));
  } catch {
    // Nothing stored
  }
}


// Dialog over the page. Closes with Escape, the × button or a click outside.
export function Modal({ title, subtitle, onClose, children, footer, wide = false }) {
  const dialogRef = useRef(null);

  useEffect(() => {
    function onKeyDown(event) {
      if (event.key === "Escape") {
        onClose();
      }
    }

    const previousFocus = document.activeElement;
    document.addEventListener("keydown", onKeyDown);
    document.body.classList.add("modal-open");
    dialogRef.current?.focus();

    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.classList.remove("modal-open");
      previousFocus?.focus?.();
    };
  }, [onClose]);

  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div
        className={`modal ${wide ? "modal-wide" : ""}`}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        ref={dialogRef}
      >
        <header className="modal-header">
          <div>
            <h2>{title}</h2>
            {subtitle && <p>{subtitle}</p>}
          </div>
          <button type="button" className="icon-button" onClick={onClose} aria-label="Close">
            ×
          </button>
        </header>

        <div className="modal-body">{children}</div>

        {footer && <footer className="modal-footer">{footer}</footer>}
      </div>
    </div>
  );
}


export function PageHeader({ title, description, children }) {
  return (
    <header className="header">
      <div>
        <h1>{title}</h1>
        {description && <p>{description}</p>}
      </div>

      {children && (
        <div className="header-actions">
          {children}
        </div>
      )}
    </header>
  );
}


// notice = { type: "success" | "error" | "info", text } or null
export function Notice({ notice }) {
  if (!notice || !notice.text) {
    return null;
  }

  return (
    <div className={`message ${notice.type || "info"}`}>
      {notice.text}
    </div>
  );
}


export function Restricted({ title = "Access restricted", children }) {
  return (
    <div className="access-denied">
      <strong>{title}</strong>
      <p>{children}</p>
    </div>
  );
}


export function RoleBadge({ role }) {
  return (
    <span className={`badge ${role}`}>
      {role}
    </span>
  );
}


export function StatusPill({ active, activeText = "Active", inactiveText = "Revoked" }) {
  return (
    <span className={`pill ${active ? "pill-ok" : "pill-off"}`}>
      {active ? activeText : inactiveText}
    </span>
  );
}


export function FunctionTags({ keys, labels }) {
  if (!keys || keys.length === 0) {
    return <span className="muted">None</span>;
  }

  return (
    <div className="tag-list">
      {keys.map((key) => (
        <span className="tag" key={key}>
          {labels ? labels(key) : key}
        </span>
      ))}
    </div>
  );
}


export class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null, errorInfo: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    console.error("ErrorBoundary caught an error:", error, errorInfo);
    this.setState({ errorInfo });
  }

  handleReset = () => {
    clearDrafts();
    try {
      sessionStorage.clear();
      localStorage.removeItem("authToken");
      localStorage.removeItem("nb-workspace");
    } catch {}
    this.setState({ hasError: false, error: null, errorInfo: null });
    window.location.reload();
  };

  render() {
    if (this.state.hasError) {
      return (
        <div
          style={{
            padding: "32px",
            maxWidth: "600px",
            margin: "40px auto",
            background: "var(--surface, #1e293b)",
            borderRadius: "12px",
            border: "1px solid var(--border-color, #334155)",
            color: "var(--text, #f8fafc)",
          }}
        >
          <h2 style={{ margin: "0 0 12px 0", color: "#ef4444" }}>⚠️ Something went wrong</h2>
          <p
            style={{
              margin: "0 0 16px 0",
              fontSize: "0.95rem",
              lineHeight: "1.5",
              color: "var(--text-secondary, #94a3b8)",
            }}
          >
            An unexpected error occurred while rendering this page:
          </p>
          <pre
            style={{
              padding: "12px",
              background: "rgba(0,0,0,0.3)",
              borderRadius: "6px",
              fontSize: "0.85rem",
              overflowX: "auto",
              color: "#fca5a5",
              marginBottom: "12px",
              whiteSpace: "pre-wrap",
            }}
          >
            {this.state.error?.message || String(this.state.error)}
          </pre>
          {this.state.error?.stack && (
            <details style={{ marginBottom: "16px", fontSize: "0.75rem", color: "var(--muted, #94a3b8)" }}>
              <summary style={{ cursor: "pointer", marginBottom: "6px" }}>View stack trace</summary>
              <pre style={{ background: "rgba(0,0,0,0.4)", padding: "8px", borderRadius: "4px", overflowX: "auto" }}>
                {this.state.error.stack}
                {this.state.errorInfo?.componentStack}
              </pre>
            </details>
          )}
          <div style={{ display: "flex", gap: "10px" }}>
            <button
              type="button"
              className="primary-button"
              onClick={this.handleReset}
            >
              Reset Drafts & Reload
            </button>
            <button
              type="button"
              className="secondary-button"
              onClick={() => {
                this.setState({ hasError: false, error: null, errorInfo: null });
                window.location.reload();
              }}
            >
              Try Again
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}


// -------------------------------------------------------------
// Universal Raw Payload Inspector & Components
// Decodes and displays raw payloads regardless of JSON, Base64, Binary, or Hex
// -------------------------------------------------------------

export function inspectPayload(input) {
  let raw = "";
  let hex = "";
  let formatHint = "";

  if (typeof input === "string") {
    raw = input.trim();
  } else if (input && typeof input === "object") {
    hex = String(input.payloadHex || input.raw_payload_hex || input.hex || "").trim();
    raw = input.rawPayload || input.raw_payload || input.payload || "";
    formatHint = String(
      input.payloadFormat ||
      input.payload_format ||
      input.format ||
      input.context?.payloadFormat ||
      input.context?.format ||
      ""
    ).toLowerCase();
  }

  // 1. Direct Object (JSON)
  if (raw && typeof raw === "object") {
    const jsonStr = JSON.stringify(raw, null, 2);
    return {
      type: "JSON",
      display: jsonStr,
      summary: JSON.stringify(raw),
      hex: hex || "",
      isJson: true,
      bytes: new TextEncoder().encode(jsonStr).length,
    };
  }

  raw = String(raw).trim();

  // 2. Direct JSON string
  if (raw && ((raw.startsWith("{") && raw.endsWith("}")) || (raw.startsWith("[") && raw.endsWith("]")))) {
    try {
      const parsed = JSON.parse(raw);
      return {
        type: "JSON",
        display: JSON.stringify(parsed, null, 2),
        summary: raw,
        hex: hex || "",
        isJson: true,
        bytes: new TextEncoder().encode(raw).length,
      };
    } catch {}
  }

  // 3. Hex check and UTF-8 / JSON inspection
  const targetHex = (hex || (/^[0-9a-fA-F\s]+$/.test(raw) && raw.length % 2 === 0 ? raw : "")).replace(/\s+/g, "");
  if (targetHex && targetHex.length >= 2 && targetHex.length % 2 === 0) {
    try {
      const byteArr = new Uint8Array(targetHex.match(/.{1,2}/g).map((b) => parseInt(b, 16)));
      const textDecoder = new TextDecoder("utf-8", { fatal: true });
      const decodedUtf8 = textDecoder.decode(byteArr);

      if (/^[\x20-\x7E\t\r\n\u00A0-\uFFFF]+$/.test(decodedUtf8)) {
        try {
          const parsed = JSON.parse(decodedUtf8);
          return {
            type: "JSON",
            display: JSON.stringify(parsed, null, 2),
            summary: decodedUtf8,
            hex: targetHex.toUpperCase(),
            isJson: true,
            bytes: byteArr.length,
          };
        } catch {
          return {
            type: "TEXT",
            display: decodedUtf8,
            summary: decodedUtf8,
            hex: targetHex.toUpperCase(),
            isText: true,
            bytes: byteArr.length,
          };
        }
      }
    } catch {
      // Not valid UTF-8
    }

    if (formatHint === "binary" && /^[01\s]+$/.test(raw)) {
      return {
        type: "BIN",
        display: raw,
        summary: raw,
        hex: targetHex.toUpperCase(),
        bytes: targetHex.length / 2,
      };
    }

    if (
      formatHint === "base64" ||
      (raw && /^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(raw) && !/^[0-9a-fA-F]+$/.test(raw))
    ) {
      return {
        type: "BASE64",
        display: raw,
        summary: raw,
        hex: targetHex.toUpperCase(),
        bytes: targetHex.length / 2,
      };
    }

    const formattedHex = targetHex.toUpperCase().match(/.{1,2}/g)?.join(" ") || targetHex.toUpperCase();
    return {
      type: "HEX",
      display: formattedHex,
      summary: formattedHex,
      hex: targetHex.toUpperCase(),
      bytes: targetHex.length / 2,
    };
  }

  // 4. Fallback strings
  if (raw) {
    if (/^[01\s]+$/.test(raw) && raw.replace(/\s+/g, "").length % 8 === 0) {
      return {
        type: "BIN",
        display: raw,
        summary: raw,
        hex: "",
        bytes: raw.replace(/\s+/g, "").length / 8,
      };
    }
    if (/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(raw)) {
      return {
        type: "BASE64",
        display: raw,
        summary: raw,
        hex: "",
        bytes: Math.floor(raw.length * 0.75),
      };
    }
    return {
      type: formatHint ? formatHint.toUpperCase() : "RAW",
      display: raw,
      summary: raw,
      hex: "",
      bytes: new TextEncoder().encode(raw).length,
    };
  }

  return {
    type: "EMPTY",
    display: "—",
    summary: "—",
    hex: "",
    bytes: 0,
  };
}

export function RawPayloadBadge({ type }) {
  const colors = {
    JSON: { bg: "rgba(16, 185, 129, 0.15)", text: "#10b981", border: "rgba(16, 185, 129, 0.3)" },
    HEX: { bg: "rgba(59, 130, 246, 0.15)", text: "#3b82f6", border: "rgba(59, 130, 246, 0.3)" },
    BASE64: { bg: "rgba(245, 158, 11, 0.15)", text: "#f59e0b", border: "rgba(245, 158, 11, 0.3)" },
    BIN: { bg: "rgba(139, 92, 246, 0.15)", text: "#8b5cf6", border: "rgba(139, 92, 246, 0.3)" },
    TEXT: { bg: "rgba(14, 165, 233, 0.15)", text: "#0ea5e9", border: "rgba(14, 165, 233, 0.3)" },
  };
  const c = colors[type] || { bg: "rgba(148, 163, 184, 0.15)", text: "#94a3b8", border: "rgba(148, 163, 184, 0.3)" };
  return (
    <span
      className="payload-format-pill"
      style={{
        display: "inline-block",
        fontSize: "0.68rem",
        fontWeight: 700,
        padding: "1px 6px",
        borderRadius: "4px",
        background: c.bg,
        color: c.text,
        border: `1px solid ${c.border}`,
        marginRight: "6px",
        textTransform: "uppercase",
        letterSpacing: "0.5px",
        verticalAlign: "middle",
      }}
    >
      {type}
    </span>
  );
}

export function RawPayloadCell({ message, maxChars = 38 }) {
  const info = inspectPayload(message);
  if (info.type === "EMPTY") {
    return <span className="muted">—</span>;
  }
  const summaryText = info.summary.length > maxChars
    ? info.summary.substring(0, maxChars) + "…"
    : info.summary;

  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        maxWidth: "280px",
        overflow: "hidden",
        textOverflow: "ellipsis",
        whiteSpace: "nowrap",
        fontFamily: info.isJson || info.type === "HEX" || info.type === "BIN" ? "monospace" : "inherit",
        fontSize: "0.82rem",
      }}
      title={info.display}
    >
      <RawPayloadBadge type={info.type} />
      <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {summaryText}
      </span>
    </span>
  );
}

export function RawPayloadBlock({ message }) {
  const info = inspectPayload(message);
  const [viewMode, setViewMode] = useState("auto");

  if (info.type === "EMPTY") {
    return <pre className="code-view">—</pre>;
  }

  const hasHex = Boolean(info.hex);
  const formattedHex = info.hex.match(/.{1,2}/g)?.join(" ") || info.hex;

  return (
    <div style={{ marginTop: "6px", marginBottom: "16px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "6px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
          <RawPayloadBadge type={info.type} />
          {info.bytes > 0 && (
            <span className="muted small-text">
              {info.bytes} byte{info.bytes === 1 ? "" : "s"}
            </span>
          )}
        </div>
        {hasHex && info.type !== "HEX" && (
          <div style={{ display: "flex", gap: "6px" }}>
            <button
              type="button"
              className={viewMode === "auto" ? "tab active" : "tab"}
              style={{ fontSize: "0.75rem", padding: "2px 8px" }}
              onClick={() => setViewMode("auto")}
            >
              Raw ({info.type})
            </button>
            <button
              type="button"
              className={viewMode === "hex" ? "tab active" : "tab"}
              style={{ fontSize: "0.75rem", padding: "2px 8px" }}
              onClick={() => setViewMode("hex")}
            >
              Hex
            </button>
          </div>
        )}
      </div>
      <pre
        className="code-view"
        style={{
          maxHeight: "220px",
          overflowY: "auto",
          whiteSpace: "pre-wrap",
          wordBreak: "break-all",
          fontSize: "0.88rem",
          margin: 0,
        }}
      >
        {viewMode === "hex" ? formattedHex : info.display}
      </pre>
    </div>
  );
}


// Reusable Pagination Component with items-per-page, page jump, and indicators
export function Pagination({
  page = 1,
  totalPages = 1,
  totalItems = 0,
  pageSize = 25,
  onPageChange,
  onPageSizeChange,
  pageSizeOptions = [10, 25, 50, 100],
  loading = false,
  itemLabel = "items",
}) {
  if (!totalItems || totalItems <= 0) {
    return null;
  }

  const startItem = (page - 1) * pageSize + 1;
  const endItem = Math.min(page * pageSize, totalItems);

  // Generate page numbers with ellipsis
  const getPageNumbers = () => {
    const pages = [];
    const maxVisible = 5;

    if (totalPages <= maxVisible + 2) {
      for (let i = 1; i <= totalPages; i++) pages.push(i);
    } else {
      pages.push(1);
      let left = Math.max(2, page - 1);
      let right = Math.min(totalPages - 1, page + 1);

      if (page <= 3) {
        right = 4;
      }
      if (page >= totalPages - 2) {
        left = totalPages - 3;
      }

      if (left > 2) pages.push("...");
      for (let i = left; i <= right; i++) pages.push(i);
      if (right < totalPages - 1) pages.push("...");
      pages.push(totalPages);
    }
    return pages;
  };

  const pageNumbers = getPageNumbers();

  return (
    <div className="pagination-bar">
      <div className="pagination-info">
        Showing <strong>{startItem.toLocaleString()}</strong>–<strong>{endItem.toLocaleString()}</strong> of{" "}
        <strong>{totalItems.toLocaleString()}</strong> {itemLabel}
      </div>

      <div className="pagination-controls">
        {onPageSizeChange && (
          <div className="pagination-size">
            <label htmlFor="pagination-size-select">Per page:</label>
            <select
              id="pagination-size-select"
              value={pageSize}
              onChange={(e) => onPageSizeChange(Number(e.target.value))}
              disabled={loading}
            >
              {pageSizeOptions.map((opt) => (
                <option key={opt} value={opt}>
                  {opt}
                </option>
              ))}
            </select>
          </div>
        )}

        <div className="pagination-buttons">
          <button
            type="button"
            className="pagination-btn"
            disabled={page <= 1 || loading}
            onClick={() => onPageChange(1)}
            aria-label="First page"
            title="First page"
          >
            «
          </button>
          <button
            type="button"
            className="pagination-btn"
            disabled={page <= 1 || loading}
            onClick={() => onPageChange(page - 1)}
            aria-label="Previous page"
            title="Previous page"
          >
            ‹ Prev
          </button>

          {pageNumbers.map((p, idx) =>
            p === "..." ? (
              <span key={`ellipsis-${idx}`} className="pagination-ellipsis">
                …
              </span>
            ) : (
              <button
                key={p}
                type="button"
                className={`pagination-btn ${p === page ? "active" : ""}`}
                disabled={loading}
                onClick={() => onPageChange(p)}
                aria-label={`Page ${p}`}
                aria-current={p === page ? "page" : undefined}
              >
                {p}
              </button>
            )
          )}

          <button
            type="button"
            className="pagination-btn"
            disabled={page >= totalPages || loading}
            onClick={() => onPageChange(page + 1)}
            aria-label="Next page"
            title="Next page"
          >
            Next ›
          </button>
          <button
            type="button"
            className="pagination-btn"
            disabled={page >= totalPages || loading}
            onClick={() => onPageChange(totalPages)}
            aria-label="Last page"
            title="Last page"
          >
            »
          </button>
        </div>
      </div>
    </div>
  );
}

