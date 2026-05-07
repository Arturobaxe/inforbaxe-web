"""
auth.py - 2FA por email + seguridad para INFORBAXE
"""
import os
import random
import string
import time
import json
import urllib.request

_codigos = {}

def generar_codigo():
    return ''.join(random.choices(string.digits, k=6))

def enviar_codigo_2fa(email_destino, codigo):
    api_key = os.environ.get("BREVO_API_KEY", "")
    if not api_key:
        print("Sin BREVO_API_KEY")
        return False
    data = json.dumps({
        "sender": {"name": "INFORBAXE", "email": "inforbaxe@gmail.com"},
        "to": [{"email": email_destino}],
        "subject": f"Tu código INFORBAXE: {codigo}",
        "htmlContent": f"<div style='font-family:sans-serif;padding:32px;background:#1B2340;border-radius:16px;text-align:center;'><div style='font-size:28px;font-weight:800;color:#E8820C;'>INFORBAXE</div><div style='background:#232D50;border-radius:12px;padding:24px;margin-top:16px;'><div style='font-size:13px;color:#A8B0D8;'>Tu código de acceso es:</div><div style='font-size:42px;font-weight:800;color:#E8820C;letter-spacing:8px;font-family:monospace;margin-top:10px;'>{codigo}</div><div style='font-size:12px;color:#6B7499;margin-top:12px;'>Válido durante 10 minutos</div></div></div>"
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.brevo.com/v3/smtp/email",
        data=data,
        headers={"api-key": api_key, "Content-Type": "application/json"},
        method="POST"
    )
    try:
        urllib.request.urlopen(req, timeout=10)
        print("Email enviado OK")
        return True
    except Exception as e:
        print(f"Brevo error: {e}")
        return False

def guardar_codigo(session_id, codigo):
    _codigos[session_id] = {
        "code":     codigo,
        "expires":  time.time() + 600,
        "attempts": 0,
    }

def verificar_codigo(session_id, codigo_usuario):
    entry = _codigos.get(session_id)
    if not entry:
        return False, "Código no encontrado o expirado"
    if time.time() > entry["expires"]:
        del _codigos[session_id]
        return False, "Código expirado"
    entry["attempts"] += 1
    if entry["attempts"] > 5:
        del _codigos[session_id]
        return False, "Demasiados intentos"
    if entry["code"] != codigo_usuario.strip():
        return False, "Código incorrecto"
    del _codigos[session_id]
    return True, "ok"

def limpiar_expirados():
    now = time.time()
    expired = [k for k, v in _codigos.items() if now > v["expires"]]
    for k in expired: del _codigos[k]