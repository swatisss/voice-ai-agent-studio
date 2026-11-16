// Spec: /architecture/external-chat-app.md (POST /api/chat)
import { guarded } from "@/lib/route.ts";
import { start } from "@/lib/platform.ts";

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  const body = await request.json().catch(() => ({}));
  const message = typeof body?.message === "string" ? body.message.slice(0, 2000) : undefined;
  return guarded((cfg) => start(cfg, message));
}
