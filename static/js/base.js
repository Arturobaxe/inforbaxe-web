/* JavaScript compartido de la plantilla base de INFORBAXE. */
(() => {
  "use strict";

  const byId = (id) => document.getElementById(id);

  function openSidebar() {
    byId("sidebar")?.classList.add("open");
    byId("sidebar-overlay")?.classList.add("open");
  }

  function closeSidebar() {
    byId("sidebar")?.classList.remove("open");
    byId("sidebar-overlay")?.classList.remove("open");
  }

  window.addEventListener("resize", () => {
    if (window.innerWidth > 768) closeSidebar();
  });

  document.addEventListener("click", (event) => {
    const target = event.target instanceof Element
      ? event.target.closest("[data-action]")
      : null;
    if (!target) return;

    switch (target.dataset.action) {
      case "open-sidebar":
        openSidebar();
        break;
      case "close-sidebar":
        closeSidebar();
        break;
      case "toggle-fab": {
        const menu = byId("fab-menu");
        const button = byId("fab-btn");
        if (!menu || !button) return;
        const isOpen = menu.classList.toggle("open");
        menu.style.display = isOpen ? "flex" : "none";
        button.textContent = isOpen ? "✕" : "＋";
        break;
      }
      default:
        break;
    }
  });

  // Conserva el cierre del menú flotante al pulsar fuera de él.
  document.addEventListener("click", (event) => {
    const target = event.target instanceof Element ? event.target : null;
    if (!target || target.closest("#fab-btn") || target.closest("#fab-menu")) return;
    const menu = byId("fab-menu");
    const button = byId("fab-btn");
    if (menu?.classList.contains("open")) {
      menu.classList.remove("open");
      menu.style.display = "none";
      if (button) button.textContent = "＋";
    }
  });

  // Búsqueda global: el contenido remoto se inserta con textContent, nunca como HTML.
  const searchInput = byId("global-search");
  const searchResults = byId("search-results");
  let searchTimer;

  function renderSearchResults(data) {
    if (!searchResults) return;
    const payload = data && typeof data === "object" ? data : {};
    searchResults.replaceChildren();

    function appendGroup(label, records, buildItem) {
      if (!Array.isArray(records) || !records.length) return;
      const heading = document.createElement("div");
      heading.className = "search-group-label";
      heading.textContent = label;
      searchResults.appendChild(heading);

      records.forEach((record) => {
        if (!record || !Number.isSafeInteger(Number(record.id)) || Number(record.id) <= 0) return;
        const details = buildItem(record);
        const link = document.createElement("a");
        link.href = details.href;
        link.className = "search-result-item";

        const title = document.createElement("div");
        title.className = "search-result-name";
        title.textContent = details.title;

        const subtitle = document.createElement("div");
        subtitle.className = "search-result-sub";
        subtitle.textContent = details.subtitle;

        link.append(title, subtitle);
        searchResults.appendChild(link);
      });
    }

    appendGroup("Clientes", payload.clientes, (c) => ({
      href: `/clientes/${encodeURIComponent(String(c.id))}/historial`,
      title: String(c.nombre || ""),
      subtitle: `${c.email || ""} ${c.telefono || ""}`
    }));

    appendGroup("Ventas", payload.ventas, (v) => ({
      href: `/ventas/${encodeURIComponent(String(v.id))}/editar`,
      title: `${v.nombre_cliente || ""} — ${v.total_pvp ?? ""}€`,
      subtitle: `${v.fecha || ""} · ${v.comentarios || ""}`
    }));

    appendGroup("Citas", payload.citas, (c) => ({
      href: `/citas/${encodeURIComponent(String(c.id))}/editar`,
      title: String(c.nombre_cliente || ""),
      subtitle: `${c.fecha || ""} ${c.hora || ""}`
    }));

    if (!searchResults.hasChildNodes()) {
      const empty = document.createElement("div");
      empty.style.cssText = "padding:14px;color:var(--t3);font-size:13px;";
      empty.textContent = "Sin resultados";
      searchResults.appendChild(empty);
    }
    searchResults.style.display = "block";
  }

  if (searchInput && searchResults) {
    searchInput.addEventListener("input", () => {
      clearTimeout(searchTimer);
      const query = searchInput.value.trim();
      if (query.length < 2) {
        searchResults.style.display = "none";
        return;
      }
      searchTimer = window.setTimeout(() => {
        fetch(`/api/buscar?q=${encodeURIComponent(query)}`)
          .then((response) => response.json())
          .then(renderSearchResults)
          .catch(() => {
            searchResults.replaceChildren();
            searchResults.style.display = "none";
          });
      }, 250);
    });

    document.addEventListener("click", (event) => {
      const target = event.target instanceof Element ? event.target : null;
      if (!target?.closest(".sidebar-search-wrap")) searchResults.style.display = "none";
    });
  }

  // Confirmación genérica para acciones declaradas en atributos data-*.
  document.addEventListener("click", (event) => {
    const button = event.target instanceof Element
      ? event.target.closest("[data-confirm-delete='true']")
      : null;
    if (!button || typeof window.confirmDelete !== "function") return;
    window.confirmDelete(button.dataset.url, button.dataset.msg);
  });

  // Función global usada por acciones de borrado en varias páginas.
  window.confirmDelete = function confirmDelete(url, message) {
    if (!confirm(message || "¿Eliminar este registro?")) return;
    fetch(url, { method: "DELETE" })
      .then((response) => response.json())
      .then(() => location.reload())
      .catch(() => alert("Error al eliminar"));
  };

  // Animación de las tarjetas numéricas.
  document.querySelectorAll(".stat-value").forEach((element) => {
    const text = element.textContent.trim();
    const hasEuro = text.includes("€");
    const hasDot = text.includes(".");
    const finalValue = parseFloat(text.replace("€", "").replace(",", ".").trim());
    if (Number.isNaN(finalValue) || finalValue === 0) return;

    element.textContent = "0" + (hasEuro ? "€" : "");
    let start = null;
    const step = (timestamp) => {
      if (!start) start = timestamp;
      const progress = Math.min((timestamp - start) / 1000, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      element.textContent = (hasDot
        ? (finalValue * eased).toFixed(2)
        : Math.round(finalValue * eased)) + (hasEuro ? "€" : "");
      if (progress < 1) requestAnimationFrame(step);
      else element.textContent = (hasDot ? finalValue.toFixed(2) : finalValue) + (hasEuro ? "€" : "");
    };
    requestAnimationFrame(step);
  });

  // Token CSRF para formularios clásicos y peticiones fetch.
  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || "";
  const originalFetch = window.fetch.bind(window);
  window.fetch = (input, init = {}) => {
    let url;
    try {
      const requestUrl = (typeof Request !== "undefined" && input instanceof Request) ? input.url : input;
      url = new URL(requestUrl, window.location.href);
    } catch (_) {
      return originalFetch(input, init);
    }

    const requestMethod = (init.method || (
      typeof Request !== "undefined" && input instanceof Request ? input.method : "GET"
    )).toUpperCase();

    if (url.origin === window.location.origin &&
        !["GET", "HEAD", "OPTIONS", "TRACE"].includes(requestMethod)) {
      const headers = new Headers(
        typeof Request !== "undefined" && input instanceof Request ? input.headers : undefined
      );
      new Headers(init.headers || undefined).forEach((value, key) => headers.set(key, value));
      headers.set("X-CSRF-Token", csrfToken);
      return originalFetch(input, { ...init, headers });
    }
    return originalFetch(input, init);
  };

  function addFormToken(form) {
    if (!form || form.method.toUpperCase() === "GET" || form.querySelector('input[name="_csrf_token"]')) return;
    const input = document.createElement("input");
    input.type = "hidden";
    input.name = "_csrf_token";
    input.value = csrfToken;
    form.appendChild(input);
  }

  document.querySelectorAll("form").forEach(addFormToken);
  document.addEventListener("submit", (event) => addFormToken(event.target), true);

  // Limpia el almacenamiento local al enviar el formulario de cierre de sesión.
  document.addEventListener("submit", (event) => {
    const form = event.target;
    if (!form.matches('form[data-clear-browser-storage="true"]')) return;
    try {
      sessionStorage.clear();
      localStorage.clear();
    } catch (_) {
      // El cierre de sesión debe continuar aunque el navegador bloquee el almacenamiento.
    }
  }, true);

  document.addEventListener("DOMContentLoaded", () => {
    // Tom Select puede no estar disponible si falla la carga del CDN.
    if (typeof window.TomSelect === "function") {
      document.querySelectorAll('select[name="id_cliente"]').forEach((element) => {
        new window.TomSelect(element, {
          create: false,
          sortField: { field: "text", direction: "asc" },
          placeholder: "Escribe para buscar..."
        });
      });
    }

    // El servidor activa esta animación solo tras guardar una venta correctamente.
    if (document.body?.dataset.saleCreated !== "true") return;
    const layer = document.createElement("div");
    layer.className = "sale-confetti-layer";
    layer.setAttribute("aria-hidden", "true");
    const colors = ["#f97316", "#facc15", "#22c55e", "#3b82f6", "#ec4899", "#a855f7", "#ffffff"];

    for (let i = 0; i < 90; i += 1) {
      const piece = document.createElement("span");
      piece.className = "sale-confetti-piece";
      piece.style.left = (Math.random() * 100) + "%";
      piece.style.width = (6 + Math.random() * 7) + "px";
      piece.style.height = (9 + Math.random() * 10) + "px";
      piece.style.backgroundColor = colors[i % colors.length];
      if (i % 4 === 0) piece.style.borderRadius = "50%";
      piece.style.setProperty("--confetti-drift", ((Math.random() - 0.5) * 260) + "px");
      piece.style.setProperty("--confetti-spin", ((Math.random() - 0.5) * 1100) + "deg");
      piece.style.animationDuration = (2.7 + Math.random() * 0.55) + "s";
      piece.style.animationDelay = (Math.random() * 0.28) + "s";
      layer.appendChild(piece);
    }

    document.body.appendChild(layer);
    window.setTimeout(() => layer.remove(), 3900);
  });
})();
