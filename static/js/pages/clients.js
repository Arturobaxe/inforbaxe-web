(() => {
  "use strict";
  const searchField = document.getElementById("clients-table-search");
  const activeFilter = document.getElementById("clients-filter-activos");
  const clientRows = Array.from(document.querySelectorAll("#clientes-table .client-row"));
  const noResults = document.getElementById("clients-no-results");
  const countLabel = document.getElementById("clients-filter-count");

  const normalize = (value) => String(value || "")
    .normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLocaleLowerCase("es");

  function filterClients() {
    if (!searchField || !activeFilter) return;
    const query = normalize(searchField.value.trim());
    const onlyActive = activeFilter.checked;
    let visible = 0;
    clientRows.forEach((row) => {
      const haystack = normalize(row.dataset.search || row.textContent);
      const isActive = row.dataset.activo === "true";
      const matches = (!query || haystack.includes(query)) && (!onlyActive || isActive);
      row.hidden = !matches;
      if (matches) visible += 1;
    });
    if (noResults) noResults.style.display = clientRows.length && visible === 0 ? "" : "none";
    if (countLabel) countLabel.textContent = `${visible} de ${clientRows.length} clientes visibles`;
  }

  async function toggleClient(button) {
    const id = button.dataset.clienteId;
    const nextActive = button.dataset.activoNext === "true";
    const name = button.dataset.nombre || "este cliente";
    const action = nextActive ? "reactivar" : "desactivar";
    if (!confirm(`¿Quieres ${action} a ${name}? Su historial y sus ventas se conservarán.`)) return;

    button.disabled = true;
    try {
      const response = await fetch(`/api/clientes/${encodeURIComponent(id)}/toggle-activo`, {
        method: "POST",
        credentials: "same-origin",
        headers: {"Content-Type": "application/json", "Accept": "application/json"},
        body: JSON.stringify({activo: nextActive})
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok || result.ok !== true) {
        throw new Error(result.error || `No se pudo ${action} el cliente (HTTP ${response.status}).`);
      }
      const row = button.closest(".client-row");
      if (!row) return;
      const isActive = result.activo === true;
      row.dataset.activo = isActive ? "true" : "false";
      const badge = row.querySelector(".client-status");
      if (badge) {
        badge.textContent = isActive ? "Activo" : "Inactivo";
        badge.classList.toggle("badge-green", isActive);
        badge.classList.toggle("badge-gray", !isActive);
      }
      button.dataset.activoNext = isActive ? "false" : "true";
      button.textContent = isActive ? "Desactivar" : "Reactivar";
      button.classList.toggle("btn-danger", isActive);
      button.classList.toggle("btn-green", !isActive);
      filterClients();
    } catch (error) {
      alert(error.message || "No se pudo actualizar el estado del cliente.");
    } finally {
      button.disabled = false;
    }
  }

  if (searchField) searchField.addEventListener("input", filterClients);
  if (activeFilter) activeFilter.addEventListener("change", filterClients);
  document.querySelectorAll("[data-toggle-cliente]").forEach((button) => {
    button.addEventListener("click", () => toggleClient(button));
  });
  filterClients();
})();
