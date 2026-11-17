// Spec: /architecture/external-chat-app.md (POST /api/chat/{id}/end)
import { guarded } from "@/lib/route.ts";
import { end } from "@/lib/platform.ts";

export const dynamic = "force-dynamic";

export async function POST(_request: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  return guarded(async (cfg) => { await end(cfg, id); return { ok: true }; });
}
