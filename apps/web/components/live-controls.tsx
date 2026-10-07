// Spec: /ui/test-call.md (Live controls), /architecture/personas.md, /architecture/turn-detection.md
"use client";

import { useEffect, useRef } from "react";
import { api, ApiError } from "@/lib/api";
import { type TurnDetection, voiceLabel } from "@/lib/voices";
import { TurnDetectionEditor } from "./voice-settings";
import { Card, Field, Select, useToast } from "./ui";

type Persona = { id: string; name: string; description?: string; voice: string; speed: number };

/**
 * Persona and turn-detection controls. Before a call they are call-start overrides (the page sends them with
 * POST /api/calls); during a call every change is applied immediately with PATCH /api/calls/{id}/live (UI-23).
 */
export function LiveControlsCard({ callId, active, voiceCall, personas, personaId, onPersona, turn, onTurn }: {
  callId: string | null; active: boolean; voiceCall: boolean; personas: Persona[]; personaId: string;
  onPersona: (id: string) => void; turn: TurnDetection; onTurn: (t: TurnDetection) => void;
}) {
  const toast = useToast();
  const appliedPersona = useRef(personaId);
  const appliedTurn = useRef(JSON.stringify(turn));
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // a new call starts with whatever is selected: nothing to patch
  useEffect(() => { appliedPersona.current = personaId; appliedTurn.current = JSON.stringify(turn); }, [callId]);  // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!callId || !active || personaId === appliedPersona.current) return;
    appliedPersona.current = personaId;
    api(`/api/calls/${callId}/live`, { method: "PATCH", json: { persona_id: personaId } }).catch((e) => toast((e as ApiError).detail, "bad"));
  }, [personaId, callId, active]);  // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!callId || !active || !voiceCall || JSON.stringify(turn) === appliedTurn.current) return;
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => {  // debounced 300 ms while sliders move
      appliedTurn.current = JSON.stringify(turn);
      api(`/api/calls/${callId}/live`, { method: "PATCH", json: { turn_detection: turn } }).catch((e) => toast((e as ApiError).detail, "bad"));
    }, 300);
    return () => { if (timer.current) clearTimeout(timer.current); };
  }, [turn, callId, active, voiceCall]);  // eslint-disable-line react-hooks/exhaustive-deps

  const chosen = personas.find((p) => p.id === personaId);
  return (
    <Card title="Live controls">
      <div className="space-y-4">
        <Field label="Persona" hint={chosen ? `${voiceLabel(chosen.voice)} · speed ${chosen.speed}×` : "The agent's own persona"}>
          <Select value={personaId} onChange={(e) => onPersona(e.target.value)}>
            <option value="">Agent default</option>
            {personas.map((p) => <option key={p.id} value={p.id}>{p.name}{p.description ? ` — ${p.description}` : ""}</option>)}
          </Select>
        </Field>
        <div className={voiceCall ? "" : "pointer-events-none opacity-60"} aria-disabled={!voiceCall}>
          <div className="mb-2 text-sm font-semibold">Turn detection</div>
          <TurnDetectionEditor value={turn} onChange={onTurn} compact />
          {!voiceCall && <div className="mt-2 text-xs text-muted">Turn detection applies to voice calls.</div>}
        </div>
        {callId && active && <div className="text-xs text-muted">Changes apply to the running call straight away.</div>}
      </div>
    </Card>
  );
}
