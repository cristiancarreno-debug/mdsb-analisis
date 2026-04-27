/**
 * Cloudflare Worker — Jira API Proxy
 * Permite al front (GitHub Pages) hacer llamadas a Jira sin CORS issues.
 * 
 * Configurar secrets en Cloudflare Dashboard:
 *   Settings → Variables → Environment Variables:
 *   - JIRA_USER: tu email de Jira
 *   - JIRA_TOKEN: tu API token de Jira
 * 
 * Deploy: npx wrangler deploy worker-jira-proxy.js --name jira-proxy
 * O pegar en https://dash.cloudflare.com → Workers & Pages → Create
 */

const JIRA_BASE = "https://jirasegurosbolivar.atlassian.net";

// Orígenes permitidos
const ALLOWED_ORIGINS = [
  "https://cristiancarreno-debug.github.io",
  // Dashboard multi-tenant de incidencias para POs (GitHub Pages)
  "https://cristiancarreno-debug.github.io",
  "http://localhost",
  "null" // file://
];

/** @type {RegExp} Formato válido de clave de proyecto Jira */
const PROJECT_KEY_REGEX = /^[A-Z][A-Z0-9]+$/;

/** @type {RegExp} Formato válido de clave de issue Jira (ej: GD941-123) */
const ISSUE_KEY_REGEX = /^[A-Z][A-Z0-9]+-\d+$/;

/**
 * Valida que una clave de proyecto Jira tenga el formato correcto.
 * @param {string} key - Clave de proyecto a validar
 * @returns {boolean} true si la clave cumple el formato /^[A-Z][A-Z0-9]+$/
 */
function validateProjectKey(key) {
  return PROJECT_KEY_REGEX.test(key) && key.length <= 10;
}

/**
 * Valida que una clave de issue Jira tenga el formato correcto.
 * @param {string} key - Clave de issue a validar (ej: GD941-123)
 * @returns {boolean} true si la clave cumple el formato /^[A-Z][A-Z0-9]+-\d+$/
 */
function validateIssueKey(key) {
  return ISSUE_KEY_REGEX.test(key);
}

/**
 * Construye un error JSON estructurado sin exponer detalles internos.
 * @param {string} type - Tipo de error (VALIDATION_ERROR, PROXY_ERROR, NETWORK_ERROR, CONFIG_ERROR)
 * @param {number} status - Código HTTP de respuesta
 * @param {string} message - Mensaje descriptivo para el cliente
 * @returns {{ type: string, status: number, message: string }}
 */
function buildErrorResponse(type, status, message) {
  return { type, status, message };
}

/**
 * Mapea códigos de estado HTTP a mensajes amigables para el usuario.
 * @param {number} status - Código HTTP de la respuesta de Jira
 * @returns {string} Mensaje amigable
 */
function getHttpErrorMessage(status) {
  const messages = {
    400: "La solicitud contiene parámetros inválidos.",
    401: "No se pudo autenticar con el servicio de Jira.",
    403: "No tienes permisos para acceder a este recurso en Jira.",
    404: "El recurso solicitado no existe en Jira.",
    429: "Se han excedido los límites de peticiones. Intenta de nuevo en unos minutos.",
    500: "Error interno del servidor de Jira. Intenta de nuevo más tarde.",
    502: "Error de comunicación con Jira. Intenta de nuevo más tarde.",
    503: "El servicio de Jira no está disponible temporalmente.",
  };
  return messages[status] || "Error inesperado al comunicarse con Jira.";
}

/**
 * Extrae la clave de issue de un path de transición o asignación.
 * Paths soportados:
 *   /rest/api/3/issue/{key}/transitions
 *   /rest/api/3/issue/{key}/assignee
 * @param {string} path - Path de la URL
 * @returns {string|null} Clave de issue extraída o null si no aplica
 */
function extractIssueKeyFromPath(path) {
  const match = path.match(/^\/rest\/api\/3\/issue\/([^/]+)\/(transitions|assignee)$/);
  return match ? match[1] : null;
}

/**
 * Extrae claves de proyecto de los parámetros JQL en la URL.
 * Busca patrones como "project = GD941" o "project in (GD941, GD981)".
 * @param {string} search - Query string de la URL
 * @returns {string[]} Array de claves de proyecto encontradas
 */
function extractProjectKeysFromSearch(search) {
  const keys = [];
  const params = new URLSearchParams(search);
  const jql = params.get("jql") || "";

  // Patrón: project = KEY
  const singleMatch = jql.match(/project\s*=\s*"?([A-Z][A-Z0-9]+)"?/gi);
  if (singleMatch) {
    for (const m of singleMatch) {
      const key = m.match(/project\s*=\s*"?([A-Z][A-Z0-9]+)"?/i);
      if (key) keys.push(key[1]);
    }
  }

  // Patrón: project in (KEY1, KEY2, ...)
  const inMatch = jql.match(/project\s+in\s*\(([^)]+)\)/gi);
  if (inMatch) {
    for (const m of inMatch) {
      const inner = m.match(/\(([^)]+)\)/);
      if (inner) {
        const parts = inner[1].split(",").map(s => s.trim().replace(/"/g, ""));
        keys.push(...parts);
      }
    }
  }

  return keys;
}

function corsHeaders(origin) {
  const allowed = ALLOWED_ORIGINS.some(o => origin?.startsWith(o)) || origin === "null";
  return {
    "Access-Control-Allow-Origin": allowed ? origin : ALLOWED_ORIGINS[0],
    "Access-Control-Allow-Methods": "GET, POST, PUT, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "86400",
  };
}

export default {
  async fetch(request, env) {
    const origin = request.headers.get("Origin") || "";
    const cors = corsHeaders(origin);

    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: cors });
    }

    // Read credentials from Cloudflare env secrets
    const user = env.JIRA_USER;
    const token = env.JIRA_TOKEN;
    if (!user || !token) {
      return new Response(JSON.stringify(
        buildErrorResponse("CONFIG_ERROR", 500, "El proxy no está configurado correctamente. Contacta al administrador.")
      ), {
        status: 500, headers: { ...cors, "Content-Type": "application/json" }
      });
    }
    const AUTH = btoa(`${user}:${token}`);

    const url = new URL(request.url);
    const path = url.pathname;

    if (!path.startsWith("/rest/")) {
      return new Response(JSON.stringify(
        buildErrorResponse("VALIDATION_ERROR", 403, "Ruta no permitida. Solo se permiten paths /rest/.")
      ), {
        status: 403, headers: { ...cors, "Content-Type": "application/json" }
      });
    }

    // Validar clave de issue en endpoints de transiciones y asignación
    const issueKey = extractIssueKeyFromPath(path);
    if (issueKey !== null && !validateIssueKey(issueKey)) {
      return new Response(JSON.stringify(
        buildErrorResponse("VALIDATION_ERROR", 400, `Formato de clave de issue inválido: "${issueKey}". Debe cumplir el patrón PROYECTO-NUMERO (ej: GD941-123).`)
      ), {
        status: 400, headers: { ...cors, "Content-Type": "application/json" }
      });
    }

    // Validar claves de proyecto en parámetros JQL
    const projectKeys = extractProjectKeysFromSearch(url.search);
    for (const key of projectKeys) {
      if (!validateProjectKey(key)) {
        return new Response(JSON.stringify(
          buildErrorResponse("VALIDATION_ERROR", 400, `Formato de clave de proyecto inválido: "${key}". Debe contener solo letras mayúsculas y dígitos (ej: GD941).`)
        ), {
          status: 400, headers: { ...cors, "Content-Type": "application/json" }
        });
      }
    }

    const jiraUrl = `${JIRA_BASE}${path}${url.search}`;
    const headers = {
      "Authorization": `Basic ${AUTH}`,
      "Accept": "application/json",
      "Content-Type": "application/json",
    };

    const fetchOpts = { method: request.method, headers };
    if (request.method !== "GET" && request.method !== "HEAD") {
      fetchOpts.body = await request.text();
    }

    try {
      const resp = await fetch(jiraUrl, fetchOpts);
      const body = await resp.text();

      // Si Jira retorna error, devolver mensaje estructurado
      if (!resp.ok) {
        return new Response(JSON.stringify(
          buildErrorResponse("PROXY_ERROR", resp.status, getHttpErrorMessage(resp.status))
        ), {
          status: resp.status, headers: { ...cors, "Content-Type": "application/json" }
        });
      }

      return new Response(body, {
        status: resp.status,
        headers: { ...cors, "Content-Type": "application/json" }
      });
    } catch (e) {
      return new Response(JSON.stringify(
        buildErrorResponse("NETWORK_ERROR", 502, "No se pudo conectar con Jira. Verifica la conectividad e intenta de nuevo.")
      ), {
        status: 502, headers: { ...cors, "Content-Type": "application/json" }
      });
    }
  }
};
