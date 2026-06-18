"""
database.py - Supabase client and all DB operations for INFORBAXE web.
"""
import os
import json
from datetime import date, datetime
from typing import Optional
from supabase import create_client, Client

_sb: Optional[Client] = None


def get_db() -> Client:
    global _sb
    if _sb is None:
        url = os.environ.get("SUPABASE_URL", "")
        key = os.environ.get("SUPABASE_KEY", "")
        if not url or not key:
            raise RuntimeError("Falta SUPABASE_URL o SUPABASE_KEY en .env")
        _sb = create_client(url, key)
    return _sb


def _flt(v, default=0.0):
    try:
        return float(str(v).replace(",", "."))
    except Exception:
        return default


# ── CLIENTES ────────────────────────────────────────────────────────────────

def get_clientes(solo_activos=False):
    db = get_db()
    q = db.table("clientes").select("*").order("nombre")
    if solo_activos:
        q = q.eq("activo", True)
    return q.execute().data or []


def get_cliente(id_cliente):
    db = get_db()
    r = db.table("clientes").select("*").eq("id", id_cliente).single().execute()
    return r.data


def add_cliente(nombre, email, telefono, notas=""):
    db = get_db()
    r = db.table("clientes").insert({
        "nombre":   nombre.strip(),
        "email":    email.strip(),
        "telefono": telefono.strip(),
        "notas":    notas.strip(),
    }).execute()
    return r.data[0] if r.data else None


def update_cliente(id_cliente, nombre, email, telefono, notas=""):
    db = get_db()
    db.table("clientes").update({
        "nombre":   nombre.strip(),
        "email":    email.strip(),
        "telefono": telefono.strip(),
        "notas":    notas.strip(),
    }).eq("id", id_cliente).execute()


def delete_cliente(id_cliente):
    db = get_db()
    db.table("clientes").delete().eq("id", id_cliente).execute()


def cancelar_cliente(id_cliente, activo=False):
    db = get_db()
    db.table("clientes").update({"activo": activo}).eq("id", id_cliente).execute()


# ── PRODUCTOS ────────────────────────────────────────────────────────────────

def get_productos():
    db = get_db()
    return db.table("productos").select("*").order("nombre").execute().data or []


def add_producto(nombre):
    db = get_db()
    r = db.table("productos").insert({"nombre": nombre.strip()}).execute()
    return r.data[0] if r.data else None


def delete_producto(id_producto):
    db = get_db()
    db.table("productos").delete().eq("id", id_producto).execute()


def rename_producto(id_producto, nuevo_nombre):
    db = get_db()
    db.table("productos").update({"nombre": nuevo_nombre.strip()}).eq("id", id_producto).execute()


# ── VENTAS ───────────────────────────────────────────────────────────────────

def _calc_totales(productos):
    total_pvp = total_benef = total_coste = 0.0
    for p in productos:
        q     = int(p.get("cantidad", 1) or 1)
        pvp   = _flt(p.get("pvp", 0))
        benef = _flt(p.get("beneficio", 0))
        coste = _flt(p.get("coste", pvp - benef))
        total_pvp   += q * pvp
        total_benef += q * benef
        total_coste += q * coste
    return total_pvp, total_benef, total_coste


def get_ventas(id_cliente=None, mes=None, limit=500):
    db = get_db()
    q = (db.table("ventas")
         .select("*, clientes(nombre)")
         .order("fecha", desc=True)
         .limit(limit))
    if id_cliente:
        q = q.eq("id_cliente", id_cliente)
    if mes:
        start = f"{mes}-01"
        year, m = mes.split("-")
        import calendar
        last_day = calendar.monthrange(int(year), int(m))[1]
        end = f"{mes}-{last_day:02d}"
        q = q.gte("fecha", start).lte("fecha", end)
    data = q.execute().data or []
    for v in data:
        v["nombre_cliente"] = (v.get("clientes") or {}).get("nombre", "—")
        v.pop("clientes", None)
        if isinstance(v.get("productos"), str):
            try:
                v["productos"] = json.loads(v["productos"])
            except Exception:
                v["productos"] = []
    return data


def add_venta(id_cliente, fecha, productos, metodo, pagado, comentarios):
    db = get_db()
    total_pvp, total_benef, total_coste = _calc_totales(productos)
    r = db.table("ventas").insert({
        "id_cliente":  int(id_cliente),
        "fecha":       str(fecha),
        "productos":   productos,
        "suma_coste":  round(total_coste, 2),
        "total_benef": round(total_benef, 2),
        "total_pvp":   round(total_pvp, 2),
        "metodo_pago": metodo,
        "pagado":      pagado,
        "comentarios": comentarios,
    }).execute()
    return r.data[0] if r.data else None


def update_venta(id_venta, id_cliente, fecha, productos, metodo, pagado, comentarios):
    db = get_db()
    total_pvp, total_benef, total_coste = _calc_totales(productos)
    db.table("ventas").update({
        "id_cliente":  int(id_cliente),
        "fecha":       str(fecha),
        "productos":   productos,
        "suma_coste":  round(total_coste, 2),
        "total_benef": round(total_benef, 2),
        "total_pvp":   round(total_pvp, 2),
        "metodo_pago": metodo,
        "pagado":      pagado,
        "comentarios": comentarios,
    }).eq("id", id_venta).execute()


def delete_venta(id_venta):
    db = get_db()
    db.table("ventas").delete().eq("id", id_venta).execute()


# ── MENSUALIDADES ─────────────────────────────────────────────────────────────

def get_mensualidades(año=None, id_cliente=None):
    db = get_db()
    q = (db.table("mensualidades")
         .select("*, clientes(nombre, activo)")
         .order("mes").order("id_cliente"))
    if año:
        q = q.like("mes", f"{año}-%")
    if id_cliente:
        q = q.eq("id_cliente", id_cliente)
    data = q.execute().data or []
    for m in data:
        cli = m.pop("clientes", None) or {}
        m["nombre_cliente"] = cli.get("nombre", "—")
        m["cliente_activo"] = cli.get("activo", True)
    return data


def add_mensualidad(id_cliente, concepto, importe, mes, pagado="No"):
    db = get_db()
    r = db.table("mensualidades").upsert({
        "id_cliente": int(id_cliente),
        "concepto":   concepto.strip(),
        "importe":    round(_flt(importe), 2),
        "mes":        mes,
        "pagado":     pagado,
    }, on_conflict="id_cliente,concepto,mes").execute()
    return r.data[0] if r.data else None


def toggle_mensualidad_pago(id_mensualidad, pagado):
    db = get_db()
    update_data = {"pagado": pagado}
    if pagado == "Sí":
        update_data["fecha_pago"] = date.today().isoformat()
    else:
        update_data["fecha_pago"] = None
    db.table("mensualidades").update(update_data).eq("id", id_mensualidad).execute()


def update_mensualidad(id_mensualidad, concepto, importe, mes, pagado):
    db = get_db()
    db.table("mensualidades").update({
        "concepto": concepto.strip(),
        "importe":  round(_flt(importe), 2),
        "mes":      mes,
        "pagado":   pagado,
    }).eq("id", id_mensualidad).execute()


def delete_mensualidad(id_mensualidad):
    db = get_db()
    db.table("mensualidades").delete().eq("id", id_mensualidad).execute()


# ── CITAS ────────────────────────────────────────────────────────────────────

def get_citas(fecha_desde=None, fecha_hasta=None, id_cliente=None):
    db = get_db()
    q = (db.table("citas")
         .select("*, clientes(nombre)")
         .order("fecha").order("hora"))
    if fecha_desde:
        q = q.gte("fecha", str(fecha_desde))
    if fecha_hasta:
        q = q.lte("fecha", str(fecha_hasta))
    if id_cliente:
        q = q.eq("id_cliente", id_cliente)
    data = q.execute().data or []
    for c in data:
        c["nombre_cliente"] = (c.pop("clientes", None) or {}).get("nombre", "—")
    return data


def add_cita(id_cliente, fecha, hora, observaciones, estado="pendiente"):
    db = get_db()
    r = db.table("citas").insert({
        "id_cliente":   int(id_cliente),
        "fecha":        str(fecha),
        "hora":         str(hora),
        "observaciones": observaciones,
        "estado":       estado,
    }).execute()
    return r.data[0] if r.data else None


def update_cita(id_cita, id_cliente, fecha, hora, observaciones, estado):
    db = get_db()
    db.table("citas").update({
        "id_cliente":   int(id_cliente),
        "fecha":        str(fecha),
        "hora":         str(hora),
        "observaciones": observaciones,
        "estado":       estado,
    }).eq("id", id_cita).execute()


def delete_cita(id_cita):
    db = get_db()
    db.table("citas").delete().eq("id", id_cita).execute()


# ── PRESUPUESTOS ──────────────────────────────────────────────────────────────

def get_presupuestos(id_cliente=None):
    db = get_db()
    q = (db.table("presupuestos")
         .select("*, clientes(nombre)")
         .order("fecha", desc=True)
         .limit(500))
    if id_cliente:
        q = q.eq("id_cliente", id_cliente)
    data = q.execute().data or []
    for p in data:
        p["nombre_cliente"] = (p.get("clientes") or {}).get("nombre", "—")
        p.pop("clientes", None)
        if isinstance(p.get("productos"), str):
            try:
                p["productos"] = json.loads(p["productos"])
            except Exception:
                p["productos"] = []
    return data


def get_presupuesto(id_presupuesto):
    db = get_db()
    try:
        r = db.table("presupuestos").select("*, clientes(nombre)").eq("id", id_presupuesto).single().execute()
        p = r.data
        if p:
            p["nombre_cliente"] = (p.get("clientes") or {}).get("nombre", "—")
            p.pop("clientes", None)
            if isinstance(p.get("productos"), str):
                try:
                    p["productos"] = json.loads(p["productos"])
                except Exception:
                    p["productos"] = []
        return p
    except Exception:
        return None


def _calc_totales_presup(productos):
    total_pvp = total_benef = 0.0
    for p in productos:
        q     = int(p.get("cantidad", 1) or 1)
        pvp   = _flt(p.get("pvp", 0))
        benef = _flt(p.get("beneficio", 0))
        total_pvp   += q * pvp
        total_benef += q * benef
    return total_pvp, total_benef


def add_presupuesto(id_cliente, fecha, productos, estado, notas, validez_dias=30):
    db = get_db()
    total_pvp, total_benef = _calc_totales_presup(productos)
    r = db.table("presupuestos").insert({
        "id_cliente":  int(id_cliente),
        "fecha":       str(fecha),
        "productos":   productos,
        "total_pvp":   round(total_pvp, 2),
        "total_benef": round(total_benef, 2),
        "estado":      estado,
        "notas":       notas,
        "validez_dias": validez_dias,
    }).execute()
    return r.data[0] if r.data else None


def update_presupuesto(id_presupuesto, id_cliente, fecha, productos, estado, notas, validez_dias=30):
    db = get_db()
    total_pvp, total_benef = _calc_totales_presup(productos)
    db.table("presupuestos").update({
        "id_cliente":  int(id_cliente),
        "fecha":       str(fecha),
        "productos":   productos,
        "total_pvp":   round(total_pvp, 2),
        "total_benef": round(total_benef, 2),
        "estado":      estado,
        "notas":       notas,
        "validez_dias": validez_dias,
    }).eq("id", id_presupuesto).execute()


def delete_presupuesto(id_presupuesto):
    db = get_db()
    db.table("presupuestos").delete().eq("id", id_presupuesto).execute()


# ── PROPINAS ──────────────────────────────────────────────────────────────────

def get_propinas(mes=None):
    db = get_db()
    q = db.table("propinas").select("*").order("fecha", desc=True)
    if mes:
        import calendar
        year, m = mes.split("-")
        last_day = calendar.monthrange(int(year), int(m))[1]
        q = q.gte("fecha", f"{mes}-01").lte("fecha", f"{mes}-{last_day:02d}")
    return q.execute().data or []


def add_propina(fecha, importe, comentario):
    db = get_db()
    r = db.table("propinas").insert({
        "fecha":      str(fecha),
        "importe":    round(_flt(importe), 2),
        "comentario": comentario.strip(),
    }).execute()
    return r.data[0] if r.data else None


def delete_propina(id_propina):
    db = get_db()
    db.table("propinas").delete().eq("id", id_propina).execute()


def get_total_propinas_mes(mes):
    propinas = get_propinas(mes=mes)
    return round(sum(_flt(p.get("importe", 0)) for p in propinas), 2)


# ── BÚSQUEDA GLOBAL ───────────────────────────────────────────────────────────

def busqueda_global(texto):
    if not texto or len(texto) < 2:
        return {"clientes": [], "ventas": [], "citas": []}
    db = get_db()
    t = texto.strip()

    clientes = db.table("clientes").select("id, nombre, email, telefono").or_(
        f"nombre.ilike.%{t}%,email.ilike.%{t}%,telefono.ilike.%{t}%"
    ).limit(10).execute().data or []

    ventas = db.table("ventas").select("id, fecha, total_pvp, comentarios, clientes(nombre)").or_(
        f"comentarios.ilike.%{t}%"
    ).limit(10).execute().data or []
    for v in ventas:
        v["nombre_cliente"] = (v.pop("clientes", None) or {}).get("nombre", "—")

    citas = db.table("citas").select("id, fecha, hora, observaciones, clientes(nombre)").or_(
        f"observaciones.ilike.%{t}%"
    ).limit(10).execute().data or []
    for c in citas:
        c["nombre_cliente"] = (c.pop("clientes", None) or {}).get("nombre", "—")

    return {"clientes": clientes, "ventas": ventas, "citas": citas}


# ── HISTORIAL CLIENTE ─────────────────────────────────────────────────────────

def get_historial_cliente(id_cliente):
    ventas        = get_ventas(id_cliente=id_cliente, limit=200)
    citas         = get_citas(id_cliente=id_cliente)
    mensualidades = get_mensualidades(id_cliente=id_cliente)
    cliente       = get_cliente(id_cliente)
    return {
        "cliente":      cliente,
        "ventas":       ventas,
        "citas":        citas,
        "mensualidades": mensualidades,
        "total_gastado": sum(_flt(v.get("total_pvp", 0)) for v in ventas),
        "total_pendiente_mens": sum(
            _flt(m.get("importe", 0)) for m in mensualidades if m.get("pagado") == "No"
        ),
    }


# ── DASHBOARD ─────────────────────────────────────────────────────────────────

def get_dashboard_stats():
    db = get_db()
    today = date.today()
    mes_actual = today.strftime("%Y-%m")
    import calendar
    last_day  = calendar.monthrange(today.year, today.month)[1]
    mes_start = f"{mes_actual}-01"
    mes_end   = f"{mes_actual}-{last_day:02d}"

    # Clientes
    clientes_data    = db.table("clientes").select("id").eq("activo", True).execute()
    clientes_activos = len(clientes_data.data or [])

    # Citas Hoy
    citas_hoy_data = (db.table("citas")
        .select("id, hora, observaciones, id_cliente, clientes(nombre)")
        .eq("fecha", today.isoformat())
        .eq("estado", "pendiente")
        .order("hora")
        .execute())
    citas_hoy = citas_hoy_data.data or []
    for c in citas_hoy:
        c["nombre_cliente"] = (c.pop("clientes", None) or {}).get("nombre", "—")

    # Próximas Citas
    from datetime import timedelta
    manana        = (today + timedelta(days=2)).isoformat()
    proximas_data = (db.table("citas")
        .select("id, fecha, hora, id_cliente, clientes(nombre)")
        .gte("fecha", today.isoformat())
        .lte("fecha", manana)
        .eq("estado", "pendiente")
        .order("fecha").order("hora")
        .execute())
    proximas_citas = proximas_data.data or []
    for c in proximas_citas:
        c["nombre_cliente"] = (c.pop("clientes", None) or {}).get("nombre", "—")

    # Mensualidades
    mens_pend        = db.table("mensualidades").select("id").like("mes", f"{mes_actual}%").eq("pagado", "No").execute()
    mens_pendientes  = len(mens_pend.data or [])
    
    mens_pagadas     = db.table("mensualidades").select("importe").eq("mes", mes_actual).eq("pagado", "Sí").execute()
    total_mens_pagadas = sum(_flt(m.get("importe", 0)) for m in (mens_pagadas.data or []))

    # Ventas
    ventas_mes  = (db.table("ventas")
                   .select("total_pvp, total_benef, pagado")
                   .gte("fecha", mes_start).lte("fecha", mes_end)
                   .execute())
    ventas_data      = ventas_mes.data or []
    total_ventas_mes = sum(_flt(v.get("total_pvp",  0)) for v in ventas_data)
    total_benef_mes  = sum(_flt(v.get("total_benef", 0)) for v in ventas_data)
    num_ventas_mes   = len(ventas_data)

    # Propinas
    total_propinas = get_total_propinas_mes(mes_actual)

    # SUMATORIA FINAL (Ventas + Mensualidades + Propinas)
    total_facturado_real = total_ventas_mes + total_mens_pagadas + total_propinas
    total_beneficio_real = total_benef_mes + total_mens_pagadas + total_propinas

    return {
        "clientes_activos":         clientes_activos,
        "citas_hoy":                citas_hoy,
        "proximas_citas":           proximas_citas,
        "mensualidades_pendientes": mens_pendientes,
        "ventas_mes": {
            "total":     round(total_facturado_real, 2),
            "beneficio": round(total_beneficio_real, 2),
            "num":       num_ventas_mes,
            "mes":       mes_actual,
        },
        "propinas_mes": {
            "total": total_propinas,
            "mes":   mes_actual,
        },
    }


def get_ventas_chart_data():
    try:
        db = get_db()
        from datetime import date
        import calendar
        
        today = date.today()
        labels = []
        values = []
        meses_nombres = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
        
        for i in range(5, -1, -1):
            m = today.month - i
            y = today.year
            while m <= 0:
                m += 12
                y -= 1
                
            mes_str = f"{y}-{m:02d}"
            last_day = calendar.monthrange(y, m)[1]
            start = f"{mes_str}-01"
            end = f"{mes_str}-{last_day:02d}"
            
            # 1. Ventas
            ventas_mes = db.table("ventas").select("total_pvp").gte("fecha", start).lte("fecha", end).execute()
            total_v = sum(_flt(v.get("total_pvp", 0)) for v in (ventas_mes.data or []))
            
            # 2. Propinas
            propinas_mes = db.table("propinas").select("importe").gte("fecha", start).lte("fecha", end).execute()
            total_p = sum(_flt(p.get("importe", 0)) for p in (propinas_mes.data or []))
            
            # 3. Mensualidades
            mens_mes = db.table("mensualidades").select("importe").eq("mes", mes_str).eq("pagado", "Sí").execute()
            total_m = sum(_flt(m.get("importe", 0)) for m in (mens_mes.data or []))
            
            # Total sumado
            total_mes = total_v + total_p + total_m
            
            labels.append(f"{meses_nombres[m-1]} {y}")
            values.append(round(total_mes, 2))
            
        return {"labels": labels, "values": values}
    except Exception as e:
        return {"labels": [], "values": [], "error": str(e)}