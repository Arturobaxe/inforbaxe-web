const CACHE_NAME = 'inforbaxe-v1';
const ASSETS = [
  '/',
  '/index.html',
  '/static/logo-192.png',
  '/static/logo-512.png',
  // Añade aquí tus CSS, JS, etc.
];

// Instalación: guarda los archivos en caché
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(ASSETS))
  );
  self.skipWaiting();
});

// Activación: elimina cachés antiguas
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys.filter(key => key !== CACHE_NAME).map(key => caches.delete(key))
      )
    )
  );
  self.clients.claim();
});

// Fetch: sirve desde caché, si falla va a la red
self.addEventListener('fetch', event => {
  event.respondWith(
    caches.match(event.request).then(cached => cached || fetch(event.request))
  );
});
