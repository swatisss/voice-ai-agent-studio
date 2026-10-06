@AGENTS.md

## Claude Code specifics

* Use `/spec-change <idea>` to draft a change proposal and spec edits (no code), and `/spec-implement CP-NNNN` to implement an accepted proposal.
* Before finishing any task, run `python scripts/spec_check.py` and the relevant tests, and report results.
* When unsure whether something is a behavior change, treat it as one and go through a CP.
