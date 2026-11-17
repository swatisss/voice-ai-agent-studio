// Spec: /ui/chat-app.md
import type { Metadata, Viewport } from "next";
import "./globals.css";

export const viewport: Viewport = { width: "device-width", initialScale: 1 };

export async function generateMetadata(): Promise<Metadata> {
  const brand = process.env.CHAT_BRAND_NAME || "Northgate Health";
  return { title: `${brand} member support`, description: `Chat with ${brand} member support` };
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
