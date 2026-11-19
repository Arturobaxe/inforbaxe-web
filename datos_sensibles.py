"""Cifrado opcional en reposo para PIN y patrón de dispositivos."""
import logging
import os

PREFIX = "enc:v1:"
CAMPOS_SENSIBLES_VENTA = ("equipo_contrasena", "equipo_patron")
log = logging.getLogger(__name__)


class SensitiveDataError(RuntimeError):
    """No se puede recuperar un valor cifrado de forma segura."""


def _cipher():
    raw = (os.environ.get("DATA_ENCRYPTION_KEY") or "").strip()
    if not raw:
        return None
    from cryptography.fernet import Fernet, MultiFernet
    keys = [Fernet(part.strip().encode("utf-8")) for part in raw.split(",") if part.strip()]
    if not keys:
        raise SensitiveDataError("DATA_ENCRYPTION_KEY no contiene una clave válida.")
    return MultiFernet(keys) if len(keys) > 1 else keys[0]


def activo():
    return bool((os.environ.get("DATA_ENCRYPTION_KEY") or "").strip())


def cifrar(valor):
    if not valor or not isinstance(valor, str) or valor.startswith(PREFIX):
        return valor
    cipher = _cipher()
    if cipher is None:
        return valor
    return PREFIX + cipher.encrypt(valor.encode("utf-8")).decode("ascii")


def descifrar(valor):
    if not isinstance(valor, str) or not valor.startswith(PREFIX):
        return valor
    cipher = _cipher()
    if cipher is None:
        raise SensitiveDataError("Hay datos cifrados pero falta DATA_ENCRYPTION_KEY.")
    try:
        return cipher.decrypt(valor[len(PREFIX):].encode("ascii")).decode("utf-8")
    except Exception as exc:
        log.error("No se pudo descifrar un dato sensible; comprueba la clave.")
        raise SensitiveDataError("No se puede descifrar un dato sensible.") from exc
