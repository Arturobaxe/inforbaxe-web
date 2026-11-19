# Seguridad de INFORBAXE

## Variables de entorno
- \`SECRET_KEY\`: aleatoria, persistente y de 48+ caracteres.
- \`ADMIN_USER\` y \`ADMIN_PASS\`: credenciales únicas; contraseña de 12+ caracteres.
- \`SUPABASE_URL\` y \`SUPABASE_KEY\`: la clave debe ser \`service_role\`; nunca la publiques.
- \`BREVO_API_KEY\` y \`MAIL_SENDER\`: envío del código 2FA.
- \`DATA_ENCRYPTION_KEY\` (opcional): cifra PIN y patrón de dispositivos. Conserva la clave en un gestor de contraseñas.

## Supabase
La revisión del 19-11-2026 verificó RLS en las 13 tablas públicas, políticas \`service_role\` exclusivas y ningún permiso de tabla para \`anon\` ni \`authenticated\`. La conversión de presupuestos ya utiliza \`FOR UPDATE\` e idempotencia. No apliques otra migración global de permisos: esa configuración ya está en producción.

Para habilitar 2FA persistente y sesiones revocables:
1. Despliega la aplicación.
2. Ejecuta \`migrations/auth_2fa_sesiones_persistentes.sql\` una sola vez en Supabase SQL Editor.
3. Ejecuta \`migrations/verificar_seguridad_supabase.sql\`; es de solo lectura.

Hasta aplicar la migración nueva, el 2FA conserva el respaldo en memoria y las sesiones nuevas no quedan registradas en servidor. Para revocación completa hace falta que la migración esté aplicada y Supabase responda.

## Cifrado de PIN y patrón
Es opcional y se activa al definir \`DATA_ENCRYPTION_KEY\` en Render:
\`\`\`bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
\`\`\`
Haz una copia de seguridad de \`ventas\`, define la clave en Render y ejecuta \`python scripts/cifrar_datos_sensibles.py\` en simulación. Solo después ejecútalo con \`--aplicar\`. Se permite rotación con claves Fernet separadas por comas: la primera cifra y todas descifran. No elimines claves que todavía puedan proteger registros. Si falta o no coincide la clave, la app bloquea la lectura del valor cifrado en vez de devolver vacío o sobrescribirlo.

## Controles
- CSRF, cookies HttpOnly/SameSite y Secure en Render.
- Sesiones de 2 h inactivas y 8 h absolutas; revocación persistente tras la migración, comprobada con caché de hasta 60 s.
- Límite de intentos por IP y límite global de 200 contraseñas fallidas por hora. El límite global puede bloquear temporalmente el login si se alcanza.
- 2FA HMAC de un solo uso, 10 minutos y 8 intentos acumulados por login, también al reenviar el código.
- SSRF: HTTPS/443, allowlist de catálogos y buscadores, DNS validado al conectar y conexión a IP resuelta; redirecciones revalidadas. La API con token no sigue redirecciones.
- XSS corregido en atributos dinámicos usando \`data-*\`.
- Recursos CDN con versiones fijadas e integridad SRI. La CSP aún permite scripts inline; quitarlo requiere una refactorización adicional.
- Los borradores no guardan PIN ni patrón y purgan campos sensibles de borradores antiguos.
- El límite global de petición está en 10 MiB para seguir admitiendo fotos de seguimiento de hasta 8 MiB.

## GitHub
Activa Dependabot alerts/security updates, secret scanning y push protection. Protege \`main\` exigiendo que pasen las pruebas y la auditoría de dependencias; si trabajas solo, evita reglas que te impidan fusionar tus propios cambios. No guardes secretos en el repositorio.
