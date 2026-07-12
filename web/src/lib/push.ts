const VAPID_PUBLIC_KEY = process.env.NEXT_PUBLIC_VAPID_PUBLIC_KEY || "";

function urlBase64ToUint8Array(base64String: string): Uint8Array {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const rawData = window.atob(base64);
  const outputArray = new Uint8Array(rawData.length);
  for (let i = 0; i < rawData.length; i++) {
    outputArray[i] = rawData.charCodeAt(i);
  }
  return outputArray;
}

async function getVapidKey(): Promise<string> {
  if (VAPID_PUBLIC_KEY) return VAPID_PUBLIC_KEY;
  const res = await fetch("/api/push/vapid-public-key", { credentials: "include" });
  if (!res.ok) throw new Error("VAPID key not available");
  const data = await res.json();
  return data.publicKey;
}

export async function isPushSupported(): Promise<boolean> {
  return "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
}

export async function getPermissionState(): Promise<NotificationPermission> {
  if (!("Notification" in window)) return "denied";
  return Notification.permission;
}

export async function subscribePush(): Promise<boolean> {
  const permission = await Notification.requestPermission();
  if (permission !== "granted") return false;

  const reg = await navigator.serviceWorker.ready;
  const vapidKey = await getVapidKey();
  const applicationServerKey = urlBase64ToUint8Array(vapidKey);

  const subscription = await reg.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey,
  });

  const sub = subscription.toJSON();
  const form = new FormData();
  form.append("endpoint", sub.endpoint || "");
  form.append("p256dh", sub.keys?.p256dh || "");
  form.append("auth", sub.keys?.auth || "");

  const res = await fetch("/api/push/subscribe", {
    method: "POST",
    credentials: "include",
    body: form,
  });
  if (!res.ok) throw new Error("Failed to save subscription");
  return true;
}

export async function unsubscribePush(): Promise<boolean> {
  const reg = await navigator.serviceWorker.ready;
  const subscription = await reg.pushManager.getSubscription();
  if (!subscription) return true;

  const endpoint = subscription.endpoint;
  await subscription.unsubscribe();

  const form = new FormData();
  form.append("endpoint", endpoint);
  await fetch("/api/push/unsubscribe", {
    method: "POST",
    credentials: "include",
    body: form,
  });
  return true;
}

export async function isSubscribed(): Promise<boolean> {
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) return false;
  const reg = await navigator.serviceWorker.ready;
  const subscription = await reg.pushManager.getSubscription();
  return subscription !== null;
}
