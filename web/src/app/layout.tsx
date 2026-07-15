import type { Metadata } from "next";
import "./globals.css";
import { AuthProvider } from "@/lib/auth";
import Sidebar from "@/components/Sidebar";
import RightSidebar from "@/components/RightSidebar";
import MobileNav from "@/components/MobileNav";
import KeyboardShortcuts from "@/components/KeyboardShortcuts";
import NotifSound from "@/components/NotifSound";
import ErrorBoundary from "@/components/ErrorBoundary";
import DeactivatedRedirect from "@/components/DeactivatedRedirect";

const siteUrl = process.env.BASE_URL || "http://localhost:3000";
const API_HOST = process.env.API_HOST || "http://localhost:8000";

const DEFAULT_TITLE = "WRIT";
const DEFAULT_DESCRIPTION = "쓰는 이들을 위한 SNS, WRIT";

async function getServerInfo(): Promise<{ name: string; description: string }> {
  try {
    const res = await fetch(`${API_HOST}/api/server-info`, { next: { revalidate: 3600 } });
    if (!res.ok) return { name: DEFAULT_TITLE, description: DEFAULT_DESCRIPTION };
    const data = await res.json();
    return {
      name: data.name || DEFAULT_TITLE,
      description: data.description || DEFAULT_DESCRIPTION,
    };
  } catch {
    return { name: DEFAULT_TITLE, description: DEFAULT_DESCRIPTION };
  }
}

export async function generateMetadata(): Promise<Metadata> {
  const { name, description } = await getServerInfo();
  return {
    metadataBase: new URL(siteUrl),
    title: name,
    description,
    icons: { icon: "/favicon.ico", apple: "/icons/icon-192.png" },
    manifest: "/api/pwa/manifest",
    appleWebApp: { capable: true, title: name, statusBarStyle: "black-translucent" },
    other: { "mobile-web-app-capable": "yes" },
    openGraph: {
      title: name,
      description,
      type: "website",
      images: [{ url: "/icons/icon-512.png" }],
    },
    twitter: {
      card: "summary",
      title: name,
      description,
      images: ["/icons/icon-512.png"],
    },
  };
}

export const viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: "#689f38",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko" suppressHydrationWarning>
      <body suppressHydrationWarning>
        <AuthProvider>
          <div className="layout" id="app-layout">
            <Sidebar />
            <main className="main-content"><ErrorBoundary>{children}</ErrorBoundary></main>
            <RightSidebar />
          </div>
          <MobileNav />
          <KeyboardShortcuts />
          <NotifSound />
          <DeactivatedRedirect />
        </AuthProvider>
        <script dangerouslySetInnerHTML={{
          __html: `
            if ('serviceWorker' in navigator) {
              navigator.serviceWorker.register('/sw.js').catch(function() {});
            }
            window.__toggleTheme = function() {
              document.body.classList.toggle('dark-theme');
              localStorage.setItem('theme', document.body.classList.contains('dark-theme') ? 'dark' : 'light');
            };
            document.addEventListener('click', function(e) {
              var a = e.target.closest('a');
              if (a && a.href && !a.href.startsWith('/') && !a.href.startsWith(window.location.origin)) {
                e.preventDefault();
                window.open(a.href, '_blank', 'noopener');
              }
            });
            (function() {
              var startY = 0;
              var pulling = false;
              var pullEl = document.querySelector('.main-content');
              document.addEventListener('touchstart', function(e) {
                if (!pullEl || pullEl.scrollTop > 0) return;
                startY = e.touches[0].clientY;
                pulling = true;
              }, { passive: true });
              document.addEventListener('touchmove', function(e) {
                if (!pulling) return;
                var diff = e.touches[0].clientY - startY;
                if (diff > 0) pullEl.style.transform = 'translateY(' + Math.min(diff * 0.4, 60) + 'px)';
                if (diff > 170) {
                  pulling = false;
                  pullEl.style.transform = '';
                  window.location.reload();
                }
              }, { passive: true });
              document.addEventListener('touchend', function() {
                if (pullEl) pullEl.style.transform = '';
                pulling = false;
              }, { passive: true });
            })();
          `
        }} />
      </body>
    </html>
  );
}
