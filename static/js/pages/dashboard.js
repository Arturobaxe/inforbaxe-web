(() => {
  "use strict";

// ── Buscador de Proveedores ───────────────────────────
function buscarProv(proveedor) {
  const query = document.getElementById('prov-query').value.trim();
  if (!query) {
    document.getElementById('prov-query').focus();
    alert('Por favor, escribe el repuesto o modelo que quieres buscar.');
    return;
  }
  
  const qEnc = encodeURIComponent(query);
  const qPlus = query.split(' ').join('+');
  
  const urls = {
    // Restauradas exactamente a la versión que funcionaba (controller=search)
    'klicfon': `https://klicfon.com/es/busqueda?controller=search&s=${qEnc}`,
    'preciosadictos': `https://www.preciosadictos.com/?controller=search&s=${qEnc}&search_query=${qEnc}`,
    'repuestos': `https://www.repuestosdigital.com/es/busqueda?controller=search&s=${qEnc}`,
    // SpainSellers con el arreglo que te ha funcionado
    'spainsellers': `https://www.spainsellers.com/buscar?s=${qPlus}&search_query=${qPlus}#ecommfinder/${qEnc}`
  };

  if (proveedor === 'todos') {
    let bloqueado = false;
    for (const key in urls) {
      const nuevaPestana = window.open(urls[key], '_blank');
      if (!nuevaPestana) bloqueado = true;
    }
    if (bloqueado) alert("⚠️ Tu navegador ha bloqueado algunas ventanas emergentes. Permite los 'Pop-ups' para abrirlas todas a la vez.");
  } else {
    window.open(urls[proveedor], '_blank');
  }
}

document.getElementById('prov-query').addEventListener('keypress', function(e) {
  if (e.key === 'Enter') {
    e.preventDefault();
    buscarProv('todos');
  }
});

// ── Números contando ──────────────────────────────────
document.querySelectorAll('.stat-value[data-count]').forEach(el => {
  const final = parseFloat(el.dataset.count);
  const dec   = parseInt(el.dataset.decimals || '0');
  const euro  = el.textContent.includes('€');
  if (isNaN(final) || final === 0) return;
  el.textContent = '0' + (euro ? '€' : '');
  let start = null;
  const step = ts => {
    if (!start) start = ts;
    const p = Math.min((ts - start) / 900, 1);
    const e = 1 - Math.pow(1 - p, 3);
    el.textContent = (dec ? (final*e).toFixed(dec) : Math.round(final*e)) + (euro ? '€' : '');
    if (p < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
});

// ── Contador días próximas citas ──────────────────────
document.querySelectorAll('.dias-badge[data-fecha]').forEach(el => {
  const fecha = new Date(el.dataset.fecha);
  const hoy   = new Date(); hoy.setHours(0,0,0,0);
  const diff  = Math.round((fecha - hoy) / 86400000);
  if (diff < 0)       { el.textContent = 'ATRASADA';   el.classList.add('urgente'); }
  else if (diff === 0){ el.textContent = 'HOY';        el.classList.add('hoy'); }
  else if (diff === 1) { el.textContent = 'Mañana';     el.classList.add('urgente'); }
  else if (diff <= 2)  { el.textContent = `En ${diff}d`; el.classList.add('urgente'); }
  else                 { el.textContent = `En ${diff}d`; }
});

// ── Notas sticky ──────────────────────────────────────
const notasEl  = document.getElementById('notas-text');
const notasSaved = document.getElementById('notas-saved');
const NOTAS_KEY  = 'inforbaxe_notas';

notasEl.value = sessionStorage.getItem(NOTAS_KEY) || '';
let notasTimer;
notasEl.addEventListener('input', () => {
  clearTimeout(notasTimer);
  notasSaved.textContent = 'Guardando...';
  notasTimer = setTimeout(() => {
    sessionStorage.setItem(NOTAS_KEY, notasEl.value);
    notasSaved.textContent = '✓ Guardado · ' + new Date().toLocaleTimeString('es-ES', {hour:'2-digit', minute:'2-digit'});
  }, 600);
});
if (notasEl.value) notasSaved.textContent = '✓ Notas cargadas';

function clearNotas() {
  if (!confirm('¿Limpiar las notas?')) return;
  notasEl.value = '';
  sessionStorage.removeItem(NOTAS_KEY);
  notasSaved.textContent = 'Limpiado';
}

// ── Gráfico ventas ────────────────────────────────────
window.addEventListener('DOMContentLoaded', async () => {
  const statusEl = document.getElementById('chart-status');
  const canvasEl = document.getElementById('ventas-chart');
  
  try {
    const res  = await fetch('/api/ventas-chart');
    if (!res.ok) throw new Error(`Error de servidor (${res.status}).`);
    
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    
    statusEl.style.display = 'none';
    canvasEl.style.display = 'block';
    
    const ctx = canvasEl.getContext('2d');
    new Chart(ctx, {
      type: 'line',
      data: {
        labels: data.labels,
        datasets: [{
          label: 'Facturación €',
          data: data.values,
          borderColor: '#E8820C',
          backgroundColor: 'rgba(232,130,12,0.06)',
          borderWidth: 3,
          pointBackgroundColor: '#E8820C',
          pointBorderColor: '#ffffff',
          pointBorderWidth: 1.5,
          pointRadius: 4,
          pointHoverRadius: 6,
          tension: 0.38,
          fill: true,
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { grid: { color: 'rgba(0,0,0,0.04)' }, ticks: { font: { size: 10.5, family: 'Sora' }, color: '#8890B5' } },
          y: { grid: { color: 'rgba(0,0,0,0.04)' }, ticks: { font: { size: 10.5, family: 'JetBrains Mono' }, color: '#8890B5',
            callback: v => v + '€' } }
        }
      }
    });
  } catch(e) {
    console.error('Chart error:', e);
    statusEl.replaceChildren();
    const title = document.createElement('span');
    title.style.color = 'var(--red)';
    title.style.fontWeight = '600';
    title.textContent = '⚠️ No se pudo cargar el gráfico';
    const detail = document.createElement('small');
    detail.style.color = 'var(--t3)';
    detail.style.display = 'block';
    detail.style.marginTop = '4px';
    detail.textContent = String(e?.message || 'Error desconocido');
    statusEl.append(title, document.createElement('br'), detail);
  }
});


  document.addEventListener("click", (event) => {
    const target = event.target instanceof Element ? event.target : null;
    const providerButton = target?.closest("[data-provider-search]");
    if (providerButton) {
      buscarProv(providerButton.dataset.providerSearch);
      return;
    }
    const notesButton = target?.closest("[data-notes-action='clear']");
    if (notesButton) clearNotas();
  });
})();
