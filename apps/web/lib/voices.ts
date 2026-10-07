// Spec: /ui/personas.md (voice select), /architecture/personas.md
export const VOICES: { id: string; label: string }[] = [
  { id: "aura-2-thalia-en", label: "Thalia (female)" },
  { id: "aura-2-andromeda-en", label: "Andromeda (female)" },
  { id: "aura-2-helena-en", label: "Helena (female)" },
  { id: "aura-2-apollo-en", label: "Apollo (male)" },
  { id: "aura-2-arcas-en", label: "Arcas (male)" },
  { id: "aura-2-orion-en", label: "Orion (male)" },
];

export const voiceLabel = (id: string) => VOICES.find((v) => v.id === id)?.label ?? id;

export type TurnDetection = {
  mode: "vad" | "semantic";
  min_silence_ms: number;
  max_extra_wait_ms: number;
  evaluator: "heuristic" | "llm";
  allow_interruptions: boolean;
};

export const DEFAULT_TURN: TurnDetection = { mode: "vad", min_silence_ms: 700, max_extra_wait_ms: 1500, evaluator: "heuristic", allow_interruptions: true };
