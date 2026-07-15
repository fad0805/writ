"use client";
import { createContext, useContext, useState, useEffect, ReactNode } from "react";
import { api, User } from "./api";

interface AuthContext {
  user: User | null;
  loading: boolean;
  refresh: () => Promise<void>;
}

const AuthCtx = createContext<AuthContext>({ user: null, loading: true, refresh: async () => {} });

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = async () => {
    try {
      const u = await api.me();
      setUser(u);
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
  }, []);

  return <AuthCtx.Provider value={{ user, loading, refresh }}>{children}</AuthCtx.Provider>;
}

export const useAuth = () => useContext(AuthCtx);
