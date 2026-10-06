// Spec: /ui/app-shell.md
"use client";

import { Bot, Headphones, LayoutDashboard, Lightbulb, Menu, Phone, PhoneCall } from "lucide-react";
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
  { href: "/test-call/", label: "Test call", icon: PhoneCall },
  { href: "/calls/", label: "Calls", icon: Phone },
  { href: "/console/", label: "Agent console", icon: Headphones, badge: "console" as const },
  { href: "/insights/", label: "Insights", icon: Lightbulb, badge: "insights" as const },
];

export function Shell({ children }: { children: ReactNode }) {
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [tenant, setTenantState] = useState("");
  const [health, setHealth] = useState<{ providers?: Record<string, boolean> } | null>(null);
  const [waiting, setWaiting] = useState(0);
  const [ready, setReady] = useState(0);
  const [navOpen, setNavOpen] = useState(false);
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

  return (
    <TenantCtx.Provider value={{ tenant, tenants }}>
      <ToastProvider>
        <div className="flex min-h-screen">
          <aside className={cx("fixed inset-y-0 left-0 z-40 w-56 border-r border-line bg-panel p-3 transition md:static md:translate-x-0", navOpen ? "translate-x-0" : "-translate-x-full")}>
            <div className="mb-4 px-2 pt-1">
              <div className="text-sm font-semibold">Voice Agent Studio</div>
              <div className="text-xs text-muted">resolve · escalate · learn</div>
            </div>
            <nav className="space-y-0.5">
              {NAV.map(({ href, label, icon: Icon, badge }) => {
                const active = href === "/" ? path === "/" : path.startsWith(href);
                const count = badge === "console" ? waiting : badge === "insights" ? ready : 0;
                return (
                  <Link key={href} href={href} onClick={() => setNavOpen(false)}
                    className={cx("flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm", active ? "bg-accent-soft text-accent font-medium" : "text-muted hover:bg-neutral-soft hover:text-fg")}>
                    <Icon size={16} />
                    <span className="flex-1">{label}</span>
                    {count > 0 && <Badge tone={badge === "console" ? "warn" : "accent"}>{count}</Badge>}
                  </Link>
                );
              })}
            </nav>
          </aside>
          <div className="flex min-w-0 flex-1 flex-col">
            <header className="sticky top-0 z-30 flex items-center gap-3 border-b border-line bg-panel/90 px-4 py-2 backdrop-blur">
              <button className="md:hidden" onClick={() => setNavOpen(!navOpen)} aria-label="Menu"><Menu size={18} /></button>
              <Select className="max-w-xs" value={tenant} onChange={(e) => setTenant(e.target.value)} aria-label="Tenant">
                {tenants.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
              </Select>
              <div className="ml-auto flex items-center gap-3 text-xs text-muted">
                {health?.providers && Object.entries(health.providers).map(([k, ok]) => (
                  <span key={k} className="inline-flex items-center gap-1" title={ok ? `${k} configured` : `${k} key missing`}>
                    <span className={cx("h-2 w-2 rounded-full", ok ? "bg-ok" : "bg-line")} />{k}
                  </span>
                ))}
              </div>
            </header>
            <main className="mx-auto w-full max-w-7xl flex-1 p-4 md:p-6">{tenant ? children : <div className="text-sm text-muted">Loading tenants… (is the API running?)</div>}</main>
          </div>
        </div>
      </ToastProvider>
    </TenantCtx.Provider>
  );
}
