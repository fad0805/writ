import type { Metadata } from "next";
import "./globals.css";
import { AuthProvider } from "@/lib/auth";
import Sidebar from "@/components/Sidebar";
import RightSidebar from "@/components/RightSidebar";
import KeyboardShortcuts from "@/components/KeyboardShortcuts";
import NotifSound from "@/components/NotifSound";
import ErrorBoundary from "@/components/ErrorBoundary";
import DeactivatedRedirect from "@/components/DeactivatedRedirect";

export const metadata: Metadata = {
  title: "WRIT",
  description: "SNS for writers",
  icons: { icon: "/favicon.ico", apple: "/icons/icon-192.png" },
  manifest: "/api/pwa/manifest",
  appleWebApp: { capable: true, title: "WRIT", statusBarStyle: "black-translucent" },
  other: { "mobile-web-app-capable": "yes" },
  openGraph: {
    title: "WRIT",
    description: "SNS for writers",
    type: "website",
    images: [{ url: "/icons/icon-512.png" }],
  },
  twitter: {
    card: "summary",
    title: "WRIT",
    description: "SNS for writers",
    images: ["/icons/icon-512.png"],
  },
};

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
          <KeyboardShortcuts />
          <NotifSound />
          <DeactivatedRedirect />
        </AuthProvider>
        <script dangerouslySetInnerHTML={{
          __html: `
            if ('serviceWorker' in navigator) {
              navigator.serviceWorker.getRegistrations().then(function(regs) {
                for (var r of regs) r.unregister();
              });
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
          `
        }} />
      </body>
    </html>
  );
}
