"""
app.py - Main Flask application for INFORBAXE web.
"""
import os
import json
import io
import time
import re
import auth as auth_module
from datetime import date
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, jsonify, flash, abort, make_response
)
from dotenv import load_dotenv

load_dotenv()
import database as db

app = Flask(__name__)
app.secret_key  = os.environ.get("SECRET_KEY", "dev-secret-change-me")
ADMIN_USER      = os.environ.get("ADMIN_USER",  "admin")
ADMIN_PASS      = os.environ.get("ADMIN_PASS",  "inforbaxe2025")
ADMIN_EMAIL     = os.environ.get("ADMIN_EMAIL", "inforbaxe@gmail.com")
METODOS_PAGO    = ["Efectivo", "Tarjeta", "Bizum", "Transferencia", "Otro"]
_login_attempts = {}
MAX_ATTEMPTS    = 5
BLOCK_SECONDS   = 300

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("logged_in"):
        return redirect(url_for("dashboard"))
    ip = request.remote_addr
    _login_attempts.setdefault(ip, {"c": 0, "r": time.time() + BLOCK_SECONDS})
    if time.time() < _login_attempts[ip]["r"] and _login_attempts[ip]["c"] >= MAX_ATTEMPTS:
        return render_template("login.html", step=1, error="Demasiados intentos. Espera 5 min."), 429
    if request.method == "POST":
        u = re.sub(r'[<>"\';\\]', '', request.form.get("username", ""))[:50]
        p = request.form.get("password", "")
        if u == ADMIN_USER and p == ADMIN_PASS:
            codigo = auth_module.generar_codigo()
            sid    = str(abs(hash(u + str(time.time()))))
            session["2fa_pending"] = True
            session["2fa_sid"]     = sid
            session["pre_user"]    = u
            auth_module.guardar_codigo(sid, codigo)
            auth_module.enviar_codigo_2fa(ADMIN_EMAIL, codigo)
            _login_attempts.pop(ip, None)
            return render_template("login.html", step=2,
                msg=f"Código enviado a {ADMIN_EMAIL[:4]}***@gmail.com")
        _login_attempts[ip]["c"] += 1
        rem = MAX_ATTEMPTS - _login_attempts[ip]["c"]
        return render_template("login.html", step=1,
            error=f"Credenciales incorrectas. Intentos restantes: {max(rem, 0)}")
    return render_template("login.html", step=1, error=None)

@app.route("/login/verificar", methods=["POST"])
def login_verificar():
    if not session.get("2fa_pending"):
        return redirect(url_for("login"))
    codigo = re.sub(r'[^0-9]', '', request.form.get("codigo", ""))[:6]
    ok, msg = auth_module.verificar_codigo(session.get("2fa_sid", ""), codigo)
    if ok:
        u = session.get("pre_user", ADMIN_USER)
        session.clear()
        session["logged_in"] = True
        session["username"]  = u
        return redirect(url_for("dashboard"))
    return render_template("login.html", step=2, error=msg)

@app.route("/login/reenviar", methods=["POST"])
def login_reenviar():
    if not session.get("2fa_pending"):
        return redirect(url_for("login"))
    codigo = auth_module.generar_codigo()
    auth_module.guardar_codigo(session.get("2fa_sid", ""), codigo)
    auth_module.enviar_codigo_2fa(ADMIN_EMAIL, codigo)
    return render_template("login.html", step=2, msg="Nuevo código enviado.")

@app.route("/sw.js")
def sw():
    return app.send_static_file("sw.js")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/")
@login_required
def dashboard():
    stats = db.get_dashboard_stats()
    return render_template("dashboard.html", stats=stats, today=date.today())

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

@app.route("/clientes")
@login_required
def clientes():
    return render_template("clientes.html", clientes=db.get_clientes())

@app.route("/clientes/nuevo", methods=["GET", "POST"])
@login_required
def cliente_nuevo():
    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        if not nombre:
            flash("El nombre es obligatorio", "error")
            return render_template("cliente_form.html", cliente=None)
        db.add_cliente(nombre, request.form.get("email", ""),
                       request.form.get("telefono", ""), request.form.get("notas", ""))
        flash(f"Cliente '{nombre}' añadido", "success")
        return redirect(url_for("clientes"))
    return render_template("cliente_form.html", cliente=None)

@app.route("/clientes/<int:id_cliente>/editar", methods=["GET", "POST"])
@login_required
def cliente_editar(id_cliente):
    cliente = db.get_cliente(id_cliente)
    if not cliente: abort(404)
    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        if not nombre:
            flash("El nombre es obligatorio", "error")
            return render_template("cliente_form.html", cliente=cliente)
        db.update_cliente(id_cliente, nombre, request.form.get("email", ""),
                          request.form.get("telefono", ""), request.form.get("notas", ""))
        flash("Cliente actualizado", "success")
        return redirect(url_for("clientes"))
    return render_template("cliente_form.html", cliente=cliente)

@app.route("/clientes/<int:id_cliente>/historial")
@login_required
def cliente_historial(id_cliente):
    return render_template("cliente_historial.html", h=db.get_historial_cliente(id_cliente))

@app.route("/api/clientes/nuevo", methods=["POST"])
@login_required
def api_nuevo_cliente():
    data = request.get_json() or {}
    nombre = data.get("nombre", "").strip()
    if not nombre: return jsonify({"error": "Nombre requerido"}), 400
    return jsonify(db.add_cliente(nombre, data.get("email", ""), data.get("telefono", "")))

@app.route("/api/clientes/<int:id_cliente>", methods=["DELETE"])
@login_required
def api_delete_cliente(id_cliente):
    db.delete_cliente(id_cliente)
    return jsonify({"ok": True})

@app.route("/api/clientes/<int:id_cliente>/toggle-activo", methods=["POST"])
@login_required
def api_toggle_activo(id_cliente):
    data = request.get_json() or {}
    db.cancelar_cliente(id_cliente, data.get("activo", True))
    return jsonify({"ok": True})

@app.route("/ventas")
@login_required
def ventas():
    desde      = request.args.get("desde", "")
    hasta      = request.args.get("hasta", "")
    id_cliente = request.args.get("id_cliente", "")
    metodo     = request.args.get("metodo", "")
    pagado     = request.args.get("pagado", "")
    lista      = db.get_ventas(id_cliente=int(id_cliente) if id_cliente else None)
    if desde:  lista = [v for v in lista if v.get("fecha", "") >= desde]
    if hasta:  lista = [v for v in lista if v.get("fecha", "") <= hasta]
    if metodo: lista = [v for v in lista if v.get("metodo_pago") == metodo]
    if pagado: lista = [v for v in lista if v.get("pagado") == pagado]
    total_pvp       = sum(float(v.get("total_pvp",  0)) for v in lista)
    total_benef     = sum(float(v.get("total_benef", 0)) for v in lista)
    total_pendiente = sum(float(v.get("total_pvp",  0)) for v in lista if v.get("pagado") == "No")
    num_pendiente   = sum(1 for v in lista if v.get("pagado") == "No")
    return render_template("ventas.html",
        ventas=lista, clientes=db.get_clientes(), metodos=METODOS_PAGO,
        filtros={"desde": desde, "hasta": hasta, "id_cliente": id_cliente,
                 "metodo": metodo, "pagado": pagado},
        total_pvp=round(total_pvp, 2), total_benef=round(total_benef, 2),
        total_pendiente=round(total_pendiente, 2), num_pendiente=num_pendiente)

@app.route("/ventas/nueva", methods=["GET", "POST"])
@login_required
def venta_nueva():
    clientes_lista  = db.get_clientes()
    productos_lista = db.get_productos()
    if request.method == "POST":
        id_cliente = request.form.get("id_cliente")
        if not id_cliente:
            flash("Selecciona un cliente", "error")
            return render_template("venta_form.html", clientes=clientes_lista,
                productos_nombres=productos_lista, metodos=METODOS_PAGO,
                venta=None, today=date.today().isoformat())
        try: productos = json.loads(request.form.get("productos_json", "[]"))
        except: productos = []
        db.add_venta(id_cliente, request.form.get("fecha", date.today().isoformat()),
                     productos, request.form.get("metodo_pago", "Efectivo"),
                     request.form.get("pagado", "Sí"), request.form.get("comentarios", ""),
                     request.form.get("equipo_modelo", ""), request.form.get("equipo_imei", ""), 
                     request.form.get("equipo_contrasena", ""), request.form.get("equipo_patron", ""))
        flash("Venta añadida", "success")
        return redirect(url_for("ventas"))
    return render_template("venta_form.html", clientes=clientes_lista,
        productos_nombres=productos_lista, metodos=METODOS_PAGO,
        venta=None, today=date.today().isoformat())

@app.route("/ventas/<int:id_venta>/editar", methods=["GET", "POST"])
@login_required
def venta_editar(id_venta):
    ventas_lista = db.get_ventas()
    venta = next((v for v in ventas_lista if v["id"] == id_venta), None)
    if not venta: abort(404)
    clientes_lista  = db.get_clientes()
    productos_lista = db.get_productos()
    if request.method == "POST":
        try: productos = json.loads(request.form.get("productos_json", "[]"))
        except: productos = []
        db.update_venta(id_venta, request.form.get("id_cliente"),
                        request.form.get("fecha"), productos,
                        request.form.get("metodo_pago", "Efectivo"),
                        request.form.get("pagado", "Sí"),
                        request.form.get("comentarios", ""),
                        request.form.get("equipo_modelo", ""), request.form.get("equipo_imei", ""), 
                        request.form.get("equipo_contrasena", ""), request.form.get("equipo_patron", ""))
        flash("Venta actualizada", "success")
        return redirect(url_for("ventas"))
    return render_template("venta_form.html", clientes=clientes_lista,
        productos_nombres=productos_lista, metodos=METODOS_PAGO,
        venta=venta, today=date.today().isoformat())

@app.route("/api/ventas/<int:id_venta>", methods=["DELETE"])
@login_required
def api_delete_venta(id_venta):
    db.delete_venta(id_venta)
    return jsonify({"ok": True})

@app.route("/api/ventas-chart")
@login_required
def api_ventas_chart():
    return jsonify(db.get_ventas_chart_data())

@app.route("/api/ventas/<int:id_venta>/cobrar", methods=["POST"])
@login_required
def api_cobrar_venta(id_venta):
    data = request.get_json() or {}
    db.get_db().table("ventas").update(
        {"pagado": "Sí", "metodo_pago": data.get("metodo", "Efectivo")}
    ).eq("id", id_venta).execute()
    return jsonify({"ok": True})

@app.route("/api/ventas/<int:id_venta>/duplicar", methods=["POST"])
@login_required
def api_duplicar_venta(id_venta):
    ventas_lista = db.get_ventas()
    v = next((x for x in ventas_lista if x["id"] == id_venta), None)
    if not v: return jsonify({"ok": False})
    db.add_venta(v["id_cliente"], date.today().isoformat(),
                 v["productos"], v["metodo_pago"], "No", v["comentarios"],
                 v.get("equipo_modelo", ""), v.get("equipo_imei", ""), 
                 v.get("equipo_contrasena", ""), v.get("equipo_patron", ""))
    return jsonify({"ok": True})

@app.route("/ventas/<int:id_venta>/albaran")
@login_required
def albaran_pdf(id_venta):
    ventas_lista = db.get_ventas()
    venta = next((v for v in ventas_lista if v["id"] == id_venta), None)
    if not venta: abort(404)
    cliente   = db.get_cliente(venta["id_cliente"])
    pdf_bytes = _generar_pdf_albaran(venta, cliente, tipo="Albarán")
    response  = make_response(pdf_bytes)
    response.headers["Content-Type"]        = "application/pdf"
    response.headers["Content-Disposition"] = f'inline; filename="albaran_{id_venta}.pdf"'
    return response

def _generar_pdf_albaran(doc, cliente, tipo="Albarán"):
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.lib.units import cm
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.enums import TA_RIGHT, TA_CENTER

        buffer  = io.BytesIO()
        doc_pdf = SimpleDocTemplate(buffer, pagesize=A4,
            leftMargin=2*cm, rightMargin=2*cm, topMargin=2*cm, bottomMargin=2*cm)

        BLUE  = colors.HexColor('#1E6FFF')
        GRAY  = colors.HexColor('#334155')
        LGRAY = colors.HexColor('#E2E8F0')
        WHITE = colors.white

        s_title = ParagraphStyle('t',   fontSize=22, textColor=BLUE, fontName='Helvetica-Bold')
        s_sub   = ParagraphStyle('s',   fontSize=10, textColor=GRAY, fontName='Helvetica')
        s_h2    = ParagraphStyle('h2',  fontSize=13, textColor=colors.HexColor('#0D1117'), fontName='Helvetica-Bold', spaceBefore=14, spaceAfter=4)
        s_n     = ParagraphStyle('n',   fontSize=10, textColor=GRAY, fontName='Helvetica', leading=14)
        s_tot   = ParagraphStyle('tot', fontSize=13, textColor=BLUE, fontName='Helvetica-Bold', alignment=TA_RIGHT)
        s_foot  = ParagraphStyle('ft',  fontSize=8,  textColor=GRAY, fontName='Helvetica', alignment=TA_CENTER)

        story = []
        ht = Table([
            [Paragraph("INFORBAXE", s_title), Paragraph(f"{tipo} #{doc.get('id','')}", s_h2)],
            [Paragraph("Informática y Tecnología", s_sub), Paragraph(f"Fecha: {doc.get('fecha','')}", s_n)],
        ], colWidths=[10*cm, 7*cm])
        ht.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('ALIGN',(1,0),(1,-1),'RIGHT')]))
        story += [ht, Spacer(1,0.4*cm), HRFlowable(width="100%",thickness=2,color=BLUE,spaceAfter=10)]

        if cliente:
            story.append(Paragraph("Cliente", s_h2))
            story.append(Paragraph(f"{cliente.get('nombre','')}", s_n))
            if cliente.get('email'):    story.append(Paragraph(cliente['email'], s_n))
            if cliente.get('telefono'): story.append(Paragraph(cliente['telefono'], s_n))
        story.append(Spacer(1,0.4*cm))
        story.append(Paragraph("Detalle", s_h2))

        productos = doc.get("productos",[])
        if isinstance(productos, str):
            try: productos = json.loads(productos)
            except: productos = []

        t_data = [["Producto","Cant.","PVP unit.","Total"]]
        for p in productos:
            pvp  = float(p.get("pvp",0))
            cant = int(p.get("cantidad",1))
            t_data.append([p.get("nombre",""), str(cant), f"{pvp:.2f} €", f"{pvp*cant:.2f} €"])

        pt = Table(t_data, colWidths=[9*cm,2*cm,3*cm,3*cm])
        pt.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,0),BLUE),('TEXTCOLOR',(0,0),(-1,0),WHITE),
            ('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),('FONTSIZE',(0,0),(-1,-1),10),
            ('ALIGN',(1,0),(-1,-1),'RIGHT'),('ALIGN',(0,0),(0,-1),'LEFT'),
            ('ROWBACKGROUNDS',(0,1),(-1,-1),[WHITE,colors.HexColor('#F8FAFC')]),
            ('GRID',(0,0),(-1,-1),0.5,LGRAY),
            ('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),6),('LEFTPADDING',(0,0),(-1,-1),8),
        ]))
        story += [pt, Spacer(1,0.3*cm), Paragraph(f"TOTAL: {float(doc.get('total_pvp',0)):.2f} €", s_tot)]

        comentarios = doc.get("comentarios") or doc.get("notas") or ""
        if comentarios:
            story += [Spacer(1,0.4*cm), HRFlowable(width="100%",thickness=0.5,color=LGRAY,spaceAfter=8),
                      Paragraph("Notas", s_h2), Paragraph(comentarios, s_n)]
        
        if doc.get("equipo_modelo") or doc.get("equipo_imei"):
            story.append(Spacer(1,0.4*cm))
            eq_text = ""
            if doc.get("equipo_modelo"): eq_text += f"Modelo: {doc['equipo_modelo']} "
            if doc.get("equipo_imei"): eq_text += f"| IMEI: {doc['equipo_imei']}"
            story.append(Paragraph(eq_text, s_n))

        if doc.get("validez_dias"):
            story.append(Paragraph(f"Presupuesto válido por {doc['validez_dias']} días.", s_n))

        story += [Spacer(1,1*cm), HRFlowable(width="100%",thickness=0.5,color=LGRAY,spaceAfter=6),
                  Paragraph("INFORBAXE · Informática y Tecnología", s_foot)]
        doc_pdf.build(story)
        return buffer.getvalue()
    except ImportError:
        return b"%PDF-1.4\n% reportlab no instalado"

@app.route("/mensualidades")
@login_required
def mensualidades():
    año        = int(request.args.get("año", date.today().year))
    filtro     = request.args.get("filtro", "all")
    buscar_str = request.args.get("buscar", "").strip().lower()
    hoy        = date.today()
    mes_actual = hoy.strftime("%Y-%m")

    todas = db.get_mensualidades()
    suscripciones = {}
    for m in todas:
        if not m.get("cliente_activo", True): continue
        key = (m["id_cliente"], m["concepto"])
        mes = m["mes"]
        if key not in suscripciones or mes > suscripciones[key]["ultimo_mes"]:
            suscripciones[key] = {"id_cliente": m["id_cliente"], "concepto": m["concepto"],
                                  "importe": m["importe"], "ultimo_mes": mes}

    for key, s in suscripciones.items():
        ultimo = s["ultimo_mes"]
        ult_año, ult_m = int(ultimo[:4]), int(ultimo[5:])
        while True:
            ult_m += 1
            if ult_m > 12: ult_m = 1; ult_año += 1
            nuevo_mes = f"{ult_año}-{ult_m:02d}"
            if nuevo_mes > mes_actual: break
            db.add_mensualidad(s["id_cliente"], s["concepto"], s["importe"], nuevo_mes, "No")

    datos = db.get_mensualidades(año=año)
    if filtro == "paid":     datos = [m for m in datos if m.get("pagado") == "Sí"]
    elif filtro == "unpaid": datos = [m for m in datos if m.get("pagado") != "Sí"]
    if buscar_str:           datos = [m for m in datos if buscar_str in m.get("nombre_cliente","").lower()]

    clientes_set = {}
    for m in datos:
        idc = m["id_cliente"]
        if idc not in clientes_set:
            clientes_set[idc] = {"id": idc, "nombre": m["nombre_cliente"],
                                 "activo": m.get("cliente_activo", True), "meses": {}}
        clientes_set[idc]["meses"][m["mes"]] = m

    meses_año      = [f"{año}-{i:02d}" for i in range(1, 13)]
    clientes_lista = sorted(clientes_set.values(), key=lambda x: x["nombre"])
    totales_mes    = {mes: {
        "pagado":    round(sum(float(m["importe"]) for c in clientes_lista for m in [c["meses"].get(mes)] if m and m.get("pagado")=="Sí"),2),
        "pendiente": round(sum(float(m["importe"]) for c in clientes_lista for m in [c["meses"].get(mes)] if m and m.get("pagado")!="Sí"),2),
    } for mes in meses_año}
    return render_template("mensualidades.html", año=año, meses=meses_año, clientes=clientes_lista,
        totales_mes=totales_mes, filtro=filtro, buscar=buscar_str, today_mes=mes_actual)

@app.route("/mensualidades/nueva", methods=["GET", "POST"])
@login_required
def mensualidad_nueva():
    clientes_lista = db.get_clientes()
    if request.method == "POST":
        id_cliente = request.form.get("id_cliente")
        concepto   = request.form.get("concepto", "").strip()
        mes        = request.form.get("mes", "").strip()
        pagado     = request.form.get("pagado", "No")
        if not id_cliente or not concepto or not mes:
            flash("Completa todos los campos", "error")
            return render_template("mensualidad_form.html", clientes=clientes_lista)
        try: importe = float(request.form.get("importe", "0").replace(",", "."))
        except:
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
    db.toggle_mensualidad_pago(id_mens, data.get("pagado", "No"))
    return jsonify({"ok": True})

@app.route("/api/mensualidades/<int:id_mens>/editar", methods=["PATCH"])
@login_required
def api_editar_mensualidad(id_mens):
    data = request.get_json() or {}
    concepto = data.get("concepto", "").strip()
    mes      = data.get("mes", "").strip()
    pagado   = data.get("pagado", "No")
    if not concepto or not mes: return jsonify({"error": "Faltan campos"}), 400
    try: importe = round(float(data.get("importe", 0)), 2)
    except: return jsonify({"error": "Importe inválido"}), 400
    db.update_mensualidad(id_mens, concepto, importe, mes, pagado)
    return jsonify({"ok": True})

@app.route("/api/mensualidades/<int:id_mens>", methods=["DELETE"])
@login_required
def api_delete_mensualidad(id_mens):
    db.delete_mensualidad(id_mens)
    return jsonify({"ok": True})

@app.route("/citas")
@login_required
def citas():
    hoy         = date.today()
    fecha_desde = request.args.get("desde", hoy.isoformat())
    buscar_str  = request.args.get("buscar", "").strip().lower()
    estado      = request.args.get("estado", "")
    lista       = db.get_citas(fecha_desde=fecha_desde or None)
    if estado:     lista = [c for c in lista if c.get("estado") == estado]
    if buscar_str: lista = [c for c in lista if buscar_str in c.get("nombre_cliente","").lower()
                            or buscar_str in c.get("observaciones","").lower()]
    return render_template("citas.html", citas=lista, clientes=db.get_clientes(),
        hoy=hoy.isoformat(), filtros={"desde": fecha_desde, "buscar": buscar_str, "estado": estado})

@app.route("/citas/nueva", methods=["GET", "POST"])
@login_required
def cita_nueva():
    clientes_lista = db.get_clientes()
    if request.method == "POST":
        id_cliente = request.form.get("id_cliente")
        fecha = request.form.get("fecha")
        hora  = request.form.get("hora")
        if not id_cliente or not fecha or not hora:
            flash("Completa todos los campos obligatorios", "error")
            return render_template("cita_form.html", clientes=clientes_lista, cita=None)
        db.add_cita(id_cliente, fecha, hora, request.form.get("observaciones",""), request.form.get("estado","pendiente"))
        flash("Cita añadida", "success")
        return redirect(url_for("citas"))
    return render_template("cita_form.html", clientes=clientes_lista, cita=None,
        fecha_defecto=request.args.get("fecha", date.today().isoformat()))

@app.route("/citas/<int:id_cita>/editar", methods=["GET", "POST"])
@login_required
def cita_editar(id_cita):
    lista = db.get_citas()
    cita  = next((c for c in lista if c["id"] == id_cita), None)
    if not cita: abort(404)
    clientes_lista = db.get_clientes()
    if request.method == "POST":
        db.update_cita(id_cita, request.form.get("id_cliente"), request.form.get("fecha"),
                       request.form.get("hora"), request.form.get("observaciones",""),
                       request.form.get("estado","pendiente"))
        flash("Cita actualizada", "success")
        return redirect(url_for("citas"))
    return render_template("cita_form.html", clientes=clientes_lista,
        cita=cita, fecha_defecto=cita.get("fecha",""))

@app.route("/api/citas/<int:id_cita>", methods=["DELETE"])
@login_required
def api_delete_cita(id_cita):
    db.delete_cita(id_cita)
    return jsonify({"ok": True})

@app.route("/api/citas/<int:id_cita>/completar", methods=["POST"])
@login_required
def api_completar_cita(id_cita):
    db.get_db().table("citas").update({"estado":"completada"}).eq("id",id_cita).execute()
    return jsonify({"ok": True})

@app.route("/productos")
@login_required
def productos():
    return render_template("productos.html", productos=db.get_productos())

@app.route("/api/productos", methods=["POST"])
@login_required
def api_add_producto():
    data = request.get_json() or {}
    nombre = data.get("nombre","").strip()
    if not nombre: return jsonify({"error":"Nombre requerido"}), 400
    return jsonify(db.add_producto(nombre))

@app.route("/api/productos/<int:id_prod>", methods=["DELETE","PATCH"])
@login_required
def api_producto(id_prod):
    if request.method == "DELETE":
        db.delete_producto(id_prod)
        return jsonify({"ok": True})
    data = request.get_json() or {}
    nombre = data.get("nombre","").strip()
    if nombre: db.rename_producto(id_prod, nombre)
    return jsonify({"ok": True})

@app.route("/presupuestos")
@login_required
def presupuestos():
    return render_template("presupuestos.html", presupuestos=db.get_presupuestos())

@app.route("/presupuestos/nuevo", methods=["GET","POST"])
@login_required
def presupuesto_nuevo():
    clientes_lista  = db.get_clientes()
    productos_lista = db.get_productos()
    if request.method == "POST":
        id_cliente = request.form.get("id_cliente")
        if not id_cliente:
            flash("Selecciona un cliente","error")
            return render_template("presupuesto_form.html", clientes=clientes_lista,
                productos_nombres=productos_lista, presupuesto=None, today=date.today().isoformat())
        try: prods = json.loads(request.form.get("productos_json","[]"))
        except: prods = []
        db.add_presupuesto(id_cliente, request.form.get("fecha",date.today().isoformat()),
                           prods, request.form.get("estado","pendiente"),
                           request.form.get("notas",""), int(request.form.get("validez_dias",30)))
        flash("Presupuesto creado","success")
        return redirect(url_for("presupuestos"))
    return render_template("presupuesto_form.html", clientes=clientes_lista,
        productos_nombres=productos_lista, presupuesto=None, today=date.today().isoformat())

@app.route("/presupuestos/<int:id_presupuesto>/editar", methods=["GET","POST"])
@login_required
def presupuesto_editar(id_presupuesto):
    presupuesto = db.get_presupuesto(id_presupuesto)
    if not presupuesto: abort(404)
    clientes_lista  = db.get_clientes()
    productos_lista = db.get_productos()
    if request.method == "POST":
        try: prods = json.loads(request.form.get("productos_json","[]"))
        except: prods = []
        db.update_presupuesto(id_presupuesto, request.form.get("id_cliente"),
                              request.form.get("fecha"), prods,
                              request.form.get("estado","pendiente"),
                              request.form.get("notas",""), int(request.form.get("validez_dias",30)))
        flash("Presupuesto actualizado","success")
        return redirect(url_for("presupuestos"))
    return render_template("presupuesto_form.html", clientes=clientes_lista,
        productos_nombres=productos_lista, presupuesto=presupuesto, today=date.today().isoformat())

@app.route("/presupuestos/<int:id_presupuesto>/pdf")
@login_required
def presupuesto_pdf(id_presupuesto):
    presupuesto = db.get_presupuesto(id_presupuesto)
    if not presupuesto: abort(404)
    cliente   = db.get_cliente(presupuesto["id_cliente"])
    pdf_bytes = _generar_pdf_albaran(presupuesto, cliente, tipo="Presupuesto")
    response  = make_response(pdf_bytes)
    response.headers["Content-Type"]        = "application/pdf"
    response.headers["Content-Disposition"] = f'inline; filename="presupuesto_{id_presupuesto}.pdf"'
    return response

@app.route("/presupuestos/<int:id_presupuesto>/convertir")
@login_required
def presupuesto_convertir(id_presupuesto):
    presupuesto = db.get_presupuesto(id_presupuesto)
    if not presupuesto: abort(404)
    db.update_presupuesto(id_presupuesto, presupuesto["id_cliente"], presupuesto["fecha"],
                          presupuesto["productos"], "aceptado",
                          presupuesto.get("notas",""), presupuesto.get("validez_dias",30))
    prods = presupuesto.get("productos",[])
    if isinstance(prods, str):
        try: prods = json.loads(prods)
        except: prods = []
    nueva_venta = db.add_venta(presupuesto["id_cliente"], date.today().isoformat(),
                               prods, "Efectivo", "No", f"Desde presupuesto #{id_presupuesto}")
    flash(f"Presupuesto #{id_presupuesto} convertido a venta.","success")
    if nueva_venta:
        return redirect(url_for("venta_editar", id_venta=nueva_venta["id"]))
    return redirect(url_for("ventas"))

@app.route("/api/presupuestos/<int:id_presupuesto>", methods=["DELETE"])
@login_required
def api_delete_presupuesto(id_presupuesto):
    db.delete_presupuesto(id_presupuesto)
    return jsonify({"ok": True})

@app.route("/propinas")
@login_required
def propinas():
    mes   = request.args.get("mes", date.today().strftime("%Y-%m"))
    lista = db.get_propinas(mes=mes)
    total = round(sum(float(p.get("importe", 0)) for p in lista), 2)
    return render_template("propinas.html", propinas=lista, total=total,
        mes=mes, today=date.today().isoformat())

@app.route("/api/propinas", methods=["POST"])
@login_required
def api_add_propina():
    data = request.get_json() or {}
    fecha      = data.get("fecha", date.today().isoformat())
    comentario = data.get("comentario", "").strip()
    try: importe = round(float(str(data.get("importe", 0)).replace(",",".")), 2)
    except: return jsonify({"error": "Importe inválido"}), 400
    if importe <= 0: return jsonify({"error": "Importe debe ser mayor que 0"}), 400
    return jsonify(db.add_propina(fecha, importe, comentario))

@app.route("/api/propinas/<int:id_propina>", methods=["DELETE"])
@login_required
def api_delete_propina(id_propina):
    db.delete_propina(id_propina)
    return jsonify({"ok": True})

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)