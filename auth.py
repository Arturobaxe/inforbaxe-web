"""
auth.py - 2FA por email + seguridad para INFORBAXE
"""
import os
import random
import string
import smtplib
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

GMAIL_USER = os.environ.get("GMAIL_USER", "inforbaxe@gmail.com")
GMAIL_PASS = os.environ.get("GMAIL_APP_PASS", "")  # Contraseña de aplicación Gmail

# Almacén en memoria de códigos 2FA: {session_key: {code, expires, attempts}}
_codigos = {}

def generar_codigo():
    return ''.join(random.choices(string.digits, k=6))

def enviar_codigo_2fa(email_destino, codigo):
    import urllib.request, json
    api_key = os.environ.get("RESEND_API_KEY", "")
    if not api_key:
        print("Sin RESEND_API_KEY")
        return False
    data = json.dumps({
        "from": "INFORBAXE <onboarding@resend.dev>",
        "to": [email_destino],
        "subject": f"Tu código INFORBAXE: {codigo}",
        "text": f"Tu código de acceso es: {codigo}\n\nVálido 10 minutos.\n\nSi no has solicitado este código, ignóralo."
    }).encode()
    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=data,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST"
    )
    try:
        urllib.request.urlopen(req, timeout=10)
        return True
    except Exception as e:
        print(f"Resend error: {e}")
        return False

    html = f"""
    <div style="font-family:sans-serif;max-width:400px;margin:0 auto;padding:32px;background:#1B2340;border-radius:16px;">
      <div style="text-align:center;margin-bottom:24px;">
        <div style="font-size:28px;font-weight:800;color:#E8820C;">INFORBAXE</div>
        <div style="font-size:13px;color:#6B7499;margin-top:4px;">Sistema de gestión</div>
      </div>
      <div style="background:#232D50;border-radius:12px;padding:24px;text-align:center;">
        <div style="font-size:13px;color:#A8B0D8;margin-bottom:12px;">Tu código de acceso es:</div>
        <div style="font-size:42px;font-weight:800;color:#E8820C;letter-spacing:8px;font-family:monospace;">{codigo}</div>
        <div style="font-size:12px;color:#6B7499;margin-top:12px;">Válido durante 10 minutos</div>
      </div>
      <div style="text-align:center;margin-top:20px;font-size:12px;color:#404870;">
        Si no has solicitado este código, ignora este mensaje.
      </div>
    </div>
    """
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_USER, GMAIL_PASS)
            server.sendmail(GMAIL_USER, email_destino, msg.as_string())
        return True
    except Exception as e:
        print(f"Error enviando email 2FA: {e}")
        return False

def guardar_codigo(session_id, codigo):
    _codigos[session_id] = {
        "code":     codigo,
        "expires":  time.time() + 600,  # 10 minutos
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
    for k in expired:
        del _codigos[k]
