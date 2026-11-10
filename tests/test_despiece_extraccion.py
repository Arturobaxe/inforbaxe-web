"""Pruebas offline de extracción y consenso del buscador de compatibilidades (Despiece).

No usan red: las páginas son fixtures HTML. Ejecutar: python -m unittest tests.test_despiece_extraccion -v
"""
import json
import sys
import types
import unittest

# `database` necesita supabase/credenciales; para estas pruebas basta un sustituto.
sys.modules.setdefault("database", types.ModuleType("database"))
from flask import Flask  # noqa: E402

import despiece_inteligente as d  # noqa: E402

REF = "EB-BN980ABY"
OTHER = "EB-BN985ABY"

OVISAT = f"""<html><head><title>Batería Samsung Galaxy Note 20 {REF} | Ovisat</title>
<meta name="description" content="Batería original {REF} para Samsung Galaxy Note 20"></head>
<body><header>Compatible con todo tipo de móviles Galaxy S99</header><h1>Batería {REF}</h1>
<table><tr><th>Referencia</th><td>{REF}</td></tr>
<tr><th>Modelos compatibles</th><td>Samsung Galaxy Note 20 SM-N980F, Galaxy Note 20 5G SM-N981B</td></tr></table>
<h2>Productos relacionados</h2>
<div class="card">Batería {OTHER} Samsung Galaxy Note 20 Ultra SM-N985F</div></body></html>"""

TECHTEK = f"""<html><head><title>Batería {REF}</title></head><body><h1>Batería {REF} Samsung</h1>
<p>Compatible con:</p><ul><li>Samsung Galaxy Note 20</li><li>Samsung Galaxy Note 20 5G</li></ul>
<p>También te puede interesar</p><ul><li>{OTHER} Galaxy Note 20 Ultra</li></ul></body></html>"""

IMPEXTROM = json.dumps({"@context": "https://schema.org", "@graph": [
    {"@type": "Product", "name": f"Batería {REF}", "sku": REF,
     "description": "Batería para <b>Galaxy Note 20</b> SM-N980F<br>Galaxy Note 20 5G SM-N981B",
     "isCompatibleWith": [{"@type": "Product", "name": "Samsung Galaxy Note 20 SM-N980F"}]},
    {"@type": "Product", "name": f"Batería {OTHER}", "sku": OTHER,
     "description": "Galaxy Note 20 Ultra SM-N985F"}]})
IMPEXTROM_HTML = f"<html><head><script type='application/ld+json'>{IMPEXTROM}</script></head><body><h1>Ficha</h1></body></html>"

ONLY_985 = f"<html><body><h1>Batería {OTHER}</h1><p>Compatible con Samsung Galaxy Note 20 Ultra SM-N985F</p></body></html>"
BOTH_ONE_LINE = f"<html><body><p>Baterías {REF} / {OTHER} para Samsung Galaxy Note 20 SM-N980F y Note 20 Ultra SM-N985F</p></body></html>"
SUFFIX = "<html><body><p>Batería EB-BN980ABYX compatible con Samsung Galaxy S5 SM-G900F</p></body></html>"

HUAWEI = """<html><head><title>Batería HB486486ECW Huawei</title></head><body>
<table><tr><td>Referencia</td><td>HB486486ECW</td></tr>
<tr><td>Compatible con</td><td>Huawei P30 Pro VOG-L29, Huawei Mate 20 Pro LYA-L29</td></tr></table></body></html>"""
HUAWEI2 = """<html><body><h1>HB486486ECW</h1><ul><li>Compatible con Huawei P30 Pro (VOG-L09)</li>
<li>Huawei Mate 20 Pro</li></ul></body></html>"""


def ev(html, domain="ovisat.com", url=None, title="", ref=REF, listing=False):
    return d._extract_evidence_from_html(ref, domain, url or f"https://{domain}/p", title, html, listing=listing)


def names(item):
    return {c["model_name"] for c in item["candidates"]}


def codes(item):
    return {c["code"] for c in item["candidates"] if c["code"]}


class ExtractionTests(unittest.TestCase):
    def test_tabla_y_titulo_extraen_modelos_y_codigos(self):
        item = ev(OVISAT)
        self.assertIn("SM-N980F", codes(item))
        self.assertIn("SM-N981B", codes(item))

    def test_no_confunde_980_con_985(self):
        for html in (OVISAT, TECHTEK, IMPEXTROM_HTML):
            item = ev(html, domain="impextrom.com" if html is IMPEXTROM_HTML else "ovisat.com")
            self.assertNotIn("SM-N985F", codes(item))
            self.assertFalse(any("Ultra" in n for n in names(item)), names(item))

    def test_pagina_de_otra_referencia_no_da_evidencia(self):
        self.assertIsNone(ev(ONLY_985))

    def test_linea_con_ambas_referencias_es_ambigua(self):
        self.assertIsNone(ev(BOTH_ONE_LINE))

    def test_referencia_exacta_no_coincide_con_sufijo(self):
        self.assertIsNone(ev(SUFFIX))

    def test_lista_html(self):
        item = ev(TECHTEK, domain="techtekshop.es")
        self.assertTrue({"Samsung Galaxy Note 20", "Samsung Galaxy Note 20 5G"} <= {n for n in names(item)} or
                        {"Galaxy Note 20", "Galaxy Note 20 5G"} <= names(item), names(item))

    def test_jsonld_descripcion_y_compatible_con(self):
        item = ev(IMPEXTROM_HTML, domain="impextrom.com")
        self.assertIn("SM-N980F", codes(item))
        self.assertIn("SM-N981B", codes(item))

    def test_jsonld_invalido_no_rompe(self):
        html = f"<html><head><script type='application/ld+json'>{{no json {REF}</script></head><body>{REF}</body></html>"
        ev(html)  # no debe lanzar excepción

    def test_otra_marca_y_pieza(self):
        a = ev(HUAWEI, ref="HB486486ECW")
        self.assertTrue({"VOG-L29", "LYA-L29"} <= codes(a))
        self.assertTrue(any("P30 Pro" in n for n in names(a)))

    def test_pagina_de_listado_solo_usa_lineas_con_la_referencia(self):
        html = f"<html><body><div>Compatible con Samsung Galaxy S5 SM-G900F</div><div>Batería {REF} Samsung Galaxy Note 20 SM-N980F</div></body></html>"
        item = ev(html, listing=True)
        self.assertEqual(codes(item), {"SM-N980F"})

    def test_titulo_de_enlace_ajeno_no_se_usa(self):
        html = f"<html><body><p>Batería {REF} compatible con SM-N980F</p></body></html>"
        item = ev(html, title="Batería EB-BN985ABY Galaxy Note 20 Ultra SM-N985F")
        self.assertNotIn("SM-N985F", codes(item))

    def test_www_y_dominio_base_son_un_solo_grupo(self):
        a = ev(OVISAT, domain="www.ovisat.com", url="https://www.ovisat.com/a")
        b = ev(OVISAT, domain="ovisat.com", url="https://ovisat.com/b")
        self.assertEqual(a["source_group"], b["source_group"])
        self.assertEqual(a["domain"], "ovisat.com")


PAGES = {
    "https://www.ovisat.com/a": ("ovisat.com", OVISAT),
    "https://www.techtekshop.es/b": ("techtekshop.es", TECHTEK),
    "https://www.impextrom.com/c": ("impextrom.com", IMPEXTROM_HTML),
    "https://ovisat.com/duplicada": ("ovisat.com", OVISAT),
    "https://www.subtel.es/d": ("subtel.es", ONLY_985),
}


class ConsensusTests(unittest.TestCase):
    def setUp(self):
        self._orig = (d._search_direct_catalog, d._global_search_urls, d._http_text, d._robots_can_fetch)
        d._REFERENCE_CACHE.clear()
        d._search_direct_catalog = lambda name, domain, templates, ref, piece="": ([], {"source": name, "domain": domain, "status": "sin_resultados", "pages_read": 0, "product_links": 0})
        d._robots_can_fetch = lambda url: True
        d._http_text = lambda url, limit=0, timeout=0: (PAGES[url][1], url, 200)

    def tearDown(self):
        d._search_direct_catalog, d._global_search_urls, d._http_text, d._robots_can_fetch = self._orig

    def run_research(self, urls):
        d._global_search_urls = lambda ref, piece="": ([(d._domain_host(u), u, "") for u in urls], [])
        return d._automatic_reference_research(REF, "bateria")

    def test_consenso_entre_fuentes_independientes_sin_985(self):
        r = self.run_research(list(PAGES))
        self.assertTrue(r["ok"], r["message"])
        found = {c for m in r["models"] for c in m["codes"]}
        self.assertTrue({"SM-N980F", "SM-N981B"} <= found, found)
        self.assertNotIn("SM-N985F", found)
        # ovisat (www y base) cuenta una vez: 3 fuentes independientes; subtel (solo 985) no aporta.
        self.assertEqual({m["total_sources"] for m in r["models"]}, {3})
        n980 = next(m for m in r["models"] if "SM-N980F" in m["codes"])
        self.assertEqual(n980["matches"], 3)
        self.assertEqual(len({s["source_group"] for s in n980["sources"]}), 3)

    def test_un_solo_dominio_no_alcanza_consenso(self):
        r = self.run_research(["https://www.ovisat.com/a", "https://ovisat.com/duplicada"])
        self.assertFalse(r["models"])

    def test_umbral_no_se_rebaja(self):
        # 3 de 4 fuentes (75%) pasan; con 4 fuentes un modelo en solo 2 (50%) no.
        extra = {"https://www.gsmobile.es/e": ("gsmobile.es", f"<html><body><p>{REF} compatible con Samsung Galaxy S5 SM-G900F</p></body></html>")}
        PAGES.update(extra)
        try:
            r = self.run_research(["https://www.ovisat.com/a", "https://www.techtekshop.es/b", "https://www.impextrom.com/c", "https://www.gsmobile.es/e"])
            found = {c for m in r["models"] for c in m["codes"]}
            self.assertNotIn("SM-G900F", found)
            self.assertIn("SM-N980F", found)
        finally:
            PAGES.pop("https://www.gsmobile.es/e")

    def test_codigo_y_nombre_en_fuentes_distintas_se_fusionan(self):
        by_domain = {
            "domain:a": {"pages": [{"domain": "a", "title": "", "url": "https://a/1", "candidates": [{"code": "SM-N980F", "brand": "Samsung", "model_name": "Galaxy Note 20"}]}]},
            "domain:b": {"pages": [{"domain": "b", "title": "", "url": "https://b/1", "candidates": [{"code": "SM-N980F/DS", "brand": "Samsung", "model_name": "Modelo identificado por código SM-N980F/DS"}]}]},
            "domain:c": {"pages": [{"domain": "c", "title": "", "url": "https://c/1", "candidates": [{"code": "", "brand": "Samsung", "model_name": "Samsung Galaxy Note 20"}]}]},
        }
        merged = d._merge_candidates(by_domain)
        self.assertEqual(len(merged), 1)
        self.assertEqual(len(next(iter(merged.values()))["domains"]), 3)


class _Q:
    def __init__(self, c, name): self.c, self.name = c, name
    def insert(self, row): self.c.calls.append(("insert", self.name, row)); self.row = row; return self
    def upsert(self, row, **kw): self.c.calls.append(("upsert", self.name, row)); return self
    def update(self, row): self.c.calls.append(("update", self.name, row)); return self
    def eq(self, *a): return self
    def execute(self): return types.SimpleNamespace(data=[{"id": 77}])


class _Client:
    def __init__(self): self.calls = []
    def table(self, name): return _Q(self, name)


class FlaskTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__); self.app.secret_key = "test"
        self.app.add_url_rule("/login", "login", lambda: "login")
        self.app.add_url_rule("/despiece", "despiece", lambda: "despiece")
        self.app.register_blueprint(d.despiece_bp)
        self.client = self.app.test_client()
        self._orig = (d._automatic_reference_research, d._find_model)
        d._find_model = lambda marca, modelo: None
        d._automatic_reference_research = lambda ref, piece="": {
            "ok": True, "reference": ref, "models": [{"brand": "Samsung", "model_name": "Galaxy Note 20", "codes": ["SM-N980F"], "matches": 3, "total_sources": 3, "confidence": 100,
                                                     "sources": [{"domain": "ovisat.com", "url": "https://ovisat.com/a", "title": "x"}]}], "sources": []}

    def tearDown(self):
        d._automatic_reference_research, d._find_model = self._orig

    def test_api_sin_sesion_devuelve_json_401(self):
        r = self.client.post("/api/despiece/buscar-referencia", json={"referencia": REF})
        self.assertEqual(r.status_code, 401)
        self.assertFalse(r.get_json()["ok"])

    def test_api_devuelve_token_y_se_guarda_solo_lo_aprobado_como_pendiente(self):
        with self.client.session_transaction() as s: s["logged_in"] = True
        r = self.client.post("/api/despiece/buscar-referencia", json={"referencia": REF})
        data = r.get_json(); self.assertTrue(data["research_token"])
        fake = _Client()
        with self.app.test_request_context():
            self.assertEqual(d._save_research_selection(fake, 5, REF, data["research_token"], "[]"), (0, ""))
            self.assertEqual(fake.calls, [])  # nada aprobado, nada guardado
            saved, warn = d._save_research_selection(fake, 5, REF, data["research_token"], "[0, 9]")
            self.assertEqual((saved, warn), (1, ""))
            rel = next(c for c in fake.calls if c[0] == "upsert" and c[1] == "despiece_repuesto_modelos")[2]
            self.assertEqual(rel["estado_compatibilidad"], "pendiente")
            self.assertIn("ovisat.com", rel["notas"])
            # token manipulado o de otra referencia: no guarda
            self.assertEqual(d._save_research_selection(_Client(), 5, "EB-BN985ABY", data["research_token"], "[0]")[0], 0)
            self.assertEqual(d._save_research_selection(_Client(), 5, REF, data["research_token"] + "x", "[0]")[0], 0)


if __name__ == "__main__":
    unittest.main()
