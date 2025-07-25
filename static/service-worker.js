self.addEventListener('push', function(event) {
  let data = {};
  if (event.data) {
    data = event.data.json();
  }

  const title = data.title || "Smart Queue";
  const options = {
    body: data.body || "You have a new notification from Smart Queue.",
    //icon: '/static/icons/icon-192.png',       // optional icon path
    //badge: '/static/icons/badge-72.png',      // optional badge path
    vibrate: [200, 100, 200],
    data: {
      url: data.url || '/',                   // page to open on click
      dateOfArrival: Date.now()
    },
    actions: [
      { action: 'open', title: 'Open Token Page' }
    ]
  };

  event.waitUntil(
    self.registration.showNotification(title, options)
  );
});

self.addEventListener('notificationclick', function(event) {
  event.notification.close();

  const targetUrl = event.notification.data?.url || '/';

  event.waitUntil(
    clients.matchAll({ type: "window", includeUncontrolled: true }).then(function(clientList) {
      for (const client of clientList) {
        if (client.url.includes(targetUrl) && 'focus' in client) {
          return client.focus();
        }
      }
      if (clients.openWindow) {
        return clients.openWindow(targetUrl);
      }
    })
  );
});
