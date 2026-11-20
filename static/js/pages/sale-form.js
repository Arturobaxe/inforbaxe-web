(() => {
  "use strict";
// --- CÓDIGO DEL PATRÓN DE DESBLOQUEO ---
const pContainer = document.getElementById('pattern-container');
const pSvg = document.getElementById('pattern-svg');
const pInput = document.getElementById('equipo-patron');
const pDots = Array.from(document.querySelectorAll('.pattern-dot-wrapper'));
let pSequence = [];
let pIsDrawing = false;

function getDotCenter(wrapper) {
    const rect = wrapper.getBoundingClientRect();
    const contRect = pContainer.getBoundingClientRect();
    return { x: rect.left - contRect.left + rect.width / 2, y: rect.top - contRect.top + rect.height / 2 };
}

function drawLines(currentX, currentY) {
    pSvg.innerHTML = '';
    if (pSequence.length === 0) return;
    let d = '';
    for (let i = 0; i < pSequence.length; i++) {
        const center = getDotCenter(pSequence[i]);
        if (i === 0) d += `M ${center.x} ${center.y} `;
        else d += `L ${center.x} ${center.y} `;
    }
    if (currentX !== undefined && currentY !== undefined) {
        const contRect = pContainer.getBoundingClientRect();
        d += `L ${currentX - contRect.left} ${currentY - contRect.top}`;
    }
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', d); path.setAttribute('class', 'pattern-line'); path.setAttribute('fill', 'none');
    pSvg.appendChild(path);
}

function handlePointerDown(e) {
    pIsDrawing = true; pSequence = [];
    pDots.forEach(d => d.querySelector('.pattern-dot').classList.remove('active'));
    handlePointerMove(e);
}

function handlePointerMove(e) {
    if (!pIsDrawing) return;
    e.preventDefault();
    const clientX = e.touches ? (e.touches[0] ? e.touches[0].clientX : null) : e.clientX;
    const clientY = e.touches ? (e.touches[0] ? e.touches[0].clientY : null) : e.clientY;
    if (clientX === null) return;
    const el = document.elementFromPoint(clientX, clientY);
    const wrapper = el ? el.closest('.pattern-dot-wrapper') : null;
    if (wrapper && !pSequence.includes(wrapper)) {
        pSequence.push(wrapper);
        wrapper.querySelector('.pattern-dot').classList.add('active');
    }
    drawLines(clientX, clientY);
}

function handlePointerUp() {
    if (!pIsDrawing) return;
    pIsDrawing = false;
    drawLines();
    pInput.value = pSequence.map(w => w.dataset.val).join('-');
    if (typeof scheduleDraftSave === 'function') scheduleDraftSave();
}

function clearPattern() {
    pSequence = []; pInput.value = '';
    pDots.forEach(d => d.querySelector('.pattern-dot').classList.remove('active'));
    drawLines();
    if (typeof scheduleDraftSave === 'function') scheduleDraftSave();
}

function initPattern() {
    const val = pInput.value;
    if (val) {
        val.split('-').forEach(v => {
            const wrapper = pDots.find(d => d.dataset.val === v);
            if (wrapper) { pSequence.push(wrapper); wrapper.querySelector('.pattern-dot').classList.add('active'); }
        });
        setTimeout(drawLines, 100); // Dar tiempo a que el DOM posicione las celdas
    }
}

pContainer.addEventListener('mousedown', handlePointerDown);
document.addEventListener('mousemove', handlePointerMove, {passive: false});
document.addEventListener('mouseup', handlePointerUp);
pContainer.addEventListener('touchstart', handlePointerDown, {passive: false});
document.addEventListener('touchmove', handlePointerMove, {passive: false});
document.addEventListener('touchend', handlePointerUp);
initPattern();
// --- FIN CÓDIGO PATRÓN ---

const saleFormRoot = document.getElementById('venta-form');
let productos = [];
try {
  productos = JSON.parse(saleFormRoot?.dataset.initialProducts || '[]');
  if (!Array.isArray(productos)) productos = [];
} catch (_) {
  productos = [];
}

function calcPVP() {
  const c = parseFloat(document.getElementById('prod-coste').value.replace(',','.')) || 0;
  const b = parseFloat(document.getElementById('prod-benef').value.replace(',','.')) || 0;
  document.getElementById('pvp-display').textContent = (c+b).toFixed(2) + ' €';
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  })[char]);
}

function renderProductos() {
  const list = document.getElementById('productos-list');
  let pvpTotal=0, benefTotal=0, costeTotal=0;
  list.innerHTML = productos.map((p,i) => {
    const linea = p.pvp * p.cantidad;
    pvpTotal   += linea;
    benefTotal += p.beneficio * p.cantidad;
    costeTotal += (p.coste||0) * p.cantidad;
    return `<div class="prod-row">
      <div class="prod-row-name">${escapeHtml(p.nombre)}</div>
      <div class="prod-row-nums">
        <span style="color:var(--t3)">coste:${parseFloat(p.coste||0).toFixed(2)}€</span>
        <span style="color:var(--green)">+${parseFloat(p.beneficio).toFixed(2)}€</span>
        <span style="color:var(--accent);font-weight:700">PVP:${parseFloat(p.pvp).toFixed(2)}€</span>
        <span>×${p.cantidad}</span>
        <span style="color:var(--t1);font-weight:700">${linea.toFixed(2)}€</span>
      </div>
      <button type="button" data-product-action="edit" data-product-index="${i}" style="background:none;border:none;cursor:pointer;color:var(--accent);font-size:14px;padding:0 4px;">✏️</button>
      <button type="button" class="prod-row-delete" data-product-action="remove" data-product-index="${i}">✕</button>
    </div>`;
  }).join('');
  document.getElementById('total-pvp').textContent   = pvpTotal.toFixed(2)   + ' €';
  document.getElementById('total-benef').textContent = benefTotal.toFixed(2) + ' €';
  document.getElementById('total-coste').textContent = costeTotal.toFixed(2) + ' €';
  document.getElementById('productos-json').value = JSON.stringify(productos);
}

function editProducto(i) {
  const p = productos[i];
  document.getElementById('prod-nombre').value = p.nombre;
  document.getElementById('prod-coste').value  = (p.coste||0).toFixed(2);
  document.getElementById('prod-benef').value  = p.beneficio.toFixed(2);
  document.getElementById('prod-cant').value   = p.cantidad;
  calcPVP();
  productos.splice(i,1);
  renderProductos();
  document.getElementById('prod-nombre').focus();
  scheduleDraftSave();
}

function addProducto() {
  const nombre = document.getElementById('prod-nombre').value.trim();
  const coste  = parseFloat(document.getElementById('prod-coste').value.replace(',','.')) || 0;
  const benef  = parseFloat(document.getElementById('prod-benef').value.replace(',','.')) || 0;
  const cant   = parseInt(document.getElementById('prod-cant').value) || 1;
  if (!nombre) { alert('Introduce el nombre del producto'); return; }
  productos.push({nombre, coste, pvp: coste+benef, beneficio: benef, cantidad: cant});
  renderProductos();
  document.getElementById('prod-nombre').value = '';
  document.getElementById('prod-coste').value  = '';
  document.getElementById('prod-benef').value  = '';
  document.getElementById('prod-cant').value   = '1';
  document.getElementById('pvp-display').textContent = '0.00 €';
  document.getElementById('prod-nombre').focus();
  scheduleDraftSave();
}

function removeProducto(i) { productos.splice(i,1); renderProductos(); scheduleDraftSave(); }

function toggleNuevoCliente() {
  const f = document.getElementById('nuevo-cliente-form');
  f.style.display = f.style.display==='none' ? 'block' : 'none';
}

function crearCliente() {
  const nombre = document.getElementById('nc-nombre').value.trim();
  if (!nombre) { alert('El nombre es obligatorio'); return; }
  fetch('/api/clientes/nuevo', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({nombre, telefono: document.getElementById('nc-tel').value, email: document.getElementById('nc-email').value, notas: document.getElementById('nc-notas').value})
  }).then(async r=>{ const d=await r.json(); if(!r.ok) throw new Error(d.error || 'No se pudo crear el cliente'); return d; }).then(d=>{
    const sel = document.querySelector('select[name="id_cliente"]');
    if (sel.tomselect) {
      sel.tomselect.addOption({value: d.id, text: d.nombre});
      sel.tomselect.setValue(d.id);
    } else {
      const opt = document.createElement('option');
      opt.value=d.id; opt.text=d.nombre; opt.selected=true;
      sel.appendChild(opt);
    }
    document.getElementById('nuevo-cliente-form').style.display='none';
    ['nc-nombre','nc-tel','nc-email','nc-notas'].forEach(id=>document.getElementById(id).value='');
    scheduleDraftSave();
  }).catch(err=>alert(err.message || 'Error al crear cliente'));
}

document.getElementById('prod-nombre').addEventListener('keydown', e => {
  if (e.key==='Enter') { e.preventDefault(); addProducto(); }
});

const ventaForm = document.getElementById('venta-form');
const draftKey = 'inforbaxe:venta:nueva:v2';
const draftStatus = document.getElementById('draft-status');
let draftTimer = null;
let enviandoVenta = false;
let draftDirty = false;

function setDraftStatus(text, color) {
  if (!draftStatus) return;
  draftStatus.textContent = text;
  draftStatus.style.color = color || 'var(--t3)';
}

function guardarBorrador() {
  if (!draftStatus || enviandoVenta || !draftDirty) return;
  try {
    const fields = {};
    ventaForm.querySelectorAll('[name]').forEach(el => {
      if (!['productos_json', 'equipo_contrasena', 'equipo_patron', '_csrf_token'].includes(el.name)) fields[el.name] = el.value;
    });
    const draft = {
      savedAt: new Date().toISOString(),
      fields,
      productos,
      scratch: {
        nombre: document.getElementById('prod-nombre').value,
        coste: document.getElementById('prod-coste').value,
        beneficio: document.getElementById('prod-benef').value,
        cantidad: document.getElementById('prod-cant').value
      }
    };
    sessionStorage.setItem(draftKey, JSON.stringify(draft));
    const hora = new Date().toLocaleTimeString([], {hour:'2-digit', minute:'2-digit', second:'2-digit'});
    setDraftStatus('✓ Borrador guardado en esta pestaña · ' + hora, 'var(--green)');
  } catch (err) {
    setDraftStatus('No se pudo guardar el borrador en este navegador', 'var(--red)');
  }
}

function scheduleDraftSave() {
  if (!draftStatus || enviandoVenta) return;
  draftDirty = true;
  setDraftStatus('Guardando borrador…', 'var(--amber)');
  clearTimeout(draftTimer);
  draftTimer = setTimeout(guardarBorrador, 250);
}

function restaurarBorrador() {
  if (!draftStatus) return;
  let draft;
  try { draft = JSON.parse(sessionStorage.getItem(draftKey) || 'null'); }
  catch (_) { sessionStorage.removeItem(draftKey); return; }
  if (!draft || !draft.fields) return;
  // Elimina datos sensibles que pudieran haberse guardado con una versión anterior.
  ['equipo_contrasena', 'equipo_patron', '_csrf_token'].forEach(key => delete draft.fields[key]);
  try { sessionStorage.setItem(draftKey, JSON.stringify(draft)); } catch (_) {}
  const guardado = draft.savedAt ? new Date(draft.savedAt).toLocaleString() : 'anteriormente';
  if (!confirm('He encontrado un borrador de venta guardado el ' + guardado + '. ¿Quieres recuperarlo?')) {
    sessionStorage.removeItem(draftKey);
    return;
  }
  Object.entries(draft.fields).forEach(([name, value]) => {
    const el = ventaForm.elements.namedItem(name);
    if (el && typeof value === 'string') el.value = value;
  });
  if (Array.isArray(draft.productos)) productos = draft.productos;
  const scratch = draft.scratch || {};
  document.getElementById('prod-nombre').value = scratch.nombre || '';
  document.getElementById('prod-coste').value = scratch.coste || '';
  document.getElementById('prod-benef').value = scratch.beneficio || '';
  document.getElementById('prod-cant').value = scratch.cantidad || '1';
  // Redibuja el patrón si formaba parte del borrador recuperado.
  const patronGuardado = document.getElementById('equipo-patron').value;
  clearPattern();
  if (patronGuardado) {
    patronGuardado.split('-').forEach(v => {
      const wrapper = pDots.find(d => d.dataset.val === v);
      if (wrapper && !pSequence.includes(wrapper)) {
        pSequence.push(wrapper);
        wrapper.querySelector('.pattern-dot').classList.add('active');
      }
    });
    drawLines();
  }
  renderProductos();
  calcPVP();
  setDraftStatus('✓ Borrador anterior recuperado. Se seguirá guardando automáticamente.', 'var(--green)');
}

if (draftStatus) {
  restaurarBorrador();
  ventaForm.addEventListener('input', scheduleDraftSave);
  ventaForm.addEventListener('change', scheduleDraftSave);
  window.addEventListener('pagehide', guardarBorrador);
}

const wasAlreadyPaid = saleFormRoot?.dataset.wasAlreadyPaid === 'true';
const isEditingSale = saleFormRoot?.dataset.isEditingSale === 'true';

document.getElementById('venta-form').addEventListener('submit', () => {
  document.getElementById('productos-json').value = JSON.stringify(productos);
  // Solo celebrar si el cliente pasa de pendiente a pagado (o crea una venta ya cobrada).
  const paymentField = document.getElementById('venta-form').elements.namedItem('pagado');
  if (paymentField && paymentField.value === 'Sí' && (!isEditingSale || !wasAlreadyPaid)) {
    try { sessionStorage.setItem('inforbaxe:celebrate-payment', '1'); } catch (_) {}
  }
  if (draftStatus) {
    guardarBorrador();
    enviandoVenta = true;
    setDraftStatus('Enviando venta…', 'var(--amber)');
    const submit = document.getElementById('venta-submit');
    if (submit) { submit.disabled = true; submit.textContent = 'Guardando…'; }
  }

});

renderProductos();

document.addEventListener('click', (event) => {
  const target = event.target instanceof Element ? event.target : null;
  const saleAction = target?.closest('[data-venta-action]');
  if (saleAction) {
    switch (saleAction.dataset.ventaAction) {
      case 'toggle-client':
        toggleNuevoCliente();
        break;
      case 'create-client':
        crearCliente();
        break;
      case 'clear-pattern':
        clearPattern();
        break;
      case 'add-product':
        addProducto();
        break;
      default:
        break;
    }
    return;
  }
  const productAction = target?.closest('[data-product-action]');
  if (!productAction) return;
  const index = Number(productAction.dataset.productIndex);
  if (productAction.dataset.productAction === 'edit') editProducto(index);
  if (productAction.dataset.productAction === 'remove') removeProducto(index);
});

['prod-coste', 'prod-benef'].forEach(id => {
  const input = document.getElementById(id);
  if (input) input.addEventListener('input', calcPVP);
});

})();
