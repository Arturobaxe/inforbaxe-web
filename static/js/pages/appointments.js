(() => {
  "use strict";

  async function resolverCita(id, estado) {
    const texto = estado === "completada"
      ? "¿Confirmas que el cliente ha asistido?"
      : "¿Confirmas que el cliente no ha asistido?";
    if (!confirm(texto)) return;
    try {
      const endpoint = estado === "completada" ? "completar" : "no-asistio";
      const response = await fetch(`/api/citas/${encodeURIComponent(String(id))}/${endpoint}`, {
        method: "POST"
      });
      if (!response.ok) throw new Error("No se pudo actualizar la cita");
      location.reload();
    } catch (error) {
      alert(error.message || "Error al actualizar la cita");
    }
  }

  document.addEventListener("click", (event) => {
    const button = event.target instanceof Element
      ? event.target.closest("[data-cita-action]")
      : null;
    if (!button) return;
    if (button.dataset.citaAction === "resolver") {
      resolverCita(button.dataset.citaId, button.dataset.citaEstado);
    } else if (button.dataset.citaAction === "delete" &&
               typeof window.confirmDelete === "function") {
      window.confirmDelete(button.dataset.url, button.dataset.msg);
    }
  });

  // Swipe para borrar en móvil.
  if ("ontouchstart" in window) {
    document.querySelectorAll('tbody tr[id^="cita-row-"]').forEach((row) => {
      let startX = 0;
      row.addEventListener("touchstart", (event) => {
        startX = event.touches[0].clientX;
      }, {passive: true});
      row.addEventListener("touchend", (event) => {
        const diff = startX - event.changedTouches[0].clientX;
        if (diff > 80) row.querySelector(".delete-cita")?.click();
      }, {passive: true});
    });
  }
})();
