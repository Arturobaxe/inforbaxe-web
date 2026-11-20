(() => {
  "use strict";
  if (typeof window.Chart === "undefined") return;
  const canvas = document.getElementById("fault-trend-chart");
  if (!canvas) return;

  let labels;
  let values;
  try {
    labels = JSON.parse(canvas.dataset.labels || "[]");
    values = JSON.parse(canvas.dataset.values || "[]");
  } catch (_) {
    return;
  }
  if (!Array.isArray(labels) || !Array.isArray(values) || labels.length !== values.length) return;

  window.Chart.defaults.font.family = "'Sora',system-ui,sans-serif";
  window.Chart.defaults.color = "#7d879e";
  new window.Chart(canvas, {
    type: "line",
    data: {
      labels,
      datasets: [{
        label: "Averías detectadas",
        data: values,
        borderColor: "#269a78",
        backgroundColor: "rgba(38,154,120,.13)",
        fill: true,
        tension: .32,
        pointRadius: 4,
        pointHoverRadius: 6,
        pointBackgroundColor: "#269a78"
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {legend: {display: false}},
      scales: {
        x: {grid: {display: false}},
        y: {beginAtZero: true, ticks: {precision: 0}, grid: {color: "rgba(120,130,150,.12)"}}
      }
    }
  });
})();
