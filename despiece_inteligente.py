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
from urllib.parse import urlencode, quote_plus, urlparse, parse_qs, unquote
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
import time
import unicodedata
import xml.etree.ElementTree as ET

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
_REFERENCE_CACHE_TTL = 6 * 60 * 60
_REFERENCE_SOURCES = (
    "ifixit.com", "impextrom.com", "ovisat.com", "servicepacksamsung.com",
    "pds.com.gr", "techtekshop.es", "subtel.es", "repuestosmovil.es",
    "restaurio.es", "techcomponentes.com", "phoneparts.es", "gsmobile.es",
    "spainsellers.com", "fixandgoparts.com", "newprime.es", "partob.com",
    "mobilepartsfinder.com", "combodekho.com", "abhaytechnicals.com",
)

# Identificadores técnicos usados por distintos fabricantes. Se extraen
# códigos de dispositivo, nunca códigos de pieza arbitrarios.
_MODEL_PATTERNS = [
    ("Samsung", re.compile(r"\b(?:SM|GT|SCH|SGH)-[A-Z0-9]{3,}(?:/[A-Z0-9]+)?\b", re.I)),
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
    ("Samsung", re.compile(r"\bGalaxy\s+(?:(?:S|A|M|F|J|Note)\s*\d{1,3}|Z\s*(?:Fold|Flip)\s*\d{1,2}|Tab\s+S?\d{1,2})(?:\s*(?:5G|4G|Ultra|Plus|FE))?\b", re.I)),
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

class _DDGResults(HTMLParser):
    def __init__(self):
        super().__init__(); self.links=[]; self._href=None; self._text=[]; self._capture=False
    def handle_starttag(self, tag, attrs):
        attrs=dict(attrs)
        if tag == "a" and ("result__a" in attrs.get("class", "") or "result-link" in attrs.get("class", "")):
            self._href=attrs.get("href"); self._text=[]; self._capture=True
    def handle_data(self, data):
        if self._capture: self._text.append(data)
    def handle_endtag(self, tag):
        if tag == "a" and self._capture:
            href=self._href or ""
            if "uddg=" in href:
                try: href=parse_qs(urlparse(href).query).get("uddg", [href])[0]
                except Exception: pass
            if href.startswith("http"):
                self.links.append((href, " ".join(self._text).strip()))
            self._href=None; self._text=[]; self._capture=False

class _VisibleText(HTMLParser):
    def __init__(self): super().__init__(); self.parts=[]; self.skip=0
    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript", "svg", "header", "footer"): self.skip+=1
    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "svg", "header", "footer") and self.skip: self.skip-=1
    def handle_data(self, data):
        if not self.skip and data.strip(): self.parts.append(data.strip())

def _http_text(url, limit=1_200_000):
    req=Request(url, headers={"User-Agent":"Mozilla/5.0 (compatible; INFORBAXE-CompatibilityResearch/2.0)",
                              "Accept":"text/html,application/xhtml+xml;q=0.9,*/*;q=0.5",
                              "Accept-Language":"es-ES,es;q=0.9,en;q=0.8"})
    with urlopen(req, timeout=6) as response:
        data=response.read(limit)
        charset=response.headers.get_content_charset() or "utf-8"
        return data.decode(charset, errors="replace"), response.geturl()

def _domain_allowed(url):
    host=(urlparse(url).hostname or "").lower().split(":")[0]
    return any(host == d or host.endswith("."+d) for d in _REFERENCE_SOURCES)

def _piece_search_terms(piece_name=""):
    """Map any workshop part label to multilingual terms for public search."""
    value=unicodedata.normalize("NFKD", _norm(piece_name)).encode("ascii", "ignore").decode("ascii")
    maps = {
        ("bater", "battery", "acumulador"): "bateria battery replacement accu",
        ("pantall", "display", "screen", "lcd", "oled"): "pantalla display screen LCD OLED replacement",
        ("camar", "camera", "lente"): "camara camera rear front lens replacement",
        ("conector", "carga", "charging", "usb", "flex carga"): "conector carga charging port USB flex replacement",
        ("altavoz", "auricular", "speaker", "earpiece", "microfono", "microphone"): "altavoz auricular speaker earpiece microphone",
        ("vibrador", "vibrator", "motor vibr"): "vibrador vibrator motor replacement",
        ("tapa", "carcasa", "housing", "back cover", "chasis"): "tapa trasera carcasa housing back cover frame",
        ("flex", "boton", "button", "encendido", "volumen"): "flex cable button power volume replacement",
        ("placa", "motherboard", "mainboard", "subplaca"): "placa base motherboard mainboard sub board",
        ("antena", "nfc", "coaxial"): "antena antenna NFC coaxial cable",
        ("sim", "bandeja", "tray"): "bandeja SIM tray card reader",
        ("sensor", "huella", "fingerprint", "proximidad"): "sensor fingerprint proximity flex",
        ("cristal", "glass", "camara trasera"): "cristal glass lens camera replacement",
    }
    for keys, terms in maps.items():
        if any(key in value for key in keys):
            return terms
    return _clean(piece_name, 80)

def _search_source_domain(reference, domain, piece_name=""):
    # La categoría del repuesto mejora la búsqueda, pero nunca sustituye a la
    # coincidencia literal de la referencia dentro de la página final.
    context=_piece_search_terms(piece_name)
    query=f'"{reference}" {context} compatibilidad modelos compatibles'.strip()
    search_url="https://html.duckduckgo.com/html/?q="+quote_plus(f'{query} site:{domain}')
    found=[]
    try:
        html,_final_url=_http_text(search_url, 500_000)
        parser=_DDGResults(); parser.feed(html)
        for url, title in parser.links:
            if _domain_allowed(url) and domain in (urlparse(url).hostname or ""):
                found.append((url, title))
            if len(found)>=2: break
    except Exception as exc:
        log.info("DuckDuckGo no disponible para %s: %s", domain, exc)
    if not found:
        try:
            bing_url="https://www.bing.com/search?format=rss&q="+quote_plus(f'{query} site:{domain}')
            xml,_final_url=_http_text(bing_url, 500_000)
            root=ET.fromstring(xml)
            for item in root.findall(".//item"):
                url=(item.findtext("link") or "").strip()
                title=(item.findtext("title") or "").strip()
                if url.startswith("http") and _domain_allowed(url) and domain in (urlparse(url).hostname or ""):
                    found.append((url,title))
                if len(found)>=2: break
        except Exception as exc:
            log.info("Bing RSS no disponible para %s: %s",domain,exc)
    return domain, found

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

def _extract_device_candidates(reference, compact, title=""):
    candidates=[]
    for brand, pattern in _MODEL_PATTERNS:
        for match in pattern.finditer(compact):
            code=match.group(0).upper()
            context=compact[max(0,match.start()-320):min(len(compact),match.end()+180)]
            names=_device_names_near(context, code)
            compatible_names=[]
            brand_groups={
                "Huawei/Honor": {"Huawei", "Honor"},
                "OPPO/OnePlus": {"OPPO", "OnePlus"},
                "Tecno/Infinix": {"Tecno", "Infinix"},
            }
            allowed_brands=brand_groups.get(brand, {brand})
            compatible_names=[item for item in names if item["marca"] in allowed_brands]
            # El código es la evidencia primaria. No asociamos por proximidad
            # nombres de otra marca: evitamos cruces en páginas multimarca.
            if compatible_names:
                for item in compatible_names[:2]:
                    candidates.append({"code":code,"brand":item["marca"],"model_name":item["modelo"]})
            else:
                candidates.append({"code":code,"brand":brand,"model_name":f"Modelo identificado por código {code}"})
    title_names=_device_names_near(title or "")
    ref_position=compact.casefold().find(reference.casefold())
    around_reference=compact[max(0,ref_position-2200):min(len(compact),ref_position+3200)] if ref_position >= 0 else compact[:3200]
    page_names=_device_names_near(around_reference)
    # Si una página separa el nombre comercial y el código en secciones
    # próximas, asociamos el nombre solo cuando hay una única opción inequívoca
    # de esa marca en el contexto de la referencia.
    all_names=title_names + page_names
    for candidate in candidates:
        if candidate["model_name"].startswith("Modelo identificado por código"):
            options=[item for item in all_names if item["marca"] == candidate["brand"]]
            unique_options={item["modelo"] for item in options}
            if len(unique_options)==1:
                candidate["model_name"]=next(iter(unique_options))
    # Los nombres comerciales sin código se aceptan solo en la misma página
    # que contiene la referencia exacta. No duplicamos nombres ya ligados a
    # un código de modelo identificado en esa misma fuente.
    coded_names={(x["brand"].casefold(),x["model_name"].casefold()) for x in candidates if x.get("code")}
    for item in all_names:
        key=(item["marca"].casefold(),item["modelo"].casefold())
        if key not in coded_names:
            candidates.append({"code":"","brand":item["marca"],"model_name":item["modelo"]})
    unique=[]; seen=set()
    for item in candidates:
        key=(item["code"].casefold(),item["brand"].casefold(),item["model_name"].casefold())
        if key not in seen:
            seen.add(key); unique.append(item)
    return unique[:60]

def _extract_evidence(reference, domain, url, title, piece_name=""):
    try:
        html,final_url=_http_text(url)
        if not _domain_allowed(final_url) or domain not in (urlparse(final_url).hostname or ""):
            return None
    except Exception as exc:
        log.info("No se pudo leer fuente %s: %s", domain, exc)
        return None
    parser=_VisibleText(); parser.feed(html)
    text=" ".join(parser.parts)
    compact=re.sub(r"\s+", " ", text)
    if reference.casefold() not in compact.casefold():
        return None
    candidates=_extract_device_candidates(reference, compact, title)
    if not candidates:
        return None
    title_clean=re.sub(r"\s+", " ", title or "").strip()[:180]
    return {"domain":domain,"url":url,"title":title_clean or domain,
            "candidates":candidates,"excerpt":compact[:1200]}

def _automatic_reference_research(reference, piece_name=""):
    ref=re.sub(r"[^A-Za-z0-9._/-]", "", _clean(reference, 80)).upper()
    piece=_clean(piece_name,100)
    if len(ref)<4:
        return {"ok":False,"message":"Introduce una referencia de al menos 4 caracteres.","sources":[],"models":[]}
    cache_key=f"{ref}|{piece.casefold()}"
    cached=_REFERENCE_CACHE.get(cache_key)
    now=time.time()
    if cached and now-cached[0] < _REFERENCE_CACHE_TTL:
        result=dict(cached[1]); result["cached"]=True; return result
    results=[]; errors=[]; discovered=[]
    # Fase 1: localizar productos en varios catálogos en paralelo.
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures={pool.submit(_search_source_domain,ref,d,piece):d for d in _REFERENCE_SOURCES}
        for future in as_completed(futures):
            domain=futures[future]
            try:
                d, links=future.result()
                discovered.extend((d,url,title) for url,title in links[:2])
            except Exception as exc:
                errors.append(domain); log.info("Búsqueda de referencia fallida en %s: %s",domain,exc)
    # Fase 2: leer páginas originales en paralelo. La búsqueda nunca depende
    # de una única fuente y no abre pestañas en el navegador del usuario.
    with ThreadPoolExecutor(max_workers=12) as pool:
        futures={pool.submit(_extract_evidence,ref,d,url,title,piece):(d,url) for d,url,title in discovered}
        for future in as_completed(futures):
            try:
                evidence=future.result()
                if evidence: results.append(evidence)
            except Exception as exc:
                log.info("No se pudo extraer evidencia de %s: %s",futures[future][0],exc)
    # Dominio independiente: cada host cuenta una sola vez por candidato.
    by_candidate={}
    evidence_domains=set()
    for item in results:
        evidence_domains.add(item["domain"])
        for candidate in item["candidates"]:
            code=candidate.get("code","")
            name=candidate.get("model_name","")
            brand=candidate.get("brand","")
            # Preferimos códigos técnicos para evitar mezclar variantes. Los
            # nombres sin código se agrupan por marca + nombre exacto.
            key=(f"{brand}:{code}".casefold() if code else f"name:{brand}:{name}".casefold())
            entry=by_candidate.setdefault(key,{**candidate,"domains":set(),"sources":[]})
            entry["domains"].add(item["domain"])
            if not any(x["url"]==item["url"] for x in entry["sources"]):
                entry["sources"].append({"domain":item["domain"],"title":item["title"],"url":item["url"]})
            # Si una fuente identifica el código y otra aporta el nombre, usar
            # el nombre comercial sin perder el código individual.
            if entry["model_name"].startswith("Modelo identificado por código") and not name.startswith("Modelo identificado"):
                entry["model_name"]=name
                entry["brand"]=brand or entry["brand"]
    total_domains=len(evidence_domains)
    minimum=max(3, int((total_domains*0.70)+0.999)) if total_domains else 3
    models=[]
    for key,item in sorted(by_candidate.items()):
        count=len(item["domains"])
        if count < minimum:
            continue
        models.append({
            "code":item.get("code", ""),
            "codes":[item.get("code")] if item.get("code") else [],
            "brand":item.get("brand") or "Marca por confirmar",
            "model_name":item.get("model_name") or "Modelo sin identificar",
            "matches":count,
            "total_sources":total_domains,
            "confidence":round(100*count/max(total_domains,1)),
            "sources":item["sources"],
        })
    source_list=[]
    for item in results:
        if not any(x["domain"]==item["domain"] for x in source_list):
            source_list.append({"domain":item["domain"],"title":item["title"],"url":item["url"]})
    result={"ok":bool(models),"reference":ref,"piece":piece,"sources":source_list,"models":models,
            "checked_domains":list(_REFERENCE_SOURCES),"successful_domains":total_domains,
            "minimum_consensus":minimum,
            "message":("Se encontraron coincidencias entre dominios distintos." if models else
                       "No hay consenso suficiente. No mostraremos compatibilidades como confirmadas."),
            "errors":errors,"cached":False}
    _REFERENCE_CACHE[cache_key]=(now,result)
    return result

@despiece_bp.post("/api/despiece/buscar-referencia")
@_login_required
def api_buscar_referencia_automatica():
    payload=request.get_json(silent=True) or {}
    reference=_clean(payload.get("referencia"),80)
    piece_name=_clean(payload.get("pieza"),120)
    try:
        result=_automatic_reference_research(reference,piece_name)
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
