---
type: Component Spec
title: Media storage
description: "Where captured frames live: a blob-store port with a local and a cloud adapter, bounded frame sizes, time-limited retention, and authorised access only."
status: draft
tags: [architecture, media, storage, retention]
generated: { by: "claude-code/claude-opus-5", at: "2026-10-12T00:00:00Z" }
---

# Why this is new ground

Nothing in this product has ever stored bytes. Knowledge upload reads a file, extracts its text and throws the file away ([/architecture/knowledge.md](/architecture/knowledge.md)), and audio recording is explicitly out of scope ([/product/scope.md](/product/scope.md)). Visual intake breaks that, because an observation nobody can check is not evidence.

So this spec exists to keep the break narrow: one port, bounded sizes, a clock on every object, and no public URLs. See [/decisions/adr-0010-media-retention.md](/decisions/adr-0010-media-retention.md) for why storing anything at all was accepted.

# The port

`ports/blobstore.py` declares the capability; `composition/` chooses the adapter, as with every other port ([/architecture/modular-structure.md](/architecture/modular-structure.md)).

| Adapter | Backing | When |
|---|---|---|
| `local` | A directory under the API's data path. | Default. Localhost, tests, and the single-instance Cloud Run service as it stands today. |
| `gcs` | A bucket. | When the service is scaled past one instance, at which point a local directory stops being shared state and starts being a bug. |

The port stores and fetches bytes by key and deletes by key. It does not list, and it does not sign URLs — both would invite the access pattern this spec is trying to prevent.

`local` is honest about its limit: it is correct for one instance and wrong for two, which is the same constraint [ADR-0005](/decisions/adr-0005-single-service.md) already places on the process-local session registry. It is named here so that the horizontal-scaling CP has one more item on its list rather than one more surprise.

# Frames are bounded on the way in

A frame is stored as JPEG, encoded by the `evidence` module from the decoded video frame the tap held ([/api/media-protocol.md](/api/media-protocol.md)) rather than passed through. The browser's capture resolution is a hint, not a guarantee, so the bounds below are applied on the server before anything is written.

| Bound | Value | Why |
|---|---|---|
| Longest edge | 1280 px | Enough for a vision model to describe damage; past this, cost rises and nothing improves. |
| Encoded size | 1 MB | A frame that will not fit is re-encoded at lower quality once, then rejected. |
| Frames per call | 12 | A look is an act, not a stream ([/architecture/visual-intake.md](/architecture/visual-intake.md)). Twelve is generous for one report and finite. |

Exceeding the per-call cap does not fail the call: `look_at_camera` returns a declined status saying enough has been captured, and the agent moves on to the case.

# Retention

Every stored object has a tenant, a call and a creation time. A `prune_media` job deletes objects older than the retention window and re-enqueues itself, so retention needs no scheduler ([/architecture/jobs-and-events.md](/architecture/jobs-and-events.md)); the default window is 30 days and it is configuration, not code.

**The observation text is not subject to retention.** Deleting a frame leaves its evidence entry intact, with the description, the confidence and the caller's words. A case therefore stays readable and auditable after its images expire, which is the behaviour a reviewer needs and the opposite of what a cascade delete would give.

# Access

Media is read through one authorised endpoint that resolves the object by id, checks the tenant the same way every other owned row is checked, and streams the bytes. There is no public URL, no signed URL and no path a browser can guess. An object whose tenant does not match is reported as not found, indistinguishably from one that never existed ([/architecture/multi-tenancy.md](/architecture/multi-tenancy.md)).

# Synthetic only

The seeded demo cases ship with synthetic images generated for this repo — a damaged bed frame, a cracked footplate, a water-stained ceiling. No photograph of a real person, a real patient, a real premises or a real document enters this repository, and no demo path invites a user to upload one. This is the same rule the rest of the demo data follows ([/demo-data/index.md](/demo-data/index.md)), restated here because images make it easy to break by accident.

# Acceptance

- **MS-01** — Given the blob-store port, when the service starts with no media configuration, then the `local` adapter is in use; and when the cloud adapter is selected by configuration without its bucket set, then start-up fails with a message naming the missing setting rather than storing to a local path.
- **MS-02** — Given a decoded frame larger than the bounds, when it is stored, then it is re-encoded within 1280 px on its longest edge and under 1 MB; and given one that still will not fit, then nothing is written and the caller receives a declined status.
- **MS-03** — Given a call that has already stored twelve frames, when the agent looks again, then no frame is stored, the tool returns a declined status saying enough has been captured, and the call continues.
- **MS-04** — Given stored media older than the retention window, when the retention job runs, then the objects are deleted and their evidence entries remain readable with description, confidence and the caller's words intact.
- **MS-05** — Given a stored object, when it is requested by id by its own tenant, then the bytes are returned; when requested by another tenant, then the response is not found; and there exists no endpoint that returns a public or signed URL for it.
