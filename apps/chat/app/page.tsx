// Spec: /ui/chat-app.md
import { Chat } from "@/components/chat";
import { readConfig } from "@/lib/platform.ts";

export const dynamic = "force-dynamic";

export default function Page() {
  const cfg = readConfig();  // the key never leaves the server: only whether it is set, and the brand name
  return <Chat brand={cfg?.brand ?? (process.env.CHAT_BRAND_NAME || "Northgate Health")} configured={cfg !== null} />;
}
