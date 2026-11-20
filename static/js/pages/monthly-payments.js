(() => {
  "use strict";
// Estado del menú activo
let _id, _concepto, _importe, _mes, _pagado, _cliente, _modoModal;

function openMenu(btn, id, concepto, importe, mes, pagado, cliente) {
  _id = id; _concepto = concepto; _importe = importe;
  _mes = mes; _pagado = pagado; _cliente = cliente;

  // Actualizar labels
  document.getElementById('cm-title').textContent = concepto + ' · ' + mes;
  document.getElementById('cm-toggle-label').textContent =
    pagado === 'Sí' ? 'Marcar como pendiente' : 'Marcar como pagado';

  // Posicionar el menú junto al botón pulsado
  const menu = document.getElementById('cell-menu');
  const rect = btn.getBoundingClientRect();
  const mW = 210, mH = 250;

  let left = rect.left;
  let top  = rect.bottom + 4;
  if (left + mW > window.innerWidth - 8)  left = window.innerWidth - mW - 8;
  if (top  + mH > window.innerHeight - 8) top  = rect.top - mH - 4;

  menu.style.left = left + 'px';
  menu.style.top  = top  + 'px';
  menu.classList.add('open');
}

function closeMenu() {
  document.getElementById('cell-menu').classList.remove('open');
}

document.addEventListener('click', function(e) {
  if (!e.target.closest('#cell-menu') && !e.target.closest('.cell-menu-btn')) closeMenu();
});
document.addEventListener('keydown', e => { if (e.key === 'Escape') { closeMenu(); cerrarModales(); } });

// ── Acciones del menú ──────────────────────────────────────
function doToggle() {
  closeMenu();
  const nuevoEstado = _pagado === 'Sí' ? 'No' : 'Sí';
  fetch('/api/mensualidades/' + _id + '/toggle', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({pagado: nuevoEstado})
  }).then(() => location.reload());
}

function openModalSoloEste() {
  closeMenu();
  _modoModal = 'solo';
  document.getElementById('modal-precio-titulo').textContent = '✏️ Precio excepcional — ' + _mes;
  document.getElementById('modal-precio-desc').textContent =
    'Solo cambia el importe de ' + _cliente + ' para ' + _mes + '. El resto de meses no se modifica.';
  document.getElementById('nuevo-importe').value = _importe;
  document.getElementById('modal-precio-btn').dataset.monthlyAction = 'save-price-single';
  document.getElementById('modal-precio').classList.add('open');
}

function openModalDesdeAhora() {
  closeMenu();
  _modoModal = 'desde';
  document.getElementById('modal-precio-titulo').textContent = '🔄 Nuevo precio desde ' + _mes;
  document.getElementById('modal-precio-desc').textContent =
    'Cambia el importe de ' + _cliente + ' desde ' + _mes + ' en adelante (todos los meses futuros de este concepto).';
  document.getElementById('nuevo-importe').value = _importe;
  document.getElementById('modal-precio-btn').dataset.monthlyAction = 'save-price-future';
  document.getElementById('modal-precio').classList.add('open');
}

function openModalFinMembresia() {
  closeMenu();
  // Mes siguiente al actual
  const [y, m] = _mes.split('-').map(Number);
  const nextMes = m === 12 ? (y+1) + '-01' : y + '-' + String(m+1).padStart(2,'0');
  document.getElementById('fin-desde').value = nextMes;
  document.getElementById('modal-fin').classList.add('open');
}

function doEliminar() {
  closeMenu();
  if (!confirm('¿Eliminar mensualidad de ' + _cliente + ' para ' + _mes + '?')) return;
  fetch('/api/mensualidades/' + _id, {method:'DELETE'})
    .then(() => location.reload());
}

function cerrarModales() {
  document.getElementById('modal-precio').classList.remove('open');
  document.getElementById('modal-fin').classList.remove('open');
}

// ── Guardar precio solo este mes ──────────────────────────
function guardarPrecioSoloEste() {
  const imp = parseFloat(document.getElementById('nuevo-importe').value);
  if (isNaN(imp)) { alert('Importe inválido'); return; }
  fetch('/api/mensualidades/' + _id + '/editar', {
    method:'PATCH', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({concepto: _concepto, importe: imp, mes: _mes, pagado: _pagado})
  }).then(r => r.json()).then(d => { if(d.ok) location.reload(); else alert('Error: ' + d.error); });
}

// ── Guardar precio desde ahora ────────────────────────────
function guardarPrecioDesdeAhora() {
  const imp = parseFloat(document.getElementById('nuevo-importe').value);
  if (isNaN(imp)) { alert('Importe inválido'); return; }
  fetch('/api/mensualidades/cambiar-precio-futuro', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({id: _id, concepto: _concepto, mes_desde: _mes, nuevo_importe: imp})
  }).then(r => r.json()).then(d => { if(d.ok) location.reload(); else alert('Error: ' + (d.error||'desconocido')); });
}

// ── Fin membresía ─────────────────────────────────────────
function doFinMembresia() {
  const desde = document.getElementById('fin-desde').value;
  if (!desde) { alert('Indica a partir de qué mes'); return; }
  fetch('/api/mensualidades/cancelar-membresia', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({id: _id, concepto: _concepto, mes_desde: desde})
  }).then(r => r.json()).then(d => { if(d.ok) { cerrarModales(); location.reload(); } else alert('Error: ' + (d.error||'desconocido')); });
}

// ── Toggle pago directo (click en la celda) ───────────────
function togglePago(id, nuevoEstado, btn) {
  btn.innerHTML = '...'; btn.disabled = true;
  fetch('/api/mensualidades/' + id + '/toggle', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({pagado: nuevoEstado})
  }).then(() => { playPing(); location.reload(); })
  .catch(() => { btn.disabled = false; alert('Error'); });
}

function playPing() {
  try {
    const ctx = new (window.AudioContext||window.webkitAudioContext)();
    const o = ctx.createOscillator(), g = ctx.createGain();
    o.connect(g); g.connect(ctx.destination);
    o.frequency.value = 880;
    g.gain.setValueAtTime(0.3, ctx.currentTime);
    g.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime+0.4);
    o.start(); o.stop(ctx.currentTime+0.4);
  } catch(e) {}
}

document.addEventListener('click', function(event) {
  const button = event.target instanceof Element
    ? event.target.closest('[data-monthly-action]')
    : null;
  if (!button) return;
  switch (button.dataset.monthlyAction) {
    case 'open-menu':
      openMenu(
        button,
        Number(button.dataset.id),
        button.dataset.concepto || '',
        Number(button.dataset.importe || 0),
        button.dataset.mes || '',
        button.dataset.pagado || 'No',
        button.dataset.cliente || ''
      );
      break;
    case 'toggle-payment':
      togglePago(Number(button.dataset.id), button.dataset.nextState, button);
      break;
    case 'toggle-current':
      doToggle();
      break;
    case 'price-single':
      openModalSoloEste();
      break;
    case 'price-future':
      openModalDesdeAhora();
      break;
    case 'end-membership':
      openModalFinMembresia();
      break;
    case 'delete-month':
      doEliminar();
      break;
    case 'close-modals':
      cerrarModales();
      break;
    case 'save-price-single':
      guardarPrecioSoloEste();
      break;
    case 'save-price-future':
      guardarPrecioDesdeAhora();
      break;
    case 'confirm-end-membership':
      doFinMembresia();
      break;
    default:
      break;
  }
});

})();
