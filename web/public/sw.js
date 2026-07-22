self.addEventListener("push", function (event) {
  if (!event.data) return;
  try {
    const data = event.data.json();
    const title = data.title || "WRIT";
    const options = {
      body: data.body || "",
      icon: data.icon || "/icons/icon-192.png",
      badge: "/icons/alert.png",
      data: { url: data.url || "/notifications" },
      tag: "writ-notif",
      renotify: true,
    };
    event.waitUntil(self.registration.showNotification(title, options));
  } catch (e) {}
});

self.addEventListener("notificationclick", function (event) {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || "/notifications";
  event.waitUntil(
    clients.matchAll({ type: "window", includeUncontrolled: true }).then(function (clientList) {
      for (var i = 0; i < clientList.length; i++) {
        var client = clientList[i];
        if (client.url.includes(self.location.origin) && "focus" in client) {
          client.focus();
          client.navigate(url);
          return;
        }
      }
      if (clients.openWindow) {
        return clients.openWindow(url);
      }
    })
  );
});
