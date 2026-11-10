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
from urllib.parse import urlencode, quote_plus, urlparse, parse_qs, unquote, urljoin
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from concurrent.futures import ThreadPoolExecutor, as_completed
from html import unescape
from html.parser import HTMLParser
import time
import unicodedata
import xml.etree.ElementTree as ET
import math

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


def _api_login_required(fn):
    """Como _login_required, pero responde JSON (un redirect HTML rompe response.json() en el navegador)."""
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not session.get("logged_in"):
            return jsonify({"ok": False, "message": "La sesión ha caducado. Vuelve a iniciar sesión.",
                            "sources": [], "models": []}), 401
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
        try:
            saved_research, research_warning = _save_research_selection(
                client, repuesto_id, referencia,
                request.form.get("investigacion_token", ""), request.form.get("investigacion_indices", "[]"))
        except Exception:
            log.exception("No se pudo guardar la selección investigada del repuesto %s", repuesto_id)
            saved_research, research_warning = 0, "La pieza se guardó, pero no se pudieron guardar los modelos investigados."
        if research_warning:
            flash(research_warning, "error")
        if saved_research:
            flash(f"Pieza añadida con {saved_research} modelo(s) compatibles pendientes de verificación.", "success")
        else:
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


# ---------------------------------------------------------------------------
# Búsqueda web asistida por referencia (sin API key ni servicio de pago)
# ---------------------------------------------------------------------------
def _reference_search_links(reference, piece_name=""):
    """Legacy helper for manually opening public search URLs; the new route searches server-side."""
    from urllib.parse import quote_plus

    reference = _clean(reference, 120)
    context = _clean(piece_name, 100)
    exact = f'"{reference}"'
    common = f'{exact} compatibilidad modelos compatibles {context}'.strip()
    searches = [
        ("Google", "Búsqueda general", "https://www.google.com/search?q=" + quote_plus(common)),
        ("Bing", "Búsqueda general", "https://www.bing.com/search?q=" + quote_plus(common)),
        ("DuckDuckGo", "Búsqueda general", "https://duckduckgo.com/?q=" + quote_plus(common)),
        ("Ovisat", "Catálogo de repuestos", "https://www.google.com/search?q=" + quote_plus(f'site:ovisat.com {exact}')),
        ("Impextrom", "Catálogo de repuestos", "https://www.google.com/search?q=" + quote_plus(f'site:impextrom.com {exact}')),
        ("Service Pack", "Repuesto original / referencias Samsung", "https://www.google.com/search?q=" + quote_plus(f'site:servicepacksamsung.com {exact}')),
        ("Techtek", "Referencias equivalentes y compatibilidad", "https://www.google.com/search?q=" + quote_plus(f'site:techtekshop.es {exact}')),
        ("Subtel", "Catálogo de repuestos", "https://www.google.com/search?q=" + quote_plus(f'site:subtel.es {exact}')),
    ]
    return [{"nombre": name, "tipo": kind, "url": url} for name, kind, url in searches]


def _parse_model_numbers(value):
    raw = re.split(r"[,;|\n]+", _clean(value, 600))
    result = []
    for item in raw:
        item = _clean(item, 100)
        if item and item.casefold() not in {x.casefold() for x in result}:
            result.append(item)
        if len(result) >= 20:
            break
    return result



# --- Investigación automática y genérica de referencias (sin API key) -------
# Busca referencias de cualquier familia de repuesto. Solo descarga páginas
# de distribuidores/catálogos permitidos y exige referencia exacta + modelo.
_REFERENCE_CACHE = {}
_REFERENCE_CACHE_POSITIVE_TTL = 6 * 60 * 60
_REFERENCE_CACHE_NEGATIVE_TTL = 5 * 60
_ROBOTS_CACHE = {}

# Fuentes con búsquedas públicas de catálogo. iFixit se excluye de la extracción
# automatizada: su robots.txt bloquea /Search y /api/*, y su API publica licencia
# no comercial. Puede ser consultado manualmente por el usuario desde su web.
_REFERENCE_SOURCES = (
    "ovisat.com", "servicepacksamsung.com", "techtekshop.es",
    "spainbateria.es", "impextrom.com", "componentidigitali.com",
    "repuestosmovil.es", "techcomponentes.com", "gsmobile.es",
    "phoneparts.es", "fixandgoparts.com", "newprime.es", "partob.com",
    "restaurio.es", "subtel.es", "thesmartphone.eu",
)

# Rutas de búsqueda pública de tiendas. Se prueban varias rutas compatibles con
# motores de tienda habituales; cada página se valida por dominio y referencia.
_DIRECT_CATALOGS = (
    ("Ovisat", "ovisat.com", (
        "https://ovisat.com/es/search?controller=search&s={q}",
        "https://ovisat.com/search?controller=search&s={q}",
        "https://ovisat.com/es/buscar?controller=search&s={q}",
    )),
    ("Service Pack Samsung", "servicepacksamsung.com", (
        "https://servicepacksamsung.com/es/search?controller=search&s={q}",
        "https://servicepacksamsung.com/search?controller=search&s={q}",
        "https://servicepacksamsung.com/es/buscar?controller=search&s={q}",
    )),
    ("Techtek", "techtekshop.es", (
        "https://www.techtekshop.es/es/search?controller=search&s={q}",
        "https://www.techtekshop.es/es/search?q={q}",
        "https://www.techtekshop.es/?s={q}",
    )),
    ("SpainBateria", "spainbateria.es", (
        "https://www.spainbateria.es/search?q={q}",
        "https://www.spainbateria.es/buscar?q={q}",
        "https://www.spainbateria.es/?s={q}",
    )),
    ("Impextrom", "impextrom.com", (
        "https://www.impextrom.com/es/search?controller=search&s={q}",
        "https://www.impextrom.com/search?q={q}",
        "https://www.impextrom.com/?s={q}",
    )),
    ("Componenti Digitali", "componentidigitali.com", (
        "https://www.componentidigitali.com/en/search?query={q}",
        "https://www.componentidigitali.com/it/search?query={q}",
        "https://www.componentidigitali.com/?s={q}",
    )),
    ("Subtel", "subtel.es", (
        "https://www.subtel.es/search?q={q}",
        "https://www.subtel.es/search?query={q}",
        "https://www.subtel.es/?s={q}",
    )),
)

# Identificadores técnicos usados por distintos fabricantes. Se extraen
# códigos de dispositivo, nunca códigos de pieza arbitrarios.
_MODEL_PATTERNS = [
    ("Samsung", re.compile(r"\b(?:SM|GT|SCH|SGH)-[A-Z0-9]{3,}(?:/(?!SM-|GT-|SCH-|SGH-)[A-Z0-9]+)?\b", re.I)),
    ("Apple", re.compile(r"\bA\d{4}\b", re.I)),
    ("Xiaomi", re.compile(r"\b(?:2[0-9]{6}[A-Z]{1,2}|[MC]\d{4}[A-Z0-9]{2,4})\b", re.I)),
    ("Huawei/Honor", re.compile(r"\b[A-Z]{3}-(?:[A-Z]{2,4}\d{1,2}|[A-Z0-9]{3,6})\b", re.I)),
    ("OPPO/OnePlus", re.compile(r"\b(?:CPH\d{4,5}|IN\d{4,5}|NE\d{4,5}|HD\d{4,5})\b", re.I)),
    ("realme", re.compile(r"\bRMX\d{4,5}\b", re.I)),
    ("Motorola", re.compile(r"\bXT\d{4,5}(?:-\d{1,2})?\b", re.I)),
    ("Nokia", re.compile(r"\bTA-\d{4}\b", re.I)),
    ("Sony", re.compile(r"\bXQ-[A-Z0-9]{2,6}\b", re.I)),
    ("LG", re.compile(r"\bLM-[A-Z0-9]{3,7}\b", re.I)),
    ("vivo", re.compile(r"\bV\d{4}[A-Z]{0,2}\b", re.I)),
    ("ASUS", re.compile(r"\b(?:ZS|ZB)\d{3,5}[A-Z]{0,3}\b|\b(?:ROG|AI)\d{3,6}[A-Z]{0,2}\b", re.I)),
    ("Tecno/Infinix", re.compile(r"\b(?:KI|CK|X)\d{1,5}[A-Z]{0,2}\b", re.I)),
    ("Alcatel/TCL", re.compile(r"\b(?:505|508|T7|T8|T9|NXTPAPER)[A-Z0-9-]{2,8}\b", re.I)),
    ("ZTE", re.compile(r"\b(?:ZTE[- ]?)?(?:A\d{4,5}|B\d{4,5}|Z\d{4,5})[A-Z]{0,2}\b", re.I)),
]

# Nombres comerciales: útiles cuando la fuente publica el nombre del terminal
# pero no un código regulatorio. El nombre solo se acepta en contexto de la
# referencia exacta presente en la misma página.
_DEVICE_NAME_PATTERNS = [
    ("Apple", re.compile(r"\b(?:iPhone\s+\d{1,2}(?:\s+(?:Pro\s+Max|Pro|Plus|mini|Air))?|iPad(?:\s+(?:Pro|Air|mini))?(?:\s+\d{1,2})?)\b", re.I)),
    ("Samsung", re.compile(r"\b(?:(?:Samsung\s+)?Galaxy\s+|Samsung\s+)(?:(?:S|A|M|F|J|Note)\s*\d{1,3}|Z\s*(?:Fold|Flip)\s*\d{1,2}|Tab\s+S?\d{1,2})(?:\s*(?:4G\s*/\s*5G|5G\s*/\s*4G|5G|4G|Ultra|Plus|FE|Pro|DUOS))?\b|\bNote\s*\d{1,3}(?:\s*(?:4G|5G|DUOS))?\b", re.I)),
    ("Xiaomi", re.compile(r"\b(?:Xiaomi\s+\d{1,2}(?:T)?(?:\s+Pro)?|Redmi\s+(?:Note\s+)?\d{1,2}(?:\s+(?:Pro|Pro\+|5G|4G))?|POCO\s+[A-Z0-9]+(?:\s+Pro)?)\b", re.I)),
    ("Huawei", re.compile(r"\b(?:Huawei\s+)?(?:P\d{1,2}(?:\s+Pro)?|Mate\s+\d{1,2}(?:\s+Pro)?|Nova\s+\d{1,2})\b", re.I)),
    ("Honor", re.compile(r"\bHonor\s+(?:Magic\s*\d{1,2}(?:\s+Pro)?|\d{1,3}(?:\s+Pro)?|X\d{1,2})\b", re.I)),
    ("OPPO", re.compile(r"\bOPPO\s+(?:Find\s+X\d{1,2}(?:\s+Pro)?|Reno\s+\d{1,2}(?:\s+Pro|\s+Z)?|A\d{1,3})\b", re.I)),
    ("realme", re.compile(r"\brealme\s+(?:GT\s*\d{1,2}(?:\s+Pro)?|\d{1,2}(?:\s+Pro|\s+5G)?)\b", re.I)),
    ("Motorola", re.compile(r"\bMotorola\s+(?:Moto\s+)?(?:G|E|Edge|Razr)\s*\d{1,3}(?:\s+(?:Plus|Power|Play|Fusion|Ultra))?\b", re.I)),
    ("Google", re.compile(r"\bGoogle\s+Pixel\s+\d{1,2}(?:\s+(?:Pro|XL|a|Fold))?\b|\bPixel\s+\d{1,2}(?:\s+(?:Pro|XL|a|Fold))?\b", re.I)),
    ("OnePlus", re.compile(r"\bOnePlus\s+(?:\d{1,2}(?:\s+(?:Pro|R))?|Nord\s+[A-Z0-9 ]{1,12})\b", re.I)),
    ("vivo", re.compile(r"\bvivo\s+(?:X|V|Y)\s*\d{1,3}(?:\s+(?:Pro|Lite))?\b", re.I)),
    ("Sony", re.compile(r"\bSony\s+Xperia\s+(?:1|5|10|L\d|Ace)(?:\s+(?:II|III|IV|V|VI|Plus|Pro))?\b", re.I)),
    ("Nokia", re.compile(r"\bNokia\s+(?:[3456789](?:\.\d)?|[A-Z]\d{1,2}|G\d{1,2})(?:\s+(?:Plus|5G|2021|2022|2023))?\b", re.I)),
    ("ASUS", re.compile(r"\bASUS\s+(?:Zenfone|ROG\s+Phone)\s*\d{1,2}\b", re.I)),
    ("LG", re.compile(r"\bLG\s+(?:V|G|K|Q)\d{1,3}(?:\s+ThinQ)?\b", re.I)),
    ("ZTE", re.compile(r"\bZTE\s+(?:Axon|Blade)\s+[A-Z0-9 ]{1,10}\b", re.I)),
    ("Tecno", re.compile(r"\bTecno\s+(?:Spark|Camon|Phantom|Pova)\s+(?:\d{1,2}(?:\s+Pro)?|[A-Z0-9]{2,8})\b", re.I)),
    ("Infinix", re.compile(r"\bInfinix\s+(?:Hot|Note|Zero|GT)\s+(?:\d{1,2}(?:\s+Pro)?|[A-Z0-9]{2,8})\b", re.I)),
]

class _ResultLinks(HTMLParser):
    """Extrae enlaces de páginas de resultados sin depender de una clase CSS concreta."""
    def __init__(self):
        super().__init__(); self.links=[]; self._href=None; self._text=[]
    def handle_starttag(self, tag, attrs):
        if tag == "a":
            attrs=dict(attrs); self._href=attrs.get("href"); self._text=[]
    def handle_data(self, data):
        if self._href: self._text.append(data)
    def handle_endtag(self, tag):
        if tag == "a" and self._href:
            self.links.append((self._href, " ".join(self._text).strip()))
            self._href=None; self._text=[]

_JSONLD_COMPAT_KEYS = {"iscompatiblewith", "isaccessoryorsparepartfor"}
_JSONLD_SKIP_KEYS = {"offers", "aggregaterating", "review", "image", "logo", "url", "isrelatedto",
                     "issimilarto", "mainentityofpage", "potentialaction", "breadcrumb"}


def _plain(value):
    """Convierte HTML incrustado en una cadena de texto con separadores."""
    text = re.sub(r"(?i)<br\s*/?>|</li>|</p>|</tr>", " ; ", str(value))
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", unescape(text)).strip()


def _jsonld_lines(raw):
    """Una línea por nodo JSON-LD, sin mezclar productos relacionados con el principal."""
    try:
        data = json.loads(raw)
    except Exception:
        text = re.sub(r"\s+", " ", raw or "").strip()
        return [text[:4000]] if text else []
    lines = []

    def scalar(v):
        return v if isinstance(v, (str, int, float)) and not isinstance(v, bool) else None

    def names(v):
        out = []
        if isinstance(v, list):
            for x in v[:100]:
                out += names(x)
        elif isinstance(v, dict):
            for k in ("name", "model", "alternateName", "description"):
                if scalar(v.get(k)) is not None:
                    out.append(_plain(v[k]))
        elif scalar(v) is not None:
            out.append(_plain(v))
        return out

    def walk(node, depth=0):
        if depth > 6:
            return
        if isinstance(node, list):
            for item in node[:200]:
                walk(item, depth + 1)
            return
        if not isinstance(node, dict):
            return
        parts = []
        for key, val in node.items():
            lk = str(key).lower()
            if lk == "@graph":
                walk(val, depth + 1)
                continue
            if str(key).startswith("@") or lk in _JSONLD_SKIP_KEYS:
                continue
            if lk in _JSONLD_COMPAT_KEYS:
                items = [x for x in names(val) if x]
                if items:
                    parts.append("Compatible con: " + ", ".join(items))
            elif lk == "additionalproperty":
                for prop in (val if isinstance(val, list) else [val]):
                    if isinstance(prop, dict) and scalar(prop.get("name")) is not None:
                        value = prop.get("value")
                        value = ", ".join(names(value)) if isinstance(value, (list, dict)) else _plain(value or "")
                        if value:
                            parts.append(f"{_plain(prop['name'])}: {value}")
            elif scalar(val) is not None:
                parts.append(f"{key}: {_plain(val)}")
            elif isinstance(val, dict) and lk in ("brand", "manufacturer") and scalar(val.get("name")):
                parts.append(f"{key}: {_plain(val['name'])}")
            elif isinstance(val, (list, dict)):
                walk(val, depth + 1)
        if parts:
            lines.append(" | ".join(parts))

    walk(data)
    return lines


class _VisibleText(HTMLParser):
    """Texto visible por líneas (tablas, listas, párrafos) + metadatos y JSON-LD."""
    _SKIP_TAGS = {"style", "noscript", "svg", "header", "footer", "nav"}
    _BLOCK_TAGS = {"p", "div", "li", "tr", "br", "h1", "h2", "h3", "h4", "h5", "h6", "table", "ul",
                   "ol", "section", "article", "dt", "dd", "dl", "caption", "title", "main", "aside",
                   "form", "select", "option", "hr", "tbody", "thead"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.primary = []      # título, h1 y descripciones meta de la ficha
        self.skip_depth = 0
        self.script_modes = []
        self._json = []
        self._primary_tag = None
        self._primary_buf = []

    def _add(self, value, maximum=12000):
        value = str(value or "").strip()
        if value:
            self.parts.append(value[:maximum])

    def _line(self, value, maximum=5000):
        self._add(value, maximum)
        self.parts.append("\n")

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script":
            script_type = (attrs.get("type") or "").lower().split(";")[0].strip()
            if script_type in ("application/ld+json", "application/json", "application/json+ld"):
                self.script_modes.append("json")
                self._json = []
            else:
                self.script_modes.append("skip")
                self.skip_depth += 1
            return
        if tag in self._SKIP_TAGS:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        if tag in self._BLOCK_TAGS:
            self.parts.append("\n")
            if tag in ("title", "h1"):
                self._primary_tag, self._primary_buf = tag, []
        elif tag in ("td", "th"):
            self.parts.append("|")

        if tag == "meta":
            content = attrs.get("content")
            meta_name = " ".join((attrs.get("name", ""), attrs.get("property", ""), attrs.get("itemprop", ""))).lower()
            if content and (not meta_name or any(x in meta_name for x in ("product", "description", "title", "model", "sku", "part", "compat"))):
                self._line(_plain(content), 5000)
                if any(x in meta_name for x in ("description", "title")):
                    self.primary.append(_plain(content)[:1000])

        for key, value in attrs.items():
            if key in ("alt", "title", "aria-label"):
                self._line(value, 1000)
            elif key.startswith("data-") and any(token in key.lower() for token in ("product", "model", "compat", "sku", "part", "reference", "title", "name")):
                self._line(value, 3000)

    def handle_endtag(self, tag):
        if tag == "script":
            if self.script_modes:
                mode = self.script_modes.pop()
                if mode == "skip":
                    self.skip_depth = max(0, self.skip_depth - 1)
                else:
                    for line in _jsonld_lines("".join(self._json)):
                        self._line(line, 6000)
                    self._json = []
            return
        if tag in self._SKIP_TAGS and self.skip_depth:
            self.skip_depth -= 1
            return
        if not self.skip_depth and tag in self._BLOCK_TAGS:
            if tag == self._primary_tag:
                text = re.sub(r"\s+", " ", " ".join(self._primary_buf)).strip()
                if text:
                    self.primary.append(text[:1000])
                self._primary_tag = None
            self.parts.append("\n")

    def handle_data(self, data):
        if self.script_modes and self.script_modes[-1] == "json":
            self._json.append(data)
        elif not self.skip_depth:
            if self._primary_tag:
                self._primary_buf.append(data)
            self._add(data, 5000)

    def lines(self):
        out = []
        for raw in " ".join(self.parts).split("\n"):
            line = re.sub(r"\s+", " ", raw).strip(" |")
            if line:
                out.append(line[:6000])
        return out


def _http_text(url, limit=1_200_000, timeout=7):
    req=Request(url, headers={
        "User-Agent":"INFORBAXE-CompatibilityResearch/1.0 (+public-catalog-search)",
        "Accept":"text/html,application/xhtml+xml,application/rss+xml,application/xml;q=0.9,*/*;q=0.5",
        "Accept-Language":"es-ES,es;q=0.9,en;q=0.8",
    })
    with urlopen(req, timeout=timeout) as response:
        data=response.read(limit)
        charset=response.headers.get_content_charset() or "utf-8"
        return data.decode(charset, errors="replace"), response.geturl(), response.status

def _domain_host(url):
    return (urlparse(url).hostname or "").lower().split(":")[0]

def _domain_allowed(url):
    host=_domain_host(url)
    return any(host == d or host.endswith("."+d) for d in _REFERENCE_SOURCES)

def _robots_can_fetch(url):
    """Respeta robots.txt: ante bloqueo o fallo de red no fuerza el rastreo."""
    parsed=urlparse(url); origin=f"{parsed.scheme}://{parsed.netloc}"; now=time.time()
    cached=_ROBOTS_CACHE.get(origin)
    if cached and now-cached[0] < 12*60*60:
        parser, allowed=cached[1], cached[2]
        return allowed if parser is None else parser.can_fetch("INFORBAXE-CompatibilityResearch", url)
    robots_url=origin+"/robots.txt"
    try:
        req=Request(robots_url,headers={"User-Agent":"INFORBAXE-CompatibilityResearch/1.0"})
        with urlopen(req,timeout=4) as response:
            text=response.read(256_000).decode(response.headers.get_content_charset() or "utf-8",errors="replace")
        parser=__import__("urllib.robotparser",fromlist=["RobotFileParser"]).RobotFileParser()
        parser.set_url(robots_url); parser.parse(text.splitlines())
        _ROBOTS_CACHE[origin]=(now,parser,True)
        return parser.can_fetch("INFORBAXE-CompatibilityResearch",url)
    except HTTPError as exc:
        # 404/410 means no published robots policy. Other HTTP errors fail closed.
        allowed=exc.code in (404,410)
        _ROBOTS_CACHE[origin]=(now,None,allowed)
        return allowed
    except Exception as exc:
        log.info("No se pudo comprobar robots.txt de %s: %s",origin,exc)
        _ROBOTS_CACHE[origin]=(now,None,False)
        return False

def _piece_search_terms(piece_name=""):
    value=unicodedata.normalize("NFKD", _norm(piece_name)).encode("ascii", "ignore").decode("ascii")
    maps = {
        ("bater", "battery", "acumulador"): "bateria battery replacement accu",
        ("pantall", "display", "screen", "lcd", "oled"): "pantalla display screen LCD OLED replacement",
        ("camar", "camera", "lente"): "camara camera rear front lens replacement",
        ("conector", "carga", "charging", "usb"): "conector carga charging port USB flex replacement",
        ("altavoz", "auricular", "speaker", "earpiece", "microfono", "microphone"): "altavoz auricular speaker earpiece microphone",
        ("vibrador", "vibrator", "motor vibr"): "vibrador vibrator motor replacement",
        ("tapa", "carcasa", "housing", "back cover", "chasis"): "tapa trasera carcasa housing back cover frame",
        ("flex", "boton", "button", "encendido", "volumen"): "flex cable button power volume replacement",
        ("placa", "motherboard", "mainboard", "subplaca"): "placa base motherboard mainboard sub board",
        ("antena", "nfc", "coaxial"): "antena antenna NFC coaxial cable",
        ("sim", "bandeja", "tray"): "bandeja SIM tray card reader",
        ("sensor", "huella", "fingerprint", "proximidad"): "sensor fingerprint proximity flex",
        ("cristal", "glass"): "cristal glass lens replacement",
    }
    for keys, terms in maps.items():
        if any(key in value for key in keys): return terms
    return _clean(piece_name,80)

def _reference_compact(value):
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())

def _reference_pattern(reference):
    """Referencia exacta: tolera separadores (EB-BN980ABY, EB BN980ABY) pero no prefijos/sufijos."""
    needle = _reference_compact(reference)
    if not needle:
        return None
    body = r"[^A-Z0-9]{0,2}".join(re.escape(char) for char in needle)
    return re.compile(r"(?<![A-Z0-9])" + body + r"(?![A-Z0-9])", re.IGNORECASE)


def _reference_in_text(reference, text):
    pattern = _reference_pattern(reference)
    return bool(pattern and pattern.search(text or ""))


def _reference_match_span(text, reference):
    pattern = _reference_pattern(reference)
    match = pattern.search(text or "") if pattern else None
    return (match.start(), match.end()) if match else None


def _is_near_reference(token, ref_compact):
    """True si token parece otra referencia de la misma familia (p. ej. BN985ABY frente a BN980ABY)."""
    token = _reference_compact(token)
    if not token or token == ref_compact or len(token) < 4:
        return False
    if not (re.search(r"[A-Z]", token) and re.search(r"\d", token)):
        return False
    if abs(len(token) - len(ref_compact)) > 2:
        return False
    if token.startswith(ref_compact) or ref_compact.startswith(token):
        return True
    prefix = 0
    for a, b in zip(token, ref_compact):
        if a != b:
            break
        prefix += 1
    if prefix >= max(3, len(ref_compact) // 2):
        return True
    return len(token) == len(ref_compact) and sum(a != b for a, b in zip(token, ref_compact)) <= 2


def _line_has_other_reference(line, ref_compact):
    tokens = re.findall(r"[A-Za-z0-9]+(?:[-_/.][A-Za-z0-9]+)*", line or "")
    candidates = []
    for tok in tokens:
        candidates.append(tok)
        candidates.extend(part for part in re.split(r"[/]", tok) if part != tok)
    for a, b in zip(tokens, tokens[1:]):
        if len(a) <= 5 and len(b) <= 12:
            candidates.append(a + b)
    return any(_is_near_reference(tok, ref_compact) for tok in candidates)


def _source_group_for_evidence(domain, text):
    """Agrupa dominios que publican fichas del mismo vendedor explícito."""
    match = re.search(
        r"\b(?:tienda|seller|vendedor|vendido\s+por|sold\s+by|store)\s*[:|]\s*(?:\|\s*)?(.{2,100})",
        text or "", re.IGNORECASE
    )
    if match:
        seller = re.split(
            r"\b(?:modelo(?:s|\(s\))?|referencia|reference|sku|part\s*number|stock|precio)\b",
            match.group(1), maxsplit=1, flags=re.IGNORECASE
        )[0]
        seller = re.sub(r"^[\s|:,-]+|[\s|:,-]+$", "", seller)
        seller = _clean(seller, 60)
        if len(seller) >= 3:
            return "seller:" + _norm(seller)
    return "domain:" + (_base_catalog_domain(domain) or "unknown")

def _base_catalog_domain(host):
    host=(host or "").lower()
    return next((d for d in _REFERENCE_SOURCES if host == d or host.endswith("."+d)), host)

def _likely_product_url(url, domain):
    path=(urlparse(url).path or "").lower()
    domain=_base_catalog_domain(domain)
    if any(x in path for x in ("/login", "/cart", "/account", "/search", "/buscar", "/contact", "/category")):
        return False
    if domain == "ovisat.com": return bool(re.search(r"-p\d+/?$",path) or "/producto/" in path)
    if domain == "techtekshop.es": return "/producto/" in path or bool(re.search(r"/\d+[-/]",path))
    if domain == "servicepacksamsung.com": return path.endswith(".html")
    if domain == "componentidigitali.com": return path.endswith(".uw") or ".gp." in path
    if domain in {"impextrom.com", "repuestosmovil.es", "techcomponentes.com", "gsmobile.es", "subtel.es"}:
        if any(token in path for token in ("/producto", "/product", "/piezas", "/repuesto", "/bateria", "/pantalla")):
            return True
    return any(path.endswith(ext) for ext in (".html", ".htm", ".uw")) or bool(re.search(r"p\d+/?$",path))

def _parse_catalog_links(html, base_url, domain, reference=""):
    parser = _ResultLinks()
    parser.feed(html)
    found = []
    seen = set()
    needle = _reference_compact(reference)
    for href, title in parser.links:
        url = urljoin(base_url, href)
        if not url.startswith("https://") or not _domain_allowed(url) or domain not in _domain_host(url):
            continue
        if not _likely_product_url(url, domain):
            continue
        key = url.split("#", 1)[0]
        if key in seen:
            continue
        seen.add(key)
        label = _clean(title, 180)
        hay = _reference_compact(unquote(key) + " " + label)
        exact = bool(needle and needle in hay)
        found.append((0 if exact else 1, key, label))
    found.sort(key=lambda item: item[0])
    return [(url, title) for _rank, url, title in found[:6]]


def _search_direct_catalog(name, domain, templates, reference, piece_name=""):
    query = quote_plus(reference)
    diagnostics = {
        "source": name, "domain": domain, "status": "sin_resultados",
        "search_pages": 0, "product_links": 0, "pages_read": 0,
        "reference_pages": 0, "exact_result_links": 0
    }
    exact_links = []
    fallback_links = []
    evidence = []
    needle = _reference_compact(reference)

    for template in templates:
        search_url = template.format(q=query)
        if not _robots_can_fetch(search_url):
            diagnostics["status"] = "bloqueado_por_robots"
            continue
        try:
            html, final_url, status = _http_text(search_url, 650_000, timeout=4)
            diagnostics["search_pages"] += 1
            if status >= 400 or domain not in _domain_host(final_url):
                diagnostics["status"] = f"http_{status}"
                continue

            links = _parse_catalog_links(html, final_url, domain, reference)
            for url, title in links:
                hay = _reference_compact(unquote(url) + " " + title)
                if needle and needle in hay:
                    exact_links.append((url, title))
                else:
                    fallback_links.append((url, title))

            parsed = _extract_evidence_from_html(
                reference, domain, final_url, f"{name} · resultados de búsqueda", html, piece_name, listing=True
            )
            if parsed:
                evidence.append(parsed)
                diagnostics["status"] = "referencia_y_modelos_en_resultados"
                break

            # No detenerse por cualquier enlace de producto: la ruta puede haber
            # devuelto productos genéricos. Probar las otras rutas de búsqueda.
            if exact_links:
                diagnostics["status"] = "resultado_exacto_encontrado"
                break
            if links:
                diagnostics["status"] = "resultados_no_especificos"
            elif diagnostics["status"] == "sin_resultados":
                diagnostics["status"] = "pagina_accesible_sin_productos"

        except HTTPError as exc:
            diagnostics["status"] = f"http_{exc.code}"
        except Exception as exc:
            diagnostics["status"] = "error_de_conexion"
            log.info("Búsqueda directa en %s falló: %s", domain, exc)

    # Priorizar enlaces cuyo título o URL contiene la referencia exacta.
    product_links = []
    seen_links = set()
    for url, title in exact_links + fallback_links:
        if url not in seen_links:
            seen_links.add(url)
            product_links.append((url, title))
        if len(product_links) >= 4:
            break

    diagnostics["exact_result_links"] = len(exact_links)
    diagnostics["product_links"] = len(product_links)

    for url, title in product_links:
        if not _robots_can_fetch(url):
            continue
        try:
            html, final_url, status = _http_text(url, 1_200_000, timeout=5)
            diagnostics["pages_read"] += 1
            item = _extract_evidence_from_html(reference, domain, final_url, title, html, piece_name)
            if item:
                diagnostics["reference_pages"] += 1
                evidence.append(item)
        except Exception as exc:
            log.info("No se pudo leer producto %s: %s", url, exc)

    return evidence, diagnostics

class _SearchEngineLinks(HTMLParser):
    def __init__(self): super().__init__(); self.links=[]; self.href=None; self.text=[]
    def handle_starttag(self,tag,attrs):
        if tag=="a": self.href=dict(attrs).get("href"); self.text=[]
    def handle_data(self,data):
        if self.href: self.text.append(data)
    def handle_endtag(self,tag):
        if tag=="a" and self.href:
            self.links.append((self.href," ".join(self.text).strip())); self.href=None; self.text=[]

def _search_engine(engine,url,reference):
    diag={"source":engine,"status":"sin_resultados","links":0}; links=[]
    try:
        html,final_url,status=_http_text(url,700_000,timeout=4)
        if status>=400: diag["status"]=f"http_{status}"; return links,diag
        if engine=="Bing RSS":
            root=ET.fromstring(html)
            for item in root.findall(".//item"):
                u=(item.findtext("link") or "").strip(); title=(item.findtext("title") or "").strip()
                if u.startswith("https://") and _domain_allowed(u): links.append((u,title))
        else:
            parser=_SearchEngineLinks(); parser.feed(html)
            for href,title in parser.links:
                u=href
                if href.startswith("//"): u="https:"+href
                if "uddg=" in u:
                    try: u=parse_qs(urlparse(u).query).get("uddg",[u])[0]
                    except Exception: pass
                elif "r.search.yahoo.com" in u:
                    try:
                        raw_path=urlparse(u).path
                        m=re.search(r"/RU=([^/]+)",raw_path)
                        if m: u=unquote(m.group(1))
                    except Exception: pass
                if u.startswith("https://") and _domain_allowed(u): links.append((u,title))
        unique=[]; seen=set()
        for u,t in links:
            key=u.split("#",1)[0]
            if key not in seen: seen.add(key); unique.append((key,t))
        links=unique[:20]; diag["links"]=len(links); diag["status"]="resultados_encontrados" if links else "sin_enlaces_de_catalogos"
    except Exception as exc:
        diag["status"]="bloqueado_o_no_disponible"; log.info("Buscador %s no disponible: %s",engine,exc)
    return links,diag

def _global_search_urls(reference,piece_name=""):
    context=_piece_search_terms(piece_name)
    queries=[f'"{reference}" {context} compatibilidad', f'"{reference}" "compatible con" OR "compatible for"']
    engines=[]
    for q in queries:
        engines.extend([
            ("DuckDuckGo Lite", "https://lite.duckduckgo.com/lite/?q="+quote_plus(q)),
            ("Bing RSS", "https://www.bing.com/search?format=rss&q="+quote_plus(q)),
            ("Yahoo", "https://search.yahoo.com/search?p="+quote_plus(q)),
            ("Mojeek", "https://www.mojeek.com/search?q="+quote_plus(q)),
        ])
    found=[]; diagnostics=[]
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures=[pool.submit(_search_engine,name,url,reference) for name,url in engines]
        for fut in as_completed(futures):
            try:
                links,diag=fut.result(); found.extend(links); diagnostics.append(diag)
            except Exception: pass
    unique=[]; seen=set()
    for u,t in found:
        domain=_domain_host(u)
        if _likely_product_url(u,domain) and u not in seen:
            seen.add(u); unique.append((domain,u,t))
    return unique[:30],diagnostics

def _brand_for_code(code):
    upper=code.upper()
    for brand, pattern in _MODEL_PATTERNS:
        if pattern.fullmatch(upper):
            if brand == "Huawei/Honor": return "Huawei/Honor"
            if brand == "OPPO/OnePlus": return "OPPO/OnePlus"
            if brand == "Tecno/Infinix": return "Tecno/Infinix"
            return brand
    return ""

def _device_names_near(text, code=None):
    candidates=[]
    haystack=text
    if code:
        pos=haystack.upper().find(code.upper())
        if pos >= 0:
            haystack=haystack[max(0,pos-260):min(len(haystack),pos+260)]
    for brand, pattern in _DEVICE_NAME_PATTERNS:
        for match in pattern.finditer(haystack):
            name=re.sub(r"\s+", " ", match.group(0)).strip(" -|,;:")
            # Quitar códigos de variante y coletillas de referencia que algunos
            # títulos concatenan al nombre comercial.
            name=re.sub(r"\b(?:SM|GT|SCH|SGH|XQ|TA|LM|XT|RMX|CPH|IN|NE|HD|VOG|ELS|MHA|ANE)-?[A-Z0-9/-]{3,}\b", "", name, flags=re.I).strip(" -|,;:")
            name=re.sub(r"\b(?:ref(?:erencia)?|part(?:\s+number)?|model(?:\s+number)?)\b.*$", "", name, flags=re.I).strip(" -|,;:")
            if name and not any(x["modelo"].casefold()==name.casefold() for x in candidates):
                candidates.append({"marca":brand,"modelo":name})
    return candidates

_COMPAT_LABEL = re.compile(
    r"\b(?:compatible\s+(?:con|para|with|for)|compatibles?\b|compatibilidad|compatibility|"
    r"model(?:o)?s?\s*(?:\(s\))?|modelos?\s+compatibles?|"
    r"fits?\s+(?:the\s+following|for|with)|se\s+adapta\s+a|se\s+ajusta\s+a|"
    r"suitable\s+for|works?\s+with|dispositivos?\s+compatibles?|aplicable\s+a|"
    r"v[aá]lid[oa]\s+para|dise[ñn]ad[oa]\s+para|designed\s+for|para\s+los\s+modelos)(?=\W|$)",
    re.IGNORECASE)
_STOP_SECTION = re.compile(
    r"\b(?:productos?\s+(?:relacionados?|similares?|recomendados?)|art[ií]culos?\s+relacionados?|"
    r"related\s+products?|you\s+may\s+also|tambi[eé]n\s+te\s+pueden?|otros\s+clientes|"
    r"customers\s+also|recently\s+viewed|vistos\s+recientemente|sugerencias?)\b", re.IGNORECASE)


def _compatibility_windows(lines, reference, listing=False, primary=()):
    """Bloques de texto que pueden hablar de la referencia buscada.

    Descarta líneas que mencionan otra referencia parecida (EB-BN985ABY frente a
    EB-BN980ABY) y corta las secciones de productos relacionados."""
    if isinstance(lines, str):
        lines = [lines]
    pattern = _reference_pattern(reference)
    ref_c = _reference_compact(reference)
    if not pattern:
        return [], False
    conflict = [_line_has_other_reference(l, ref_c) for l in lines]
    stop = [bool(_STOP_SECTION.search(l)) for l in lines]
    ref_idx = [i for i, l in enumerate(lines) if pattern.search(l)]
    windows = []
    for i in ref_idx:
        if not conflict[i] and not stop[i]:
            windows.append(lines[i])
    if not listing and ref_idx:
        first = ref_idx[0]
        for i, line in enumerate(lines):
            if conflict[i] or stop[i] or not _COMPAT_LABEL.search(line) or i < first - 2:
                continue
            block = [line]
            for j in range(i + 1, min(len(lines), i + 15)):
                if conflict[j] or stop[j]:
                    break
                block.append(lines[j])
            windows.append(" ; ".join(block))
        # Título/h1/meta de la ficha: solo si la página no menciona otras referencias parecidas.
        if not any(conflict):
            windows.extend(x for x in primary if x)
    unique, seen = [], set()
    for window in windows:
        value = re.sub(r"\s+", " ", window).strip()
        key = value[:500].casefold()
        if value and key not in seen:
            seen.add(key)
            unique.append(value)
        if len(unique) >= 24:
            break
    return unique, any(_COMPAT_LABEL.search(w) for w in unique)


def _closest_device_name(text, code_start, code_end, brand):
    groups = {
        "Huawei/Honor": {"Huawei", "Honor"},
        "OPPO/OnePlus": {"OPPO", "OnePlus"},
        "Tecno/Infinix": {"Tecno", "Infinix"},
    }
    allowed = groups.get(brand, {brand})
    radius = 900
    left = max(0, code_start - radius)
    right = min(len(text), code_end + radius)
    window = text[left:right]
    matches = []
    for name_brand, pattern in _DEVICE_NAME_PATTERNS:
        if name_brand not in allowed:
            continue
        for match in pattern.finditer(window):
            absolute_start = left + match.start()
            absolute_end = left + match.end()
            distance = min(abs(absolute_end - code_start), abs(absolute_start - code_end))
            name = re.sub(r"\s+", " ", match.group(0)).strip(" -|,;:")
            if name and distance <= radius:
                matches.append((distance, name_brand, name))
    if not matches:
        return None
    matches.sort(key=lambda item: (item[0], len(item[2])))
    if len(matches) > 1 and matches[0][0] == matches[1][0] and matches[0][2].casefold() != matches[1][2].casefold():
        return None
    return {"marca": matches[0][1], "modelo": matches[0][2]}


def _extract_device_candidates(reference, lines, title="", primary=(), listing=False):
    ref_c = _reference_compact(reference)
    pattern = _reference_pattern(reference)
    windows, _explicit = _compatibility_windows(lines, reference, listing, primary)
    # El título del resultado solo vale si contiene la referencia exacta y ninguna otra parecida.
    if title and pattern and pattern.search(title) and not _line_has_other_reference(title, ref_c):
        windows.append(re.sub(r"\s+", " ", title).strip())
    if not windows:
        return []
    candidates = []
    names_pool = []
    for window in windows:
        span = _reference_match_span(window, reference)
        has_label = bool(_COMPAT_LABEL.search(window))
        window_codes = 0
        used_names = set()
        for brand, pat in _MODEL_PATTERNS:
            for match in pat.finditer(window):
                code = match.group(0).upper()
                if span and match.start() < span[1] and match.end() > span[0]:
                    continue
                if _reference_compact(code) == ref_c or _is_near_reference(code, ref_c):
                    continue
                detected_brand = _brand_for_code(code) or brand
                name = _closest_device_name(window, match.start(), match.end(), detected_brand)
                window_codes += 1
                if name:
                    used_names.add((name["marca"].casefold(), name["modelo"].casefold()))
                    candidates.append({"code": code, "brand": name["marca"], "model_name": name["modelo"]})
                else:
                    candidates.append({"code": code, "brand": detected_brand,
                                       "model_name": f"Modelo identificado por código {code}"})
        names = {}
        for brand, pat in _DEVICE_NAME_PATTERNS:
            for match in pat.finditer(window):
                model_name = re.sub(r"\s+", " ", match.group(0)).strip(" -|,;:")
                if model_name:
                    names[(brand.casefold(), model_name.casefold())] = {"code": "", "brand": brand, "model_name": model_name}
        # Nombres sin código: en secciones de compatibilidad explícitas se aceptan todos;
        # en el resto, solo si la línea identifica un único modelo.
        for key, item in names.items():
            if key in used_names:
                continue
            if has_label or (len(names) == 1 and not window_codes):
                names_pool.append(item)
    candidates.extend(names_pool)
    unique, seen = [], set()
    for item in candidates:
        key = (item.get("code", "").casefold(), item.get("brand", "").casefold(), item.get("model_name", "").casefold())
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique[:60]


def _extract_evidence_from_html(reference, domain, url, title, html, piece_name="", listing=False):
    if not _domain_allowed(url) or domain not in _domain_host(url):
        return None
    parser = _VisibleText()
    parser.feed(html)
    lines = parser.lines()
    pattern = _reference_pattern(reference)
    if not pattern or not any(pattern.search(line) for line in lines):
        return None
    candidates = _extract_device_candidates(reference, lines, title, parser.primary, listing)
    if not candidates:
        return None
    base = _base_catalog_domain(domain)
    compact = " ".join(lines)
    title_clean = re.sub(r"\s+", " ", title or "").strip()[:180] or base
    return {
        "domain": base,
        "source_group": _source_group_for_evidence(base, compact),
        "url": url,
        "title": title_clean,
        "candidates": candidates,
        "excerpt": compact[:1200],
    }


def _candidate_consensus_key(candidate):
    """Compara el nombre comercial reconocido; si no, utiliza el código técnico exacto."""
    brand = _clean(candidate.get("brand"), 80).casefold()
    name = _clean(candidate.get("model_name"), 140)
    code = _clean(candidate.get("code"), 100).upper()
    normalized = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii").casefold()
    if normalized and not normalized.startswith("modelo identificado por codigo"):
        if brand == "samsung":
            normalized = re.sub(r"\b(?:samsung|galaxy)\b", " ", normalized)
        normalized = re.sub(r"[^a-z0-9]+", "", normalized)
        if normalized:
            return f"name:{brand}:{normalized}"
    if code:
        return f"code:{brand}:{code}"
    return f"name:{brand}:{normalized}"

def _candidate_keys(candidate):
    keys = []
    code = _reference_compact((candidate.get("code") or "").split("/")[0])
    if code:
        keys.append("code:" + code)
    if not str(candidate.get("model_name") or "").startswith("Modelo identificado por código"):
        name_key = _candidate_consensus_key({**candidate, "code": ""})
        if name_key and not name_key.endswith(":"):
            keys.append(name_key)
    return keys


def _merge_candidates(by_domain):
    """Agrupa candidatos que comparten código o nombre normalizado y cuenta fuentes independientes.

    Antes un modelo citado por código en una tienda y por nombre en otra nunca coincidía."""
    parent = {}

    def find(x):
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    entries = []
    for source_group, container in by_domain.items():
        for page in container["pages"]:
            for candidate in page.get("candidates", []):
                keys = _candidate_keys(candidate)
                if not keys:
                    continue
                for other in keys[1:]:
                    parent[find(other)] = find(keys[0])
                find(keys[0])
                entries.append((source_group, page, candidate, keys[0]))
    clusters = {}
    for source_group, page, candidate, key in entries:
        entry = clusters.setdefault(find(key), {"brand": "", "model_name": "", "codes": [], "domains": set(),
                                                "sources": [], "names": []})
        entry["domains"].add(source_group)
        code = (candidate.get("code") or "").upper().strip()
        if code and code not in entry["codes"]:
            entry["codes"].append(code)
        name = (candidate.get("model_name") or "").strip()
        if name and not name.startswith("Modelo identificado por código"):
            entry["names"].append((name, (candidate.get("brand") or "").strip()))
        elif not entry["brand"]:
            entry["brand"] = (candidate.get("brand") or "").strip()
            entry["model_name"] = name
        ref = {"domain": page["domain"], "title": page["title"], "url": page["url"], "source_group": source_group}
        if not any(src["url"] == ref["url"] for src in entry["sources"]):
            entry["sources"].append(ref)
    for entry in clusters.values():
        if entry["names"]:
            counts = {}
            for name, brand in entry["names"]:
                counts[(name, brand)] = counts.get((name, brand), 0) + 1
            name, brand = sorted(counts, key=lambda k: (-counts[k], len(k[0]), k[0]))[0]
            entry["model_name"], entry["brand"] = name, brand or entry["brand"]
        entry["code"] = entry["codes"][0] if entry["codes"] else ""
    return {f"cluster:{i}": v for i, v in enumerate(clusters.values())}


def _automatic_reference_research(reference,piece_name=""):
    ref=re.sub(r"[^A-Za-z0-9._/-]","",_clean(reference,80)).upper()
    piece=_clean(piece_name,100)
    if len(ref)<4:
        return {"ok":False,"message":"Introduce una referencia de al menos 4 caracteres.","sources":[],"models":[]}
    cache_key=f"{ref}|{piece.casefold()}"; now=time.time()
    cached=_REFERENCE_CACHE.get(cache_key)
    if cached and now-cached[0] < (_REFERENCE_CACHE_POSITIVE_TTL if cached[1].get("models") else _REFERENCE_CACHE_NEGATIVE_TTL):
        result=dict(cached[1]); result["cached"]=True; return result

    evidence=[]; diagnostics=[]; discovered=[]
    # 1) Buscar directamente dentro de los catálogos públicos (sin pasar por
    # motores externos como intermediarios). Se respeta robots.txt.
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures=[pool.submit(_search_direct_catalog,*catalog,ref,piece) for catalog in _DIRECT_CATALOGS]
        for future in as_completed(futures):
            try:
                items,diag=future.result(); evidence.extend(items); diagnostics.append(diag)
            except Exception as exc:
                log.info("Conector directo fallido: %s",exc)

    # 2) Complementar con buscadores públicos: una consulta global, no una
    # consulta por cada dominio. Solo se aceptan URLs de catálogos permitidos.
    search_urls,engine_diagnostics=_global_search_urls(ref,piece)
    diagnostics.extend(engine_diagnostics)
    diagnostics.append({"source":"Resultados públicos globales","status":"enlaces_encontrados" if search_urls else "sin_enlaces_de_catalogos","links":len(search_urls),"pages_read":0})
    seen_urls={x["url"] for x in evidence}
    # Un máximo de 12 páginas, para no saturar Render ni las tiendas.
    global_read_attempts=0
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures={pool.submit(_extract_evidence_page,ref,domain,url,title,piece):(domain,url) for domain,url,title in search_urls[:12] if url not in seen_urls}
        for future in as_completed(futures):
            global_read_attempts += 1
            try:
                item=future.result()
                if item: evidence.append(item)
            except Exception as exc:
                log.info("Lectura de fuente externa fallida: %s",exc)
    diagnostics[-1]["pages_read"]=global_read_attempts

    # 3) Una sola evidencia por vendedor/origen editorial. Si dos dominios
    # publican una ficha cuyo campo "Tienda" identifica al mismo vendedor,
    # cuentan como una única confirmación independiente.
    by_domain = {}
    for item in evidence:
        domain = item["domain"]
        source_group = item.get("source_group") or ("domain:" + domain)
        current = by_domain.setdefault(source_group, {
            "source_group": source_group, "domains": set(), "pages": []
        })
        current["domains"].add(domain)
        if not any(page["url"] == item["url"] for page in current["pages"]):
            current["pages"].append(item)

    independent_sources = sorted(by_domain)
    total_domains = len(independent_sources)
    by_candidate = _merge_candidates(by_domain)

    minimum = max(2, math.ceil((2 / 3) * total_domains)) if total_domains >= 2 else 2
    models = []
    for key, item in sorted(by_candidate.items(), key=lambda kv: (-len(kv[1]["domains"]), kv[1].get("model_name", ""))):
        count = len(item["domains"])
        if count < minimum:
            continue
        models.append({
            "code": (item.get("codes") or [item.get("code", "")])[0],
            "codes": item.get("codes") or ([item.get("code")] if item.get("code") else []),
            "brand": item.get("brand") or "Marca por confirmar",
            "model_name": item.get("model_name") or "Modelo sin identificar",
            "matches": count,
            "total_sources": total_domains,
            "confidence": round(100 * count / max(total_domains, 1)),
            "sources": item["sources"],
        })

    sources = []
    for source_group, container in by_domain.items():
        for page in container["pages"]:
            if not any(existing["url"] == page["url"] for existing in sources):
                sources.append({
                    "domain": page["domain"], "title": page["title"], "url": page["url"],
                    "source_group": source_group
                })
    source_diags=[d for d in diagnostics if d.get("source")]
    # Resumen compatible con el formulario de alta de piezas. En versiones
    # anteriores, el backend devolvía diagnostics como una lista mientras que
    # el formulario esperaba un objeto; por eso la interfaz enseñaba ceros.
    direct_diags=[d for d in source_diags if d.get("domain")]
    domains_with_links={
        d.get("domain") for d in direct_diags
        if int(d.get("product_links", 0) or 0) > 0
    }
    domains_with_links.update(domain for domain, _url, _title in search_urls if domain)
    discovered_urls=set()
    for d in direct_diags:
        # Los conectores directos exponen enlaces de producto por dominio,
        # aunque no se incluya el URL individual en el diagnóstico.
        for idx in range(int(d.get("product_links", 0) or 0)):
            discovered_urls.add(f"direct:{d.get('domain')}:{idx}")
    discovered_urls.update(url for _domain, url, _title in search_urls)
    pages_checked=sum(int(d.get("pages_read", 0) or 0) for d in direct_diags) + int(global_read_attempts)
    exact_reference_urls={item.get("url") for item in evidence if item.get("url")}
    errors=[d for d in source_diags if (
        d.get("status") in ("error_de_conexion", "bloqueado_por_robots", "bloqueado_o_no_disponible")
        or str(d.get("status", "")).startswith("http_")
    )]
    domains_with_model_candidates=len({item.get("domain") for item in evidence if item.get("domain") and item.get("candidates")})
    diagnostics_summary={
        "domains_consulted": len(direct_diags),
        "domains_with_search_results": len(domains_with_links),
        "pages_discovered": len(discovered_urls),
        "pages_checked": pages_checked,
        "pages_with_exact_reference": len(exact_reference_urls),
        "domains_with_evidence": domains_with_model_candidates,
        "independent_sources_with_evidence": total_domains,
        "search_errors": errors,
        "source_diagnostics": source_diags,
    }
    result={"ok":bool(models),"reference":ref,"piece":piece,"sources":sources,"models":models,
        "checked_domains":[x[1] for x in _DIRECT_CATALOGS],"successful_domains":total_domains,
        "minimum_consensus":minimum,"diagnostics":source_diags,
        "diagnostics_summary":diagnostics_summary,
        "source_diagnostics":source_diags,
        "pages_read":pages_checked,
        "message":("Se encontraron coincidencias entre fuentes independientes." if models else
                   "No se ha podido confirmar ninguna compatibilidad con evidencia suficiente."),
        "errors":errors,
        "cached":False}
    ttl=_REFERENCE_CACHE_POSITIVE_TTL if models else _REFERENCE_CACHE_NEGATIVE_TTL
    _REFERENCE_CACHE[cache_key]=(now,result)
    return result

def _extract_evidence_page(reference,domain,url,title,piece_name=""):
    if not _robots_can_fetch(url): return None
    try:
        html,final_url,status=_http_text(url,1_200_000,timeout=5)
        if status>=400 or domain not in _domain_host(final_url): return None
        return _extract_evidence_from_html(reference,domain,final_url,title,html,piece_name)
    except Exception as exc:
        log.info("No se pudo leer fuente %s: %s",domain,exc); return None

def _research_serializer():
    from itsdangerous import URLSafeTimedSerializer
    from flask import current_app
    return URLSafeTimedSerializer(current_app.secret_key, salt="despiece-research-v1")


def _make_research_token(result):
    """Token firmado con los modelos propuestos: el servidor solo guarda lo que él mismo propuso."""
    models = []
    for m in (result.get("models") or [])[:25]:
        models.append({
            "brand": _clean(m.get("brand"), 80), "model_name": _clean(m.get("model_name"), 140),
            "codes": [_clean(c, 60) for c in (m.get("codes") or [])[:10]],
            "matches": int(m.get("matches") or 0), "total_sources": int(m.get("total_sources") or 0),
            "confidence": int(m.get("confidence") or 0),
            "sources": [{"domain": _clean(x.get("domain"), 100), "url": _clean(x.get("url"), 500),
                         "title": _clean(x.get("title"), 80)} for x in (m.get("sources") or [])[:6]],
        })
    return _research_serializer().dumps({"ref": result.get("reference", ""), "models": models})


def _save_research_selection(client, repuesto_id, referencia, token, raw_indexes):
    """Guarda como PENDIENTES los modelos que el usuario marcó. Devuelve (guardados, aviso)."""
    if not token:
        return 0, ""
    try:
        indexes = [int(x) for x in json.loads(raw_indexes or "[]")]
    except (TypeError, ValueError):
        return 0, "No se pudo leer la selección de modelos investigados."
    if not indexes:
        return 0, ""
    try:
        data = _research_serializer().loads(token, max_age=2 * 60 * 60)
    except Exception:
        return 0, "La investigación ha caducado o no es válida; vuelve a investigar para asociar modelos."
    if _reference_compact(data.get("ref")) != _reference_compact(referencia):
        return 0, "La referencia cambió después de investigar; vuelve a investigar."
    saved = 0
    for index in dict.fromkeys(indexes):
        if not 0 <= index < len(data.get("models", [])):
            continue
        item = data["models"][index]
        marca = _clean(item.get("brand"), 80)
        codes = [c for c in item.get("codes", []) if c]
        modelo = _clean(item.get("model_name"), 140)
        if modelo.startswith("Modelo identificado por código"):
            modelo = codes[0] if codes else ""
        if not marca or marca == "Marca por confirmar" or not modelo:
            continue
        model = _find_model(marca, modelo)
        if model:
            model_id = int(model["id"])
            if model.get("estado") == "ignorado":
                client.table("despiece_modelos").update({"estado": "pendiente", "origen": "busqueda_referencia"}).eq("id", model_id).execute()
        else:
            inserted = client.table("despiece_modelos").insert({
                "marca": marca, "modelo": modelo, "nombre_completo": f"{marca} {modelo}",
                "numero_modelo": codes[0] if codes else "", "numeros_modelo": codes,
                "tipo": "phone", "estado": "pendiente", "origen": "busqueda_referencia",
                "proveedor": "busqueda_web_manual", "proveedor_id": "",
            }).execute().data or []
            if not inserted:
                continue
            model_id = int(inserted[0]["id"])
        links = " | ".join(f"{x['domain']}: {x['url']}" for x in item.get("sources", [])
                           if x.get("url", "").startswith("https://") and _domain_allowed(x["url"]))
        note = (f"Referencia consultada: {referencia}. Consenso de fuentes: {item.get('confidence')}% "
                f"({item.get('matches')}/{item.get('total_sources')} fuentes independientes). "
                f"Fuentes: {links}. Aprobado por el usuario; pendiente de verificación.")[:1000]
        client.table("despiece_repuesto_modelos").upsert({
            "repuesto_id": repuesto_id, "modelo_id": model_id,
            "estado_compatibilidad": "pendiente", "notas": note,
        }, on_conflict="repuesto_id,modelo_id").execute()
        saved += 1
    return saved, ""


@despiece_bp.post("/api/despiece/buscar-referencia")
@_api_login_required
def api_buscar_referencia_automatica():
    payload=request.get_json(silent=True) or {}
    reference=_clean(payload.get("referencia"),80)
    piece_name=_clean(payload.get("pieza"),120)
    try:
        result=dict(_automatic_reference_research(reference,piece_name))
        result["research_token"]=_make_research_token(result)
        return jsonify(result)
    except Exception:
        log.exception("Error en investigación automática de referencia")
        return jsonify({"ok":False,"message":"No se pudo completar la búsqueda automática. Inténtalo más tarde.","sources":[],"models":[]}), 502

@despiece_bp.get("/despiece/buscar-referencia")
@_login_required
def buscar_referencia():
    """Open public web searches for a part number and record sourced candidates."""
    client = db.get_db()
    repuesto_id = request.args.get("repuesto_id", "").strip()
    repuesto = None
    if repuesto_id:
        try:
            repuesto_id_int = int(repuesto_id)
        except (TypeError, ValueError):
            abort(404)
        rows = (client.table("despiece_repuestos")
                .select("id,familia_id,marca,modelo,pieza,referencia,descripcion")
                .eq("id", repuesto_id_int).limit(1).execute().data or [])
        if not rows:
            abort(404)
        repuesto = rows[0]
        repuesto_id = str(repuesto_id_int)

    reference = _clean(request.args.get("referencia") or (repuesto or {}).get("referencia"), 120)
    piece_name = _clean(request.args.get("pieza") or (repuesto or {}).get("pieza"), 120)
    links = []

    current_models = []
    if repuesto:
        relations = (client.table("despiece_repuesto_modelos")
                     .select("modelo_id,estado_compatibilidad,notas")
                     .eq("repuesto_id", int(repuesto_id)).execute().data or [])
        model_ids = [int(x["modelo_id"]) for x in relations]
        models_by_id = {}
        if model_ids:
            found = (client.table("despiece_modelos")
                     .select("id,marca,modelo,numero_modelo,estado")
                     .in_("id", model_ids).execute().data or [])
            models_by_id = {int(x["id"]): x for x in found}
        for relation in relations:
            item = models_by_id.get(int(relation["modelo_id"]))
            if item:
                current_models.append({**item,
                    "estado_compatibilidad": relation.get("estado_compatibilidad", "pendiente"),
                    "notas": relation.get("notas", "")})

    return render_template(
        "despiece_buscar_referencia.html",
        repuesto=repuesto,
        repuesto_id=repuesto_id,
        referencia=reference,
        pieza=piece_name,
        enlaces_busqueda=links,
        modelos_asociados=current_models,
    )


@despiece_bp.post("/despiece/buscar-referencia/guardar")
@_login_required
def guardar_modelo_por_referencia():
    """Save a candidate model + relation; default is pending, never auto-verified."""
    client = db.get_db()
    try:
        repuesto_id = int(request.form.get("repuesto_id", ""))
    except (TypeError, ValueError):
        abort(400)
    repuestos = (client.table("despiece_repuestos")
                 .select("id,referencia,pieza")
                 .eq("id", repuesto_id).limit(1).execute().data or [])
    if not repuestos:
        abort(404)

    marca = _clean(request.form.get("marca"), 80)
    modelo = _clean(request.form.get("modelo"), 140)
    numbers = _parse_model_numbers(request.form.get("numeros_modelo", ""))
    source_url = _clean(request.form.get("fuente_url"), 500)
    consensus = _clean(request.form.get("consenso"), 80)
    try:
        submitted_sources = json.loads(request.form.get("fuentes_json", "[]"))
        if not isinstance(submitted_sources, list):
            submitted_sources = []
    except (TypeError, ValueError):
        submitted_sources = []
    reference = _clean(request.form.get("referencia") or repuestos[0].get("referencia"), 120)
    if not marca or not modelo:
        flash("Indica la marca y el modelo encontrado.", "error")
        return redirect(url_for("despiece_inteligente.buscar_referencia", repuesto_id=repuesto_id, referencia=reference))
    if source_url and not re.match(r"^https?://[^\s]+$", source_url, re.IGNORECASE):
        flash("La fuente debe ser una dirección web que empiece por http:// o https://.", "error")
        return redirect(url_for("despiece_inteligente.buscar_referencia", repuesto_id=repuesto_id, referencia=reference))

    try:
        model = _find_model(marca, modelo)
        if model:
            model_id = int(model["id"])
            if model.get("estado") == "ignorado":
                client.table("despiece_modelos").update({"estado": "pendiente", "origen": "busqueda_referencia"}).eq("id", model_id).execute()
        else:
            payload = {
                "marca": marca,
                "modelo": modelo,
                "nombre_completo": f"{marca} {modelo}",
                "numero_modelo": numbers[0] if numbers else "",
                "numeros_modelo": numbers,
                "tipo": _clean(request.form.get("tipo_dispositivo"), 30).lower() or "phone",
                "estado": "pendiente",
                "origen": "busqueda_referencia",
                "proveedor": "busqueda_web_manual",
                "proveedor_id": "",
            }
            inserted = client.table("despiece_modelos").insert(payload).execute().data or []
            if not inserted:
                raise RuntimeError("Supabase no devolvió el modelo creado.")
            model_id = int(inserted[0]["id"])

        existing_relation = (client.table("despiece_repuesto_modelos")
                             .select("estado_compatibilidad,notas")
                             .eq("repuesto_id", repuesto_id).eq("modelo_id", model_id)
                             .limit(1).execute().data or [])
        explicitly_verified = request.form.get("verificada") == "1" and bool(source_url)
        old_verified = bool(existing_relation and existing_relation[0].get("estado_compatibilidad") == "verificada")
        status = "verificada" if (explicitly_verified or old_verified) else "pendiente"
        note_parts = [f"Referencia consultada: {reference or 'sin referencia'}."]
        if consensus:
            note_parts.append(f"Consenso de fuentes: {consensus}")
        safe_sources=[]
        for source in submitted_sources[:12]:
            if not isinstance(source, dict):
                continue
            source_domain=_clean(source.get("domain"), 100)
            source_link=_clean(source.get("url"), 500)
            if source_domain and re.match(r"^https?://[^\s]+$", source_link, re.IGNORECASE) and _domain_allowed(source_link):
                safe_sources.append(f"{source_domain}: {source_link}")
        if safe_sources:
            note_parts.append("Fuentes consultadas: " + " | ".join(safe_sources))
        elif source_url:
            note_parts.append(f"Fuente: {source_url}")
        note_parts.append("Investigación automática multi-componente; compatibilidad revisada por el usuario antes de guardar.")
        old_notes = existing_relation[0].get("notas", "") if existing_relation else ""
        notes = " ".join(x for x in [old_notes, " ".join(note_parts)] if x).strip()[:1000]
        client.table("despiece_repuesto_modelos").upsert({
            "repuesto_id": repuesto_id,
            "modelo_id": model_id,
            "estado_compatibilidad": status,
            "notas": notes,
        }, on_conflict="repuesto_id,modelo_id").execute()

        model_state = (client.table("despiece_modelos").select("estado")
                       .eq("id", model_id).limit(1).execute().data or [{}])[0].get("estado", "pendiente")
        if status == "verificada":
            flash("Compatibilidad guardada como verificada. El modelo nuevo, si lo era, sigue pendiente de aprobación en el catálogo.", "success")
        elif model_state == "pendiente":
            flash("Modelo y compatibilidad guardados como pendientes. Aprueba el modelo desde Catálogo de modelos cuando quieras incorporarlo.", "success")
        else:
            flash("Modelo asociado. La compatibilidad queda pendiente de verificación.", "success")
    except Exception:
        log.exception("No se pudo guardar la compatibilidad desde búsqueda web para el repuesto %s", repuesto_id)
        flash("No se pudo guardar el modelo. Comprueba que está instalada la migración del catálogo inteligente.", "error")

    return redirect(url_for("despiece_inteligente.buscar_referencia", repuesto_id=repuesto_id, referencia=reference))
