const VAPID_PUBLIC_KEY = process.env.NEXT_PUBLIC_VAPID_PUBLIC_KEY || "";

function urlBase64ToUint8Array(base64String: string): ArrayBuffer {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const rawData = window.atob(base64);
  const outputArray = new Uint8Array(rawData.length);
  for (let i = 0; i < rawData.length; i++) {
    outputArray[i] = rawData.charCodeAt(i);
  }
  return outputArray.buffer as ArrayBuffer;
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
  if (permission !== "granted") {
    throw new Error(`브라우저 알림 권한이 거부되었습니다 (status: ${permission})`);
  }

  const reg = await navigator.serviceWorker.ready;
  const vapidKey = await getVapidKey();
  const applicationServerKey = urlBase64ToUint8Array(vapidKey);

  let subscription: PushSubscription;
  const existing = await reg.pushManager.getSubscription();
  if (existing) {
    subscription = existing;
  } else {
    subscription = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey,
    });
  }

  const sub = subscription.toJSON();
  const form = new FormData();
  form.append("endpoint", sub.endpoint || "");
  form.append("p256dh", sub.keys?.p256dh || "");
  form.append("auth", sub.keys?.auth || "");

  const ua = navigator.userAgent;
  let deviceName = "알 수 없는 기기";
  if (ua.includes("Android")) deviceName = "Android";
  else if (ua.includes("iPhone") || ua.includes("iPad")) deviceName = "iOS";
  else if (ua.includes("Mac OS")) deviceName = "macOS";
  else if (ua.includes("Windows")) deviceName = "Windows";
  else if (ua.includes("Linux")) deviceName = "Linux";
  if (ua.includes("Chrome") && !ua.includes("Edg")) deviceName += " Chrome";
  else if (ua.includes("Firefox")) deviceName += " Firefox";
  else if (ua.includes("Safari") && !ua.includes("Chrome")) deviceName += " Safari";
  else if (ua.includes("Edg")) deviceName += " Edge";
  form.append("device_name", deviceName);

  const res = await fetch("/api/push/subscribe", {
    method: "POST",
    credentials: "include",
    body: form,
  });
  const body = await res.text().catch(() => "");
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

export async function syncPushPermission(): Promise<void> {
  if (!("Notification" in window) || !("serviceWorker" in navigator) || !("PushManager" in window)) return;
  if (Notification.permission === "denied") {
    const reg = await navigator.serviceWorker.ready;
    const subscription = await reg.pushManager.getSubscription();
    if (subscription) {
      const endpoint = subscription.endpoint;
      await subscription.unsubscribe().catch(() => {});
      const form = new FormData();
      form.append("endpoint", endpoint);
      await fetch("/api/push/unsubscribe", { method: "POST", credentials: "include", body: form }).catch(() => {});
    }
  }
}

export async function isSubscribed(): Promise<boolean> {
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) return false;
  const reg = await navigator.serviceWorker.ready;
  const subscription = await reg.pushManager.getSubscription();
  if (!subscription) return false;
  try {
    const res = await fetch("/api/push/status", { credentials: "include" });
    if (res.ok) {
      const data = await res.json();
      if (!data.subscribed) return false;
    }
  } catch {}
  return true;
}
