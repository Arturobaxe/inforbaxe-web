(() => {
  "use strict";

let ventaIdCobro = null;
if (new URLSearchParams(window.location.search).get('venta_guardada') === '1') {
  try { sessionStorage.removeItem('inforbaxe:venta:nueva:v2'); } catch (_) {}
}

function marcarPagado(id, nombre) {
  ventaIdCobro = id;
  document.getElementById('modal-cliente-name').textContent = 'Cliente: ' + nombre;
  document.getElementById('modal-cobro').style.display = 'flex';
}
function cerrarModal() {
  document.getElementById('modal-cobro').style.display = 'none';
  ventaIdCobro = null;
}

function celebrarPago() {
  const overlay = document.createElement('div');
  overlay.className = 'payment-celebration';
  overlay.setAttribute('aria-live', 'polite');
  overlay.setAttribute('aria-atomic', 'true');

  const toast = document.createElement('div');
  toast.className = 'payment-toast';
  const title = document.createElement('strong');
  title.textContent = '¡PAGO RECIBIDO!';
  const subtitle = document.createElement('span');
  subtitle.textContent = 'Cobro registrado correctamente';
  toast.append(title, subtitle);
  overlay.appendChild(toast);

  const reduceMotion = window.matchMedia &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (!reduceMotion) {
    const symbols = ['€', '💶', '🪙', '💸', '€', '💶', '🪙', '€'];
    for (let i = 0; i < 30; i++) {
      const coin = document.createElement('span');
      coin.className = 'payment-coin';
      coin.textContent = symbols[i % symbols.length];
      coin.style.left = (24 + Math.random() * 52) + '%';
      coin.style.top = (51 + Math.random() * 15) + '%';
      coin.style.fontSize = (22 + Math.random() * 21) + 'px';
      coin.style.setProperty('--money-drift', ((Math.random() - .5) * 520) + 'px');
      coin.style.setProperty('--money-spin', ((Math.random() - .5) * 760) + 'deg');
      coin.style.animationDelay = (Math.random() * 280) + 'ms';
      overlay.appendChild(coin);
    }

    const notes = ['€5', '€10', '€20', '€50', '€100', '€20', '€50', '€10', '€100', '€20', '€50', '€10'];
    notes.forEach((amount, index) => {
      const note = document.createElement('span');
      note.className = 'payment-note';
      note.textContent = amount;
      note.style.left = (20 + Math.random() * 60) + '%';
      note.style.top = (52 + Math.random() * 13) + '%';
      note.style.setProperty('--money-drift', ((Math.random() - .5) * 620) + 'px');
      note.style.setProperty('--money-spin', ((Math.random() - .5) * 680) + 'deg');
      note.style.animationDelay = (Math.random() * 280) + 'ms';
      overlay.appendChild(note);
    });
  }

  document.body.appendChild(overlay);
  requestAnimationFrame(() => overlay.classList.add('is-active'));

  if (!reduceMotion && typeof window.confetti === 'function') {
    window.confetti({
      particleCount: 78, spread: 74, startVelocity: 38,
      origin: { x: .5, y: .58 },
      colors: ['#16a34a', '#facc15', '#0ea5e9', '#ffffff']
    });
  }

  window.setTimeout(() => {
    overlay.classList.remove('is-active');
    window.setTimeout(() => overlay.remove(), 350);
  }, 3450);
}

function confirmarCobro() {
  if (!ventaIdCobro) return;
  const button = document.getElementById('btn-confirmar-cobro');
  const metodo = document.getElementById('modal-metodo').value;
  if (button) { button.disabled = true; button.textContent = 'Registrando…'; }

  fetch(`/api/ventas/${ventaIdCobro}/cobrar`, {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({metodo})
  }).then(async response => {
    if (!response.ok) throw new Error('No se pudo registrar el cobro.');
    const result = await response.json();
    if (!result || result.ok !== true) throw new Error('El servidor no ha confirmado el cobro.');
    cerrarModal();
    celebrarPago();
    window.setTimeout(() => location.reload(), 3650);
  }).catch(error => {
    if (button) { button.disabled = false; button.textContent = '✓ Cobrado'; }
    alert(error.message || 'No se ha podido registrar el cobro. Inténtalo de nuevo.');
  });
}
document.getElementById('modal-cobro').addEventListener('click', e => {
  if(e.target===document.getElementById('modal-cobro')) cerrarModal();
});

// Si se cambió una venta de pendiente a pagada desde su ficha, celebrar al volver al listado.
(() => {
  let pending = false;
  try {
    pending = sessionStorage.getItem('inforbaxe:celebrate-payment') === '1';
    if (pending) sessionStorage.removeItem('inforbaxe:celebrate-payment');
  } catch (_) {}
  if (pending) window.setTimeout(celebrarPago, 180);
})();

function duplicarVenta(id) {
  if (!confirm('¿Duplicar esta venta con fecha de hoy?')) return;
  fetch(`/api/ventas/${id}/duplicar`, {method:'POST'})
    .then(r=>r.json()).then(d=>{ if(d.ok) location.reload(); });
}

(() => {
  const cards = [...document.querySelectorAll('[data-sale-swipe]')];
  cards.forEach(card => {
    let startX = 0, startY = 0;
    card.addEventListener('touchstart', event => {
      if (event.target.closest('a,button,form,input,select')) return;
      startX = event.changedTouches[0].clientX;
      startY = event.changedTouches[0].clientY;
    }, { passive: true });
    card.addEventListener('touchend', event => {
      if (!startX && !startY) return;
      const dx = event.changedTouches[0].clientX - startX;
      const dy = event.changedTouches[0].clientY - startY;
      if (Math.abs(dx) > 58 && Math.abs(dx) > Math.abs(dy) * 1.25) {
        if (dx < 0) {
          cards.forEach(other => { if (other !== card) other.classList.remove('is-open'); });
          card.classList.add('is-open');
        } else {
          card.classList.remove('is-open');
        }
      }
      startX = 0; startY = 0;
    }, { passive: true });
  });
  document.addEventListener('touchstart', event => {
    if (!event.target.closest('[data-sale-swipe]')) cards.forEach(card => card.classList.remove('is-open'));
  }, { passive: true });
})();

  document.addEventListener("click", (event) => {
    const button = event.target instanceof Element
      ? event.target.closest("[data-sale-action]")
      : null;
    if (!button) return;
    switch (button.dataset.saleAction) {
      case "mark-paid":
        marcarPagado(button.dataset.saleId, button.dataset.nombre || "");
        break;
      case "duplicate":
        duplicarVenta(button.dataset.saleId);
        break;
      case "close-payment":
        cerrarModal();
        break;
      case "confirm-payment":
        confirmarCobro();
        break;
      default:
        break;
    }
  });

  document.querySelectorAll("form[data-confirm-message]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      if (!confirm(form.dataset.confirmMessage || "¿Continuar?")) event.preventDefault();
    });
  });
})();
