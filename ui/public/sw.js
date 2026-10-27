const CACHE_VERSION = "fuel-v2";
const STATIC_CACHE = `${CACHE_VERSION}-static`;
const ALL_CACHES = [STATIC_CACHE];

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(STATIC_CACHE).then((c) => c.addAll(["/", "/index.html"])).catch(() => {})
  );
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => !ALL_CACHES.includes(k)).map((k) => caches.delete(k)))
    ).then(() => clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const { request } = e;
  if (request.method !== "GET") return;

  const url = new URL(request.url);

  // Only handle our own origin. Cross-origin requests (the backend API,
  // Firebase, Google) pass straight through: API responses are per-user and
  // Cache Storage is keyed by URL alone, so caching them could show one
  // user's data to the next person on a shared device.
  if (url.origin !== self.location.origin) return;

  // Static assets with content hash in URL: cache-first
  if (url.pathname.startsWith("/assets/")) {
    e.respondWith(
      caches.match(request).then((cached) => {
        if (cached) return cached;
        return fetch(request).then((res) => {
          const copy = res.clone(); // clone before the page consumes the body
          caches.open(STATIC_CACHE).then((c) => c.put(request, copy));
          return res;
        });
      })
    );
    return;
  }

  // App shell: network-first, fall back to cached index.html
  e.respondWith(
    fetch(request)
      .then((res) => {
        const copy = res.clone(); // clone before the page consumes the body
        caches.open(STATIC_CACHE).then((c) => c.put(request, copy));
        return res;
      })
      .catch(() => caches.match(request).then((cached) => cached || caches.match("/index.html")))
  );
});

self.addEventListener("push", (e) => {
  let title = "Fuel";
  let body = "Check your nutrition and activity balance.";
  let url = "/";

  if (e.data) {
    try {
      const data = e.data.json();
      title = data.title || title;
      body = data.body || body;
      url = data.url || url;
    } catch {
      body = e.data.text() || body;
    }
  }

  e.waitUntil(
    self.registration.showNotification(title, {
      body,
      icon: "/icons/icon-192.png",
      badge: "/icons/icon-192.png",
      tag: "fuel-nudge",
      data: { url },
    })
  );
});

self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  e.waitUntil(
    clients.matchAll({ type: "window", includeUncontrolled: true }).then((cs) => {
      const existing = cs.find((c) => c.url.includes(self.location.origin));
      if (existing) return existing.focus();
      return clients.openWindow(e.notification.data?.url || "/");
    })
  );
});
