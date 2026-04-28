# ── AÑADIR ESTAS FUNCIONES A database.py ────────────────────────────────────
# 1. En la sección de MENSUALIDADES, añade update_mensualidad:

def update_mensualidad(id_mensualidad, concepto, importe, mes, pagado):
    db = get_db()
    update_data = {
        "concepto": concepto.strip(),
        "importe":  round(float(importe), 2),
        "mes":      mes,
        "pagado":   pagado,
    }
    if pagado == "Sí":
        from datetime import date
        update_data["fecha_pago"] = date.today().isoformat()
    else:
        update_data["fecha_pago"] = None
    db.table("mensualidades").update(update_data).eq("id", id_mensualidad).execute()


# ── SUPABASE: HABILITAR DATA API ─────────────────────────────────────────────
# Si ves el error "No access to Data API" en Supabase, sigue estos pasos:
#
# 1. Ve a https://supabase.com/dashboard → tu proyecto → Settings → API
# 2. En "Data API" asegúrate de que está ENABLED (toggle activado)
# 3. En "Exposed schemas" verifica que "public" aparece en la lista
# 4. Si usas RLS (Row Level Security):
#    - Ve a Table Editor → selecciona la tabla → Authentication → RLS
#    - Añade una policy: "Enable all for authenticated users" o desactiva RLS
#      para desarrollo con: ALTER TABLE mensualidades DISABLE ROW LEVEL SECURITY;
# 5. Verifica que tu SUPABASE_KEY en .env es la "service_role" key (no anon):
#    Settings → API → "service_role" key (tiene acceso total, ignora RLS)
#
# KEY correcta para backend Flask = service_role (empieza por eyJhbGciOiJIUzI1...)
# KEY para frontend público       = anon key
#
# En tu .env debe quedar:
#   SUPABASE_URL=https://xxxx.supabase.co
#   SUPABASE_KEY=eyJ...service_role_key...
