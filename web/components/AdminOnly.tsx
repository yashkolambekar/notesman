"use client";

import { useAuth } from "./AuthProvider";
import { isAdmin } from "@/lib/auth";

export default function AdminOnly({ children }: { children: React.ReactNode }) {
  const { user } = useAuth();
  return isAdmin(user) ? <>{children}</> : null;
}
