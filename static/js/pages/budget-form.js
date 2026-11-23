(() => {
  "use strict";
const budgetForm = document.getElementById('presup-form');
let productos = [];
try {
  productos = JSON.parse(budgetForm?.dataset.initialProducts || '[]');
  if (!Array.isArray(productos)) productos = [];
} catch (_) {
  productos = [];
}

function calcPVP() {
  const c = parseFloat(document.getElementById('prod-coste').value)||0;
  const b = parseFloat(document.getElementById('prod-benef').value)||0;
  document.getElementById('pvp-display').textContent = (c+b).toFixed(2)+' €';
}

function toggleNuevoClientePresupuesto() {
  const panel = document.getElementById('nuevo-cliente-presupuesto');
  panel.style.display = panel.style.display === 'none' ? 'block' : 'none';
}

async function crearClientePresupuesto() {
  const nombre = document.getElementById('ncp-nombre').value.trim();
  if (!nombre) { alert('El nombre es obligatorio'); return; }
  try {
    const response = await fetch('/api/clientes/nuevo', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({
        nombre,
        telefono: document.getElementById('ncp-tel').value,
        email: document.getElementById('ncp-email').value,
        notas: document.getElementById('ncp-notas').value
      })
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'No se pudo crear el cliente');
    const select = document.querySelector('select[name="id_cliente"]');
    if (select.tomselect) {
      select.tomselect.addOption({value: String(data.id), text: data.nombre});
      select.tomselect.setValue(String(data.id));
    } else {
      const option = document.createElement('option');
      option.value = data.id; option.textContent = data.nombre; option.selected = true;
      select.appendChild(option);
    }
    ['ncp-nombre','ncp-tel','ncp-email','ncp-notas'].forEach(id => document.getElementById(id).value = '');
    document.getElementById('nuevo-cliente-presupuesto').style.display = 'none';
  } catch (error) {
    alert(error.message || 'Error al crear cliente');
  }
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  })[char]);
}

function renderProductos() {
  const list = document.getElementById('productos-list');
  let pvpT=0, benT=0, costeT=0;
  list.innerHTML = productos.map((p,i)=>{
    pvpT += p.pvp*p.cantidad; benT += p.beneficio*p.cantidad; costeT += (p.coste||0)*p.cantidad;
    return `<div class="prod-row" style="flex-wrap:wrap;">
      <div class="prod-row-name" style="width:100%;margin-bottom:4px;">${escapeHtml(p.nombre)}</div>
      <div class="prod-row-nums" style="flex:1;">
        <span style="color:var(--t3)">coste:${parseFloat(p.coste||0).toFixed(2)}€</span>
        <span style="color:var(--green)">+${parseFloat(p.beneficio).toFixed(2)}€</span>
        <span style="color:var(--blue);font-weight:700;">PVP:${parseFloat(p.pvp).toFixed(2)}€</span>
        <span>×${p.cantidad}</span>
      </div>
      <button type="button" data-product-action="edit" data-product-index="${i}" style="background:none;border:none;cursor:pointer;color:var(--accent);font-size:14px;padding:0 4px;" title="Editar">✏️</button>
      <button type="button" class="prod-row-delete" data-product-action="remove" data-product-index="${i}">✕</button>
    </div>`;
  }).join('');
  document.getElementById('total-pvp').textContent = pvpT.toFixed(2)+' €';
  document.getElementById('total-coste').textContent = costeT.toFixed(2)+' €';
  document.getElementById('total-benef').textContent = benT.toFixed(2)+' €';
  document.getElementById('productos-json').value = JSON.stringify(productos);
}

function editProducto(i) {
  const p = productos[i];
  document.getElementById('prod-nombre').value = p.nombre;
  document.getElementById('prod-coste').value  = (p.coste||0).toFixed(2);
  document.getElementById('prod-benef').value  = p.beneficio.toFixed(2);
  document.getElementById('prod-cant').value   = p.cantidad;
  calcPVP();
  productos.splice(i, 1);
  renderProductos();
  document.getElementById('prod-nombre').focus();
}

function addProducto() {
  const nombre = document.getElementById('prod-nombre').value.trim();
  const coste = parseFloat(document.getElementById('prod-coste').value)||0;
  const benef = parseFloat(document.getElementById('prod-benef').value)||0;
  const pvp = coste+benef;
  const cant = parseInt(document.getElementById('prod-cant').value)||1;
  if (!nombre) { alert('Introduce el nombre'); return; }
  productos.push({nombre,coste,pvp,beneficio:benef,cantidad:cant});
  renderProductos();
  ['prod-nombre','prod-coste','prod-benef'].forEach(id=>document.getElementById(id).value='');
  document.getElementById('prod-cant').value='1';
  document.getElementById('pvp-display').textContent='0.00 €';
  document.getElementById('prod-nombre').focus();
}

function removeProducto(i) { productos.splice(i,1); renderProductos(); }

document.getElementById('presup-form').addEventListener('submit',()=>{
  document.getElementById('productos-json').value=JSON.stringify(productos);
});
renderProductos();

document.addEventListener('click', (event) => {
  const action = event.target instanceof Element
    ? event.target.closest('[data-budget-action], [data-product-action]')
    : null;
  if (!action) return;
  if (action.dataset.budgetAction === 'toggle-client') toggleNuevoClientePresupuesto();
  else if (action.dataset.budgetAction === 'create-client') crearClientePresupuesto();
  else if (action.dataset.budgetAction === 'add-product') addProducto();
  else if (action.dataset.productAction === 'edit') editProducto(Number(action.dataset.productIndex));
  else if (action.dataset.productAction === 'remove') removeProducto(Number(action.dataset.productIndex));
});

['prod-coste', 'prod-benef'].forEach(id => {
  const input = document.getElementById(id);
  if (input) input.addEventListener('input', calcPVP);
});

})();
