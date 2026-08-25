"use client";
import dynamic from "next/dynamic";
import Sidebar from "@/components/Sidebar";
import NotifSound from "@/components/NotifSound";
import AnnouncementToast from "@/components/AnnouncementToast";
import DeactivatedRedirect from "@/components/DeactivatedRedirect";
import CsrfInit from "@/components/CsrfInit";
import ScrollRestoration from "@/components/ScrollRestoration";

const RightSidebar = dynamic(() => import("@/components/RightSidebar"), { loading: () => null, ssr: false });
const MobileNav = dynamic(() => import("@/components/MobileNav"), { loading: () => null, ssr: false });
const KeyboardShortcuts = dynamic(() => import("@/components/KeyboardShortcuts"), { loading: () => null, ssr: false });

export default function ClientProviders({ children }: { children: React.ReactNode }) {
  return (
    <div className="layout" id="app-layout">
      <Sidebar />
      <main className="main-content">{children}</main>
      <RightSidebar />
      <MobileNav />
      <KeyboardShortcuts />
      <ScrollRestoration />
      <NotifSound />
      <AnnouncementToast />
      <DeactivatedRedirect />
      <CsrfInit />
    </div>
  );
}
