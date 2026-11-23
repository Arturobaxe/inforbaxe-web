(() => {
  "use strict";
  if (typeof window.Chart === "undefined") return;
  window.Chart.defaults.font.family = "'Sora', system-ui, sans-serif";
  window.Chart.defaults.color = "#7d879e";
  window.Chart.defaults.plugins.legend.labels.usePointStyle = true;

  const canvas = document.getElementById("profit-clients-chart");
  if (canvas) {
    let names;
    let profits;
    try {
      names = JSON.parse(canvas.dataset.labels || "[]");
      profits = JSON.parse(canvas.dataset.values || "[]");
    } catch (_) {
      names = [];
      profits = [];
    }
    if (Array.isArray(names) && Array.isArray(profits) && names.length === profits.length) {
      const colors = ["#e88a2c","#24a477","#527fd0","#9c70c6","#e4b64a","#38a6b7","#e06f86","#668cbb","#a3a45c","#dc955b","#6b9e83","#9576a8"];
      new window.Chart(canvas, {
        type: "bar",
        data: {labels: names, datasets: [{
          label: "Beneficio",
          data: profits,
          backgroundColor: profits.map((_, i) => colors[i % colors.length]),
          borderRadius: 7,
          borderSkipped: false,
          maxBarThickness: 24
        }]},
        options: {
          indexAxis: "y",
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: {display: false},
            tooltip: {callbacks: {
              label: (context) => "Beneficio: " + Number(context.raw || 0).toLocaleString("es-ES", {style: "currency", currency: "EUR"})
            }}
          },
          scales: {
            x: {beginAtZero: true, grid: {color: "rgba(120,130,150,.12)"}, ticks: {callback: (value) => value + " €"}},
            y: {grid: {display: false}}
          }
        }
      });
    }
  }

  const split = document.getElementById("profit-split-chart");
  if (split) {
    let expenses = 0;
    let profit = 0;
    try {
      expenses = Number(JSON.parse(split.dataset.expenses || "0"));
      profit = Number(JSON.parse(split.dataset.profit || "0"));
    } catch (_) {
      return;
    }
    if (Number.isFinite(expenses) && Number.isFinite(profit)) {
      new window.Chart(split, {
        type: "doughnut",
        data: {
          labels: ["Gastos en piezas", "Beneficio"],
          datasets: [{
            data: [expenses, profit],
            backgroundColor: ["#ed9b35", "#27a577"],
            borderColor: "#fff",
            borderWidth: 4,
            hoverOffset: 9
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          cutout: "66%",
          plugins: {
            legend: {position: "bottom"},
            tooltip: {callbacks: {
              label: (context) => context.label + ": " + Number(context.raw || 0).toLocaleString("es-ES", {style: "currency", currency: "EUR"})
            }}
          }
        }
      });
    }
  }
})();
