"""Catálogo inteligente de dispositivos y compatibilidades para INFORBAXE.

Módulo independiente: se registra como Blueprint desde app.py para no
reemplazar ni reescribir las rutas existentes de la aplicación.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from functools import wraps
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, session, url_for

import database as db

log = logging.getLogger(__name__)
despiece_bp = Blueprint("despiece_inteligente", __name__)

API_BASE = "https://api.mobileapi.dev"
API_TIMEOUT = 8
MAX_SEARCH = 20
SYNC_INTERVAL_DAYS = 7
_EXTERNAL_SEARCH_CACHE = {}


def _login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapped


def _clean(value, maximum=120):
    return " ".join(str(value or "").strip().split())[:maximum]


def _norm(value):
    return _clean(value, 160).casefold()


def _safe_term(value, maximum=80):
    value = _clean(value, maximum)
    # Evita que caracteres reservados alteren filtros PostgREST.
    return re.sub(r"[,()%_*\\\"']", " ", value).strip()


def _api_key():
    return os.environ.get("MOBILEAPI_API_KEY", "").strip()


def _provider_request(path, params=None):
    key = _api_key()
    if not key:
        raise RuntimeError("La búsqueda externa no está configurada en Render.")
    url = f"{API_BASE}{path}"
    if params:
        url += "?" + urlencode(params)
    req = Request(url, headers={"Authorization": f"Token {key}", "Accept": "application/json"})
    try:
        with urlopen(req, timeout=API_TIMEOUT) as response:
            payload = response.read(2_000_000)
            return json.loads(payload.decode("utf-8"))
    except HTTPError as exc:
        if exc.code == 429:
            raise RuntimeError("El proveedor ha alcanzado el límite temporal de consultas.") from exc
        if exc.code in (401, 403):
            raise RuntimeError("La clave o el plan del proveedor no permite esta consulta.") from exc
        raise RuntimeError(f"El proveedor respondió con el error {exc.code}.") from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError("No se ha podido conectar con el catálogo externo.") from exc


def _provider_device(raw):
    brand = raw.get("brand") or raw.get("manufacturer") or raw.get("manufacturer_name") or raw.get("brand_name") or ""
    if isinstance(brand, dict):
        brand = brand.get("name") or brand.get("manufacturer_name") or ""
    model = raw.get("name") or raw.get("model") or ""
    full_name = raw.get("full_name") or (f"{brand} {model}".strip())
    model_numbers = raw.get("model_numbers") or raw.get("model_number") or ""
    if isinstance(model_numbers, str):
        model_numbers = [x.strip() for x in re.split(r"[,;|]", model_numbers) if x.strip()]
    elif not isinstance(model_numbers, list):
        model_numbers = []
    return {
        "marca": _clean(brand, 80),
        "modelo": _clean(model, 140),
        "nombre_completo": _clean(full_name, 220),
        "numero_modelo": _clean(model_numbers[0] if model_numbers else "", 100),
        "numeros_modelo": [_clean(x, 100) for x in model_numbers[:20] if _clean(x, 100)],
        "tipo": _clean(raw.get("device_type") or raw.get("type") or "phone", 30).lower(),
        "proveedor": "mobileapi",
        "proveedor_id": str(raw.get("id") or "")[:80],
    }


def _find_model(marca, modelo):
    client = db.get_db()
    rows = (client.table("despiece_modelos")
            .select("id,marca,modelo,estado,numero_modelo,numeros_modelo,origen,proveedor_id")
            .ilike("marca", marca)
            .ilike("modelo", modelo)
            .limit(1).execute().data or [])
    for row in rows:
        if _norm(row.get("marca")) == _norm(marca) and _norm(row.get("modelo")) == _norm(modelo):
            return row
    return None


def _stage_provider_device(device):
    if not device["marca"] or not device["modelo"]:
        return None, False
    existing = _find_model(device["marca"], device["modelo"])
    client = db.get_db()
    if existing:
        # No degradar un modelo aprobado a pendiente por una nueva coincidencia externa.
        update = {
            "ultimo_visto_externo": datetime.now(timezone.utc).isoformat(),
            "proveedor": device.get("proveedor", "mobileapi"),
        }
        if device.get("proveedor_id"):
            update["proveedor_id"] = device["proveedor_id"]
        if device.get("numero_modelo") and not existing.get("numero_modelo"):
            update["numero_modelo"] = device["numero_modelo"]
        client.table("despiece_modelos").update(update).eq("id", existing["id"]).execute()
        return existing, False

    payload = {
        **device,
        "estado": "pendiente",
        "origen": "proveedor_externo",
        "ultimo_visto_externo": datetime.now(timezone.utc).isoformat(),
    }
    try:
        result = client.table("despiece_modelos").insert(payload).execute().data or []
        return (result[0] if result else None), True
    except Exception:
        # Una consulta simultánea puede haber creado el mismo modelo.
        existing = _find_model(device["marca"], device["modelo"])
        if existing:
            return existing, False
        raise


def _get_models(estado=None, term="", brand="", limit=250):
    client = db.get_db()
    query = (client.table("despiece_modelos")
             .select("id,marca,modelo,nombre_completo,numero_modelo,numeros_modelo,tipo,estado,origen,created_at,aprobado_at")
             .order("marca").order("modelo").limit(min(max(int(limit), 1), 1000)))
    if estado:
        query = query.eq("estado", estado)
    clean_brand = _safe_term(brand, 80)
    clean_term = _safe_term(term, 80)
    if clean_brand:
        query = query.ilike("marca", f"*{clean_brand}*")
    if clean_term:
        query = query.or_(
            f"modelo.ilike.*{clean_term}*,nombre_completo.ilike.*{clean_term}*,"
            f"marca.ilike.*{clean_term}*,numero_modelo.ilike.*{clean_term}*"
        )
    return query.execute().data or []


def _get_sync_state():
    rows = (db.get_db().table("despiece_catalogo_sync")
            .select("id,ultimo_intento_at,ultima_sync_at,ultimo_resultado")
            .eq("id", 1).limit(1).execute().data or [])
    return rows[0] if rows else {}


def _sync_new_devices(force=False):
    if not _api_key():
        return {"enabled": False, "message": "Falta MOBILEAPI_API_KEY en Render."}

    state = _get_sync_state()
    now = datetime.now(timezone.utc)
    last_attempt = state.get("ultimo_intento_at")
    if last_attempt and not force:
        try:
            last = datetime.fromisoformat(last_attempt.replace("Z", "+00:00"))
            interval = timedelta(days=SYNC_INTERVAL_DAYS) if state.get("ultima_sync_at") else timedelta(minutes=20)
            if now - last < interval:
                return {"enabled": True, "skipped": True, "message": "El catálogo se comprobó recientemente."}
        except (TypeError, ValueError):
            pass

    # Reservar el intento antes de consultar para evitar llamadas duplicadas
    # cuando varios usuarios abren la pantalla a la vez.
    sync_table = db.get_db().table("despiece_catalogo_sync")
    sync_table.upsert({"id": 1, "ultimo_intento_at": now.isoformat()}, on_conflict="id").execute()

    year = now.year
    added = 0
    checked = 0
    # Revisar hasta 5 páginas (máximo aproximado de 50 modelos) del año actual.
    # Limita el consumo del proveedor y deja las novedades pendientes de aprobación.
    first_page = _provider_request("/devices/by-year/", {"year": year, "page": 1})
    payloads = [first_page]
    total_pages = int(first_page.get("total_pages", 1)) if isinstance(first_page, dict) else 1
    for page in range(2, min(total_pages, 5) + 1):
        payloads.append(_provider_request("/devices/by-year/", {"year": year, "page": page}))
    for payload in payloads:
        items = payload.get("devices", []) if isinstance(payload, dict) else []
        for raw in items[:50]:
            device = _provider_device(raw)
            if not device["marca"] or not device["modelo"]:
                continue
            _, created = _stage_provider_device(device)
            added += int(created)
            checked += 1

    summary = f"{checked} dispositivos revisados; {added} novedades pendientes."
    sync_table.upsert({
        "id": 1,
        "ultimo_intento_at": now.isoformat(),
        "ultima_sync_at": now.isoformat(),
        "ultimo_resultado": summary,
    }, on_conflict="id").execute()
    return {"enabled": True, "added": added, "checked": checked, "message": summary}


@despiece_bp.get("/despiece/modelos")
@_login_required
def modelos():
    term = request.args.get("q", "")[:80]
    estado = request.args.get("estado", "pendiente")
    if estado not in ("pendiente", "activo"):
        estado = "pendiente"
    pendientes = _get_models("pendiente", limit=300)
    activos = _get_models("activo", term=term, limit=1000)
    sync_state = _get_sync_state()
    return render_template(
        "despiece_modelos.html",
        pendientes=pendientes,
        activos=activos,
        q=term,
        estado=estado,
        api_configurada=bool(_api_key()),
        sync_state=sync_state,
        sincronizacion_auto=os.environ.get("MOBILEAPI_AUTO_SYNC", "true").lower() in ("1", "true", "yes", "on"),
    )


@despiece_bp.post("/api/despiece/modelos/sincronizar")
@_login_required
def api_sincronizar_modelos():
    auto_enabled = os.environ.get("MOBILEAPI_AUTO_SYNC", "true").lower() in ("1", "true", "yes", "on")
    try:
        force = bool((request.get_json(silent=True) or {}).get("force", False))
        if not auto_enabled and not force:
            return jsonify({"ok": False, "message": "La sincronización automática está desactivada. Puedes comprobarla manualmente."}), 400
        result = _sync_new_devices(force=force)
        return jsonify({"ok": True, **result})
    except Exception as exc:
        log.warning("No se pudo sincronizar el catálogo externo: %s", exc)
        return jsonify({"ok": False, "message": str(exc)}), 502


@despiece_bp.post("/api/despiece/modelos/buscar-externo")
@_login_required
def api_buscar_modelos_externos():
    term = _clean(request.json.get("q") if request.is_json else request.form.get("q"), 80)
    if len(term) < 2:
        return jsonify({"ok": False, "message": "Escribe al menos dos caracteres."}), 400
    if not _api_key():
        return jsonify({"ok": False, "message": "La búsqueda externa todavía no está configurada en Render."}), 503
    try:
        cache_key = _norm(term)
        cached = _EXTERNAL_SEARCH_CACHE.get(cache_key)
        if cached and datetime.now(timezone.utc) - cached["at"] < timedelta(minutes=15):
            return jsonify({"ok": True, "resultados": cached["resultados"], "nuevos_pendientes": cached["nuevos_pendientes"], "pendientes_en_revision": cached["pendientes_en_revision"], "cached": True})
        payload = _provider_request("/devices/autocomplete/", {"q": term, "limit": 12})
        items = payload if isinstance(payload, list) else payload.get("results", payload.get("devices", []))
        staged = []
        for raw in items[:12]:
            device = _provider_device(raw)
            if not device["marca"] or not device["modelo"]:
                continue
            row, created = _stage_provider_device(device)
            if row:
                staged.append({"id": row.get("id"), "marca": device["marca"], "modelo": device["modelo"], "nuevo": created, "estado": row.get("estado", "pendiente")})
        new_count = sum(1 for x in staged if x["nuevo"])
        pending_count = sum(1 for x in staged if x.get("estado") == "pendiente")
        cache_value = {"resultados": staged, "nuevos_pendientes": new_count, "pendientes_en_revision": pending_count}
        _EXTERNAL_SEARCH_CACHE[cache_key] = {"at": datetime.now(timezone.utc), **cache_value}
        # Evitar que el caché en memoria crezca sin límite.
        for key, entry in list(_EXTERNAL_SEARCH_CACHE.items()):
            if datetime.now(timezone.utc) - entry["at"] > timedelta(hours=1):
                _EXTERNAL_SEARCH_CACHE.pop(key, None)
        return jsonify({"ok": True, **cache_value, "cached": False})
    except Exception as exc:
        log.warning("Error consultando catálogo externo: %s", exc)
        return jsonify({"ok": False, "message": str(exc)}), 502


@despiece_bp.post("/despiece/modelos/<int:model_id>/aprobar")
@_login_required
def aprobar_modelo(model_id):
    client = db.get_db()
    result = (client.table("despiece_modelos")
              .update({"estado": "activo", "aprobado_at": datetime.now(timezone.utc).isoformat()})
              .eq("id", model_id).eq("estado", "pendiente").select("id,marca,modelo").execute())
    if not result.data:
        flash("El modelo ya no estaba pendiente o no existe.", "warning")
    else:
        # Los repuestos históricos con exactamente esa marca/modelo se enlazan,
        # pero siempre como compatibilidad pendiente de verificar.
        model = result.data[0]
        model_id = int(model["id"])
        repuestos = (client.table("despiece_repuestos").select("id")
                     .ilike("marca", model.get("marca", ""))
                     .ilike("modelo", model.get("modelo", "")).limit(500).execute().data or [])
        if repuestos:
            relations = [{"repuesto_id": row["id"], "modelo_id": model_id,
                          "estado_compatibilidad": "pendiente",
                          "notas": "Vinculado al aprobar el modelo; compatibilidad por verificar."}
                         for row in repuestos]
            client.table("despiece_repuesto_modelos").upsert(
                relations, on_conflict="repuesto_id,modelo_id"
            ).execute()
        flash("Modelo incorporado al catálogo.", "success")
    return redirect(url_for("despiece_inteligente.modelos"))


@despiece_bp.post("/despiece/modelos/<int:model_id>/ignorar")
@_login_required
def ignorar_modelo(model_id):
    client = db.get_db()
    result = (client.table("despiece_modelos")
              .update({"estado": "ignorado"})
              .eq("id", model_id).eq("estado", "pendiente").select("id").execute())
    flash("Modelo descartado." if result.data else "El modelo ya no estaba pendiente.", "success")
    return redirect(url_for("despiece_inteligente.modelos"))


@despiece_bp.post("/despiece/modelos/manual")
@_login_required
def crear_modelo_manual():
    marca = _clean(request.form.get("marca"), 80)
    modelo = _clean(request.form.get("modelo"), 140)
    numero = _clean(request.form.get("numero_modelo"), 100)
    if not marca or not modelo:
        flash("La marca y el modelo son obligatorios.", "error")
        return redirect(url_for("despiece_inteligente.modelos"))
    existing = _find_model(marca, modelo)
    if existing:
        if existing.get("estado") == "pendiente":
            flash("Ese modelo ya está pendiente de aprobación.", "warning")
        elif existing.get("estado") == "activo":
            flash("Ese modelo ya existe en tu catálogo.", "info")
        else:
            db.get_db().table("despiece_modelos").update({"estado": "activo", "origen": "manual"}).eq("id", existing["id"]).execute()
            flash("Modelo reactivado en el catálogo.", "success")
        return redirect(url_for("despiece_inteligente.modelos"))
    payload = {
        "marca": marca,
        "modelo": modelo,
        "nombre_completo": f"{marca} {modelo}",
        "numero_modelo": numero,
        "numeros_modelo": [numero] if numero else [],
        "estado": "activo",
        "origen": "manual",
        "proveedor": "manual",
        "tipo": "phone",
    }
    db.get_db().table("despiece_modelos").insert(payload).execute()
    flash("Modelo añadido al catálogo.", "success")
    return redirect(url_for("despiece_inteligente.modelos"))


@despiece_bp.get("/api/despiece/marcas")
@_login_required
def api_marcas():
    rows = (db.get_db().table("despiece_modelos")
            .select("marca").eq("estado", "activo")
            .order("marca").limit(1000).execute().data or [])
    brands = sorted({(_clean(row.get("marca"), 80)) for row in rows if _clean(row.get("marca"), 80)}, key=str.casefold)
    return jsonify({"ok": True, "marcas": brands})


@despiece_bp.get("/api/despiece/modelos/sugerencias")
@_login_required
def api_sugerencias_modelos():
    term = _clean(request.args.get("q"), 80)
    brand = _clean(request.args.get("marca"), 80)
    if len(term) < 2:
        return jsonify({"ok": True, "modelos": []})
    models = _get_models("activo", term=term, brand=brand, limit=MAX_SEARCH)
    return jsonify({"ok": True, "modelos": [
        {"id": m["id"], "marca": m["marca"], "modelo": m["modelo"], "numero_modelo": m.get("numero_modelo") or ""}
        for m in models
    ]})


@despiece_bp.get("/despiece/pieza-inteligente/nueva")
@_login_required
def nueva_pieza_inteligente():
    familias = db.get_despiece_familias()
    if not familias:
        flash("Antes de añadir piezas, crea al menos una familia.", "error")
        return redirect(url_for("despiece"))
    brand_rows = (db.get_db().table("despiece_modelos").select("marca")
                  .eq("estado", "activo").order("marca").limit(1000).execute().data or [])
    marcas = sorted({(_clean(row.get("marca"), 80)) for row in brand_rows if _clean(row.get("marca"), 80)}, key=str.casefold)
    return render_template("despiece_form_inteligente.html", familias=familias, marcas=marcas)


@despiece_bp.post("/despiece/pieza-inteligente/nueva")
@_login_required
def guardar_pieza_inteligente():
    client = db.get_db()
    try:
        familia_id = int(request.form.get("familia_id", ""))
    except (TypeError, ValueError):
        flash("Selecciona una familia válida.", "error")
        return redirect(url_for("despiece_inteligente.nueva_pieza_inteligente"))
    marca = _clean(request.form.get("marca"), 80)
    modelo = _clean(request.form.get("modelo"), 120)
    pieza = _clean(request.form.get("pieza"), 120)
    referencia = _clean(request.form.get("referencia"), 120)
    descripcion = _clean(request.form.get("descripcion"), 1000)
    try:
        valid_family = client.table("despiece_familias").select("id").eq("id", familia_id).limit(1).execute().data or []
        if not valid_family or not modelo or not pieza:
            raise ValueError("Completa una familia válida, un modelo y una pieza.")
        inserted = (client.table("despiece_repuestos").insert({
            "familia_id": familia_id,
            "marca": marca,
            "modelo": modelo,
            "pieza": pieza,
            "referencia": referencia,
            "descripcion": descripcion,
        }).execute().data or [])
        if not inserted:
            raise RuntimeError("Supabase no devolvió el repuesto creado.")
        repuesto_id = inserted[0]["id"]
        selected = []
        for raw_id in request.form.getlist("modelo_id"):
            try:
                value = int(raw_id)
            except (TypeError, ValueError):
                continue
            if value not in selected:
                selected.append(value)
        if selected:
            valid_models = (client.table("despiece_modelos").select("id")
                            .in_("id", selected).eq("estado", "activo").execute().data or [])
            valid_ids = {int(item["id"]) for item in valid_models}
            relations = [{"repuesto_id": repuesto_id, "modelo_id": model_id, "estado_compatibilidad": "pendiente"}
                         for model_id in selected if model_id in valid_ids]
            if relations:
                client.table("despiece_repuesto_modelos").insert(relations).execute()
        else:
            # Si el modelo ya existe en el catálogo, enlazarlo automáticamente como pendiente de verificación.
            existing = _find_model(marca, modelo)
            if existing and existing.get("estado") == "activo":
                client.table("despiece_repuesto_modelos").insert({
                    "repuesto_id": repuesto_id,
                    "modelo_id": existing["id"],
                    "estado_compatibilidad": "pendiente",
                }).execute()
            else:
                # La pieza no se pierde: su modelo queda en el campo tradicional y se propone al catálogo.
                if marca and modelo and not existing:
                    _stage_provider_device({
                        "marca": marca, "modelo": modelo,
                        "nombre_completo": f"{marca} {modelo}",
                        "numero_modelo": "", "numeros_modelo": [],
                        "tipo": "phone", "proveedor": "manual", "proveedor_id": "",
                    })
        flash("Pieza añadida. Revisa sus compatibilidades desde el catálogo.", "success")
        return redirect(url_for("despiece"))
    except ValueError as exc:
        flash(str(exc), "error")
    except Exception as exc:
        log.exception("No se pudo crear pieza inteligente: %s", exc)
        flash("No se ha podido guardar la pieza. Comprueba la conexión y las tablas del catálogo inteligente.", "error")
    return redirect(url_for("despiece_inteligente.nueva_pieza_inteligente"))


@despiece_bp.get("/despiece/pieza-inteligente/<int:repuesto_id>/compatibilidades")
@_login_required
def gestionar_compatibilidades(repuesto_id):
    client = db.get_db()
    piezas = (client.table("despiece_repuestos").select("id,marca,modelo,pieza,referencia")
              .eq("id", repuesto_id).limit(1).execute().data or [])
    if not piezas:
        abort(404)
    relaciones = (client.table("despiece_repuesto_modelos")
                  .select("modelo_id,estado_compatibilidad,notas")
                  .eq("repuesto_id", repuesto_id).execute().data or [])
    relaciones_map = {int(x["modelo_id"]): x for x in relaciones}
    modelos_activos = _get_models("activo", limit=1000)
    return render_template(
        "despiece_compatibilidades.html",
        repuesto=piezas[0],
        modelos=modelos_activos,
        relaciones=relaciones_map,
    )


@despiece_bp.get("/despiece/modelos/<int:model_id>/piezas")
@_login_required
def piezas_por_modelo(model_id):
    client = db.get_db()
    modelos = (client.table("despiece_modelos")
               .select("id,marca,modelo,numero_modelo")
               .eq("id", model_id).eq("estado", "activo").limit(1).execute().data or [])
    if not modelos:
        abort(404)
    links = (client.table("despiece_repuesto_modelos")
             .select("repuesto_id,estado_compatibilidad")
             .eq("modelo_id", model_id).execute().data or [])
    piezas = []
    if links:
        ids = [int(row["repuesto_id"]) for row in links]
        piezas = (client.table("despiece_repuestos")
                  .select("id,familia_id,marca,modelo,pieza,referencia,descripcion")
                  .in_("id", ids).order("pieza").execute().data or [])
    familias = {int(row["id"]): row["nombre"] for row in db.get_despiece_familias()}
    estados = {int(row["repuesto_id"]): row["estado_compatibilidad"] for row in links}
    for pieza in piezas:
        pieza["familia_nombre"] = familias.get(int(pieza.get("familia_id") or 0), "Sin familia")
        pieza["estado_compatibilidad"] = estados.get(int(pieza["id"]), "pendiente")
    return render_template("despiece_modelo_piezas.html", modelo=modelos[0], piezas=piezas)


@despiece_bp.post("/despiece/pieza-inteligente/<int:repuesto_id>/compatibilidades")
@_login_required
def guardar_compatibilidades(repuesto_id):
    client = db.get_db()
    exists = (client.table("despiece_repuestos").select("id")
              .eq("id", repuesto_id).limit(1).execute().data or [])
    if not exists:
        abort(404)
    selected = []
    for raw_id in request.form.getlist("modelo_id"):
        try:
            model_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        if model_id not in selected:
            selected.append(model_id)
    verified = set()
    for raw_id in request.form.getlist("verificado_id"):
        try:
            verified.add(int(raw_id))
        except (TypeError, ValueError):
            pass
    valid_ids = set()
    if selected:
        valid = (client.table("despiece_modelos").select("id")
                 .in_("id", selected).eq("estado", "activo").execute().data or [])
        valid_ids = {int(x["id"]) for x in valid}
    relations = [{
        "repuesto_id": repuesto_id,
        "modelo_id": model_id,
        "estado_compatibilidad": "verificada" if model_id in verified else "pendiente",
    } for model_id in selected if model_id in valid_ids]
    try:
        client.table("despiece_repuesto_modelos").delete().eq("repuesto_id", repuesto_id).execute()
        if relations:
            client.table("despiece_repuesto_modelos").insert(relations).execute()
        flash("Compatibilidades actualizadas.", "success")
    except Exception:
        log.exception("No se pudieron guardar las compatibilidades del repuesto %s", repuesto_id)
        flash("No se pudieron guardar todas las compatibilidades. Vuelve a intentarlo.", "error")
    return redirect(url_for("despiece_inteligente.gestionar_compatibilidades", repuesto_id=repuesto_id))


@despiece_bp.get("/api/despiece/repuestos/<int:repuesto_id>/compatibles")
@_login_required
def api_repuestos_compatibles(repuesto_id):
    client = db.get_db()
    rows = (client.table("despiece_repuesto_modelos")
            .select("estado_compatibilidad,despiece_modelos(id,marca,modelo,numero_modelo)")
            .eq("repuesto_id", repuesto_id).execute().data or [])
    return jsonify({"ok": True, "modelos": [
        {"marca": row.get("despiece_modelos", {}).get("marca"),
         "modelo": row.get("despiece_modelos", {}).get("modelo"),
         "numero_modelo": row.get("despiece_modelos", {}).get("numero_modelo"),
         "verificada": row.get("estado_compatibilidad") == "verificada"}
        for row in rows if row.get("despiece_modelos")
    ]})
