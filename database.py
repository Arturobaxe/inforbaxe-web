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


def get_cliente_por_codigo(codigo_cliente):
    """Busca un cliente por su código visible IBX, sin exponer el ID interno."""
    codigo = (codigo_cliente or "").strip().upper()
    if not codigo:
        return None
    db = get_db()
    r = (db.table("clientes").select("*")
         .eq("codigo_cliente", codigo).limit(1).execute())
    return r.data[0] if r.data else None

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
    """Activa/desactiva sin borrar; devuelve el estado persistido o None."""
    db = get_db()
    db.table("clientes").update({"activo": bool(activo)}).eq("id", int(id_cliente)).execute()
    r = (db.table("clientes")
         .select("id,activo,codigo_cliente")
         .eq("id", int(id_cliente)).limit(1).execute())
    return r.data[0] if r.data else None

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

# ── DESPIECE Y REPUESTOS ────────────────────────────────────────────────────
# Catálogo independiente: no modifica ventas, clientes ni reparaciones.
DESPIECE_PAGE_SIZE = 100


def get_despiece_familias():
    db = get_db()
    return (db.table("despiece_familias")
            .select("id,nombre")
            .order("nombre")
            .execute().data or [])


def get_despiece_repuestos(familia_id=None, busqueda="", page=1, familias=None):
    db = get_db()
    page = max(int(page or 1), 1)
    inicio = (page - 1) * DESPIECE_PAGE_SIZE
    q = (db.table("despiece_repuestos")
         .select("id,familia_id,marca,modelo,pieza,referencia,descripcion,created_at")
         .order("marca")
         .order("modelo")
         .range(inicio, inicio + DESPIECE_PAGE_SIZE))  # 101 filas: la última solo indica si hay página siguiente.

    if familia_id:
        q = q.eq("familia_id", int(familia_id))

    # Sanitizar caracteres reservados de la sintaxis OR de PostgREST.
    termino = (busqueda or "").strip()[:80]
    for char in ',()%_*\\"':
        termino = termino.replace(char, " ")
    termino = " ".join(termino.split())

    if termino:
        lista_familias = familias if familias is not None else get_despiece_familias()
        familias_coincidentes = [
            str(f["id"]) for f in lista_familias
            if termino.casefold() in (f.get("nombre") or "").casefold()
        ]
        filtros = [
            f"marca.ilike.*{termino}*",
            f"modelo.ilike.*{termino}*",
            f"pieza.ilike.*{termino}*",
            f"referencia.ilike.*{termino}*",
            f"descripcion.ilike.*{termino}*",
        ]
        if familias_coincidentes:
            filtros.append(f"familia_id.in.({','.join(familias_coincidentes)})")
        q = q.or_(",".join(filtros))

    return q.execute().data or []


def get_despiece_repuesto(id_repuesto):
    db = get_db()
    return (db.table("despiece_repuestos")
            .select("id,familia_id,marca,modelo,pieza,referencia,descripcion")
            .eq("id", int(id_repuesto))
            .single().execute().data)


def add_despiece_familia(nombre):
    db = get_db()
    r = db.table("despiece_familias").insert({"nombre": nombre.strip()}).execute()
    return r.data[0] if r.data else None


def update_despiece_familia(id_familia, nombre):
    db = get_db()
    db.table("despiece_familias").update({"nombre": nombre.strip()}).eq("id", int(id_familia)).execute()


def delete_despiece_familia(id_familia):
    db = get_db()
    existente = (db.table("despiece_repuestos").select("id")
                 .eq("familia_id", int(id_familia)).limit(1).execute().data or [])
    if existente:
        raise ValueError("No puedes eliminar una familia que todavía contiene piezas.")
    db.table("despiece_familias").delete().eq("id", int(id_familia)).execute()


def add_despiece_repuesto(familia_id, marca, modelo, pieza, referencia="", descripcion=""):
    db = get_db()
    payload = {
        "familia_id": int(familia_id),
        "marca": (marca or "").strip(),
        "modelo": modelo.strip(),
        "pieza": pieza.strip(),
        "referencia": (referencia or "").strip(),
        "descripcion": (descripcion or "").strip(),
    }
    r = db.table("despiece_repuestos").insert(payload).execute()
    return r.data[0] if r.data else None


def update_despiece_repuesto(id_repuesto, familia_id, marca, modelo, pieza, referencia="", descripcion=""):
    db = get_db()
    payload = {
        "familia_id": int(familia_id),
        "marca": (marca or "").strip(),
        "modelo": modelo.strip(),
        "pieza": pieza.strip(),
        "referencia": (referencia or "").strip(),
        "descripcion": (descripcion or "").strip(),
    }
    db.table("despiece_repuestos").update(payload).eq("id", int(id_repuesto)).execute()


def delete_despiece_repuesto(id_repuesto):
    db = get_db()
    db.table("despiece_repuestos").delete().eq("id", int(id_repuesto)).execute()

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

def _normalizar_ventas(data):
    """Normaliza las relaciones y el JSON de productos devueltos por Supabase."""
    for venta in data or []:
        venta["nombre_cliente"] = (venta.get("clientes") or {}).get("nombre", "—")
        venta.pop("clientes", None)
        if isinstance(venta.get("productos"), str):
            try:
                venta["productos"] = json.loads(venta["productos"])
            except Exception:
                venta["productos"] = []
    return data or []


def get_ventas(id_cliente=None, mes=None, limit=500):
    """Consulta compatible con llamadas antiguas; usa paginación explícita en listados."""
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
    return _normalizar_ventas(q.execute().data or [])


def get_venta(id_venta):
    """Obtiene una venta concreta sin depender de un límite de listado."""
    db = get_db()
    try:
        result = (db.table("ventas").select("*, clientes(nombre)")
                  .eq("id", int(id_venta)).single().execute())
        data = result.data
        return _normalizar_ventas([data])[0] if data else None
    except Exception:
        return None


def get_ventas_pagina(page=1, page_size=25, desde=None, hasta=None,
                       id_cliente=None, metodo=None, pagado=None):
    """Devuelve una página de ventas; todos los filtros se aplican en PostgreSQL."""
    db = get_db()
    page = max(int(page or 1), 1)
    page_size = min(max(int(page_size or 25), 1), 100)
    q = (db.table("ventas")
         .select("*, clientes(nombre)", count="exact")
         .order("fecha", desc=True).order("id", desc=True))
    if desde:
        q = q.gte("fecha", str(desde))
    if hasta:
        q = q.lte("fecha", str(hasta))
    if id_cliente:
        q = q.eq("id_cliente", int(id_cliente))
    if metodo:
        q = q.eq("metodo_pago", str(metodo))
    if pagado:
        q = q.eq("pagado", str(pagado))
    response = q.range((page - 1) * page_size, page * page_size - 1).execute()
    return {
        "items": _normalizar_ventas(response.data or []),
        "total": int(response.count or 0),
        "page": page,
        "page_size": page_size,
    }


def get_ventas_resumen(desde=None, hasta=None, id_cliente=None, metodo=None, pagado=None):
    """Totales globales del conjunto filtrado, no solo de la página visible."""
    params = {
        "p_desde": str(desde) if desde else None,
        "p_hasta": str(hasta) if hasta else None,
        "p_id_cliente": int(id_cliente) if id_cliente else None,
        "p_metodo": str(metodo) if metodo else None,
        "p_pagado": str(pagado) if pagado else None,
    }
    result = get_db().rpc("get_ventas_resumen", params).execute()
    data = result.data
    if isinstance(data, list) and data:
        data = data[0]
    return data or {"cantidad": 0, "total_pvp": 0, "total_benef": 0,
                    "total_pendiente": 0, "num_pendiente": 0}


def get_resumen_ventas_cliente(id_cliente):
    result = get_db().rpc("get_resumen_ventas_cliente", {"p_id_cliente": int(id_cliente)}).execute()
    data = result.data
    if isinstance(data, list) and data:
        data = data[0]
    return data or {"cantidad": 0, "total_gastado": 0}

def add_venta(id_cliente, fecha, productos, metodo, pagado, comentarios, equipo_modelo="", equipo_imei="", equipo_contrasena="", equipo_patron="", creation_token=None):
    db = get_db()
    total_pvp, total_benef, total_coste = _calc_totales(productos)
    payload = {
        "id_cliente":  int(id_cliente),
        "fecha":       str(fecha),
        "productos":   productos,
        "suma_coste":  round(total_coste, 2),
        "total_benef": round(total_benef, 2),
        "total_pvp":   round(total_pvp, 2),
        "metodo_pago": metodo,
        "pagado":      pagado,
        "comentarios": comentarios,
        "equipo_modelo": equipo_modelo.strip(),
        "equipo_imei": equipo_imei.strip(),
        "equipo_contrasena": equipo_contrasena.strip(),
        "equipo_patron": equipo_patron.strip(),
    }
    if creation_token:
        payload["creation_token"] = str(creation_token)
    try:
        r = db.table("ventas").insert(payload).execute()
        return r.data[0] if r.data else None
    except Exception:
        # Si el servidor guardó la venta pero se cortó la respuesta, el reintento
        # con el mismo token recupera la venta existente en lugar de duplicarla.
        if creation_token:
            existing = (db.table("ventas").select("*")
                        .eq("creation_token", str(creation_token)).limit(1).execute().data or [])
            if existing:
                return existing[0]
        raise

def update_venta(id_venta, id_cliente, fecha, productos, metodo, pagado, comentarios, equipo_modelo="", equipo_imei="", equipo_contrasena="", equipo_patron=""):
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
        "equipo_modelo": equipo_modelo.strip(),
        "equipo_imei": equipo_imei.strip(),
        "equipo_contrasena": equipo_contrasena.strip(),
        "equipo_patron": equipo_patron.strip()
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
    update_data = {
        "concepto": concepto.strip(),
        "importe":  round(_flt(importe), 2),
        "mes":      mes,
        "pagado":   pagado,
        "fecha_pago": date.today().isoformat() if pagado == "Sí" else None,
    }
    db.table("mensualidades").update(update_data).eq("id", id_mensualidad).execute()

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
        # Mantiene visibles las citas atrasadas mientras sigan pendientes.
        q = q.or_(f"fecha.gte.{str(fecha_desde)},estado.eq.pendiente")
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



def convertir_presupuesto_a_venta(id_presupuesto):
    """Conversión atómica e idempotente implementada por una función SQL."""
    response = get_db().rpc(
        "convertir_presupuesto_a_venta",
        {"p_id_presupuesto": int(id_presupuesto)},
    ).execute()
    data = response.data
    if isinstance(data, list) and data:
        data = data[0]
    if isinstance(data, dict):
        data = data.get("convertir_presupuesto_a_venta") or data.get("id")
    return int(data) if data is not None else None

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
    if not texto or len(texto.strip()) < 2:
        return {"clientes": [], "ventas": [], "citas": []}
    # La función SQL busca también en todo el JSONB de productos, sin limitarse
    # a las últimas 200 ventas ni descargar filas irrelevantes al servidor Flask.
    result = get_db().rpc("buscar_global_inforbaxe", {"p_texto": texto.strip()[:100]}).execute()
    data = result.data
    if isinstance(data, list) and data:
        data = data[0]
    return data or {"clientes": [], "ventas": [], "citas": []}

# ── HISTORIAL CLIENTE ─────────────────────────────────────────────────────────

def get_historial_cliente(id_cliente, page=1, page_size=20):
    resumen_ventas = get_resumen_ventas_cliente(id_cliente)
    total_ventas = int(resumen_ventas.get("cantidad", 0) or 0)
    total_paginas = max((total_ventas + page_size - 1) // page_size, 1)
    page = min(max(int(page or 1), 1), total_paginas)
    ventas_pagina = get_ventas_pagina(page=page, page_size=page_size, id_cliente=id_cliente)
    citas = get_citas(id_cliente=id_cliente)
    mensualidades = get_mensualidades(id_cliente=id_cliente)
    cliente = get_cliente(id_cliente)
    return {
        "cliente": cliente,
        "ventas": ventas_pagina["items"],
        "ventas_total": total_ventas,
        "ventas_pagina": int(page),
        "ventas_paginas": total_paginas,
        "citas": citas,
        "mensualidades": mensualidades,
        "total_gastado": _flt(resumen_ventas.get("total_gastado", 0)),
        "total_pendiente_mens": sum(
            _flt(m.get("importe", 0)) for m in mensualidades if m.get("pagado") == "No"
        ),
    }

# ── DASHBOARD ─────────────────────────────────────────────────────────────────

def get_dashboard_stats():
    db = get_db()
    today = date.today()
    mes_actual = today.strftime("%Y-%m")
    clientes_data    = db.table("clientes").select("id", count="exact").eq("activo", True).execute()
    clientes_activos = int(clientes_data.count or 0)

    citas_hoy_data = (db.table("citas")
        .select("id, hora, observaciones, id_cliente, clientes(nombre)")
        .eq("fecha", today.isoformat())
        .eq("estado", "pendiente")
        .order("hora")
        .execute())
    citas_hoy = citas_hoy_data.data or []
    for c in citas_hoy:
        c["nombre_cliente"] = (c.pop("clientes", None) or {}).get("nombre", "—")

    # Muestra las citas atrasadas aún sin resolver y, por separado, las próximas.
    from datetime import timedelta
    hasta_proximas = (today + timedelta(days=2)).isoformat()
    atrasadas_data = (db.table("citas")
        .select("id, fecha, hora, id_cliente, clientes(nombre)")
        .eq("estado", "pendiente")
        .lt("fecha", today.isoformat())
        .order("fecha", desc=True).order("hora")
        .limit(10)
        .execute())
    futuras_data = (db.table("citas")
        .select("id, fecha, hora, id_cliente, clientes(nombre)")
        .eq("estado", "pendiente")
        .gt("fecha", today.isoformat())
        .lte("fecha", hasta_proximas)
        .order("fecha").order("hora")
        .limit(10)
        .execute())
    proximas_citas = (atrasadas_data.data or []) + (futuras_data.data or [])
    for c in proximas_citas:
        c["nombre_cliente"] = (c.pop("clientes", None) or {}).get("nombre", "—")

    mens_pend = (db.table("mensualidades").select("id", count="exact")
                 .like("mes", f"{mes_actual}%").eq("pagado", "No").execute())
    mens_pendientes = int(mens_pend.count or 0)

    resumen_mes_response = db.rpc("get_dashboard_resumen_mes", {"p_mes": mes_actual}).execute()
    resumen_mes = resumen_mes_response.data
    if isinstance(resumen_mes, list) and resumen_mes:
        resumen_mes = resumen_mes[0]
    resumen_mes = resumen_mes or {}
    total_ventas_mes = _flt(resumen_mes.get("ventas_total", 0))
    total_benef_mes = _flt(resumen_mes.get("ventas_beneficio", 0))
    num_ventas_mes = int(resumen_mes.get("num_ventas", 0) or 0)
    total_mens_pagadas = _flt(resumen_mes.get("mensualidades_pagadas", 0))
    total_propinas = _flt(resumen_mes.get("propinas", 0))

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
        result = get_db().rpc("get_ventas_chart_data_inforbaxe", {}).execute()
        data = result.data
        if isinstance(data, list) and data:
            data = data[0]
        return data or {"labels": [], "values": []}
    except Exception as exc:
        return {"labels": [], "values": [], "error": str(exc)}

