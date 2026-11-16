const CACHE_NAME = 'inforbaxe-static-v2';
const ASSETS = [
  '/static/logo-192.png',
  '/static/logo-512.png',
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(ASSETS))
  );
  self.skipWaiting();
});

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

self.addEventListener('fetch', event => {
  const request = event.request;
  const url = new URL(request.url);

  // Never cache authenticated pages, navigation, forms, APIs or cross-origin requests.
  if (
    request.method !== 'GET' ||
    url.origin !== self.location.origin ||
    request.mode === 'navigate' ||
    !url.pathname.startsWith('/static/')
  ) {
    return;
  }

  event.respondWith(
    caches.match(request).then(cached => cached || fetch(request))
  );
});
