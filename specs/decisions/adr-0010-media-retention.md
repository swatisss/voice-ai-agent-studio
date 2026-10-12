---
type: Decision Record
title: ADR-0010 Store captured frames, with a clock on every object
description: "Accept the first byte storage in the product, narrowly: a blob-store port, bounded frames, a retention window, no public URLs, and observation text that outlives the image."
status: draft
tags: [decision, media, storage, retention, compliance]
generated: { by: "claude-code/claude-opus-5", at: "2026-10-12T00:00:00Z" }
---

# Context

Nothing in this product has ever stored a byte of caller content. Knowledge upload extracts text and throws the file away ([/architecture/knowledge.md](/architecture/knowledge.md)); audio recording and playback are explicitly out of scope ([/product/scope.md](/product/scope.md)). That was not an accident of the build order — it is why the product has no retention policy to get wrong.

[Visual intake](/architecture/visual-intake.md) puts pressure on it from two sides. A case a human has to act on needs evidence a human can check, and an agent that may withhold confidence needs its withheld looks on the record. Both mean keeping the frame.

# Options

1. **Keep nothing.** Describe the frame, store the description, discard the image. Preserves the no-bytes property exactly.
2. **Keep the frame for the life of the case**, deleted when the case is closed or the call is deleted.
3. **Keep the frame under a retention window**, with the observation text outliving it.

# Decision

Option 3, with the window as configuration and a default of 30 days.

Option 1 was tempting and is wrong. An observation nobody can check is not evidence, it is an assertion by a model — and the whole point of the confidence field is that a reviewer can tell a careful agent from a lucky one. They cannot do that from prose. A `not_confirmed` look is exactly the case where someone will want to see the frame.

Option 2 ties the image's lifetime to a workflow state, which means an abandoned case keeps its images forever and a quickly-closed one loses them while the ticket is still open. A clock is simpler to reason about and simpler to defend.

The decision that does the real work is **splitting the two lifetimes**. The frame expires; the description, the confidence, the `asked_for` and the caller's words do not. A case therefore stays readable and auditable after its images are gone, which is what a reviewer actually needs, and the opposite of what a cascade delete would leave them.

Three limits keep the break narrow:

* **One port, two adapters.** `BlobStore` with a `local` directory and a `gcs` bucket ([/architecture/media-storage.md](/architecture/media-storage.md)). Nothing else in the product learns how to store bytes.
* **Bounded on the way in.** 1280 px longest edge, 1 MB encoded, 12 frames per call. A cap that is reached declines the look; it never fails the call.
* **No URL anyone can hold.** The port does not sign URLs and does not list. Media is read through one authorised endpoint that checks the tenant like any other owned row, and reports another tenant's object as not found.

# Consequences

* The product now has a retention window, so it has to say what it is: 30 days, in configuration, named in the spec and in the demo. v1 still has no audit log and no deletion-on-request path, and [healthcare compliance](/product/healthcare-compliance.md) records that as a production gap rather than implying it is handled.
* `local` is correct for one instance and wrong for two, the same constraint [ADR-0005](/decisions/adr-0005-single-service.md) already places on the process-local session registry. It is written down so the horizontal-scaling CP gets one more list item instead of one more surprise.
* Retention runs as an ordinary `prune_media` job that re-enqueues itself ([/architecture/jobs-and-events.md](/architecture/jobs-and-events.md)), so no scheduler is introduced.
* The demo ships synthetic images only, and no demo path invites a user to upload a photograph of a real person or premises ([/architecture/imagery.md](/architecture/imagery.md)).
* Audio recording stays out of scope. This decision is about frames the agent chose to look at, and it is not a precedent for keeping the call.
