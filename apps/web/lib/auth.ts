// Spec: /ui/app-shell.md (Sign-in), /architecture/studio-auth.md
"use client";

import { createContext, useContext } from "react";

export type StudioUser = { email: string; name: string; role: "admin" | "reviewer" | "specialist"; tenant_id?: string };
export type Me = { enabled: boolean; user: StudioUser | null };

export const MeCtx = createContext<Me>({ enabled: false, user: null });

/** The signed-in user; with sign-in off the API reports the built-in admin "Studio". */
export const useMe = () => useContext(MeCtx);

/** Reviewers see admin-only controls disabled with "Admin only" (UI-70). */
export const useIsAdmin = () => useMe().user?.role === "admin";

/** The Agent Desk specialist (UI-77): a five-item workspace, read-only apart from the console and pattern comments. */
export const useIsSpecialist = () => useMe().user?.role === "specialist";

export const ROLE_LABEL: Record<StudioUser["role"], string> = { admin: "Admin", reviewer: "Reviewer", specialist: "Agent Desk" };

/** Where each role lands after signing in. */
export const homeFor = (role?: StudioUser["role"]) => (role === "specialist" ? "/console/" : "/");

/** Paths a specialist may open; anything else goes back to the console with a toast (UI-77). */
export const SPECIALIST_PATHS = ["/console", "/calls", "/patterns", "/knowledge", "/agents/view", "/members/memory"];
export const specialistMayOpen = (path: string) => SPECIALIST_PATHS.some((p) => path === p || path.startsWith(`${p}/`));

export const ADMIN_ONLY_HINT = "Admin only";

export function loginUrl(): string {
  const here = typeof window === "undefined" ? "/" : window.location.pathname + window.location.search;
  return `/login/?next=${encodeURIComponent(here)}`;
}
