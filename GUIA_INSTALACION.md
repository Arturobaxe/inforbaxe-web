# 🚀 GUÍA COMPLETA — INFORBAXE WEB
## Cómo subir y poner en marcha tu aplicación web
### (Para principiantes, paso a paso)

---

## ✅ RESUMEN DE LO QUE VAMOS A HACER
1. Crear tu base de datos en Supabase (GRATIS)
2. Subir el código a Railway (GRATIS, sin tarjeta de crédito)
3. Acceder desde cualquier sitio con tu URL propia

**Tiempo estimado: 30-45 minutos**

---

## PASO 1 — Crear cuenta en Supabase (base de datos)

**Supabase** es donde se guardarán todos tus datos (clientes, ventas, citas, mensualidades). Es gratis hasta 500MB.

1. Ve a **https://supabase.com**
2. Haz clic en **"Start your project"** → Regístrate con Google o email
3. Haz clic en **"New project"**
4. Rellena:
   - **Name:** `inforbaxe`
   - **Database Password:** pon una contraseña segura y **GUÁRDALA** (la necesitarás)
   - **Region:** `West EU (Ireland)` ← el más cercano a España
5. Haz clic en **"Create new project"** y espera 2 minutos

### Crear las tablas (copiar y pegar SQL)

6. En el menú izquierdo, haz clic en **"SQL Editor"**
7. Haz clic en **"New query"**
8. Abre el archivo `schema.sql` que está en tu carpeta del proyecto
9. **Copia TODO el contenido** y pégalo en el editor de Supabase
10. Haz clic en **"Run"** (botón verde)
    - Deberías ver: `Success. No rows returned`
    - ✅ Las tablas ya están creadas

### Conseguir tus claves de Supabase

11. En el menú izquierdo ve a **"Project Settings"** (icono de tuerca) → **"API"**
12. Copia y guarda estos dos valores:
    - **Project URL** → algo como `https://abcdefgh.supabase.co`
    - **service_role key** (la que pone "secret") → una cadena larga que empieza por `eyJ...`
    - ⚠️ **NO uses la "anon key"**, usa la "service_role key"

---

## PASO 2 — Subir el código a GitHub

Necesitas GitHub para que Railway pueda descargar tu código.

1. Ve a **https://github.com** → Crea una cuenta si no tienes
2. Haz clic en **"+"** (arriba a la derecha) → **"New repository"**
3. Nombre: `inforbaxe-web`
4. Pon el repositorio en **Private** (privado)
5. Haz clic en **"Create repository"**

### Subir los archivos

Si tienes Git instalado en tu ordenador:

```bash
# Abre una terminal en la carpeta del proyecto y ejecuta:
cd inforbaxe-web
git init
git add .
git commit -m "Primera versión de INFORBAXE web"
git branch -M main
git remote add origin https://github.com/TU_USUARIO/inforbaxe-web.git
git push -u origin main
```

**Si NO tienes Git / no sabes usarlo:**
1. En la página de tu repositorio vacío en GitHub, haz clic en **"uploading an existing file"**
2. Arrastra TODOS los archivos de la carpeta `inforbaxe-web` al navegador
3. Haz clic en **"Commit changes"**

---

## PASO 3 — Desplegar en Railway (hosting gratis)

**Railway** ejecuta tu aplicación web. Tiene plan gratuito con 500 horas/mes (suficiente para uso personal).

1. Ve a **https://railway.app**
2. Haz clic en **"Start a New Project"** → Regístrate con GitHub
3. Haz clic en **"Deploy from GitHub repo"**
4. Selecciona tu repositorio `inforbaxe-web`
5. Railway detectará automáticamente que es una app Python/Flask

### Configurar las variables de entorno

6. En Railway, haz clic en tu proyecto → **"Variables"**
7. Añade estas variables (una a una, con "Add Variable"):

| Variable | Valor |
|----------|-------|
| `SUPABASE_URL` | La URL que copiaste en el Paso 1 (`https://xxxx.supabase.co`) |
| `SUPABASE_KEY` | La service_role key que copiaste en el Paso 1 |
| `SECRET_KEY` | Escribe cualquier texto largo aleatorio, ej: `mi-clave-super-secreta-2025-inforbaxe` |
| `ADMIN_USER` | El usuario con el que quieres entrar, ej: `arturo` |
| `ADMIN_PASS` | La contraseña con la que quieres entrar, ej: `micontrasena123` |

8. Railway reiniciará la app automáticamente

### Obtener tu URL

9. Ve a la pestaña **"Settings"** → **"Networking"** → **"Generate Domain"**
10. Te dará una URL como: `https://inforbaxe-web-production.up.railway.app`
11. **¡Esa es tu aplicación web!** Ábrela en el navegador

---

## PASO 4 — Crear el archivo Procfile (necesario para Railway)

Antes de subir a GitHub (Paso 2), asegúrate de que el archivo `Procfile` existe en tu carpeta:

**Contenido del Procfile:**
```
web: gunicorn app:app --bind 0.0.0.0:$PORT
```

Y añade `gunicorn` al `requirements.txt`:
```
flask>=3.0.0
flask-login>=0.6.3
supabase>=2.4.0
python-dotenv>=1.0.0
werkzeug>=3.0.0
reportlab>=4.1.0
Pillow>=10.3.0
gunicorn>=21.2.0
```

---

## PASO 5 — Acceder desde el móvil (sin instalar nada)

Tu app ya es accesible desde cualquier dispositivo:

- **Ordenador:** Abre el navegador y ve a tu URL de Railway
- **Móvil:** Abre el navegador del móvil y ve a la misma URL
- **Tablet:** Igual

**Truco para acceder rápido desde el móvil:**
1. Abre la URL en Safari (iPhone) o Chrome (Android)
2. Toca el botón de compartir → **"Añadir a pantalla de inicio"**
3. Tendrás un icono como si fuera una app

---

## ALTERNATIVAS GRATUITAS DE HOSTING

Si Railway no te funciona, prueba estas alternativas:

### Render.com (muy fácil)
1. Ve a **https://render.com** → Regístrate con GitHub
2. **"New"** → **"Web Service"** → Conecta tu repositorio
3. Configura: Runtime `Python`, Build Command `pip install -r requirements.txt`, Start Command `gunicorn app:app`
4. Añade las mismas variables de entorno
5. Haz clic en **"Create Web Service"**

### PythonAnywhere (opción gratuita permanente)
1. Ve a **https://www.pythonanywhere.com** → Regístrate gratis
2. Ve a **"Web"** → **"Add a new web app"** → Flask → Python 3.10
3. Sube los archivos via la consola o el gestor de archivos
4. Configura las variables de entorno en el archivo `.env`

---

## MANTENIMIENTO — Cómo actualizar la app

Cuando hagas cambios en el código:

```bash
git add .
git commit -m "Descripción del cambio"
git push
```

Railway desplegará los cambios automáticamente en 1-2 minutos.

---

## 🆘 SOLUCIÓN DE PROBLEMAS COMUNES

### "Application Error" al abrir la URL
- Ve a Railway → Logs → Mira qué error aparece
- Lo más común: falta alguna variable de entorno

### "No se puede conectar a Supabase"
- Comprueba que `SUPABASE_URL` y `SUPABASE_KEY` son correctas
- Asegúrate de usar la **service_role key**, no la anon key

### Las tablas están vacías
- Asegúrate de haber ejecutado el `schema.sql` en Supabase

### Contraseña incorrecta al entrar
- Comprueba las variables `ADMIN_USER` y `ADMIN_PASS` en Railway

---

## 📦 ESTRUCTURA DE ARCHIVOS DEL PROYECTO

```
inforbaxe-web/
├── app.py                  ← Aplicación principal Flask
├── database.py             ← Conexión y operaciones con Supabase
├── requirements.txt        ← Librerías necesarias
├── Procfile                ← Instrucciones para Railway
├── .env.example            ← Plantilla de variables de entorno
├── schema.sql              ← Script SQL para crear las tablas
└── templates/              ← Páginas HTML
    ├── base.html           ← Plantilla base (sidebar, navegación)
    ├── login.html          ← Página de inicio de sesión
    ├── dashboard.html      ← Panel principal
    ├── clientes.html       ← Lista de clientes
    ├── cliente_form.html   ← Formulario añadir/editar cliente
    ├── cliente_historial.html ← Historial completo del cliente
    ├── ventas.html         ← Lista de ventas
    ├── venta_form.html     ← Formulario nueva/editar venta
    ├── citas.html          ← Lista de citas
    ├── cita_form.html      ← Formulario nueva/editar cita
    ├── mensualidades.html  ← Cuadrícula de mensualidades
    ├── mensualidad_form.html ← Formulario nueva mensualidad
    ├── productos.html      ← Catálogo de productos
    └── buscar.html         ← Búsqueda global
```

---

## ✨ FUNCIONALIDADES INCLUIDAS

- 🔐 **Login seguro** con usuario y contraseña
- 📊 **Dashboard** con stats en tiempo real
- 👥 **Clientes** — añadir, editar, desactivar, buscar duplicados
- 📋 **Historial de cliente** — todas sus ventas, citas y mensualidades
- 🛒 **Ventas** — filtros por mes/cliente/método, totales, beneficio mensual
- 📅 **Mensualidades** — cuadrícula año × mes, marcar pagado con un clic, vencidas en rojo
- 🗓️ **Citas** — con estados (pendiente/completada/cancelada), notificaciones 48h
- 📦 **Productos** — catálogo editable
- 🔍 **Búsqueda global** — en tiempo real desde el sidebar
- 📱 **Accesible desde móvil** sin instalar nada
```
