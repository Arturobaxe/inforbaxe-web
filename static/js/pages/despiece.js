(() => {
  "use strict";

  function editFamily(button) {
    const id = button.dataset.familyId;
    const currentName = button.dataset.familyName;
    const name = prompt("Nuevo nombre de la familia:", currentName);
    if (!name || !name.trim() || name.trim() === currentName) return;

    const form = document.createElement("form");
    form.method = "POST";
    form.action = `/despiece/familias/${encodeURIComponent(String(id))}/editar`;

    const input = document.createElement("input");
    input.type = "hidden";
    input.name = "nombre";
    input.value = name.trim();
    form.appendChild(input);

    // form.submit() no dispara el evento submit; incorpora el token CSRF expresamente.
    const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";
    const token = document.createElement("input");
    token.type = "hidden";
    token.name = "_csrf_token";
    token.value = csrf;
    form.appendChild(token);

    document.body.appendChild(form);
    form.submit();
  }

  document.addEventListener("click", (event) => {
    const button = event.target instanceof Element
      ? event.target.closest("[data-family-action='edit']")
      : null;
    if (button) editFamily(button);
  });

  document.querySelectorAll("form[data-confirm-message]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      if (!confirm(form.dataset.confirmMessage || "¿Continuar?")) event.preventDefault();
    });
  });
})();
