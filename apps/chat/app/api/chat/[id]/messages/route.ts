// Spec: /architecture/external-chat-app.md (messages routes)
import { NextResponse } from "next/server";
import { guarded } from "@/lib/route.ts";
import { poll, send } from "@/lib/platform.ts";

export const dynamic = "force-dynamic";

export async function GET(request: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const cursor = new URL(request.url).searchParams.get("cursor");
  return guarded((cfg) => poll(cfg, id, cursor));
}

export async function POST(request: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const body = await request.json().catch(() => ({}));
  const text = typeof body?.text === "string" ? body.text.trim() : "";
  if (!text || text.length > 2000) return NextResponse.json({ error: "invalid_message", detail: "Type a message of up to 2000 characters." }, { status: 422 });
  const cursor = typeof body?.cursor === "string" ? body.cursor : null;
  return guarded((cfg) => send(cfg, id, text, cursor));
}
