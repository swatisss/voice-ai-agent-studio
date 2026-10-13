---
type: Component Spec
title: Reference and sample imagery
description: "The seeded synthetic images the agent offers when there is no camera, and the demo path that feeds one through the look pipeline — both labelled so neither can pass as evidence."
status: draft
tags: [architecture, imagery, demo, evidence]
generated: { by: "claude-code/claude-opus-5", at: "2026-10-12T00:00:00Z" }
---

# Two different problems

A caller with no camera, and a demo on a laptop with no webcam, look the same from the outside and are not the same problem.

1. **No camera, real report.** The agent cannot look, but it can still take the report by description. It offers a small set of **reference images** for the asset type and asks which is closest. The answer narrows the report; it is not a picture of the caller's thing.
2. **No camera, demo.** The visual pipeline needs to be demonstrable without hardware. A **sample image** is fed through the same `look_at_camera` path a captured frame takes, producing a real observation from a real vision call.

Both use images shipped in this repository. Neither may end up indistinguishable from a frame the caller's camera produced, which is the single rule this spec exists to hold.

# No image is generated at runtime

The agent never generates an image. Not of the damage, not of an example, not of an avatar.

This is not a cost decision. The discipline the whole feature rests on is that the agent does not claim more than it can see ([/architecture/visual-intake.md](/architecture/visual-intake.md)). A product that can synthesise a convincing picture of a cracked footplate, inside the flow whose output is an insurance case, is one careless prompt away from manufacturing the evidence it is supposed to be checking. The images are therefore fixed, few, reviewed and checked in.

# Reference images

A reference image is a neutral illustration of a **kind** of fault, seeded per asset type and listed in [/demo-data/evergreen-health.md](/demo-data/evergreen-health.md). The agent offers at most three, by description, and the caller picks one or says none fits.

A reference image:

* is **never** pinned as evidence and never stored in the blob store — it is already in the repository;
* contributes the caller's selection to the case `narrative` as a stated similarity ("the caller says it resembles a snapped side-rail"), never as an observation;
* does not produce a `confidence`, because nothing was looked at.

A case built this way reaches `missing` with a photo still outstanding, and its `routing` is `needs_docs` until someone supplies one. Both are enforced in code rather than asked of the drafting model, because they are facts about the case and not judgements. That is the honest answer: a description plus a pointed-at picture is a report, not evidence.

# Sample images

A sample image is a synthetic photograph of a specific fault — a bent bed side-rail, a cracked footplate, a water-stained ceiling tile, a dented car door. The Test call page offers them when a video call has no camera ([/ui/visual-case.md](/ui/visual-case.md)).

A sample goes through the ordinary path: it is bounded and stored like any frame ([/architecture/media-storage.md](/architecture/media-storage.md)), described by the `vision` role, and pinned. The difference is one field the whole way down:

* the evidence entry records `source: sample` rather than `source: camera`;
* the case narrative opens with the sample marker, and the ticket payload carries it;
* the UI labels the entry **Sample** wherever it labels the confidence.

A case whose evidence is entirely samples can still be filed, because that is the demo, and it is filed saying so.

# Synthetic only

Every image in this repository is generated for it. No photograph of a real person, a real patient, a real premises or a real document enters the repository, and no demo path invites a user to upload one — the only way a real image reaches the product is a caller pointing their own camera at their own thing, which is the point ([/demo-data/index.md](/demo-data/index.md), [/product/healthcare-compliance.md](/product/healthcare-compliance.md)).

# Acceptance

- **IMG-01** — Given any code path in the product, when it is searched for image generation, then there is none: no adapter, no role and no tool produces an image.
- **IMG-02** — Given a video call with no camera and a caller describing a fault, when the agent offers help identifying it, then it offers at most three seeded reference images by description, and selecting one adds a stated similarity to the case narrative with no `confidence` and no evidence entry.
- **IMG-03** — Given a reference image, when the call ends, then nothing was written to the blob store for it and no evidence entry names it.
- **IMG-04** — Given a sample image chosen in a video call, when the agent looks, then an observation is produced by the same path a captured frame takes and the evidence entry records `source: sample`.
- **IMG-05** — Given a case whose evidence is entirely samples, when it is filed, then the narrative and the ticket payload both carry the sample marker, and the UI labels every such entry as a sample.
- **IMG-06** — Given the seeded imagery, when each file is checked, then every image is one of the synthetic files shipped in this repository and the set is the one [/demo-data/evergreen-health.md](/demo-data/evergreen-health.md) lists.
