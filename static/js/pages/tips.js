(() => {
  "use strict";

  async function addPropina() {
    const importeInput = document.getElementById("p-importe");
    const fechaInput = document.getElementById("p-fecha");
    const comentarioInput = document.getElementById("p-comentario");
    const importe = importeInput ? parseFloat(importeInput.value) : NaN;
    if (!Number.isFinite(importe) || importe <= 0) {
      alert("Introduce un importe válido");
      return;
    }
    try {
      const response = await fetch("/api/propinas", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          fecha: fechaInput?.value || "",
          importe,
          comentario: comentarioInput?.value || ""
        })
      });
      if (!response.ok) throw new Error("Error al guardar la propina");
      location.reload();
    } catch (error) {
      alert(error.message || "Error");
    }
  }

  document.addEventListener("click", (event) => {
    const button = event.target instanceof Element
      ? event.target.closest("[data-propina-action]")
      : null;
    if (!button) return;
    if (button.dataset.propinaAction === "add") addPropina();
    if (button.dataset.propinaAction === "delete" &&
        typeof window.confirmDelete === "function") {
      window.confirmDelete(button.dataset.url, button.dataset.msg);
    }
  });

  const month = document.getElementById("propinas-month-filter");
  if (month) month.addEventListener("change", () => {
    window.location.href = `/propinas?mes=${encodeURIComponent(month.value)}`;
  });

  const comment = document.getElementById("p-comentario");
  if (comment) comment.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      addPropina();
    }
  });
})();
