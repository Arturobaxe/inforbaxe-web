(() => {
  "use strict";
  const labels = ["pieza_en_camino", "reparando", "reparacion_acabada"];
  const titles = ["Pieza en camino", "Reparando", "Reparación acabada"];
  const phaseTitles = [
    "¿Qué significa esta fase?",
    "Tu dispositivo está en reparación",
    "¡Tu reparación está terminada!"
  ];
  const phaseDescriptions = [
    "La pieza que necesita tu dispositivo está en camino. En cuanto la recibamos y podamos comenzar el trabajo, actualizaremos este seguimiento.",
    "Nuestro técnico está trabajando en tu dispositivo. Cuando termine la intervención, marcaremos la reparación como acabada y añadiremos una fotografía del interior.",
    "Hemos terminado la reparación. Ya puedes consultar la fotografía que hemos añadido para mostrarte el interior del dispositivo."
  ];
  const steps = [...document.querySelectorAll("[data-step]")];
  const photo = document.getElementById("final-photo");
  const updated = document.getElementById("updated-at");
  const currentStatus = document.getElementById("current-status");
  const progressCount = document.getElementById("progress-count");
  const progressFill = document.getElementById("progress-fill");
  const progressTrack = document.getElementById("progress-track");
  const phaseTitle = document.getElementById("phase-title");
  const phaseDescription = document.getElementById("phase-description");
  const phaseIcon = document.getElementById("phase-icon");
  if (!photo || !updated || !currentStatus || !progressCount || !progressFill ||
      !progressTrack || !phaseTitle || !phaseDescription || !phaseIcon) return;
  const photoUrl = photo.dataset.photoUrl || "";

  function formatUpdated(value) {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? value : date.toLocaleString("es-ES");
  }

  function apply(data) {
    if (data.expired) {
      location.reload();
      return;
    }
    const index = labels.indexOf(data.estado);
    if (index >= 0) {
      steps.forEach((step, i) => {
        step.classList.toggle("done", i < index);
        step.classList.toggle("current", i === index);
        const marker = step.querySelector(".step-marker");
        if (marker) marker.textContent = i < index ? "✓" : String(i + 1);
      });
      currentStatus.textContent = titles[index];
      progressCount.textContent = (index + 1) + " de 3 fases";
      progressFill.style.width = (((index + 1) / 3) * 100) + "%";
      progressTrack.setAttribute("aria-valuenow", String(index + 1));
      phaseTitle.textContent = phaseTitles[index];
      phaseDescription.textContent = phaseDescriptions[index];
      phaseIcon.textContent = index === 2 ? "✓" : String(index + 1);
    }
    if (data.equipo) {
      const device = document.getElementById("device-name");
      if (device) device.textContent = data.equipo;
    }
    if (data.fecha_actualizacion) updated.textContent = formatUpdated(data.fecha_actualizacion);
    if (data.foto_disponible && photo.hidden && photoUrl) {
      const image = document.createElement("img");
      image.className = "photo";
      image.alt = "Fotografía del interior del dispositivo reparado";
      image.src = photoUrl;
      photo.appendChild(image);
      photo.hidden = false;
    }
  }

  updated.textContent = formatUpdated(updated.textContent);
  async function refresh() {
    try {
      const response = await fetch(location.pathname + "/estado", {cache: "no-store"});
      if (response.status === 410 || response.status === 404) {
        location.reload();
        return;
      }
      if (response.ok) apply(await response.json());
    } catch (_) {
      // Si no hay conexión, se conserva el último estado recibido.
    }
  }
  window.setInterval(refresh, 20000);
})();
