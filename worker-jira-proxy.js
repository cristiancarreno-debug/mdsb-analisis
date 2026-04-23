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
  "http://localhost",
  "null" // file://
];

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
      return new Response(JSON.stringify({ error: "JIRA_USER and JIRA_TOKEN must be set as Worker secrets" }), {
        status: 500, headers: { ...cors, "Content-Type": "application/json" }
      });
    }
    const AUTH = btoa(`${user}:${token}`);

    const url = new URL(request.url);
    const path = url.pathname;

    if (!path.startsWith("/rest/")) {
      return new Response(JSON.stringify({ error: "Not allowed" }), {
        status: 403, headers: { ...cors, "Content-Type": "application/json" }
      });
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
      return new Response(body, {
        status: resp.status,
        headers: { ...cors, "Content-Type": "application/json" }
      });
    } catch (e) {
      return new Response(JSON.stringify({ error: e.message }), {
        status: 502, headers: { ...cors, "Content-Type": "application/json" }
      });
    }
  }
};
