// Only public application assets are eligible for offline storage.
const CACHE = 'ledger-public-v3-ui';
const ASSETS = ['/offline', '/static/css/main.css', '/static/js/main.js',
  '/static/js/utils.js', '/static/js/identity.js'];
self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(ASSETS)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(keys
    .filter(key => key.startsWith('ledger-') && key !== CACHE)
    .map(key => caches.delete(key)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', event => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== 'GET' || url.origin !== self.location.origin) return;
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(caches.match(request).then(cached => cached || fetch(request)));
  } else if (request.mode === 'navigate') {
    event.respondWith(fetch(request).catch(async () =>
      (await caches.match('/offline')) || new Response('Offline', {status: 503})));
  }
});
