(() => {
  "use strict";
  document.querySelectorAll('input[name="modelo_id"]').forEach((input) => {
    const card = input.closest("div");
    const verified = card ? card.querySelector('input[name="verificado_id"]') : null;
    if (!verified) return;
    input.addEventListener("change", () => {
      verified.disabled = !input.checked;
      if (!input.checked) verified.checked = false;
    });
  });
})();
