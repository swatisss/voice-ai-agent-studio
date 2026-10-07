// Spec: /ui/app-shell.md
import type { Metadata } from "next";
import { Shell } from "@/components/shell";
import "./globals.css";

export const metadata: Metadata = {
  title: "Echo Mind Voice Agent Studio",
  description: "Multi-tenant voice AI agents that resolve, escalate with context, and learn.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Shell>{children}</Shell>
      </body>
    </html>
  );
}
