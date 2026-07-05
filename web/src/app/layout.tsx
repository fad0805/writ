import type { Metadata } from "next";
import "./globals.css";
import { AuthProvider } from "@/lib/auth";
import Sidebar from "@/components/Sidebar";
import RightSidebar from "@/components/RightSidebar";
import KeyboardShortcuts from "@/components/KeyboardShortcuts";

export const metadata: Metadata = {
  title: "WRIT",
  description: "SNS for writers",
  icons: { icon: "/favicon.ico" },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko" suppressHydrationWarning>
      <body>
        <AuthProvider>
          <div className="layout" id="app-layout">
            <Sidebar />
            <main className="main-content">{children}</main>
            <RightSidebar />
          </div>
          <KeyboardShortcuts />
        </AuthProvider>
        <script dangerouslySetInnerHTML={{
          __html: `
            if (localStorage.getItem('theme') === 'dark') {
              document.body.classList.add('dark-theme');
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
