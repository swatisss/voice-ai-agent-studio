// Spec: /ui/app-shell.md, /ui/design-system.md (Layout)
"use client";

import { Bot, Headphones, HeartPulse, LayoutDashboard, Lightbulb, Menu, Phone, PhoneCall, UserRound, X } from "lucide-react";
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

/** The business unit's brand is the part of its name before " · ". */
export const brandOf = (name: string) => (name.split("·")[0] || name).trim();

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

  const brand = brandOf(tenants.find((t) => t.id === tenant)?.name ?? "Voice Agent Studio");
  // compact: between 768 and 1279 px only the active item keeps its label so the bar fits (design-system: Navigation)
  const renderItems = (compact: boolean) => NAV.map(({ href, label, icon: Icon, badge }) => {
    const active = href === "/" ? path === "/" : path.startsWith(href);
    const count = badge === "console" ? waiting : badge === "insights" ? ready : 0;
    return (
      <Link key={href} href={href} className="nav-link" aria-current={active ? "page" : undefined} aria-label={compact ? label : undefined} title={compact ? label : undefined}>
        <Icon size={18} aria-hidden="true" />
        <span className={compact && !active ? "hidden xl:inline" : undefined}>{label}</span>
        {count > 0 && <Badge tone={badge === "console" ? "warn" : "accent"}>{count}</Badge>}
      </Link>
    );
  });

  return (
    <TenantCtx.Provider value={{ tenant, tenants }}>
      <ToastProvider>
        <a href="#main" className="skip-link">Skip to content</a>
        <header className="sticky top-0 z-30 border-b border-line bg-panel shadow-[var(--shadow)]">
          <div className="mx-auto flex max-w-7xl items-center gap-4 px-4 md:px-6 xl:gap-6">
            <Link href="/" className="flex items-center gap-3 py-3" aria-label={`${brand} home`}>
              <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent text-on-accent"><HeartPulse size={22} aria-hidden="true" /></span>
              <span className="whitespace-nowrap leading-tight">
                <span className="block text-lg font-semibold">{brand}</span>
                <span className="block text-xs text-muted">Voice Agent Studio</span>
              </span>
            </Link>
            <nav className="hidden items-center gap-3 md:flex xl:gap-5" aria-label="Primary">{renderItems(true)}</nav>
            <div className="ml-auto flex items-center gap-3">
              <label className="sr-only" htmlFor="business-unit">Business unit</label>
              <Select id="business-unit" className="max-w-[13rem]" value={tenant} onChange={(e) => setTenant(e.target.value)}>
                {tenants.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
              </Select>
              <div className="hidden items-center gap-2 text-xs text-muted lg:flex">
                {health?.providers && Object.entries(health.providers).map(([k, ok]) => (
                  <span key={k} className="inline-flex items-center gap-1" title={ok ? `${k} configured` : `${k} key missing`}>
                    <span className={cx("h-2.5 w-2.5 rounded-full", ok ? "bg-ok" : "bg-line")} /><span className="sr-only 2xl:not-sr-only">{k}</span>
                  </span>
                ))}
              </div>
              <button className="rounded-full p-2 hover:bg-accent-soft md:hidden" onClick={() => setMenuOpen(!menuOpen)} aria-label="Menu" aria-expanded={menuOpen}>
                {menuOpen ? <X size={22} /> : <Menu size={22} />}
              </button>
            </div>
          </div>
          {menuOpen && <nav className="flex flex-col gap-1 border-t border-line px-4 pb-3 md:hidden" aria-label="Primary (menu)">{renderItems(false)}</nav>}
        </header>
        <main id="main" className="mx-auto w-full max-w-7xl p-4 md:p-6">
          {tenant ? children : <div className="text-sm text-muted">Loading business units… (is the API running?)</div>}
        </main>
      </ToastProvider>
    </TenantCtx.Provider>
  );
}
