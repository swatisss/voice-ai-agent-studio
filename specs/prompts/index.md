# Prompts

The code loads each prompt directly from the fenced `text` block under the `# Prompt` heading of these files; `{{variable}}` placeholders are filled at runtime. Editing a prompt here changes agent behavior, so it follows the [SDD workflow](../process/sdd-workflow.md).

* [Agent system prompt](agent-system-prompt.md) - The realtime agent's instructions: speaking style, grounding, verification, escalation, skills
* [Escalation packet](escalation-packet.md) - Turns a transcript into the groundwork packet for the human
* [Call analysis](call-analysis.md) - Post-call outcome, intent, root cause, gap summary and caller goal
* [Cluster naming](cluster-naming.md) - Names and describes a cluster of similar gaps
* [Fix draft](fix-draft.md) - Drafts a knowledge article, skill or policy rule from cluster evidence
* [Caller simulator](caller-simulator.md) - Plays a caller with a goal during evaluations
* [Eval judge](eval-judge.md) - Grades a simulated call against its goal and expected outcome
