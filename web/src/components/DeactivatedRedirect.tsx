"use client";
import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";

export default function DeactivatedRedirect() {
  const { user, loading } = useAuth();
  const pathname = usePathname();
  const router = useRouter();

  useEffect(() => {
    if (loading || !user) return;
    const isDeactivated = (user as any)?.is_deactivated;
    const isOnDeactivatedPage = pathname === "/users/settings/deactivated";
    if (isDeactivated && !isOnDeactivatedPage) {
      router.replace("/users/settings/deactivated");
    }
  }, [user, loading, pathname, router]);

  return null;
}
