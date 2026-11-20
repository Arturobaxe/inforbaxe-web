(() => {
  "use strict";
  const button = document.getElementById("copy-share");
  if (button) {
    button.addEventListener("click", async () => {
      const input = document.getElementById("share-url");
      if (!input) return;
      try {
        await navigator.clipboard.writeText(input.value);
      } catch (_) {
        input.select();
        document.execCommand("copy");
      }
      button.textContent = "✓ Copiado";
    });
  }

  document.querySelectorAll("form[data-confirm-message]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      if (!confirm(form.dataset.confirmMessage || "¿Continuar?")) event.preventDefault();
    });
  });
})();
