// Spec: /ui/app-shell.md (Sign-in), /architecture/studio-auth.md
"use client";

import { createContext, useContext } from "react";

export type StudioUser = { email: string; name: string; role: "admin" | "reviewer" };
export type Me = { enabled: boolean; user: StudioUser | null };

export const MeCtx = createContext<Me>({ enabled: false, user: null });

/** The signed-in user; with sign-in off the API reports the built-in admin "Studio". */
export const useMe = () => useContext(MeCtx);

/** Reviewers see admin-only controls disabled with "Admin only" (UI-70). */
export const useIsAdmin = () => useMe().user?.role === "admin";

export const ADMIN_ONLY_HINT = "Admin only";

export function loginUrl(): string {
  const here = typeof window === "undefined" ? "/" : window.location.pathname + window.location.search;
  return `/login/?next=${encodeURIComponent(here)}`;
}
