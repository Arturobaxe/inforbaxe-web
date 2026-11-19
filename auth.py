"""2FA por email y sesiones revocables para INFORBAXE."""
import hashlib, hmac, json, os, secrets, time, urllib.request

CODE_TTL_SECONDS = 600
MAX_CODE_ATTEMPTS = 8
_codigos = {}


def generar_codigo():
    return f"{secrets.randbelow(1_000_000):06d}"


def _digest(kind, value):
    from flask import current_app
    secret = current_app.secret_key
    secret = secret.encode("utf-8") if isinstance(secret, str) else secret
    return hmac.new(secret, f"{kind}:{value}".encode("utf-8"), hashlib.sha256).hexdigest()


def _rpc(name, params):
    import database as db
    return db.get_db().rpc(name, params).execute().data


def enviar_codigo_2fa(email_destino, codigo):
    api_key = os.environ.get("BREVO_API_KEY", "")
    if not api_key:
        return False
    data = json.dumps({
        "sender": {"name": "INFORBAXE", "email": os.environ.get("MAIL_SENDER") or "inforbaxe@gmail.com"},
        "to": [{"email": email_destino}],
        "subject": "Tu código de acceso a INFORBAXE",
        "htmlContent": (
            "<div style='font-family:sans-serif;padding:32px;background:#1B2340;border-radius:16px;text-align:center;'>"
            "<div style='font-size:28px;font-weight:800;color:#E8820C;'>INFORBAXE</div>"
            "<div style='background:#232D50;border-radius:12px;padding:24px;margin-top:16px;'>"
            "<div style='font-size:13px;color:#A8B0D8;'>Tu código de acceso es:</div>"
            f"<div style='font-size:42px;font-weight:800;color:#E8820C;letter-spacing:8px;font-family:monospace;margin-top:10px;'>{codigo}</div>"
            "<div style='font-size:12px;color:#6B7499;margin-top:12px;'>Válido durante 10 minutos. Si no has sido tú, ignora este mensaje.</div>"
            "</div></div>"
        )
    }).encode("utf-8")
    req = urllib.request.Request("https://api.brevo.com/v3/smtp/email", data=data,
        headers={"api-key": api_key, "Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return 200 <= response.status < 300
    except Exception as exc:
        print(f"Brevo error: {type(exc).__name__}")
        return False


def guardar_codigo(session_id, codigo):
    try:
        _rpc("inforbaxe_2fa_store", {
            "p_sid_hash": _digest("2fa-sid", session_id),
            "p_code_hash": _digest(f"2fa-code:{session_id}", codigo),
            "p_ttl_seconds": CODE_TTL_SECONDS,
        })
        _codigos.pop(session_id, None)
        return
    except Exception:
        pass
    now = time.time()
    if len(_codigos) >= 1000:
        for old_id, entry in list(_codigos.items()):
            if now > entry.get("expires", 0):
                _codigos.pop(old_id, None)
        if len(_codigos) >= 1000:
            oldest = min(_codigos, key=lambda key: _codigos[key].get("expires", 0))
            _codigos.pop(oldest, None)
    previous = _codigos.get(session_id)
    attempts = previous["attempts"] if previous and now <= previous["expires"] else 0
    _codigos[session_id] = {"code": codigo, "expires": now + CODE_TTL_SECONDS, "attempts": attempts}


def _verificar_memoria(session_id, codigo_usuario):
    entry = _codigos.get(session_id)
    if not entry:
        return False, "Código no encontrado o expirado"
    if time.time() > entry["expires"]:
        del _codigos[session_id]
        return False, "Código expirado"
    if entry["attempts"] >= MAX_CODE_ATTEMPTS:
        del _codigos[session_id]
        return False, "Demasiados intentos"
    if not hmac.compare_digest(entry["code"], codigo_usuario):
        entry["attempts"] += 1
        if entry["attempts"] >= MAX_CODE_ATTEMPTS:
            del _codigos[session_id]
            return False, "Demasiados intentos"
        return False, "Código incorrecto"
    del _codigos[session_id]
    return True, "ok"


_MESSAGES = {"invalid":"Código incorrecto","expired":"Código expirado",
             "locked":"Demasiados intentos","missing":"Código no encontrado o expirado"}


def verificar_codigo(session_id, codigo_usuario):
    codigo_usuario = (codigo_usuario or "").strip()
    if session_id in _codigos:
        return _verificar_memoria(session_id, codigo_usuario)
    try:
        status = _rpc("inforbaxe_2fa_verify", {
            "p_sid_hash": _digest("2fa-sid", session_id),
            "p_code_hash": _digest(f"2fa-code:{session_id}", codigo_usuario),
            "p_max_attempts": MAX_CODE_ATTEMPTS,
        })
    except Exception:
        return False, "Código no encontrado o expirado"
    return (True, "ok") if status == "ok" else (False, _MESSAGES.get(status, "Código no encontrado o expirado"))


def limpiar_expirados():
    now = time.time()
    for key in [key for key, value in _codigos.items() if now > value["expires"]]:
        del _codigos[key]


def registrar_sesion(session_id, ttl_seconds):
    try:
        _rpc("inforbaxe_session_register", {"p_sid_hash": _digest("session", session_id), "p_ttl_seconds": int(ttl_seconds)})
        return True
    except Exception:
        return False


def estado_sesion(session_id):
    try:
        status = _rpc("inforbaxe_session_check", {"p_sid_hash": _digest("session", session_id)})
        return status if status in ("ok", "revoked", "missing") else "error"
    except Exception:
        return "error"


def revocar_sesion(session_id):
    try:
        _rpc("inforbaxe_session_revoke", {"p_sid_hash": _digest("session", session_id)})
        return True
    except Exception:
        return False


def revocar_todas_las_sesiones():
    try:
        return int(_rpc("inforbaxe_session_revoke_all", {}) or 0)
    except Exception:
        return None
