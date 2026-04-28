"""
app.py - Main Flask application for INFORBAXE web.
"""
import os
import json
import io
from datetime import date, datetime
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, jsonify, flash, abort, make_response
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
            return render_template("cliente_form.html", cliente=None)
        db.add_cliente(nombre, email, telefono, notas)
        flash(f"Cliente '{nombre}' añadido correctamente", "success")
        return redirect(url_for("clientes"))
    return render_template("cliente_form.html", cliente=None)


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
            return render_template("cliente_form.html", cliente=cliente)
        db.update_cliente(id_cliente, nombre, email, telefono, notas)
        flash("Cliente actualizado", "success")
        return redirect(url_for("clientes"))
    return render_template("cliente_form.html", cliente=cliente)


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
    if metodo:
        lista = [v for v in lista if v.get("metodo_pago") == metodo]
    if pagado:
        lista = [v for v in lista if v.get("pagado") == pagado]

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
            return render_template("venta_form.html", clientes=clientes_lista, productos_nombres=productos_lista, metodos=METODOS_PAGO, venta=None, today=date.today().isoformat())
        db.add_venta(id_cliente, fecha, productos, metodo, pagado, comentarios)
        flash("Venta añadida correctamente", "success")
        return redirect(url_for("ventas"))
    return render_template("venta_form.html", clientes=clientes_lista, productos_nombres=productos_lista, metodos=METODOS_PAGO, venta=None, today=date.today().isoformat())


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
    return render_template("venta_form.html", clientes=clientes_lista, productos_nombres=productos_lista, metodos=METODOS_PAGO, venta=venta, today=date.today().isoformat())


@app.route("/api/ventas/<int:id_venta>", methods=["DELETE"])
@login_required
def api_delete_venta(id_venta):
    db.delete_venta(id_venta)
    return jsonify({"ok": True})


# ── ALBARÁN PDF ───────────────────────────────────────────────────────────────

@app.route("/ventas/<int:id_venta>/albaran")
@login_required
def albaran_pdf(id_venta):
    ventas_lista = db.get_ventas()
    venta = next((v for v in ventas_lista if v["id"] == id_venta), None)
    if not venta:
        abort(404)
    cliente = db.get_cliente(venta["id_cliente"])
    pdf_bytes = _generar_pdf_albaran(venta, cliente, tipo="Albarán")
    response = make_response(pdf_bytes)
    response.headers["Content-Type"] = "application/pdf"
    response.headers["Content-Disposition"] = f'inline; filename="albaran_{id_venta}.pdf"'
    return response


def _generar_pdf_albaran(doc, cliente, tipo="Albarán"):
    """Genera PDF con reportlab para albarán o presupuesto."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.lib.units import cm
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_RIGHT, TA_CENTER, TA_LEFT

        buffer = io.BytesIO()
        doc_pdf = SimpleDocTemplate(
            buffer, pagesize=A4,
            leftMargin=2*cm, rightMargin=2*cm,
            topMargin=2*cm, bottomMargin=2*cm
        )

        BLUE  = colors.HexColor('#1E6FFF')
        DARK  = colors.HexColor('#0D1117')
        GRAY  = colors.HexColor('#334155')
        LGRAY = colors.HexColor('#E2E8F0')
        WHITE = colors.white

        styles = getSampleStyleSheet()
        s_title  = ParagraphStyle('t', fontSize=22, textColor=BLUE, fontName='Helvetica-Bold', spaceAfter=2)
        s_sub    = ParagraphStyle('s', fontSize=10, textColor=GRAY, fontName='Helvetica')
        s_h2     = ParagraphStyle('h2', fontSize=13, textColor=DARK, fontName='Helvetica-Bold', spaceBefore=14, spaceAfter=4)
        s_normal = ParagraphStyle('n', fontSize=10, textColor=GRAY, fontName='Helvetica', leading=14)
        s_right  = ParagraphStyle('r', fontSize=10, textColor=GRAY, fontName='Helvetica', alignment=TA_RIGHT)
        s_total  = ParagraphStyle('tot', fontSize=13, textColor=BLUE, fontName='Helvetica-Bold', alignment=TA_RIGHT)

        story = []

        # Header
        header_data = [
            [Paragraph("INFORBAXE", s_title), Paragraph(f"<b>{tipo}</b> #{doc.get('id','')}", s_h2)],
            [Paragraph("Informática y Tecnología", s_sub), Paragraph(f"Fecha: {doc.get('fecha','')}", s_normal)],
        ]
        header_table = Table(header_data, colWidths=[10*cm, 7*cm])
        header_table.setStyle(TableStyle([
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('ALIGN', (1,0), (1,-1), 'RIGHT'),
        ]))
        story.append(header_table)
        story.append(Spacer(1, 0.4*cm))

        # Línea separadora
        from reportlab.platypus import HRFlowable
        story.append(HRFlowable(width="100%", thickness=2, color=BLUE, spaceAfter=10))

        # Datos cliente
        if cliente:
            story.append(Paragraph("Cliente", s_h2))
            story.append(Paragraph(f"<b>{cliente.get('nombre','')}</b>", s_normal))
            if cliente.get('email'):
                story.append(Paragraph(cliente['email'], s_normal))
            if cliente.get('telefono'):
                story.append(Paragraph(cliente['telefono'], s_normal))
        story.append(Spacer(1, 0.4*cm))

        # Tabla productos
        story.append(Paragraph("Detalle", s_h2))
        productos = doc.get("productos", [])
        if isinstance(productos, str):
            try: productos = json.loads(productos)
            except: productos = []

        t_data = [["Producto", "Cant.", "PVP unit.", "Total"]]
        for p in productos:
            pvp   = float(p.get("pvp", 0))
            cant  = int(p.get("cantidad", 1))
            total = pvp * cant
            t_data.append([
                p.get("nombre", ""),
                str(cant),
                f"{pvp:.2f} €",
                f"{total:.2f} €",
            ])

        prod_table = Table(t_data, colWidths=[9*cm, 2*cm, 3*cm, 3*cm])
        prod_table.setStyle(TableStyle([
            ('BACKGROUND',  (0,0), (-1,0), BLUE),
            ('TEXTCOLOR',   (0,0), (-1,0), WHITE),
            ('FONTNAME',    (0,0), (-1,0), 'Helvetica-Bold'),
            ('FONTSIZE',    (0,0), (-1,-1), 10),
            ('ALIGN',       (1,0), (-1,-1), 'RIGHT'),
            ('ALIGN',       (0,0), (0,-1), 'LEFT'),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [WHITE, colors.HexColor('#F8FAFC')]),
            ('GRID',        (0,0), (-1,-1), 0.5, LGRAY),
            ('TOPPADDING',  (0,0), (-1,-1), 6),
            ('BOTTOMPADDING',(0,0), (-1,-1), 6),
            ('LEFTPADDING', (0,0), (-1,-1), 8),
        ]))
        story.append(prod_table)
        story.append(Spacer(1, 0.3*cm))

        # Total
        total_pvp = float(doc.get("total_pvp", 0))
        story.append(Paragraph(f"<b>TOTAL: {total_pvp:.2f} €</b>", s_total))

        # Notas / comentarios
        comentarios = doc.get("comentarios") or doc.get("notas") or ""
        if comentarios:
            story.append(Spacer(1, 0.4*cm))
            story.append(HRFlowable(width="100%", thickness=0.5, color=LGRAY, spaceAfter=8))
            story.append(Paragraph("Notas", s_h2))
            story.append(Paragraph(comentarios, s_normal))

        # Validez (presupuestos)
        validez = doc.get("validez_dias")
        if validez:
            story.append(Spacer(1, 0.2*cm))
            story.append(Paragraph(f"Presupuesto válido por {validez} días.", s_normal))

        # Footer
        story.append(Spacer(1, 1*cm))
        story.append(HRFlowable(width="100%", thickness=0.5, color=LGRAY, spaceAfter=6))
        story.append(Paragraph("INFORBAXE · Informática y Tecnología", ParagraphStyle('ft', fontSize=8, textColor=GRAY, fontName='Helvetica', alignment=TA_CENTER)))

        doc_pdf.build(story)
        return buffer.getvalue()
    except ImportError:
        return b"%PDF-1.4\n% reportlab no instalado"


# ── MENSUALIDADES ─────────────────────────────────────────────────────────────

@app.route("/mensualidades")
@login_required
def mensualidades():
    año = request.args.get("año", str(date.today().year))
    try:
        año = int(año)
    except Exception:
        año = date.today().year
    filtro = request.args.get("filtro", "all")
    buscar_str = request.args.get("buscar", "").strip().lower()

    datos = db.get_mensualidades(año=año)

    if filtro == "paid":
        datos = [m for m in datos if m.get("pagado") == "Sí"]
    elif filtro == "unpaid":
        datos = [m for m in datos if m.get("pagado") != "Sí"]
    if buscar_str:
        datos = [m for m in datos if buscar_str in m.get("nombre_cliente", "").lower()]

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
        mes = m["mes"]
        clientes_set[idc]["meses"][mes] = m

    meses_año = [f"{año}-{i:02d}" for i in range(1, 13)]
    clientes_lista = sorted(clientes_set.values(), key=lambda x: x["nombre"])

    totales_mes = {}
    for mes in meses_año:
        pagados = sum(float(m["importe"]) for c in clientes_lista for m in [c["meses"].get(mes)] if m and m.get("pagado") == "Sí")
        pendientes = sum(float(m["importe"]) for c in clientes_lista for m in [c["meses"].get(mes)] if m and m.get("pagado") != "Sí")
        totales_mes[mes] = {"pagado": round(pagados, 2), "pendiente": round(pendientes, 2)}

    today_mes = date.today().strftime("%Y-%m")
    return render_template(
        "mensualidades.html",
        año=año, meses=meses_año, clientes=clientes_lista,
        totales_mes=totales_mes, filtro=filtro, buscar=buscar_str, today_mes=today_mes,
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
    hoy = date.today()
    fecha_desde = request.args.get("desde", hoy.isoformat())
    buscar_str = request.args.get("buscar", "").strip().lower()
    estado = request.args.get("estado", "")
    lista = db.get_citas(fecha_desde=fecha_desde if fecha_desde else None)
    if estado:
        lista = [c for c in lista if c.get("estado") == estado]
    if buscar_str:
        lista = [c for c in lista if buscar_str in c.get("nombre_cliente", "").lower() or buscar_str in c.get("observaciones", "").lower()]
    clientes_lista = db.get_clientes()
    return render_template("citas.html", citas=lista, clientes=clientes_lista, hoy=hoy.isoformat(),
                           filtros={"desde": fecha_desde, "buscar": buscar_str, "estado": estado})


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


# ── PRESUPUESTOS ──────────────────────────────────────────────────────────────

@app.route("/presupuestos")
@login_required
def presupuestos():
    lista = db.get_presupuestos()
    return render_template("presupuestos.html", presupuestos=lista)


@app.route("/presupuestos/nuevo", methods=["GET", "POST"])
@login_required
def presupuesto_nuevo():
    clientes_lista = db.get_clientes()
    productos_lista = db.get_productos()
    if request.method == "POST":
        id_cliente = request.form.get("id_cliente")
        fecha = request.form.get("fecha", date.today().isoformat())
        validez = request.form.get("validez_dias", 30)
        estado = request.form.get("estado", "pendiente")
        notas = request.form.get("notas", "")
        prods_json = request.form.get("productos_json", "[]")
        try:
            prods = json.loads(prods_json)
        except Exception:
            prods = []
        if not id_cliente:
            flash("Selecciona un cliente", "error")
            return render_template("presupuesto_form.html", clientes=clientes_lista, productos_nombres=productos_lista, presupuesto=None, today=date.today().isoformat())
        db.add_presupuesto(id_cliente, fecha, prods, estado, notas, int(validez))
        flash("Presupuesto creado", "success")
        return redirect(url_for("presupuestos"))
    return render_template("presupuesto_form.html", clientes=clientes_lista, productos_nombres=productos_lista, presupuesto=None, today=date.today().isoformat())


@app.route("/presupuestos/<int:id_presupuesto>/editar", methods=["GET", "POST"])
@login_required
def presupuesto_editar(id_presupuesto):
    presupuesto = db.get_presupuesto(id_presupuesto)
    if not presupuesto:
        abort(404)
    clientes_lista = db.get_clientes()
    productos_lista = db.get_productos()
    if request.method == "POST":
        id_cliente = request.form.get("id_cliente")
        fecha = request.form.get("fecha")
        validez = request.form.get("validez_dias", 30)
        estado = request.form.get("estado", "pendiente")
        notas = request.form.get("notas", "")
        prods_json = request.form.get("productos_json", "[]")
        try:
            prods = json.loads(prods_json)
        except Exception:
            prods = []
        db.update_presupuesto(id_presupuesto, id_cliente, fecha, prods, estado, notas, int(validez))
        flash("Presupuesto actualizado", "success")
        return redirect(url_for("presupuestos"))
    return render_template("presupuesto_form.html", clientes=clientes_lista, productos_nombres=productos_lista, presupuesto=presupuesto, today=date.today().isoformat())


@app.route("/presupuestos/<int:id_presupuesto>/pdf")
@login_required
def presupuesto_pdf(id_presupuesto):
    presupuesto = db.get_presupuesto(id_presupuesto)
    if not presupuesto:
        abort(404)
    cliente = db.get_cliente(presupuesto["id_cliente"])
    pdf_bytes = _generar_pdf_albaran(presupuesto, cliente, tipo="Presupuesto")
    response = make_response(pdf_bytes)
    response.headers["Content-Type"] = "application/pdf"
    response.headers["Content-Disposition"] = f'inline; filename="presupuesto_{id_presupuesto}.pdf"'
    return response


@app.route("/presupuestos/<int:id_presupuesto>/convertir")
@login_required
def presupuesto_convertir(id_presupuesto):
    """Convierte presupuesto aceptado a venta, redirige al form de venta con datos precargados."""
    presupuesto = db.get_presupuesto(id_presupuesto)
    if not presupuesto:
        abort(404)
    # Marcar como aceptado
    db.update_presupuesto(
        id_presupuesto,
        presupuesto["id_cliente"],
        presupuesto["fecha"],
        presupuesto["productos"],
        "aceptado",
        presupuesto.get("notas", ""),
        presupuesto.get("validez_dias", 30),
    )
    # Crear la venta directamente
    comentarios = f"Desde presupuesto #{id_presupuesto}"
    prods = presupuesto.get("productos", [])
    if isinstance(prods, str):
        try: prods = json.loads(prods)
        except: prods = []
    nueva_venta = db.add_venta(
        presupuesto["id_cliente"],
        date.today().isoformat(),
        prods,
        "Efectivo",
        "No",
        comentarios,
    )
    flash(f"Presupuesto #{id_presupuesto} convertido a venta. Revisa y completa los datos.", "success")
    if nueva_venta:
        return redirect(url_for("venta_editar", id_venta=nueva_venta["id"]))
    return redirect(url_for("ventas"))


@app.route("/api/presupuestos/<int:id_presupuesto>", methods=["DELETE"])
@login_required
def api_delete_presupuesto(id_presupuesto):
    db.delete_presupuesto(id_presupuesto)
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
