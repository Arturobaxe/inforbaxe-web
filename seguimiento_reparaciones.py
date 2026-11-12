"""Seguimiento privado de reparaciones para clientes de INFORBAXE."""
import hashlib
import hmac
import io
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import (
    Blueprint, abort, flash, jsonify, make_response,
    redirect, render_template, request, session, url_for,
)
from PIL import Image, ImageOps, UnidentifiedImageError

import database as db

log = logging.getLogger(__name__)
seguimiento_bp = Blueprint("seguimiento_reparaciones", __name__)
BUCKET = "inforbaxe-seguimientos"
MAX_UPLOAD_BYTES = 8 * 1024 * 1024
MAX_STORED_BYTES = 5 * 1024 * 1024
PUBLIC_STATES = (
    ("pieza_en_camino", "Pieza en camino"),
    ("reparando", "Reparando"),
    ("reparacion_acabada", "Reparación acabada"),
)
STATE_LABELS = dict(PUBLIC_STATES)


def _utcnow():
    return datetime.now(timezone.utc)


def _iso(dt):
    return dt.astimezone(timezone.utc).isoformat()


def _parse_datetime(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _expiration_for(completed_at):
    return completed_at + timedelta(days=5)


def _is_expired(row, now=None):
    expiry = _parse_datetime((row or {}).get("fecha_caducidad"))
    return bool(expiry and expiry <= (now or _utcnow()))


def _token_hash(token):
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()


def _staff_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapped


def _table():
    return db.get_db().table("seguimientos_reparacion")


def _tracking_by_id(tracking_id):
    rows = (_table().select("*").eq("id", int(tracking_id)).limit(1).execute().data or [])
    return rows[0] if rows else None


def _tracking_by_token(token):
    if not token or len(token) > 100:
        return None
    rows = (_table().select("*").eq("token_hash", _token_hash(token)).limit(1).execute().data or [])
    return rows[0] if rows else None


def _photo_storage():
    return db.get_db().storage.from_(BUCKET)


def _remove_photo(path):
    if not path:
        return True
    try:
        _photo_storage().remove([path])
        return True
    except Exception:
        log.exception("No se pudo eliminar la fotografía del seguimiento")
        return False


def _clear_expired_photo(row):
    path = row.get("foto_path")
    if not path or not _remove_photo(path):
        return not path
    now = _iso(_utcnow())
    try:
        (_table().update({
            "foto_path": None,
            "fecha_foto_eliminada": now,
            "fecha_actualizacion": now,
        }).eq("id", int(row["id"])).eq("foto_path", path).execute())
        row["foto_path"] = None
        return True
    except Exception:
        log.exception("No se pudo actualizar el seguimiento tras borrar la fotografía")
        return False


def _prepare_photo(upload):
    """Valida, reduce y recodifica la imagen; no conserva EXIF ni GPS."""
    if not upload or not getattr(upload, "filename", ""):
        raise ValueError("Selecciona una fotografía del dispositivo.")
    raw = upload.read(MAX_UPLOAD_BYTES + 1)
    if not raw:
        raise ValueError("El archivo está vacío.")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ValueError("La fotografía no puede superar los 8 MB.")
    try:
        image = Image.open(io.BytesIO(raw))
        if image.format not in {"JPEG", "PNG", "WEBP"}:
            raise ValueError("Utiliza una imagen JPG, PNG o WebP.")
        image.verify()
        image = Image.open(io.BytesIO(raw))
        if image.width * image.height > 35_000_000:
            raise ValueError("La resolución de la fotografía es demasiado grande.")
        image = ImageOps.exif_transpose(image).convert("RGB")
        image.thumbnail((1600, 1600))
        output = io.BytesIO()
        quality = 86
        while quality >= 54:
            output.seek(0)
            output.truncate(0)
            image.save(output, format="JPEG", quality=quality, optimize=True, progressive=True)
            content = output.getvalue()
            if len(content) <= MAX_STORED_BYTES:
                return content
            quality -= 8
        raise ValueError("No se ha podido reducir la fotografía por debajo de 5 MB.")
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("El archivo no parece ser una imagen válida.") from exc


def _public_base_url():
    configured = (os.environ.get("PUBLIC_BASE_URL") or "").strip().rstrip("/")
    if configured:
        return configured
    host = request.headers.get("X-Forwarded-Host") or request.host
    scheme = (request.headers.get("X-Forwarded-Proto") or request.scheme).split(",")[0].strip()
    if scheme not in {"http", "https"}:
        scheme = "https"
    return f"{scheme}://{host}"


def _public_payload(row):
    return {
        "estado": row.get("estado"),
        "equipo": row.get("equipo") or "Tu dispositivo",
        "trabajo": row.get("trabajo") or "",
        "fecha_actualizacion": row.get("fecha_actualizacion"),
        "foto_disponible": bool(row.get("foto_path")) and row.get("estado") == "reparacion_acabada",
    }


@seguimiento_bp.route("/clientes/<int:id_cliente>/seguimientos", methods=["GET", "POST"])
@_staff_required
def admin_cliente(id_cliente):
    cliente = db.get_cliente(id_cliente)
    if not cliente:
        abort(404)

    if request.method == "POST":
        equipo = (request.form.get("equipo") or "").strip()[:120]
        trabajo = (request.form.get("trabajo") or "").strip()[:180]
        if not equipo:
            flash("Indica el modelo o nombre del dispositivo.", "error")
        else:
            now = _iso(_utcnow())
            try:
                _table().insert({
                    "id_cliente": int(id_cliente),
                    "equipo": equipo,
                    "trabajo": trabajo,
                    "estado": "pieza_en_camino",
                    "activo": False,
                    "token_hash": None,
                    "foto_path": None,
                    "fecha_creacion": now,
                    "fecha_actualizacion": now,
                    "fecha_finalizacion": None,
                    "fecha_caducidad": None,
                    "fecha_foto_eliminada": None,
                }).execute()
                flash("Seguimiento creado. Todavía no hay ningún enlace activo.", "success")
            except Exception:
                log.exception("No se pudo crear el seguimiento")
                flash("No se pudo crear el seguimiento. Comprueba que has ejecutado el SQL de instalación en Supabase.", "error")
        return redirect(url_for("seguimiento_reparaciones.admin_cliente", id_cliente=id_cliente))

    try:
        seguimientos = (_table().select("*").eq("id_cliente", int(id_cliente))
                        .order("fecha_creacion", desc=True).limit(50).execute().data or [])
        for item in seguimientos:
            item["caducado"] = _is_expired(item)
    except Exception:
        log.exception("No se pudieron consultar los seguimientos")
        seguimientos = []
        flash("Falta instalar la tabla de seguimientos en Supabase. Ejecuta migrations/seguimientos_reparaciones.sql.", "error")

    share_url = None
    share_cliente = session.pop("seguimiento_share_cliente", None)
    stored_url = session.pop("seguimiento_share_url", None)
    if share_cliente == int(id_cliente):
        share_url = stored_url
    return render_template(
        "seguimientos_cliente.html",
        cliente=cliente,
        seguimientos=seguimientos,
        share_url=share_url,
        state_labels=STATE_LABELS,
        now=_iso(_utcnow()),
    )


@seguimiento_bp.route("/seguimientos/enlaces-activos")
@_staff_required
def enlaces_activos():
    """Panel global de enlaces de seguimiento activos."""
    enlaces = []
    offset = 0
    page_size = 500
    while True:
        rows = (_table()
                .select("id,id_cliente,equipo,trabajo,estado,activo,fecha_creacion,fecha_actualizacion,fecha_finalizacion,fecha_caducidad,clientes(nombre)")
                .eq("activo", True)
                .order("fecha_creacion", desc=True)
                .range(offset, offset + page_size - 1)
                .execute().data or [])
        for row in rows:
            cliente = row.pop("clientes", None) or {}
            if isinstance(cliente, list):
                cliente = cliente[0] if cliente else {}
            row["nombre_cliente"] = cliente.get("nombre", "Cliente")
            row["caducado"] = _is_expired(row)
            enlaces.append(row)
        if len(rows) < page_size:
            break
        offset += page_size
    disponibles = sum(1 for item in enlaces if not item["caducado"])
    caducados = len(enlaces) - disponibles
    return render_template(
        "enlaces_activos.html",
        enlaces=enlaces,
        state_labels=STATE_LABELS,
        total=len(enlaces),
        disponibles=disponibles,
        caducados=caducados,
    )


@seguimiento_bp.route("/ventas/<int:id_venta>/seguimiento", methods=["POST"])
@_staff_required
def crear_desde_venta(id_venta):
    """Crea y activa un seguimiento privado a partir del dispositivo de una venta."""
    venta = db.get_venta(id_venta)
    if not venta:
        abort(404)

    equipo = (venta.get("equipo_modelo") or "").strip()[:120]
    if not equipo:
        flash("Esta venta no tiene el modelo del dispositivo. Rellénalo en Editar y vuelve a pulsar Seguimiento.", "error")
        return redirect(url_for("venta_editar", id_venta=id_venta))

    id_cliente = int(venta["id_cliente"])
    now = _iso(_utcnow())
    tracking_id = None
    try:
        created = (_table().insert({
            "id_cliente": id_cliente,
            "equipo": equipo,
            "trabajo": "Reparación del dispositivo",
            "estado": "pieza_en_camino",
            "activo": False,
            "token_hash": None,
            "foto_path": None,
            "fecha_creacion": now,
            "fecha_actualizacion": now,
            "fecha_finalizacion": None,
            "fecha_caducidad": None,
            "fecha_foto_eliminada": None,
        }).execute().data or [])
        if not created or not created[0].get("id"):
            raise RuntimeError("No se recibió el identificador del seguimiento.")
        tracking_id = int(created[0]["id"])

        token = secrets.token_urlsafe(32)
        _table().update({
            "token_hash": _token_hash(token),
            "activo": True,
            "fecha_actualizacion": now,
        }).eq("id", tracking_id).execute()

        share_url = f"{_public_base_url()}{url_for('seguimiento_reparaciones.public_tracking', token=token)}"
        session["seguimiento_share_cliente"] = id_cliente
        session["seguimiento_share_url"] = share_url
        flash("Seguimiento creado para esta venta. Copia el enlace y envíaselo al cliente cuando quieras.", "success")
    except Exception:
        if tracking_id:
            try:
                _table().delete().eq("id", tracking_id).execute()
            except Exception:
                log.exception("No se pudo limpiar un seguimiento incompleto de la venta %s", id_venta)
        log.exception("No se pudo crear el seguimiento desde la venta %s", id_venta)
        flash("No se pudo crear el seguimiento. Comprueba la instalación de seguimientos en Supabase.", "error")

    return redirect(url_for("seguimiento_reparaciones.admin_cliente", id_cliente=id_cliente))


@seguimiento_bp.route("/seguimientos/<int:id_seguimiento>/enlace", methods=["POST"])
@_staff_required
def generar_enlace(id_seguimiento):
    row = _tracking_by_id(id_seguimiento)
    if not row:
        abort(404)
    if _is_expired(row):
        flash("Este seguimiento ya ha caducado. Crea uno nuevo para otra reparación.", "error")
        return redirect(url_for("seguimiento_reparaciones.admin_cliente", id_cliente=row["id_cliente"]))

    token = secrets.token_urlsafe(32)
    now = _iso(_utcnow())
    _table().update({
        "token_hash": _token_hash(token),
        "activo": True,
        "fecha_actualizacion": now,
    }).eq("id", int(id_seguimiento)).execute()
    share_url = f"{_public_base_url()}{url_for('seguimiento_reparaciones.public_tracking', token=token)}"
    session["seguimiento_share_cliente"] = int(row["id_cliente"])
    session["seguimiento_share_url"] = share_url
    flash("Enlace generado. Solo el cliente al que se lo envíes podrá consultar el seguimiento.", "success")
    return redirect(url_for("seguimiento_reparaciones.admin_cliente", id_cliente=row["id_cliente"]))


@seguimiento_bp.route("/seguimientos/<int:id_seguimiento>/estado", methods=["POST"])
@_staff_required
def actualizar_estado(id_seguimiento):
    row = _tracking_by_id(id_seguimiento)
    if not row:
        abort(404)
    estado = (request.form.get("estado") or "").strip()
    if estado not in {"pieza_en_camino", "reparando"}:
        abort(400)
    if row.get("estado") == "reparacion_acabada":
        flash("Una reparación finalizada no se puede reabrir desde este seguimiento.", "error")
    elif _is_expired(row):
        flash("El seguimiento ya ha caducado.", "error")
    else:
        _table().update({"estado": estado, "fecha_actualizacion": _iso(_utcnow())}).eq("id", int(id_seguimiento)).execute()
        flash("Estado actualizado.", "success")
    return redirect(url_for("seguimiento_reparaciones.admin_cliente", id_cliente=row["id_cliente"]))


@seguimiento_bp.route("/seguimientos/<int:id_seguimiento>/finalizar", methods=["POST"])
@_staff_required
def finalizar_reparacion(id_seguimiento):
    row = _tracking_by_id(id_seguimiento)
    if not row:
        abort(404)
    if row.get("estado") == "reparacion_acabada" or _is_expired(row):
        flash("Este seguimiento ya está finalizado o ha caducado.", "error")
        return redirect(url_for("seguimiento_reparaciones.admin_cliente", id_cliente=row["id_cliente"]))

    try:
        content = _prepare_photo(request.files.get("foto"))
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("seguimiento_reparaciones.admin_cliente", id_cliente=row["id_cliente"]))

    path = f"{int(id_seguimiento)}/{secrets.token_hex(16)}.jpg"
    old_path = row.get("foto_path")
    try:
        _photo_storage().upload(
            path,
            content,
            file_options={"content-type": "image/jpeg", "cache-control": "no-store", "upsert": "false"},
        )
        completed = _utcnow()
        _table().update({
            "estado": "reparacion_acabada",
            "foto_path": path,
            "fecha_actualizacion": _iso(completed),
            "fecha_finalizacion": _iso(completed),
            "fecha_caducidad": _iso(_expiration_for(completed)),
            "fecha_foto_eliminada": None,
        }).eq("id", int(id_seguimiento)).execute()
        if old_path and old_path != path:
            _remove_photo(old_path)
        flash("Reparación finalizada. La fotografía y el enlace caducarán en cinco días.", "success")
    except Exception:
        _remove_photo(path)
        log.exception("No se pudo finalizar la reparación")
        flash("No se pudo guardar la fotografía. No se ha cambiado el estado.", "error")
    return redirect(url_for("seguimiento_reparaciones.admin_cliente", id_cliente=row["id_cliente"]))


@seguimiento_bp.route("/seguimientos/<int:id_seguimiento>/revocar", methods=["POST"])
@_staff_required
def revocar_enlace(id_seguimiento):
    row = _tracking_by_id(id_seguimiento)
    if not row:
        abort(404)
    path = row.get("foto_path")
    _table().update({
        "activo": False,
        "token_hash": None,
        "foto_path": None,
        "fecha_foto_eliminada": _iso(_utcnow()) if path else row.get("fecha_foto_eliminada"),
        "fecha_actualizacion": _iso(_utcnow()),
    }).eq("id", int(id_seguimiento)).execute()
    if path:
        _remove_photo(path)
    flash("Enlace desactivado. El cliente ya no puede consultar el seguimiento.", "success")
    if request.form.get("origen") == "panel":
        return redirect(url_for("seguimiento_reparaciones.enlaces_activos"))
    return redirect(url_for("seguimiento_reparaciones.admin_cliente", id_cliente=row["id_cliente"]))


def _public_row(token):
    row = _tracking_by_token(token)
    if not row or not row.get("activo"):
        return None, False
    expired = _is_expired(row)
    if expired:
        _clear_expired_photo(row)
    return row, expired


@seguimiento_bp.route("/seguimiento/<token>")
def public_tracking(token):
    row, expired = _public_row(token)
    if not row:
        abort(404)
    if expired:
        response = make_response(render_template("seguimiento_publico.html", expired=True))
    else:
        state_index = next((i for i, item in enumerate(PUBLIC_STATES) if item[0] == row.get("estado")), 0)
        response = make_response(render_template(
            "seguimiento_publico.html",
            expired=False,
            payload=_public_payload(row),
            states=PUBLIC_STATES,
            state_index=state_index,
            token=token,
        ))
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@seguimiento_bp.route("/seguimiento/<token>/estado")
def public_tracking_status(token):
    row, expired = _public_row(token)
    if not row:
        return jsonify({"expired": True}), 404
    if expired:
        return jsonify({"expired": True}), 410
    response = jsonify(_public_payload(row))
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response


@seguimiento_bp.route("/seguimiento/<token>/foto")
def public_tracking_photo(token):
    row, expired = _public_row(token)
    if not row or expired or row.get("estado") != "reparacion_acabada" or not row.get("foto_path"):
        abort(404)
    try:
        content = _photo_storage().download(row["foto_path"])
    except Exception:
        log.exception("No se pudo servir la fotografía del seguimiento")
        abort(404)
    response = make_response(bytes(content))
    response.headers["Content-Type"] = "image/jpeg"
    response.headers["Content-Disposition"] = "inline; filename=dispositivo-reparado.jpg"
    response.headers["Cache-Control"] = "private, no-store, max-age=0"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


def _cleanup_expired_photos(limit=100):
    now = _utcnow()
    rows = (_table().select("id,foto_path,fecha_caducidad")
            .eq("estado", "reparacion_acabada")
            .lte("fecha_caducidad", _iso(now))
            .limit(limit).execute().data or [])
    removed = failed = 0
    for row in rows:
        path = row.get("foto_path")
        if not path:
            continue
        if _remove_photo(path):
            try:
                (_table().update({
                    "foto_path": None,
                    "fecha_foto_eliminada": _iso(now),
                    "fecha_actualizacion": _iso(now),
                }).eq("id", int(row["id"])).eq("foto_path", path).execute())
                removed += 1
            except Exception:
                failed += 1
                log.exception("No se pudo marcar como eliminada la foto del seguimiento %s", row["id"])
        else:
            failed += 1
    return {"removed": removed, "failed": failed, "checked": len(rows)}


@seguimiento_bp.route("/interno/seguimientos/limpiar", methods=["POST"])
def cleanup_expired_photos():
    expected = (os.environ.get("SEGUIMIENTOS_CLEANUP_TOKEN") or "").strip()
    supplied = request.headers.get("Authorization") or ""
    supplied = supplied[7:].strip() if supplied.lower().startswith("bearer ") else ""
    if not expected or not supplied or not hmac.compare_digest(expected, supplied):
        return jsonify({"ok": False, "error": "No autorizado"}), 401
    try:
        return jsonify({"ok": True, **_cleanup_expired_photos()})
    except Exception:
        log.exception("Falló la limpieza programada de fotos caducadas")
        return jsonify({"ok": False, "error": "No se pudo completar la limpieza"}), 500
