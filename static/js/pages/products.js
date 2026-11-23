(() => {
  "use strict";
  const search = document.getElementById("search-prod");
  if (search) {
    search.addEventListener("input", function () {
      const query = this.value.toLowerCase();
      document.querySelectorAll(".prod-item").forEach((element) => {
        element.style.display = (element.dataset.nombre || "").toLowerCase().includes(query) ? "" : "none";
      });
    });
  }

  async function addProducto() {
    const input = document.getElementById("nuevo-nombre");
    const nombre = input ? input.value.trim() : "";
    if (!nombre) return;
    try {
      const response = await fetch("/api/productos", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({nombre})
      });
      if (!response.ok) throw new Error("No se pudo añadir el producto.");
      location.reload();
    } catch (error) {
      alert(error.message || "No se pudo añadir el producto.");
    }
  }

  async function startEdit(id) {
    const row = document.querySelector(`.prod-item[data-id="${CSS.escape(String(id))}"]`);
    const nameEl = row ? row.querySelector(".prod-name") : null;
    if (!nameEl) return;
    const oldName = nameEl.textContent.trim();
    const newName = prompt("Nuevo nombre:", oldName);
    if (!newName || newName.trim() === oldName) return;
    try {
      const response = await fetch(`/api/productos/${encodeURIComponent(String(id))}`, {
        method: "PATCH",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({nombre: newName.trim()})
      });
      if (!response.ok) throw new Error("No se pudo renombrar el producto.");
      location.reload();
    } catch (error) {
      alert(error.message || "No se pudo renombrar el producto.");
    }
  }

  document.addEventListener("click", (event) => {
    const button = event.target instanceof Element
      ? event.target.closest("[data-product-action]")
      : null;
    if (!button) return;
    switch (button.dataset.productAction) {
      case "add":
        addProducto();
        break;
      case "edit":
        startEdit(button.dataset.productId);
        break;
      case "delete":
        if (typeof window.confirmDelete === "function") {
          window.confirmDelete(button.dataset.url, button.dataset.msg);
        }
        break;
      default:
        break;
    }
  });

  const newName = document.getElementById("nuevo-nombre");
  if (newName) newName.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      addProducto();
    }
  });
})();
