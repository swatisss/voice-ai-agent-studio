// Spec: /ui/app-shell.md, /ui/design-system.md (Layout)
"use client";

import { AudioWaveform, Bot, Headphones, LayoutDashboard, Lightbulb, Menu, Phone, PhoneCall, UserRound, X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, setApiTenant, useEvents } from "@/lib/api";
import { Badge, cx, Select, ToastProvider } from "./ui";

type Tenant = { id: string; name: string };
const TenantCtx = createContext<{ tenant: string; tenants: Tenant[] }>({ tenant: "", tenants: [] });
export const useTenant = () => useContext(TenantCtx);

const NAV = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/agents/", label: "Agents", icon: Bot },
  { href: "/personas/", label: "Personas", icon: UserRound },
  { href: "/test-call/", label: "Test call", icon: PhoneCall },
  { href: "/calls/", label: "Calls", icon: Phone },
  { href: "/console/", label: "Agent console", icon: Headphones, badge: "console" as const },
  { href: "/insights/", label: "Insights", icon: Lightbulb, badge: "insights" as const },
];

const PRODUCT = "Echo Mind";
const CAPTION = "Voice Agent Studio";

/** The business unit is the part of a tenant name after " · " (the whole name when there is none). */
export const unitOf = (name: string) => (name.includes("·") ? name.split("·").slice(1).join("·") : name).trim();

export function Shell({ children }: { children: ReactNode }) {
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [tenant, setTenantState] = useState("");
  const [health, setHealth] = useState<{ providers?: Record<string, boolean> } | null>(null);
  const [waiting, setWaiting] = useState(0);
  const [ready, setReady] = useState(0);
  const [menuOpen, setMenuOpen] = useState(false);
  const path = usePathname();

  const setTenant = useCallback((t: string) => {
    setApiTenant(t);
    try { localStorage.setItem("tenant", t); } catch { /* storage unavailable */ }
    setTenantState(t);
  }, []);

  useEffect(() => {
    api<{ items: Tenant[] }>("/api/tenants").then((r) => {
      setTenants(r.items);
      let saved = "";
      try { saved = localStorage.getItem("tenant") ?? ""; } catch { /* ignore */ }
      setTenant(r.items.some((t) => t.id === saved) ? saved : r.items[0]?.id ?? "");
    }).catch(() => setTenants([]));
    api("/healthz").then(setHealth).catch(() => setHealth(null));
  }, [setTenant]);

  const refreshBadges = useCallback(() => {
    if (!tenant) return;
    api<{ items: unknown[] }>("/api/escalations?status=waiting").then((r) => setWaiting(r.items.length)).catch(() => undefined);
    api<{ items: { ready_for_fix: boolean }[] }>("/api/insights/clusters").then((r) => setReady(r.items.filter((c) => c.ready_for_fix).length)).catch(() => undefined);
  }, [tenant]);
  useEffect(() => { refreshBadges(); }, [refreshBadges]);
  useEvents(["console", "insights"], (e) => {  // UI-02
    if (e.type.startsWith("escalation") || e.type.startsWith("cluster") || e.type.startsWith("proposal")) refreshBadges();
  }, tenant);
  useEffect(() => { setMenuOpen(false); }, [path]);
  useEffect(() => {
    if (!menuOpen) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setMenuOpen(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [menuOpen]);

  const brand = (
    <>
      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-accent text-on-accent"><AudioWaveform size={22} aria-hidden="true" /></span>
      <span className="whitespace-nowrap leading-tight">
        <span className="block text-lg font-semibold">{PRODUCT}</span>
        <span className="block text-xs text-muted">{CAPTION}</span>
      </span>
    </>
  );

  /** The sidebar body, used by the fixed desktop sidebar and by the mobile drawer (ids differ per copy). */
  const sidebar = (label: string, copy: string, onClose?: () => void) => (
    <div className="flex h-full flex-col overflow-y-auto">
      <div className="flex items-center justify-between gap-2 px-5 py-5">
        <Link href="/" className="flex items-center gap-3" aria-label={`${PRODUCT} ${CAPTION} home`}>{brand}</Link>
        {onClose && (
          <button className="rounded-full p-2 hover:bg-accent-soft" onClick={onClose} aria-label="Close menu" autoFocus><X size={22} /></button>
        )}
      </div>
      <nav className="flex-1 space-y-1 px-3" aria-label={label}>
        {NAV.map(({ href, label: text, icon: Icon, badge }) => {
          const active = href === "/" ? path === "/" : path.startsWith(href);
          const count = badge === "console" ? waiting : badge === "insights" ? ready : 0;
          return (
            <Link key={href} href={href} className="nav-link" aria-current={active ? "page" : undefined}>
              <Icon size={20} aria-hidden="true" />
              <span>{text}</span>
              {count > 0 && <Badge className="ml-auto" tone={badge === "console" ? "warn" : "accent"}>{count}</Badge>}
            </Link>
          );
        })}
      </nav>
      <div className="space-y-3 border-t border-line p-4">
        <div>
          <label className="mb-1 block text-xs font-medium text-muted" htmlFor={`business-unit-${copy}`}>Business unit</label>
          <Select id={`business-unit-${copy}`} className="unit-select" value={tenant} onChange={(e) => setTenant(e.target.value)}>
            {tenants.map((t) => <option key={t.id} value={t.id}>{unitOf(t.name)}</option>)}
          </Select>
        </div>
        {health?.providers && (
          <ul className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs text-muted" aria-label="Provider status">
            {Object.entries(health.providers).map(([k, ok]) => (
              <li key={k} className="inline-flex items-center gap-1.5" title={ok ? `${k} configured` : `${k} key missing`}>
                <span className={cx("h-2.5 w-2.5 shrink-0 rounded-full", ok ? "bg-ok" : "bg-line")} aria-hidden="true" />
                <span>{k}{!ok && <span className="sr-only"> key missing</span>}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );

  return (
    <TenantCtx.Provider value={{ tenant, tenants }}>
      <ToastProvider>
        <a href="#main" className="skip-link">Skip to content</a>
        <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 border-r border-line bg-panel md:block">{sidebar("Primary", "side")}</aside>
        <div className="md:pl-64">
          <header className="sticky top-0 z-30 flex items-center justify-between border-b border-line bg-panel px-4 py-2 shadow-[var(--shadow)] md:hidden">
            <Link href="/" className="flex items-center gap-3" aria-label={`${PRODUCT} ${CAPTION} home`}>{brand}</Link>
            <button className="rounded-full p-2 hover:bg-accent-soft" onClick={() => setMenuOpen(true)} aria-label="Menu" aria-expanded={menuOpen}><Menu size={22} /></button>
          </header>
          {menuOpen && (
            <div className="fixed inset-0 z-40 md:hidden" role="dialog" aria-modal="true" aria-label="Menu">
              <div className="absolute inset-0 bg-black/40" onClick={() => setMenuOpen(false)} />
              <aside className="relative h-full w-72 max-w-[85vw] bg-panel shadow-xl">{sidebar("Primary (menu)", "menu", () => setMenuOpen(false))}</aside>
            </div>
          )}
          <main id="main" className="mx-auto w-full max-w-7xl p-4 md:p-6">
            {tenant ? children : <div className="text-sm text-muted">Loading business units… (is the API running?)</div>}
          </main>
        </div>
      </ToastProvider>
    </TenantCtx.Provider>
  );
}
