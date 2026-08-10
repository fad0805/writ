self.addEventListener("push", function (event) {
  if (!event.data) return;
  try {
    if (Notification.permission === "denied") return;
    event.waitUntil(
      clients.matchAll({ type: "window", includeUncontrolled: true }).then(function (clientList) {
        for (var i = 0; i < clientList.length; i++) {
          if (clientList[i].visibilityState === "visible") return;
        }
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
        return self.registration.showNotification(title, options);
      })
    );
  } catch (e) {}
});

self.addEventListener("notificationclick", function (event) {
  event.notification.close();
  const origin = self.location.origin;
  const dataUrl = (event.notification.data && event.notification.data.url) || "/notifications";
  let target;
  try {
    const parsed = new URL(dataUrl, origin);
    target = parsed.origin === origin ? parsed.href : origin + "/notifications";
  } catch (e) {
    target = origin + "/notifications";
  }
  event.waitUntil(
    clients.matchAll({ type: "window", includeUncontrolled: true }).then(function (clientList) {
      for (var i = 0; i < clientList.length; i++) {
        var client = clientList[i];
        var clientOrigin = "";
        try {
          clientOrigin = new URL(client.url).origin;
        } catch (e) {}
        if (clientOrigin === origin && "focus" in client) {
          client.focus();
          client.navigate(target);
          return;
        }
      }
      if (clients.openWindow) {
        return clients.openWindow(target);
      }
    })
  );
});
