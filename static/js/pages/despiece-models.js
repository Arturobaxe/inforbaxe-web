(() => {
  "use strict";
  const status = document.getElementById("sync-status");
  const syncButton = document.getElementById("sync-now");
  const endpoint = status?.dataset.syncEndpoint;
  let running = false;

  async function runSync(force) {
    if (running || !endpoint) return;
    running = true;
    if (status) status.textContent = "Comprobando novedades del catálogo externo…";
    if (syncButton) syncButton.disabled = true;
    try {
      const response = await fetch(endpoint, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({force: !!force})
      });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.message || "No se pudo comprobar el catálogo.");
      if (status) status.textContent = data.message || "Catálogo comprobado.";
      if (data.added > 0) window.setTimeout(() => window.location.reload(), 700);
    } catch (error) {
      if (status) status.textContent = error.message || "No se pudo comprobar el catálogo externo.";
    } finally {
      running = false;
      if (syncButton) syncButton.disabled = false;
    }
  }

  if (syncButton) syncButton.addEventListener("click", () => runSync(true));
  if (status?.dataset.autoSync === "true") runSync(false);

  document.querySelectorAll("form[data-confirm-message]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      if (!confirm(form.dataset.confirmMessage || "¿Continuar?")) event.preventDefault();
    });
  });
})();
