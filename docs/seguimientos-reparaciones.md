# Seguimiento privado de reparaciones

## Instalación necesaria antes de usarlo

1. En Supabase, abre **SQL Editor** y ejecuta el archivo `migrations/seguimientos_reparaciones.sql`.
   - Crea la tabla `seguimientos_reparacion`.
   - Crea el bucket privado `inforbaxe-seguimientos`.
   - No hace público el bucket ni las fotografías.
2. En Render, añade la variable de entorno `SEGUIMIENTOS_CLEANUP_TOKEN` con un valor aleatorio largo (por ejemplo, 40 o más caracteres). No la pongas en el código ni en GitHub como texto visible.
3. En GitHub, en **Settings → Secrets and variables → Actions**:
   - Crea el **secret** `SEGUIMIENTOS_CLEANUP_TOKEN` con exactamente el mismo valor que Render.
   - Crea la **variable** `INFORBAXE_RENDER_URL` con la URL HTTPS pública de la aplicación Render, sin barra final.
4. Comprueba que GitHub Actions está habilitado para el repositorio. El workflow `.github/workflows/limpiar-seguimientos.yml` ejecuta la limpieza cada 15 minutos y también permite ejecución manual.

## Uso

1. Abre el historial de un cliente y pulsa **Seguimientos**.
2. Crea un seguimiento con dispositivo y trabajo.
3. El seguimiento no genera ni comparte un enlace automáticamente.
4. Pulsa **Generar enlace privado** solo si decides enviárselo a ese cliente. Al renovarlo, el enlace anterior queda invalidado.
5. Cambia el estado a **Pieza en camino** o **Reparando** cuando corresponda.
6. Al terminar, sube la foto del interior y pulsa **Finalizar reparación**. En ese instante se fija la caducidad a cinco días exactos.
7. El cliente puede ver el progreso desde su enlace; la página consulta el estado cada 20 segundos.

## Privacidad y caducidad

- El token público es aleatorio y solo se almacena su hash en la base de datos.
- La página pública no muestra nombre, teléfono, correo, importes, notas internas ni identificadores de cliente.
- El bucket de imágenes es privado. Las fotos se sirven desde Flask solo si el token es válido, el seguimiento está activo y no ha caducado.
- Al llegar la hora exacta de caducidad, la página y la ruta de la foto dejan de servir contenido. La foto se elimina al primer acceso caducado o en la siguiente ejecución del workflow (cada 15 minutos).
- Si GitHub Actions está deshabilitado o faltan sus dos valores de configuración, el acceso público seguirá caducando, pero la eliminación física de fotos dependerá de que alguien abra el enlace caducado. Por eso hay que configurar y verificar el workflow.
- Puedes desactivar el enlace manualmente antes de los cinco días; esto también elimina la foto.
- Las fotos aceptadas son JPG, PNG o WebP de hasta 8 MB. El servidor las reduce a JPEG y elimina metadatos EXIF/GPS antes de almacenarlas.

## Notas

No se añaden servicios de pago ni claves de terceros. Se reutilizan Flask, Supabase Storage y Pillow, que ya forman parte del proyecto.
