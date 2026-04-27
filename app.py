"""
app.py - Main Flask application for INFORBAXE web.
"""
import os
import json
from datetime import date, datetime
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, jsonify, flash, abort
)
from dotenv import load_dotenv

load_dotenv()
import database as db

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")

ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASS = os.environ.get("ADMIN_PASS", "inforbaxe2025")

METODOS_PAGO = ["Efectivo", "Tarjeta", "Bizum", "Transferencia", "Otro"]


# ── AUTH ─────────────────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        u = request.form.get("username", "").strip()
        p = request.form.get("password", "")
        if u == ADMIN_USER and p == ADMIN_PASS:
            session["logged_in"] = True
            session["username"] = u
            return redirect(url_for("dashboard"))
        error = "Usuario o contraseña incorrectos"
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ── DASHBOARD ─────────────────────────────────────────────────────────────────

@app.route("/")
@login_required
def dashboard():
    stats = db.get_dashboard_stats()
    return render_template("dashboard.html", stats=stats, today=date.today())


# ── BÚSQUEDA GLOBAL ──────────────────────────────────────────────────────────

@app.route("/buscar")
@login_required
def buscar():
    q = request.args.get("q", "").strip()
    resultados = db.busqueda_global(q) if q else {"clientes": [], "ventas": [], "citas": []}
    return render_template("buscar.html", q=q, resultados=resultados)


@app.route("/api/buscar")
@login_required
def api_buscar():
    q = request.args.get("q", "").strip()
    return jsonify(db.busqueda_global(q))


# ── CLIENTES ──────────────────────────────────────────────────────────────────

@app.route("/clientes")
@login_required
def clientes():
    lista = db.get_clientes()
    return render_template("clientes.html", clientes=lista)


@app.route("/clientes/nuevo", methods=["GET", "POST"])
@login_required
def cliente_nuevo():
    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        email = request.form.get("email", "").strip()
        telefono = request.form.get("telefono", "").strip()
        notas = request.form.get("notas", "").strip()
        if not nombre:
            flash("El nombre es obligatorio", "error")
            return render_template("cliente_form.html", cliente=None, action="nuevo")
        db.add_cliente(nombre, email, telefono, notas)
        flash(f"Cliente '{nombre}' añadido correctamente", "success")
        return redirect(url_for("clientes"))
    return render_template("cliente_form.html", cliente=None, action="nuevo")


@app.route("/clientes/<int:id_cliente>/editar", methods=["GET", "POST"])
@login_required
def cliente_editar(id_cliente):
    cliente = db.get_cliente(id_cliente)
    if not cliente:
        abort(404)
    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        email = request.form.get("email", "").strip()
        telefono = request.form.get("telefono", "").strip()
        notas = request.form.get("notas", "").strip()
        if not nombre:
            flash("El nombre es obligatorio", "error")
            return render_template("cliente_form.html", cliente=cliente, action="editar")
        db.update_cliente(id_cliente, nombre, email, telefono, notas)
        flash("Cliente actualizado", "success")
        return redirect(url_for("clientes"))
    return render_template("cliente_form.html", cliente=cliente, action="editar")


@app.route("/clientes/<int:id_cliente>/historial")
@login_required
def cliente_historial(id_cliente):
    historial = db.get_historial_cliente(id_cliente)
    return render_template("cliente_historial.html", h=historial)


@app.route("/api/clientes/<int:id_cliente>/toggle-activo", methods=["POST"])
@login_required
def api_toggle_activo(id_cliente):
    data = request.get_json() or {}
    activo = data.get("activo", True)
    db.cancelar_cliente(id_cliente, activo)
    return jsonify({"ok": True})


@app.route("/api/clientes/<int:id_cliente>", methods=["DELETE"])
@login_required
def api_delete_cliente(id_cliente):
    db.delete_cliente(id_cliente)
    return jsonify({"ok": True})


# ── VENTAS ────────────────────────────────────────────────────────────────────

@app.route("/ventas")
@login_required
def ventas():
    mes = request.args.get("mes", "")
    id_cliente = request.args.get("id_cliente", "")
    metodo = request.args.get("metodo", "")
    pagado = request.args.get("pagado", "")

    lista = db.get_ventas(
        id_cliente=int(id_cliente) if id_cliente else None,
        mes=mes if mes else None,
    )

    # Filtros adicionales en Python
    if metodo:
        lista = [v for v in lista if v.get("metodo_pago") == metodo]
    if pagado:
        lista = [v for v in lista if v.get("pagado") == pagado]

    # Total del mes
    total_pvp = sum(float(v.get("total_pvp") or 0) for v in lista)
    total_benef = sum(float(v.get("total_benef") or 0) for v in lista)

    clientes_lista = db.get_clientes()
    return render_template(
        "ventas.html",
        ventas=lista,
        clientes=clientes_lista,
        metodos=METODOS_PAGO,
        filtros={"mes": mes, "id_cliente": id_cliente, "metodo": metodo, "pagado": pagado},
        total_pvp=round(total_pvp, 2),
        total_benef=round(total_benef, 2),
    )


@app.route("/ventas/nueva", methods=["GET", "POST"])
@login_required
def venta_nueva():
    clientes_lista = db.get_clientes()
    productos_lista = db.get_productos()
    if request.method == "POST":
        id_cliente = request.form.get("id_cliente")
        fecha = request.form.get("fecha", date.today().isoformat())
        metodo = request.form.get("metodo_pago", "Efectivo")
        pagado = request.form.get("pagado", "Sí")
        comentarios = request.form.get("comentarios", "")
        prods_json = request.form.get("productos_json", "[]")
        try:
            productos = json.loads(prods_json)
        except Exception:
            productos = []
        if not id_cliente:
            flash("Selecciona un cliente", "error")
            return render_template("venta_form.html", clientes=clientes_lista, productos_nombres=productos_lista, metodos=METODOS_PAGO, venta=None)
        db.add_venta(id_cliente, fecha, productos, metodo, pagado, comentarios)
        flash("Venta añadida correctamente", "success")
        return redirect(url_for("ventas"))
    return render_template("venta_form.html", clientes=clientes_lista, productos_nombres=productos_lista, metodos=METODOS_PAGO, venta=None)


@app.route("/ventas/<int:id_venta>/editar", methods=["GET", "POST"])
@login_required
def venta_editar(id_venta):
    ventas_lista = db.get_ventas()
    venta = next((v for v in ventas_lista if v["id"] == id_venta), None)
    if not venta:
        abort(404)
    clientes_lista = db.get_clientes()
    productos_lista = db.get_productos()
    if request.method == "POST":
        id_cliente = request.form.get("id_cliente")
        fecha = request.form.get("fecha")
        metodo = request.form.get("metodo_pago", "Efectivo")
        pagado = request.form.get("pagado", "Sí")
        comentarios = request.form.get("comentarios", "")
        prods_json = request.form.get("productos_json", "[]")
        try:
            productos = json.loads(prods_json)
        except Exception:
            productos = []
        db.update_venta(id_venta, id_cliente, fecha, productos, metodo, pagado, comentarios)
        flash("Venta actualizada", "success")
        return redirect(url_for("ventas"))
    return render_template("venta_form.html", clientes=clientes_lista, productos_nombres=productos_lista, metodos=METODOS_PAGO, venta=venta)


@app.route("/api/ventas/<int:id_venta>", methods=["DELETE"])
@login_required
def api_delete_venta(id_venta):
    db.delete_venta(id_venta)
    return jsonify({"ok": True})


# ── MENSUALIDADES ─────────────────────────────────────────────────────────────

@app.route("/mensualidades")
@login_required
def mensualidades():
    año = request.args.get("año", str(date.today().year))
    try:
        año = int(año)
    except Exception:
        año = date.today().year
    filtro = request.args.get("filtro", "all")  # all / paid / unpaid
    buscar = request.args.get("buscar", "").strip().lower()

    datos = db.get_mensualidades(año=año)

    # Filtro pagado/pendiente
    if filtro == "paid":
        datos = [m for m in datos if m.get("pagado") == "Sí"]
    elif filtro == "unpaid":
        datos = [m for m in datos if m.get("pagado") != "Sí"]

    # Búsqueda por nombre
    if buscar:
        datos = [m for m in datos if buscar in m.get("nombre_cliente", "").lower()]

    # Construir matriz: clientes × meses
    clientes_set = {}
    for m in datos:
        idc = m["id_cliente"]
        if idc not in clientes_set:
            clientes_set[idc] = {
                "id": idc,
                "nombre": m["nombre_cliente"],
                "activo": m.get("cliente_activo", True),
                "meses": {},
            }
        mes = m["mes"]  # YYYY-MM
        clientes_set[idc]["meses"][mes] = m

    meses_año = [f"{año}-{i:02d}" for i in range(1, 13)]
    clientes_lista = sorted(clientes_set.values(), key=lambda x: x["nombre"])

    # Totales por mes
    totales_mes = {}
    for mes in meses_año:
        pagados = sum(float(m["importe"]) for c in clientes_lista for m in [c["meses"].get(mes)] if m and m.get("pagado") == "Sí")
        pendientes = sum(float(m["importe"]) for c in clientes_lista for m in [c["meses"].get(mes)] if m and m.get("pagado") != "Sí")
        totales_mes[mes] = {"pagado": round(pagados, 2), "pendiente": round(pendientes, 2)}

    today_mes = date.today().strftime("%Y-%m")

    return render_template(
        "mensualidades.html",
        año=año,
        meses=meses_año,
        clientes=clientes_lista,
        totales_mes=totales_mes,
        filtro=filtro,
        buscar=buscar,
        today_mes=today_mes,
    )


@app.route("/mensualidades/nueva", methods=["GET", "POST"])
@login_required
def mensualidad_nueva():
    clientes_lista = db.get_clientes()
    if request.method == "POST":
        id_cliente = request.form.get("id_cliente")
        concepto = request.form.get("concepto", "").strip()
        importe_raw = request.form.get("importe", "0").replace(",", ".")
        mes = request.form.get("mes", "").strip()
        pagado = request.form.get("pagado", "No")
        if not id_cliente or not concepto or not mes:
            flash("Completa todos los campos", "error")
            return render_template("mensualidad_form.html", clientes=clientes_lista)
        try:
            importe = float(importe_raw)
        except Exception:
            flash("Importe inválido", "error")
            return render_template("mensualidad_form.html", clientes=clientes_lista)
        db.add_mensualidad(id_cliente, concepto, importe, mes, pagado)
        flash("Mensualidad añadida", "success")
        return redirect(url_for("mensualidades"))
    return render_template("mensualidad_form.html", clientes=clientes_lista)


@app.route("/api/mensualidades/<int:id_mens>/toggle", methods=["POST"])
@login_required
def api_toggle_mensualidad(id_mens):
    data = request.get_json() or {}
    pagado = data.get("pagado", "No")
    db.toggle_mensualidad_pago(id_mens, pagado)
    return jsonify({"ok": True})


@app.route("/api/mensualidades/<int:id_mens>", methods=["DELETE"])
@login_required
def api_delete_mensualidad(id_mens):
    db.delete_mensualidad(id_mens)
    return jsonify({"ok": True})


# ── CITAS ─────────────────────────────────────────────────────────────────────

@app.route("/citas")
@login_required
def citas():
    from datetime import timedelta
    hoy = date.today()
    # Por defecto muestra próximos 30 días
    fecha_desde = request.args.get("desde", hoy.isoformat())
    fecha_hasta = request.args.get("hasta", (hoy.replace(day=1) if False else hoy).isoformat())
    buscar = request.args.get("buscar", "").strip().lower()
    estado = request.args.get("estado", "")

    lista = db.get_citas(fecha_desde=fecha_desde if fecha_desde else None)

    if estado:
        lista = [c for c in lista if c.get("estado") == estado]
    if buscar:
        lista = [c for c in lista if buscar in c.get("nombre_cliente", "").lower() or buscar in c.get("observaciones", "").lower()]

    clientes_lista = db.get_clientes()
    return render_template("citas.html", citas=lista, clientes=clientes_lista, hoy=hoy.isoformat(),
                           filtros={"desde": fecha_desde, "buscar": buscar, "estado": estado})


@app.route("/citas/nueva", methods=["GET", "POST"])
@login_required
def cita_nueva():
    clientes_lista = db.get_clientes()
    if request.method == "POST":
        id_cliente = request.form.get("id_cliente")
        fecha = request.form.get("fecha")
        hora = request.form.get("hora")
        obs = request.form.get("observaciones", "")
        estado = request.form.get("estado", "pendiente")
        if not id_cliente or not fecha or not hora:
            flash("Completa todos los campos obligatorios", "error")
            return render_template("cita_form.html", clientes=clientes_lista, cita=None)
        db.add_cita(id_cliente, fecha, hora, obs, estado)
        flash("Cita añadida", "success")
        return redirect(url_for("citas"))
    fecha_defecto = request.args.get("fecha", date.today().isoformat())
    return render_template("cita_form.html", clientes=clientes_lista, cita=None, fecha_defecto=fecha_defecto)


@app.route("/citas/<int:id_cita>/editar", methods=["GET", "POST"])
@login_required
def cita_editar(id_cita):
    lista = db.get_citas()
    cita = next((c for c in lista if c["id"] == id_cita), None)
    if not cita:
        abort(404)
    clientes_lista = db.get_clientes()
    if request.method == "POST":
        id_cliente = request.form.get("id_cliente")
        fecha = request.form.get("fecha")
        hora = request.form.get("hora")
        obs = request.form.get("observaciones", "")
        estado = request.form.get("estado", "pendiente")
        db.update_cita(id_cita, id_cliente, fecha, hora, obs, estado)
        flash("Cita actualizada", "success")
        return redirect(url_for("citas"))
    return render_template("cita_form.html", clientes=clientes_lista, cita=cita, fecha_defecto=cita.get("fecha", ""))


@app.route("/api/citas/<int:id_cita>", methods=["DELETE"])
@login_required
def api_delete_cita(id_cita):
    db.delete_cita(id_cita)
    return jsonify({"ok": True})


# ── PRODUCTOS ─────────────────────────────────────────────────────────────────

@app.route("/productos")
@login_required
def productos():
    lista = db.get_productos()
    return render_template("productos.html", productos=lista)


@app.route("/api/productos", methods=["POST"])
@login_required
def api_add_producto():
    data = request.get_json() or {}
    nombre = data.get("nombre", "").strip()
    if not nombre:
        return jsonify({"error": "Nombre requerido"}), 400
    p = db.add_producto(nombre)
    return jsonify(p)


@app.route("/api/productos/<int:id_prod>", methods=["DELETE", "PATCH"])
@login_required
def api_producto(id_prod):
    if request.method == "DELETE":
        db.delete_producto(id_prod)
        return jsonify({"ok": True})
    data = request.get_json() or {}
    nombre = data.get("nombre", "").strip()
    if nombre:
        db.rename_producto(id_prod, nombre)
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
