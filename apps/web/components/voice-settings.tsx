// Spec: /ui/agent-builder.md (Voice tab), /ui/test-call.md (Live controls), /architecture/turn-detection.md
"use client";

import { type TurnDetection } from "@/lib/voices";
import { cx } from "./ui";

function Slider({ label, value, min, max, step, unit, onChange, hint }: {
  label: string; value: number; min: number; max: number; step: number; unit: string; onChange: (v: number) => void; hint?: string;
}) {
  const id = `slider-${label.replace(/\s+/g, "-").toLowerCase()}`;
  return (
    <div>
      <div className="flex items-baseline justify-between">
        <label htmlFor={id} className="text-sm font-medium">{label}</label>
        <span className="text-sm font-semibold text-accent tabular-nums">{value} {unit}</span>
      </div>
      <input id={id} type="range" className="mt-1 w-full accent-[var(--accent)]" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} />
      {hint && <div className="text-xs text-muted">{hint}</div>}
    </div>
  );
}

const MODES = [
  { id: "vad" as const, title: "Normal detection", text: "Ends the turn after a pause in speech. Fast and predictable." },
  { id: "semantic" as const, title: "Semantic detection", text: "After the pause, also checks whether the caller has finished, and waits when they are mid-thought or dictating a number." },
];

/** Turn-detection editor used by the builder's Voice tab (UI-22) and the Test call live controls (UI-23). */
export function TurnDetectionEditor({ value, onChange, compact = false }: { value: TurnDetection; onChange: (v: TurnDetection) => void; compact?: boolean }) {
  const set = (patch: Partial<TurnDetection>) => onChange({ ...value, ...patch });
  return (
    <div className="space-y-4">
      <div role="radiogroup" aria-label="Turn detection mode" className={cx("grid gap-2", compact ? "grid-cols-2" : "md:grid-cols-2")}>
        {MODES.map((m) => (
          <button key={m.id} type="button" role="radio" aria-checked={value.mode === m.id} onClick={() => set({ mode: m.id })}
            className={cx("rounded-2xl border-[1.5px] p-3 text-left transition", value.mode === m.id ? "border-accent bg-accent-soft" : "border-line bg-panel hover:bg-neutral-soft")}>
            <div className="text-sm font-semibold">{m.title}</div>
            {!compact && <div className="mt-1 text-xs text-muted">{m.text}</div>}
          </button>
        ))}
      </div>
      <Slider label="Silence before the agent replies" value={value.min_silence_ms} min={200} max={2000} step={50} unit="ms" onChange={(v) => set({ min_silence_ms: v })}
        hint={compact ? undefined : "Shorter feels snappier; longer avoids cutting callers off."} />
      {value.mode === "semantic" && (
        <>
          <Slider label="Extra wait when the caller seems unfinished" value={value.max_extra_wait_ms} min={0} max={4000} step={100} unit="ms" onChange={(v) => set({ max_extra_wait_ms: v })}
            hint={compact ? undefined : "0 behaves like normal detection."} />
          <fieldset>
            <legend className="text-sm font-medium">How to judge "finished?"</legend>
            <div className="mt-1 flex flex-wrap gap-2">
              {([["heuristic", "Local rules (instant, free)"], ["llm", "LLM check (adds a small model call)"]] as const).map(([id, label]) => (
                <label key={id} className={cx("flex cursor-pointer items-center gap-2 rounded-full border-[1.5px] px-3 py-1.5 text-sm", value.evaluator === id ? "border-accent bg-accent-soft" : "border-line")}>
                  <input type="radio" name="evaluator" className="accent-[var(--accent)]" checked={value.evaluator === id} onChange={() => set({ evaluator: id })} />{label}
                </label>
              ))}
            </div>
          </fieldset>
        </>
      )}
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" className="h-4 w-4 accent-[var(--accent)]" checked={value.allow_interruptions} onChange={(e) => set({ allow_interruptions: e.target.checked })} />
        Allow the caller to interrupt the agent
      </label>
    </div>
  );
}
