(() => {
  "use strict";
  const input = document.getElementById("link-search");
  const list = document.getElementById("links-list");
  if (input && list) {
    const rows = [...list.querySelectorAll(".link-row")];
    const count = document.getElementById("link-count");
    const empty = document.getElementById("no-search-results");
    input.addEventListener("input", () => {
      const query = input.value.trim().toLocaleLowerCase("es");
      let shown = 0;
      rows.forEach((row) => {
        const match = (row.dataset.search || "").includes(query);
        row.hidden = !match;
        if (match) shown += 1;
      });
      if (count) count.textContent = shown + (shown === 1 ? " enlace" : " enlaces");
      if (empty) empty.hidden = shown !== 0;
    });
  }

  // Confirmación del borrado del enlace en lugar de un onsubmit inline.
  document.querySelectorAll('form[data-confirm-revoke="true"]').forEach((form) => {
    form.addEventListener("submit", (event) => {
      const name = form.dataset.nombre || "este cliente";
      if (!confirm(`¿Revocar el enlace de ${name}? El cliente perderá el acceso y se eliminará la fotografía asociada.`)) {
        event.preventDefault();
      }
    });
  });
})();
