## What and why

<!-- One or two sentences. Link the change proposal: specs/changes/cp-NNNN-*.md -->

## Spec-driven checklist

- [ ] The change started as a spec edit (change proposal + affected specs), and the spec diff is the first thing to review
- [ ] Specs and code are in this PR together; `specs/log.md` has an entry
- [ ] New or changed acceptance criteria have IDs and tests that cite them (`Covers: XX-NN`)
- [ ] Touched specs are `status: stable` and the CP is `cp_state: implemented`
- [ ] `python scripts/spec_check.py --ci --base origin/main` passes locally
- [ ] No behavior change? Then say so and use `[no-spec]` in a commit message (or ask a maintainer for the `no-spec` label)

## How I verified it

<!-- Tests run, manual steps. Say plainly what you could not verify. -->
