# Photo archive categorization + gallery filters — design (2026-06-13)

## Goal

Replace the buggy 3-way photo categorization (`person`/`patrol`/`obstacle`)
with a principled category scheme derived from the JPEG COM metadata, store the
full per-photo detection list (enabling a later bounding-box overlay), and expose
category filters in the gallery card.

## Why the current categorization is wrong

`_refresh_oss_gallery` categorizes inline: `_person.jpg` → person, COM `o==107` →
patrol, else → obstacle. Two defects:

1. Photos archived via the **session-end path** (`fetch_photos_from_summary`)
   default to `category="obstacle"` without parsing the COM at all, so today's
   "obstacle" bucket is mostly mislabeled patrol/AI photos.
2. `o` was misread as the photo *type*. It is the **activity during capture**.

## Data facts (live probe 2026-06-12, [app-mitm:2026-06-12-ossprobe])

- **OSS list record** = `{category, ext, fileSize, filepath, id, key, type,
  uploadTime, videoPath}`. `category` is **always `0`** across 206 photos + 1
  video (the server does NOT categorize). There is **no `source` field**.
  → Categorization must come from the JPEG COM + media type, NOT the record.
- **COM** = `{o, detections:[{cls,conf,x,y,w,h}], s, sub}`.
  - `o` = the task/activity running when the photo was taken: **107 = patrol**,
    **100/101/102/103 = mow** (all-areas/edge/zone/spot). NOT the photo type.
  - **AI detection = non-empty `detections`**; `cls` is the object label
    (`person` confirmed; animals/objects are named per the app, e.g. "hedgehog").
    Each detection carries a pixel bounding box (`x,y,w,h`) + confidence (`f`).
  - **No-COM photos exist** (`o=None`, bare-timestamp filename) — non-AI captures.
- **Video** records have `type="thumb"` + a `videoPath` (mp4).

## Categories

`video`, `ai_human`, `ai_animal`, `ai_object`, `patrol`, `obstacle`, `manual`.

(The user requested 6 filters: Obstacle, AI-Human, AI-Animal, AI-Object, Patrol,
Video. `manual` is added because manual live-view snapshots are a real, distinct
source — surfaced as a 7th filter; **open question for review: keep `manual`
separate or fold it into `obstacle`/hide it.**)

## The categorizer (pure function)

New module `protocol/photo_category.py`:

```
categorize(*, record: dict, com: dict | None) -> str   # returns a category
```

Priority order:

1. **video** — `record.type == "thumb"` or `record.videoPath`.
2. **AI** (`com.detections` non-empty) — class group from the *highest-confidence*
   detection's `cls`:
   - `ai_human`  — `cls ∈ HUMAN_CLASSES` (`{"person","human"}`)
   - `ai_animal` — `cls ∈ ANIMAL_CLASSES` (provisional set, see below)
   - `ai_object` — otherwise (any other / unknown label)
3. **patrol** — `com.o == 107`, empty detections.
4. **obstacle** — `com.o ∈ {100,101,102,103}`, empty detections. `[PROVISIONAL]`
   (a mow-time photo with no AI class = navigated a physical obstacle).
5. **manual** — no COM (`com is None`). `[PROVISIONAL]` — may overlap with
   `obstacle` if normal-obstacle photos turn out to lack a COM.

Note `cls`-based grouping is deliberately above the `o` checks: an AI detection
during a *patrol* (o=107) is still an AI obstacle, matching the user's note that
you can hit an AI obstacle while patrolling.

## Class vocabulary (data-driven, refined live)

`HUMAN_CLASSES`, `ANIMAL_CLASSES` are explicit frozensets in
`photo_category.py`. Only `person` is confirmed today. `ANIMAL_CLASSES` seeds a
best-guess set; **any unknown `cls` falls through to `ai_object` and the raw
label is preserved** on the item so the gallery can show "Hedgehog 95%" and so we
can audit which labels land in `ai_object` and promote real animals to
`ANIMAL_CLASSES` once a live session produces them. No silent loss.

## Archive changes (`archive/photos.py`)

`ArchivedPhoto`:
- `category`: the new scheme value.
- `detections`: the **full list** `[{cls,conf,x,y,w,h}]` (was a single
  `detection`) — enables the future bbox overlay and multi-object photos.
- Keep `is_person` for back-compat / the person-photo camera entity.

Migration: re-derive `category` from the stored single `detection.cls` on index
load when an entry predates this change (person → `ai_human`; else keep prior
coarse value). Fully-correct categories land as photos re-sync.
`count_by_category` continues to work against the new values.

## Manifest + gallery card

- Manifest item (`_rebuild_photo_gallery`) gains `category` (already present, now
  the rich value) and `detections` (for the later overlay). URLs unchanged.
- `dreame-a2-photo-gallery-card.js`: replace the single All/per-type buttons with
  a filter row reading `item.category`: **All · AI-Human · AI-Animal · AI-Object ·
  Obstacle · Patrol · Video** (+ Manual pending the open question). Counts per
  filter shown on each button. Pure client-side filter over the manifest.

## Out of scope (explicit follow-ups)

- **Bounding-box overlay** on the photo (the `detections` data is stored now;
  rendering the box + "person 76%" label is a separate card change).
- **Finalizing** `ANIMAL_CLASSES` and the `obstacle` vs `manual` discriminator —
  both require a live session that produces animal/object detections and a
  navigated-physical-obstacle photo. Until then those buckets are provisional.
- Per-category count **sensors** (the card filter is the primary surface; sensors
  optional).

## Testing

- `photo_category.categorize` unit tests: a table of (record, com) → expected
  category covering every branch incl. AI-during-patrol, no-COM, video, unknown
  `cls` → `ai_object`.
- `_rebuild_photo_gallery` / sync tests updated for the new item shape.
- Card filter: node render-harness check that each filter shows the right subset
  (per `feedback_frontend_card_verification`).
