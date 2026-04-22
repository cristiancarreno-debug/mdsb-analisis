#!/usr/bin/env python3
"""
Extrae incidencias en curso (sin subtareas, epics, iniciativas, upstream)
de GD941 y GD981 y genera reporte HTML unificado con filtros multi-checkbox.

v4: UX mejorada - filtros en layout grid, búsqueda separada, botón limpiar,
    active tags, paneles responsivos
"""
import urllib.request, urllib.parse, json, base64, time, os
from datetime import datetime

USER = os.environ.get("JIRA_USER", "")
TOKEN = os.environ.get("JIRA_TOKEN", "")
if not USER or not TOKEN:
    # Fallback: try to read from local config
    _cfg = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env.local")
    if os.path.exists(_cfg):
        for line in open(_cfg):
            if line.startswith("JIRA_USER="): USER = line.strip().split("=",1)[1]
            if line.startswith("JIRA_TOKEN="): TOKEN = line.strip().split("=",1)[1]
    if not USER or not TOKEN:
        print("⚠ Set JIRA_USER and JIRA_TOKEN env vars or create .env.local")
        exit(1)
BASE_URL = "https://jirasegurosbolivar.atlassian.net"
AUTH = base64.b64encode(f"{USER}:{TOKEN}".encode()).decode()

PROJECTS = [
    {"key": "GD941", "equipo": "EO Cumplimiento"},
    {"key": "GD981", "equipo": "Evolutivos Plataforma"},
]

TYPE_MAP = {
    "Error Productivo": "Incidente",
    "Defecto QA":       "Incidente",
    "Historia":         "Mejora",
    "Spike":            "Spike",
    "Bug":              "Incidente",
    "Task":             "Tarea",
    "Story":            "Mejora",
}

OUTPUT_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "incidencias_en_curso.json")
OUTPUT_HTML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "extracto-incidencias-en-curso.html")


def fetch_jql_page(jql, next_page_token=None, max_results=100):
    params = {
        "jql": jql,
        "maxResults": max_results,
        "fields": "summary,assignee,status,created,updated,priority,issuetype,parent",
    }
    if next_page_token:
        params["nextPageToken"] = next_page_token
    url = f"{BASE_URL}/rest/api/3/search/jql?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Basic {AUTH}",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"  ⚠ Error: {e}", flush=True)
        return {"issues": [], "isLast": True}


def classify_type(issuetype):
    return TYPE_MAP.get(issuetype, issuetype)


def fetch_all_issues(project_key, equipo):
    jql = (
        f"project = {project_key} "
        f'AND issuetype != Sub-tarea AND issuetype != "Sub-task" '
        f'AND issuetype != Epic AND issuetype != Iniciativa '
        f'AND issuetype != Upstream '
        f"AND status != Done AND status != Closed AND status != Cancelado "
        f"AND status != Cancelled AND status != Resolved "
        f'AND status != "Hecho" AND status != "Cerrado" AND status != "Producción" '
        f"ORDER BY created DESC"
    )
    print(f"\n📋 Consultando {project_key} ({equipo})...", flush=True)
    all_issues, next_token, page = [], None, 0
    while True:
        page += 1
        result = fetch_jql_page(jql, next_page_token=next_token)
        issues = result.get("issues", [])
        is_last = result.get("isLast", True)
        next_token = result.get("nextPageToken")
        for issue in issues:
            f = issue["fields"]
            assignee = f.get("assignee")
            a_name = assignee.get("displayName", "Sin asignar") if assignee else "Sin asignar"
            created = f.get("created", "")
            if created:
                try:
                    dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                    c_fmt = dt.strftime("%d/%m/%Y")
                except Exception:
                    c_fmt = created[:10]
            else:
                c_fmt = "—"
            itype = f.get("issuetype", {}).get("name", "")
            parent = f.get("parent")
            if parent:
                ek = parent.get("key", "")
                es = parent.get("fields", {}).get("summary", "")
                epic = f"{ek} - {es}" if ek else "Sin épica"
            else:
                epic = "Sin épica"
            all_issues.append({
                "key": issue["key"], "summary": f.get("summary", ""),
                "assignee": a_name, "created": c_fmt, "created_raw": created,
                "status": f.get("status", {}).get("name", ""),
                "issuetype": itype, "tipo": classify_type(itype),
                "project": project_key, "equipo": equipo, "epic": epic,
            })
        print(f"  Página {page}: +{len(issues)} (acumulado: {len(all_issues)})", flush=True)
        if is_last or not next_token or not issues:
            break
        time.sleep(0.3)
    return all_issues


def format_date_now():
    now = datetime.now()
    m = ["enero","febrero","marzo","abril","mayo","junio",
         "julio","agosto","septiembre","octubre","noviembre","diciembre"]
    return f"{now.day} de {m[now.month-1]} de {now.year}, {now.strftime('%H:%M')}"

def sc(s):
    s = s.lower()
    if "progress" in s or "curso" in s or "desarrollo" in s: return "#2196F3"
    if "review" in s or "revisión" in s or "qa" in s or "test" in s: return "#ff9800"
    if "to do" in s or "backlog" in s or "abierto" in s or "open" in s or "hacer" in s: return "#9e9e9e"
    if "block" in s or "impedido" in s: return "#c0392b"
    if "wait" in s or "espera" in s or "pending" in s: return "#e67e22"
    return "#607d8b"

def tc(t):
    t = t.lower()
    if "incidente" in t: return "#e53935"
    if "mejora" in t: return "#43a047"
    if "spike" in t: return "#8e24aa"
    return "#607d8b"

def ec(e):
    if "Cumplimiento" in e: return "#1565c0"
    if "Plataforma" in e: return "#2e7d32"
    return "#607d8b"


def esc(s):
    return s.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace('"','&quot;')


# ─── RICE Analysis for EO Cumplimiento ───────────────────────────────
# Context: Seguros de Cumplimiento en Colombia (Ley 80/1993, Ley 1150/2007,
# Decreto 1082/2015, Estatuto Orgánico del Sistema Financiero).
# Amparos: Cumplimiento del contrato, Pago de salarios/prestaciones,
# Estabilidad de obra, Calidad del bien/servicio, Correcto manejo del anticipo,
# Responsabilidad Civil Extracontractual (RC).

def rice_analyze(issue):
    """
    Aplica framework RICE a cualquier incidencia.
    Contexto legal: Seguros de Cumplimiento Colombia (Ley 80/1993, Ley 1150/2007,
    Decreto 1082/2015, Estatuto Orgánico del Sistema Financiero, normativa SFC).

    Reach: 1-100 (usuarios/pólizas afectadas por periodo)
    Impact: 3=Masivo, 2=Alto, 1=Medio, 0.5=Bajo, 0.25=Mínimo
    Confidence: 1.0=Alta, 0.8=Media, 0.5=Baja
    Effort: personas-mes (mayor = menor score)
    """
    s = issue["summary"].lower()
    tipo = issue["tipo"]
    status = issue["status"]
    equipo = issue.get("equipo", "")

    # ── Fase 1: Conocimiento - Identificar riesgo legal/negocio ──
    if any(x in s for x in ["emisión", "emision", "cliente restringido"]):
        risk = "emisión"
        reach, impact, confidence, effort = 60, 2, 0.8, 2
    elif any(x in s for x in ["anulacion", "anulación"]):
        risk = "anulación"
        reach, impact, confidence, effort = 40, 2, 0.8, 1.5
    elif any(x in s for x in ["reaseguro"]):
        risk = "reaseguro"
        reach, impact, confidence, effort = 30, 3, 0.8, 3
    elif any(x in s for x in ["sarlaft", "lavado", "laft"]):
        # SARLAFT = riesgo regulatorio crítico (SFC, UIAF)
        risk = "SARLAFT/cumplimiento normativo"
        reach, impact, confidence, effort = 80, 3, 0.8, 3
    elif any(x in s for x in ["prima", "tasa", "facturación", "facturacion", "cruce", "recálculo", "recalculo"]):
        risk = "primas/tasas"
        reach, impact, confidence, effort = 50, 2, 0.8, 2
    elif any(x in s for x in ["devolución", "devolucion"]):
        risk = "devolución prima"
        reach, impact, confidence, effort = 35, 2, 0.8, 2
    elif any(x in s for x in ["impresión", "impresion", "pdf", "certificado"]):
        risk = "documentación"
        reach, impact, confidence, effort = 45, 1, 0.8, 1
    elif any(x in s for x in ["documento", "adjunt", "carga de archivo", "lectura"]):
        risk = "gestión documental"
        reach, impact, confidence, effort = 35, 1, 0.8, 1.5
    elif any(x in s for x in ["endoso", "modificacion", "vigencia", "traslado"]):
        risk = "endosos"
        reach, impact, confidence, effort = 40, 2, 0.8, 2.5
    elif any(x in s for x in ["deducible", "valor asegurado"]):
        risk = "cobertura"
        reach, impact, confidence, effort = 35, 2, 0.8, 2
    elif any(x in s for x in ["retroactiv"]):
        risk = "retroactividad"
        reach, impact, confidence, effort = 50, 2, 0.8, 3
    elif any(x in s for x in ["cotización", "cotizacion", "cotizar"]):
        risk = "cotización"
        reach, impact, confidence, effort = 55, 1, 0.8, 2
    elif any(x in s for x in ["póliza", "poliza"]):
        risk = "gestión pólizas"
        reach, impact, confidence, effort = 50, 2, 0.8, 2
    elif any(x in s for x in ["comisión", "comision", "sobrecomisión", "sobrecomision", "intermediario"]):
        risk = "comisiones/intermediarios"
        reach, impact, confidence, effort = 30, 1, 0.8, 2
    elif any(x in s for x in ["parametri", "parámetro", "autogestión", "autogestion", "config"]):
        risk = "parametrización"
        reach, impact, confidence, effort = 30, 1, 0.8, 1.5
    elif any(x in s for x in ["control", "levantamiento"]):
        risk = "controles"
        reach, impact, confidence, effort = 25, 1, 0.8, 1.5
    elif any(x in s for x in ["grupo", "delima"]):
        risk = "intermediarios"
        reach, impact, confidence, effort = 20, 1, 0.8, 2
    elif any(x in s for x in ["clausulado"]):
        risk = "clausulados"
        reach, impact, confidence, effort = 30, 2, 0.8, 2
    elif any(x in s for x in ["contrato", "obligatoriedad"]):
        risk = "contratos"
        reach, impact, confidence, effort = 35, 2, 0.8, 2.5
    elif any(x in s for x in ["migra", "integra"]):
        risk = "migración/integración"
        reach, impact, confidence, effort = 25, 1, 0.5, 3
    elif any(x in s for x in ["reporte", "informe", "consulta", "trazabilidad"]):
        risk = "reportes/trazabilidad"
        reach, impact, confidence, effort = 30, 1, 0.8, 1.5
    elif any(x in s for x in ["portal", "web", "online", "link", "url"]):
        risk = "canal digital"
        reach, impact, confidence, effort = 40, 1, 0.5, 1.5
    elif any(x in s for x in ["permiso", "delegación", "delegacion", "rol", "autorización"]):
        risk = "permisos/autorización"
        reach, impact, confidence, effort = 35, 1, 0.8, 1.5
    elif any(x in s for x in ["notificación", "notificacion", "correo", "email", "envío", "envio"]):
        risk = "notificaciones"
        reach, impact, confidence, effort = 30, 0.5, 0.8, 1
    elif any(x in s for x in ["validación", "validacion", "regla", "restricción"]):
        risk = "validaciones/reglas"
        reach, impact, confidence, effort = 35, 1, 0.8, 2
    elif any(x in s for x in ["error", "401", "404", "500", "fallo", "bug"]):
        risk = "error técnico"
        reach, impact, confidence, effort = 40, 1, 0.5, 1.5
    elif any(x in s for x in ["automatización", "automatizacion", "lineamiento"]):
        risk = "automatización"
        reach, impact, confidence, effort = 15, 0.5, 0.5, 2
    elif "tronador" in s:
        risk = "plataforma core"
        reach, impact, confidence, effort = 50, 2, 0.5, 2
    elif "simon web" in s and "cumplimiento" in s:
        risk = "canal online cumplimiento"
        reach, impact, confidence, effort = 40, 1, 0.5, 1.5
    elif "simon web" in s:
        risk = "canal web"
        reach, impact, confidence, effort = 35, 1, 0.5, 1.5
    elif "test" == s.strip():
        risk = "test"
        reach, impact, confidence, effort = 1, 0.25, 0.5, 0.5
    elif tipo == "Incidente":
        risk = "incidente genérico"
        reach, impact, confidence, effort = 30, 1, 0.5, 1.5
    elif tipo == "Mejora":
        risk = "mejora funcional"
        reach, impact, confidence, effort = 25, 1, 0.5, 2
    else:
        risk = "sin clasificar"
        reach, impact, confidence, effort = 20, 0.5, 0.5, 2

    # ── Ajustes por estado ──
    if status in ("En Progreso", "En Pruebas QA", "En Pruebas UAT"):
        confidence = min(confidence + 0.2, 1.0)
    if status == "Pendiente PAP":
        confidence = min(confidence + 0.1, 1.0)
        effort = max(effort * 0.7, 0.5)
    if status == "Bloqueado":
        effort = effort * 1.5

    # ── Fase 2: Evaluación - Fórmula RICE ──
    score = round((reach * impact * confidence) / effort, 1)

    # ── Fase 3: Clasificación ──
    if score >= 40:
        priority = "Crítica"
    elif score >= 20:
        priority = "Alta"
    elif score >= 10:
        priority = "Media"
    else:
        priority = "Baja"

    return {
        "risk": risk,
        "reach": reach,
        "impact": impact,
        "confidence": confidence,
        "effort": effort,
        "score": score,
        "priority": priority,
    }


def rice_priority_color(priority):
    if priority == "Crítica": return "#b71c1c"
    if priority == "Alta": return "#e65100"
    if priority == "Media": return "#f9a825"
    if priority == "Baja": return "#2e7d32"
    return "#607d8b"


def cb_html(fid, icon, label, items, wide=False):
    """Dropdown multi-checkbox. wide=True for panels that need more space."""
    w = "340" if wide else "240"
    h = f'''<div class="fd{' fd-wide' if wide else ''}">
      <button class="fb" onclick="toggleDD('{fid}')">{icon} {label} <span class="fc" id="{fid}-c"></span><span class="arrow">▾</span></button>
      <div class="fp" id="{fid}-p" style="min-width:{w}px">
        <div class="fp-search"><input type="text" placeholder="Buscar..." oninput="searchFilter('{fid}',this.value)"></div>
        <div class="fa">
          <a href="#" onclick="tAll('{fid}',true);return false">✓ Todos</a>
          <a href="#" onclick="tAll('{fid}',false);return false">✗ Ninguno</a>
        </div>
        <div class="fl">
'''
    for item in sorted(items.keys()):
        cnt = items[item]
        safe = esc(item)
        h += f'          <label><input type="checkbox" class="fcb" data-filter="{fid}" value="{safe}" checked onchange="filterAll()"> <span class="fl-text">{safe}</span> <span class="fcnt">{cnt}</span></label>\n'
    h += '        </div>\n      </div>\n    </div>'
    return h


def generate_html(all_issues):
    gen_date = format_date_now()
    total = len(all_issues)
    st_c, tp_c, eq_c, as_c, ep_c, rice_c = {}, {}, {}, {}, {}, {}
    for i in all_issues:
        st_c[i["status"]] = st_c.get(i["status"], 0) + 1
        tp_c[i["tipo"]] = tp_c.get(i["tipo"], 0) + 1
        eq_c[i["equipo"]] = eq_c.get(i["equipo"], 0) + 1
        as_c[i["assignee"]] = as_c.get(i["assignee"], 0) + 1
        ep_c[i["epic"]] = ep_c.get(i["epic"], 0) + 1
        rice = i.get("rice")
        rp = rice["priority"] if rice else "N/A"
        rice_c[rp] = rice_c.get(rp, 0) + 1

    eo = eq_c.get("EO Cumplimiento", 0)
    ev = eq_c.get("Evolutivos Plataforma", 0)

    html = f'''<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Incidencias en Curso — Tribu Empresas</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Segoe UI',system-ui,-apple-system,sans-serif;background:#f0f2f8;color:#1a1a2e;font-size:14px;line-height:1.6}}

/* Header */
header{{background:linear-gradient(135deg,#1a237e 0%,#283593 50%,#303f9f 100%);color:#fff;padding:2rem 2.5rem;box-shadow:0 4px 20px rgba(0,0,0,.25)}}
header h1{{font-size:1.6rem;font-weight:800;letter-spacing:-.5px}}
header p{{opacity:.75;margin-top:.3rem;font-size:.85rem}}
.hstats{{display:flex;gap:1.2rem;margin-top:1.2rem;flex-wrap:wrap}}
.hs{{background:rgba(255,255,255,.1);padding:.5rem 1rem;border-radius:10px;text-align:center;backdrop-filter:blur(4px)}}
.hs strong{{font-size:1.5rem;display:block;font-weight:800}}
.hs span{{font-size:.72rem;opacity:.8}}

main{{max-width:1600px;margin:0 auto;padding:1.5rem 2rem}}
.back-link{{display:inline-block;margin-bottom:.8rem;color:#1a237e;text-decoration:none;font-size:.82rem}}
.back-link:hover{{text-decoration:underline}}

/* KPIs */
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:.8rem;margin-bottom:1.5rem}}
.kpi{{background:#fff;border-radius:10px;padding:.8rem;box-shadow:0 1px 6px rgba(0,0,0,.06);text-align:center;border-top:3px solid #1a237e;transition:transform .15s}}
.kpi:hover{{transform:translateY(-2px);box-shadow:0 4px 12px rgba(0,0,0,.1)}}
.kpi .n{{font-size:1.6rem;font-weight:800;color:#1a237e}}
.kpi .l{{color:#6c757d;font-size:.72rem;margin-top:.1rem}}

/* Filter section */
.filter-section{{background:#fff;border-radius:12px;padding:1rem 1.2rem;box-shadow:0 1px 6px rgba(0,0,0,.06);margin-bottom:1.2rem}}
.filter-row-search{{display:flex;gap:.6rem;margin-bottom:.8rem;align-items:center}}
.filter-row-search input{{flex:1;padding:.6rem 1rem;border:1.5px solid #dee2e6;border-radius:8px;font-size:.85rem;transition:border-color .2s}}
.filter-row-search input:focus{{outline:none;border-color:#1a237e;box-shadow:0 0 0 3px rgba(26,35,126,.08)}}
.clear-btn{{padding:.6rem 1rem;border:1.5px solid #dee2e6;border-radius:8px;font-size:.8rem;background:#fff;cursor:pointer;color:#6c757d;white-space:nowrap;transition:all .2s}}
.clear-btn:hover{{background:#e8eaf6;border-color:#1a237e;color:#1a237e}}
.refresh-btn{{padding:.6rem 1rem;border:1.5px solid #1a237e;border-radius:8px;font-size:.8rem;background:#e8eaf6;cursor:pointer;color:#1a237e;white-space:nowrap;transition:all .2s;font-weight:600}}
.refresh-btn:hover{{background:#1a237e;color:#fff}}
.refresh-btn:disabled{{opacity:.5;cursor:wait}}
.refresh-btn.loading{{animation:pulse 1s infinite}}
@keyframes pulse{{0%,100%{{opacity:1}}50%{{opacity:.5}}}}
.refresh-status{{font-size:.75rem;color:#6c757d;white-space:nowrap}}

.filter-row{{display:grid;grid-template-columns:repeat(6,1fr);gap:.5rem}}
@media(max-width:1100px){{.filter-row{{grid-template-columns:repeat(3,1fr)}}}}
@media(max-width:700px){{.filter-row{{grid-template-columns:1fr 1fr}}}}
@media(max-width:480px){{.filter-row{{grid-template-columns:1fr}}}}

/* Active filter tags */
.active-tags{{display:flex;flex-wrap:wrap;gap:.4rem;margin-top:.6rem;min-height:0}}
.active-tags:empty{{display:none}}
.atag{{display:inline-flex;align-items:center;gap:.3rem;padding:.15rem .5rem;background:#e8eaf6;border-radius:20px;font-size:.7rem;color:#1a237e;cursor:default}}
.atag .ax{{cursor:pointer;font-weight:700;opacity:.6;margin-left:.1rem}}
.atag .ax:hover{{opacity:1}}

/* Filter dropdowns */
.fd{{position:relative;width:100%}}
.fd-wide .fp{{min-width:360px!important}}
.fb{{width:100%;padding:.5rem .8rem;border:1.5px solid #dee2e6;border-radius:8px;font-size:.8rem;background:#fff;cursor:pointer;text-align:left;display:flex;align-items:center;gap:.4rem;transition:border-color .2s}}
.fb:hover{{border-color:#1a237e}}
.fb .arrow{{margin-left:auto;font-size:.65rem;color:#9e9e9e}}
.fc{{background:#1a237e;color:#fff;padding:0 .35rem;border-radius:8px;font-size:.65rem;display:none}}
.fp{{display:none;position:absolute;top:calc(100% + 4px);left:0;z-index:200;background:#fff;border:1px solid #dee2e6;border-radius:10px;box-shadow:0 8px 28px rgba(0,0,0,.15);max-height:340px;overflow:hidden}}
.fp.open{{display:block}}
.fp-search{{padding:.5rem .6rem;border-bottom:1px solid #f0f0f0}}
.fp-search input{{width:100%;padding:.35rem .6rem;border:1px solid #eee;border-radius:6px;font-size:.78rem}}
.fp-search input:focus{{outline:none;border-color:#1a237e}}
.fa{{padding:.4rem .6rem;border-bottom:1px solid #f0f0f0;display:flex;gap:.8rem;font-size:.75rem}}
.fa a{{color:#1a237e;text-decoration:none}}
.fa a:hover{{text-decoration:underline}}
.fl{{max-height:220px;overflow-y:auto;padding:.3rem .6rem}}
.fl label{{display:flex;align-items:center;padding:.2rem .2rem;font-size:.78rem;cursor:pointer;border-radius:4px;gap:.3rem}}
.fl label:hover{{background:#f5f5ff}}
.fl input[type=checkbox]{{margin:0;accent-color:#1a237e;flex-shrink:0}}
.fl-text{{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.fcnt{{color:#bbb;font-size:.68rem;flex-shrink:0}}

/* Table */
.table-wrap{{overflow-x:auto;border-radius:12px;box-shadow:0 1px 6px rgba(0,0,0,.06);margin-bottom:.4rem}}
table{{width:100%;border-collapse:collapse;background:#fff;font-size:.8rem}}
thead{{background:#1a237e;color:#fff;position:sticky;top:0;z-index:10}}
th{{padding:.65rem .7rem;text-align:left;font-weight:600;white-space:nowrap;cursor:pointer;user-select:none;font-size:.75rem}}
th:hover{{background:#283593}}
td{{padding:.45rem .7rem;border-bottom:1px solid #eee;vertical-align:middle}}
tr:hover td{{background:#f8f9ff}}
.badge{{display:inline-block;padding:.15rem .5rem;border-radius:20px;font-size:.68rem;font-weight:600;color:#fff;white-space:nowrap}}
.row-count{{margin-top:.4rem;color:#6c757d;font-size:.8rem;display:flex;align-items:center;gap:.5rem}}
footer{{text-align:center;padding:1.2rem;color:#9e9e9e;font-size:.78rem;border-top:1px solid #eee;margin-top:2rem}}
</style>
</head>
<body>
<header>
  <h1>📋 Incidencias en Curso — Tribu Empresas</h1>
  <p>EO Cumplimiento (GD941) · Evolutivos Plataforma (GD981)</p>
  <div class="hstats">
    <div class="hs"><strong>{total}</strong><span>Total</span></div>
    <div class="hs"><strong>{eo}</strong><span>EO Cumplimiento</span></div>
    <div class="hs"><strong>{ev}</strong><span>Evolutivos Plataforma</span></div>
    <div class="hs"><strong>{len(tp_c)}</strong><span>Tipos</span></div>
    <div class="hs"><strong>{len(ep_c)}</strong><span>Épicas</span></div>
    <div class="hs"><strong>{len(as_c)}</strong><span>Responsables</span></div>
  </div>
</header>
<main>
  <a href="index.html" class="back-link">← Volver al índice</a>
  <p style="color:#9e9e9e;font-size:.78rem;margin-bottom:1rem">Generado: {gen_date}</p>

  <div class="kpis">
'''
    for tipo in sorted(tp_c.keys()):
        html += f'    <div class="kpi"><div class="n">{tp_c[tipo]}</div><div class="l">{tipo}</div></div>\n'
    # RICE priority KPIs
    rice_order = ["Crítica", "Alta", "Media", "Baja", "N/A"]
    rice_kpi_colors = {"Crítica":"#b71c1c","Alta":"#e65100","Media":"#f9a825","Baja":"#2e7d32","N/A":"#9e9e9e"}
    for rp in rice_order:
        if rp in rice_c:
            c = rice_kpi_colors.get(rp, "#607d8b")
            html += f'    <div class="kpi" style="border-top-color:{c}"><div class="n" style="color:{c}">{rice_c[rp]}</div><div class="l">RICE {rp}</div></div>\n'

    html += '''  </div>

  <div class="filter-section">
    <div class="filter-row-search">
      <input type="text" id="searchBox" placeholder="🔍 Buscar por HU, nombre, responsable, épica..." oninput="filterAll()">
      <button class="clear-btn" onclick="clearAll()">🗑 Limpiar filtros</button>
      <button class="refresh-btn" id="refreshBtn" onclick="refreshFromJira()">🔄 Actualizar desde Jira</button>
      <span class="refresh-status" id="refreshStatus"></span>
    </div>
    <div class="filter-row">
'''
    html += '      ' + cb_html("fEquipo", "🏢", "Equipo", eq_c) + '\n'
    html += '      ' + cb_html("fTipo", "🏷", "Tipo", tp_c) + '\n'
    html += '      ' + cb_html("fStatus", "📊", "Estado", st_c) + '\n'
    html += '      ' + cb_html("fRice", "🎯", "Prioridad RICE", rice_c) + '\n'
    html += '      ' + cb_html("fAssignee", "👤", "Responsable", as_c, wide=True) + '\n'
    html += '      ' + cb_html("fEpic", "📁", "Épica", ep_c, wide=True) + '\n'

    html += '''    </div>
    <div class="active-tags" id="activeTags"></div>
  </div>

  <div class="table-wrap">
    <table id="mainTable">
      <thead>
        <tr>
          <th onclick="sortT(0)">HU ↕</th>
          <th onclick="sortT(1)">Nombre de HU ↕</th>
          <th onclick="sortT(2)">Equipo ↕</th>
          <th onclick="sortT(3)">Tipo ↕</th>
          <th onclick="sortT(4)">Épica ↕</th>
          <th onclick="sortT(5)">Responsable ↕</th>
          <th onclick="sortT(6)">Fecha Inicio ↕</th>
          <th onclick="sortT(7)">Estado ↕</th>
          <th onclick="sortT(8)">RICE ↕</th>
        </tr>
      </thead>
      <tbody>
'''
    for i in all_issues:
        s = sc(i["status"]); t = tc(i["tipo"]); e = ec(i["equipo"])
        u = f'{BASE_URL}/browse/{i["key"]}'
        sm = esc(i["summary"]); ep = esc(i["epic"]); an = esc(i["assignee"])
        rice = i.get("rice")
        if rice:
            rp = rice["priority"]
            rs = rice["score"]
            rc = rice_priority_color(rp)
            rk = rice["risk"]
            rice_td = f'<td style="text-align:center"><span class="badge" style="background:{rc}" title="Score: {rs} | R:{rice["reach"]} I:{rice["impact"]} C:{rice["confidence"]} E:{rice["effort"]} | {rk}">{rp} ({rs})</span></td>'
            rice_data = esc(rp)
        else:
            rice_td = '<td style="text-align:center;color:#ccc;font-size:.72rem">—</td>'
            rice_data = "N/A"
        html += f'''        <tr data-equipo="{esc(i["equipo"])}" data-tipo="{esc(i["tipo"])}" data-status="{esc(i["status"])}" data-assignee="{an}" data-epic="{ep}" data-rice="{rice_data}">
          <td><a href="{u}" target="_blank" style="color:#3949ab;text-decoration:none;font-weight:600">{i["key"]}</a></td>
          <td style="max-width:320px">{sm}</td>
          <td><span class="badge" style="background:{e}">{i["equipo"]}</span></td>
          <td><span class="badge" style="background:{t}">{i["tipo"]}</span></td>
          <td style="font-size:.73rem;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="{ep}">{ep}</td>
          <td style="white-space:nowrap;font-size:.78rem">{i["assignee"]}</td>
          <td style="white-space:nowrap">{i["created"]}</td>
          <td><span class="badge" style="background:{s}">{i["status"]}</span></td>
          {rice_td}
        </tr>
'''

    html += f'''      </tbody>
    </table>
  </div>
  <div class="row-count"><span id="rowCount">{total} incidencias mostradas</span></div>
'''
    html += '''
  <script>
  const FILTERS = ['fEquipo','fTipo','fStatus','fAssignee','fEpic','fRice'];
  const LABELS = {fEquipo:'Equipo',fTipo:'Tipo',fStatus:'Estado',fAssignee:'Responsable',fEpic:'Épica',fRice:'RICE'};

  function toggleDD(id) {
    document.querySelectorAll('.fp').forEach(p => { if(p.id!==id+'-p') p.classList.remove('open'); });
    document.getElementById(id+'-p').classList.toggle('open');
  }
  document.addEventListener('click', e => {
    if(!e.target.closest('.fd')) document.querySelectorAll('.fp').forEach(p=>p.classList.remove('open'));
  });

  function tAll(fid, state) {
    // Only toggle visible (not hidden by search) checkboxes
    document.querySelectorAll(`#${fid}-p .fl label`).forEach(lbl => {
      if(lbl.style.display !== 'none') lbl.querySelector('input').checked = state;
    });
    filterAll();
  }

  function searchFilter(fid, q) {
    q = q.toLowerCase();
    document.querySelectorAll(`#${fid}-p .fl label`).forEach(lbl => {
      lbl.style.display = lbl.textContent.toLowerCase().includes(q) ? '' : 'none';
    });
  }

  function getChecked(fid) {
    const r = [];
    document.querySelectorAll(`input.fcb[data-filter="${fid}"]:checked`).forEach(cb => r.push(cb.value));
    return r;
  }

  function updateCounts() {
    FILTERS.forEach(fid => {
      const all = document.querySelectorAll(`input.fcb[data-filter="${fid}"]`).length;
      const chk = document.querySelectorAll(`input.fcb[data-filter="${fid}"]:checked`).length;
      const el = document.getElementById(fid+'-c');
      if(chk < all) { el.textContent = chk + '/' + all; el.style.display = 'inline'; }
      else { el.style.display = 'none'; }
    });
  }

  function updateTags() {
    const box = document.getElementById('activeTags');
    let tags = '';
    FILTERS.forEach(fid => {
      const all = document.querySelectorAll(`input.fcb[data-filter="${fid}"]`);
      const unchecked = document.querySelectorAll(`input.fcb[data-filter="${fid}"]:not(:checked)`);
      if(unchecked.length > 0 && unchecked.length < all.length) {
        const checked = document.querySelectorAll(`input.fcb[data-filter="${fid}"]:checked`);
        checked.forEach(cb => {
          const v = cb.value;
          const short = v.length > 30 ? v.substring(0,28)+'…' : v;
          tags += `<span class="atag">${LABELS[fid]}: ${short} <span class="ax" onclick="removeTag('${fid}','${v.replace(/'/g,"\\'")}')">×</span></span>`;
        });
      } else if(unchecked.length === all.length) {
        tags += `<span class="atag" style="background:#ffebee;color:#c62828">${LABELS[fid]}: ninguno</span>`;
      }
    });
    const search = document.getElementById('searchBox').value;
    if(search) tags += `<span class="atag">Búsqueda: "${search}" <span class="ax" onclick="document.getElementById('searchBox').value='';filterAll()">×</span></span>`;
    box.innerHTML = tags;
  }

  function removeTag(fid, val) {
    document.querySelectorAll(`input.fcb[data-filter="${fid}"]`).forEach(cb => {
      if(cb.value === val) cb.checked = false;
    });
    filterAll();
  }

  function filterAll() {
    const search = document.getElementById('searchBox').value.toLowerCase();
    const sets = {};
    FILTERS.forEach(fid => sets[fid] = new Set(getChecked(fid)));
    const rows = document.querySelectorAll('#mainTable tbody tr');
    let visible = 0;
    rows.forEach(row => {
      const text = row.textContent.toLowerCase();
      const ok = (!search || text.includes(search))
        && sets.fEquipo.has(row.dataset.equipo)
        && sets.fTipo.has(row.dataset.tipo)
        && sets.fStatus.has(row.dataset.status)
        && sets.fAssignee.has(row.dataset.assignee)
        && sets.fEpic.has(row.dataset.epic)
        && sets.fRice.has(row.dataset.rice);
      row.style.display = ok ? '' : 'none';
      if(ok) visible++;
    });
    document.getElementById('rowCount').textContent = visible + ' incidencias mostradas';
    updateCounts();
    updateTags();
  }

  function clearAll() {
    document.getElementById('searchBox').value = '';
    document.querySelectorAll('input.fcb').forEach(cb => cb.checked = true);
    // Clear search inputs inside filter panels
    document.querySelectorAll('.fp-search input').forEach(inp => { inp.value = ''; });
    document.querySelectorAll('.fl label').forEach(lbl => lbl.style.display = '');
    filterAll();
  }

  let sortDirs = {};
  function sortT(col) {
    const k = 'c'+col;
    sortDirs[k] = !sortDirs[k];
    const tbody = document.querySelector('#mainTable tbody');
    const rows = Array.from(tbody.querySelectorAll('tr'));
    rows.sort((a,b) => {
      const aT = a.cells[col].textContent.trim();
      const bT = b.cells[col].textContent.trim();
      if(col===6) {
        const aD = aT.split('/').reverse().join('');
        const bD = bT.split('/').reverse().join('');
        return sortDirs[k] ? aD.localeCompare(bD) : bD.localeCompare(aD);
      }
      if(col===8) {
        const aN = parseFloat(aT.replace(/[^0-9.]/g,'')) || 0;
        const bN = parseFloat(bT.replace(/[^0-9.]/g,'')) || 0;
        return sortDirs[k] ? aN - bN : bN - aN;
      }
      return sortDirs[k] ? aT.localeCompare(bT) : bT.localeCompare(aT);
    });
    rows.forEach(r => tbody.appendChild(r));
  }

  updateCounts();

  // ── Jira Live Refresh ──
  const JIRA_BASE = "''' + BASE_URL + '''";
  const JIRA_AUTH = "Basic ''' + AUTH + '''";

  async function refreshFromJira() {
    const btn = document.getElementById('refreshBtn');
    const sts = document.getElementById('refreshStatus');
    btn.disabled = true;
    btn.classList.add('loading');
    btn.textContent = '⏳ Actualizando...';
    sts.textContent = '';
    const rows = document.querySelectorAll('#mainTable tbody tr');
    const total = rows.length;
    let updated = 0, errors = 0;
    for (let i = 0; i < rows.length; i++) {
      const row = rows[i];
      const link = row.cells[0].querySelector('a');
      if (!link) continue;
      const key = link.textContent.trim();
      sts.textContent = (i+1)+'/'+total+' — '+key+'...';
      try {
        const resp = await fetch(
          JIRA_BASE+'/rest/api/3/issue/'+key+'?fields=status,assignee,summary',
          { headers: { 'Authorization': JIRA_AUTH, 'Accept': 'application/json' } }
        );
        if (!resp.ok) { errors++; continue; }
        const data = await resp.json();
        const f = data.fields;
        const newSt = f.status ? f.status.name : '';
        if (newSt && newSt !== row.dataset.status) {
          row.dataset.status = newSt;
          const b = row.cells[7].querySelector('.badge');
          if (b) { b.textContent = newSt; b.style.background = gSC(newSt); }
          flash(row.cells[7]); updated++;
        }
        const newA = f.assignee ? f.assignee.displayName : 'Sin asignar';
        if (newA !== row.dataset.assignee) {
          row.dataset.assignee = newA;
          row.cells[5].textContent = newA;
          flash(row.cells[5]);
        }
        const newSum = f.summary || '';
        if (newSum && newSum !== row.cells[1].textContent.trim()) {
          row.cells[1].textContent = newSum;
          flash(row.cells[1]);
        }
      } catch(e) { errors++; }
      if (i % 10 === 9) await new Promise(r => setTimeout(r, 300));
    }
    btn.disabled = false;
    btn.classList.remove('loading');
    btn.textContent = '🔄 Actualizar desde Jira';
    const now = new Date().toLocaleTimeString('es-CO');
    sts.textContent = '✅ '+updated+' cambios, '+errors+' errores — '+now;
    sts.style.color = errors > 0 ? '#e65100' : '#2e7d32';
    filterAll();
  }
  function flash(el) {
    el.style.outline = '2px solid #4caf50';
    setTimeout(function(){ el.style.outline = ''; }, 3000);
  }
  function gSC(s) {
    s = s.toLowerCase();
    if (s.includes('progress') || s.includes('curso')) return '#2196F3';
    if (s.includes('qa') || s.includes('test') || s.includes('review')) return '#ff9800';
    if (s.includes('backlog') || s.includes('hacer') || s.includes('to do')) return '#9e9e9e';
    if (s.includes('block') || s.includes('impedido')) return '#c0392b';
    if (s.includes('pap') || s.includes('espera') || s.includes('pending')) return '#e67e22';
    if (s.includes('done') || s.includes('hecho') || s.includes('producción')) return '#2e7d32';
    return '#607d8b';
  }
  </script>
</main>
<footer>
'''
    html += f'  Generado automáticamente desde Jira · {gen_date} · Seguros Bolívar · Tribu Empresas\n'
    html += '</footer>\n</body>\n</html>'
    return html


def main():
    print("=" * 60)
    print("🚀 Extracción de incidencias en curso — GD941 & GD981")
    print("   v4: UX mejorada, filtros grid + tags activos")
    print("=" * 60)
    all_issues = []
    for proj in PROJECTS:
        issues = fetch_all_issues(proj["key"], proj["equipo"])
        all_issues.extend(issues)
        print(f"  ✅ {proj['key']} ({proj['equipo']}): {len(issues)} incidencias")

    # Apply RICE analysis to ALL issues
    for issue in all_issues:
        issue["rice"] = rice_analyze(issue)
    print(f"\n📊 RICE aplicado a {len(all_issues)} incidencias (100%)")

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(all_issues, f, ensure_ascii=False, indent=2)
    print(f"\n💾 JSON guardado: {OUTPUT_JSON}")
    html = generate_html(all_issues)
    os.makedirs(os.path.dirname(OUTPUT_HTML), exist_ok=True)
    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"📄 HTML guardado: {OUTPUT_HTML}")
    print(f"\n✅ Total: {len(all_issues)} incidencias en curso")
    print("=" * 60)

if __name__ == "__main__":
    main()
