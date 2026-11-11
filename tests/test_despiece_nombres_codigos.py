"""Nombre sin marca duplicada, enlaces de fuentes y separación de códigos (SM-N980 / SM-N981).
Sin red. Ejecutar: python -m unittest tests.test_despiece_nombres_codigos -v"""
import json, pathlib, re, shutil, subprocess, sys, tempfile, types, unittest
sys.modules.setdefault("database", types.ModuleType("database"))
import despiece_inteligente as d  # noqa: E402

REF = "EB-BN980ABY"
TEMPLATE = pathlib.Path(__file__).resolve().parent.parent / "templates" / "despiece_form_inteligente.html"

P_OVISAT = f"<html><body><p>Batería {REF} Compatible con: Samsung Galaxy Note 20 SM-N980F, Samsung Galaxy Note 20 5G SM-N981B</p></body></html>"
P_TECHTEK = f"<html><body><h1>Batería {REF}</h1><p>Compatible con: Galaxy Note 20 (SM-N980F, SM-N980F/DS), Galaxy Note 20 5G (SM-N981B, SM-N981U)</p></body></html>"
PAGES = {"https://www.ovisat.com/a": ("ovisat.com", P_OVISAT), "https://www.techtekshop.es/b": ("techtekshop.es", P_TECHTEK)}


def family(code):
    return re.match(r"SM-N98\d", code).group(0)


class Association(unittest.TestCase):
    def cands(self, text):
        return d._extract_device_candidates(REF, [f"{REF} Compatible con: {text}"])

    def test_codigos_siguen_al_nombre_que_los_precede(self):
        got = {c["code"]: c["model_name"] for c in self.cands("Galaxy Note 20 (SM-N980F, SM-N980F/DS), Galaxy Note 20 5G (SM-N981B, SM-N981U)")}
        self.assertEqual(got["SM-N980F"], "Galaxy Note 20")
        self.assertEqual(got["SM-N980F/DS"], "Galaxy Note 20")
        self.assertEqual(got["SM-N981B"], "Galaxy Note 20 5G")
        self.assertEqual(got["SM-N981U"], "Galaxy Note 20 5G")

    def test_codigo_delante_del_nombre(self):
        got = {c["code"]: c["model_name"] for c in self.cands("SM-N980F Galaxy Note 20 | SM-N981B Galaxy Note 20 5G")}
        self.assertEqual((got["SM-N980F"], got["SM-N981B"]), ("Galaxy Note 20", "Galaxy Note 20 5G"))

    def test_lista_ambigua_no_adivina_la_asociacion(self):
        for c in self.cands("SM-N980F SM-N981B Samsung Galaxy Note 20 / Note 20 5G"):
            if c["code"]:
                self.assertTrue(c["model_name"].startswith("Modelo identificado por código"), c)

    def test_otro_fabricante_con_un_solo_nombre_conserva_sus_codigos(self):
        got = d._extract_device_candidates("HB486486ECW", ["HB486486ECW compatible con Huawei P30 Pro VOG-L29, VOG-L09"])
        self.assertEqual({(c["code"], c["model_name"]) for c in got if c["code"]},
                         {("VOG-L29", "Huawei P30 Pro"), ("VOG-L09", "Huawei P30 Pro")})


class Naming(unittest.TestCase):
    def test_strip_brand(self):
        self.assertEqual(d._strip_brand("Samsung", "Samsung Galaxy Note 20 5G"), "Galaxy Note 20 5G")
        self.assertEqual(d._strip_brand("Samsung", "Samsung Samsung Galaxy Note 20"), "Galaxy Note 20")
        self.assertEqual(d._strip_brand("Samsung", "Galaxy Note 20"), "Galaxy Note 20")
        self.assertEqual(d._strip_brand("Huawei", "Huawei P30 Pro"), "P30 Pro")
        self.assertEqual(d._strip_brand("Samsung", "Samsung"), "Samsung")

    def test_mismo_modelo_con_y_sin_marca_es_una_sola_clave(self):
        a = d._candidate_consensus_key({"brand": "Huawei", "model_name": "Huawei P30 Pro"})
        b = d._candidate_consensus_key({"brand": "Huawei", "model_name": "P30 Pro"})
        self.assertEqual(a, b)


class EndToEnd(unittest.TestCase):
    def setUp(self):
        self._o = (d._search_direct_catalog, d._global_search_urls, d._http_text, d._robots_can_fetch)
        d._REFERENCE_CACHE.clear()
        d._search_direct_catalog = lambda n, dom, t, r, p="": ([], {"source": n, "domain": dom, "status": "sin_resultados_especificos", "product_links": 0, "pages_read": 0, "found_pages": []})
        d._robots_can_fetch = lambda u: True
        d._http_text = lambda u, limit=0, timeout=0: (PAGES[u][1], u, 200)
        d._global_search_urls = lambda r, p="": ([(d._domain_host(u), u, "") for u in PAGES], [])

    def tearDown(self):
        d._search_direct_catalog, d._global_search_urls, d._http_text, d._robots_can_fetch = self._o

    def test_4g_y_5g_separados_marca_sin_duplicar_y_dos_fuentes_cada_uno(self):
        r = d._automatic_reference_research(REF, "bateria")
        self.assertTrue(r["ok"], r["message"])
        for m in r["models"]:
            self.assertFalse(m["model_name"].lower().startswith("samsung"), m)
            self.assertNotIn("Samsung Samsung", f'{m["brand"]} {m["model_name"]}')
        by_name = {m["model_name"]: m for m in r["models"]}
        self.assertEqual(set(by_name), {"Galaxy Note 20", "Galaxy Note 20 5G"})
        n4, n5 = by_name["Galaxy Note 20"], by_name["Galaxy Note 20 5G"]
        self.assertTrue(all(family(c) == "SM-N980" for c in n4["codes"]), n4["codes"])
        self.assertTrue(all(family(c) == "SM-N981" for c in n5["codes"]), n5["codes"])
        for m in (n4, n5):   # cada compatibilidad la respaldan las dos fuentes independientes
            self.assertEqual((m["matches"], m["total_sources"]), (2, 2))
            self.assertEqual({s["source_group"] for s in m["sources"]}, {"domain:ovisat.com", "domain:techtekshop.es"})


@unittest.skipUnless(shutil.which("node"), "node no disponible")
class SourceLinks(unittest.TestCase):
    def render(self, sources):
        html = TEMPLATE.read_text(encoding="utf-8")
        esc = re.search(r"  function escapeHtml\(value\)[^\n]*\n", html).group(0)
        fn = re.search(r"  function researchSourcesHtml\(list\) \{.*?\n  \}\n", html, re.S).group(0)
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
            f.write(esc + fn + f"console.log(JSON.stringify(researchSourcesHtml({json.dumps(sources)})));")
        out = subprocess.run(["node", f.name], capture_output=True, text=True, check=True).stdout
        return json.loads(out)

    def test_enlaces_reales_no_escapados(self):
        out = self.render([{"domain": "ovisat.com", "url": "https://ovisat.com/p?a=1&b=2"}, {"domain": "techtekshop.es", "url": "https://www.techtekshop.es/x"}])
        self.assertEqual(out.count("<a href="), 2)
        self.assertNotIn("&lt;a", out)
        self.assertIn('href="https://ovisat.com/p?a=1&amp;b=2"', out)
        self.assertIn('rel="noopener noreferrer"', out)
        self.assertIn("ovisat.com ↗</a> · <a", out)

    def test_urls_peligrosas_y_texto_se_escapan(self):
        out = self.render([{"domain": "<img src=x onerror=1>", "url": "javascript:alert(1)"}, {"domain": 'a"b', "url": 'https://x.com/"><script>'}])
        self.assertNotIn("<img", out); self.assertNotIn("<script>", out); self.assertNotIn('href="javascript', out)
        self.assertIn("&lt;img", out)

    def test_la_plantilla_ya_no_escapa_dos_veces(self):
        self.assertNotIn("escapeHtml(sources)", TEMPLATE.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
