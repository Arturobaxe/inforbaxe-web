(() => {
  "use strict";
  const codeInput = document.getElementById("buscar-codigo-input");
  const searchButton = document.getElementById("buscar-codigo-btn");
  const result = document.getElementById("buscar-resultado");

  async function buscarPorCodigo() {
    if (!codeInput || !result) return;
    const codigo = codeInput.value.trim().toUpperCase();
    if (!codigo) {
      result.textContent = "Introduce un código IBX.";
      result.style.color = "var(--red)";
      return;
    }
    result.textContent = "Buscando cliente...";
    result.style.color = "var(--t3)";
    if (searchButton) searchButton.disabled = true;
    try {
      const response = await fetch(`/api/clientes/buscar?codigo=${encodeURIComponent(codigo)}`, {
        credentials: "same-origin",
        headers: {"Accept": "application/json"}
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data.id) throw new Error(data.error || "No se ha encontrado el cliente.");
      result.textContent = `Cliente encontrado: ${data.codigo_cliente} · ${data.nombre}. Abriendo ficha...`;
      result.style.color = "var(--green)";
      window.location.href = `/clientes/${encodeURIComponent(data.id)}/editar`;
    } catch (error) {
      result.textContent = "❌ " + (error.message || "Error al buscar el cliente.");
      result.style.color = "var(--red)";
    } finally {
      if (searchButton) searchButton.disabled = false;
    }
  }

  if (searchButton) searchButton.addEventListener("click", buscarPorCodigo);
  if (codeInput) codeInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      buscarPorCodigo();
    }
  });
})();
