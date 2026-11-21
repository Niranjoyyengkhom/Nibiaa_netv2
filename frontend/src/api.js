// One place for talking to the backend.
//
// Every request carries the signed-in user's token. A 401 means the
// token is no longer accepted (expired, or the user / organization was
// revoked), so the app signs out and shows the reason on the login page.

export const API =
  import.meta.env.VITE_API_URL ||
  (typeof window !== "undefined" && (window.location.port === "8080" || window.location.protocol === "https:" || window.location.hostname !== "localhost")
    ? "/api"
    : "http://127.0.0.1:3002");

export const DECODER_API =
  import.meta.env.VITE_DECODER_API_URL ||
  (typeof window !== "undefined" && (window.location.port === "8080" || window.location.protocol === "https:" || window.location.hostname !== "localhost")
    ? "/decoder"
    : "http://127.0.0.1:3001");

export const IAM_API =
  import.meta.env.VITE_IAM_API_URL ||
  (typeof window !== "undefined" && (window.location.port === "8080" || window.location.protocol === "https:" || window.location.hostname !== "localhost")
    ? "/iam"
    : "http://127.0.0.1:3003");


// FastAPI returns a string for HTTPException
// and a list of errors for validation failures
export function errorMessage(data, fallback = "Request failed") {
  if (!data || !data.detail) {
    return fallback;
  }

  if (Array.isArray(data.detail)) {
    return data.detail
      .map((error) => {
        const field = (error.loc || [])
          .filter((part) => part !== "body")
          .join(".");

        return field ? `${field}: ${error.msg}` : error.msg;
      })
      .join(", ");
  }

  return data.detail;
}


export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}


export function createApi(token, onUnauthorized, baseUrl = API) {
  async function request(path, { method = "GET", body, query } = {}) {
    let url = `${baseUrl}${path}`;

    if (query) {
      const params = new URLSearchParams();

      Object.entries(query).forEach(([key, value]) => {
        if (value !== undefined && value !== null && value !== "") {
          params.append(key, value);
        }
      });

      if ([...params].length > 0) {
        url += `?${params}`;
      }
    }

    const headers = { Authorization: `Bearer ${token}` };

    if (body !== undefined) {
      headers["Content-Type"] = "application/json";
    }

    const response = await fetch(url, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });

    // 204 No Content
    const data = response.status === 204
      ? null
      : await response.json().catch(() => null);

    if (response.status === 401 && onUnauthorized) {
      onUnauthorized(errorMessage(data, "Your session has expired. Please sign in again."));
    }

    if (!response.ok) {
      throw new ApiError(errorMessage(data), response.status);
    }

    if (data === null && response.status !== 204) {
      throw new ApiError("Invalid response received from server", 502);
    }

    return data;
  }

  return {
    token,
    get: (path, query) => request(path, { query }),
    post: (path, body = {}) => request(path, { method: "POST", body }),
    put: (path, body) => request(path, { method: "PUT", body }),
    patch: (path, body) => request(path, { method: "PATCH", body }),
    delete: (path) => request(path, { method: "DELETE" }),
  };
}


export function formatUtcDate(value) {
  if (!value) return "—";
  try {
    let d;
    if (typeof value === "number") {
      d = new Date(value < 1e11 ? value * 1000 : value);
    } else if (typeof value === "string") {
      let s = value.trim();
      if (!s) return "—";
      if (/^\d+$/.test(s)) {
        const num = Number(s);
        d = new Date(num < 1e11 ? num * 1000 : num);
      } else {
        if (s.includes(" ") && !s.includes("T")) {
          s = s.replace(" ", "T");
        }
        if (!s.endsWith("Z") && !/[+-]\d{2}:?\d{2}$/.test(s)) {
          s += "Z";
        }
        d = new Date(s);
      }
    } else {
      d = new Date(value);
    }

    if (isNaN(d.getTime())) return String(value);

    const year = d.getUTCFullYear();
    const month = String(d.getUTCMonth() + 1).padStart(2, "0");
    const day = String(d.getUTCDate()).padStart(2, "0");
    const hours = String(d.getUTCHours()).padStart(2, "0");
    const minutes = String(d.getUTCMinutes()).padStart(2, "0");
    const seconds = String(d.getUTCSeconds()).padStart(2, "0");
    return `${year}-${month}-${day} ${hours}:${minutes}:${seconds} UTC`;
  } catch {
    return String(value);
  }
}


export function formatDate(value) {
  return formatUtcDate(value);
}


// The functions an owner can give a collaborator (RBAC matrix)
export const COLLABORATOR_FUNCTIONS = [
  {
    key: "manage_devices",
    label: "Manage Devices",
    description: "View and update devices, including remote configuration.",
  },
  {
    key: "create_devices",
    label: "Create Devices",
    description: "Register new devices.",
  },
  {
    key: "delete_devices",
    label: "Delete Devices",
    description: "Delete devices.",
  },
  {
    key: "manage_application",
    label: "Manage Application",
    description: "View and update applications (name, decoder).",
  },
  {
    key: "read_application_traffic",
    label: "Read Application Traffic",
    description: "Read the telemetry received from the organization's devices.",
  },
  {
    key: "create_decoder",
    label: "Create Decoder",
    description: "Create decoders and new decoder versions.",
  },
  {
    key: "manage_decoder",
    label: "Manage Decoder",
    description: "View, test, activate (roll back) and delete decoders.",
  },
];

export const NO_FUNCTIONS = Object.fromEntries(
  COLLABORATOR_FUNCTIONS.map((fn) => [fn.key, false])
);

export function functionLabel(key) {
  return COLLABORATOR_FUNCTIONS.find((fn) => fn.key === key)?.label || key;
}
