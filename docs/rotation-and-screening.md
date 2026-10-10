# Rotation watcher and IP screening pipeline: what the brief implies, and what is actually true

Working notes for the Rust skin store dashboard. Written 2026-10-10 after checking the sources cited
inline. Read `DESIGN.md` for look and feel, this file for how it works.

## 1. Corrections to the brief

| Brief says | Verified reality | Consequence |
|---|---|---|
| "download the skin zip file" | There is no per-skin ZIP. A skin is a folder: `manifest/manifest.txt` plus loose PNG/JPG textures, or a legacy raw Unity upload (`.mat`, `.meta`, `.tga/.psd`, optional `meta.asset`) | The fetch stage is SteamCMD pulling Workshop content, then ingest. `tools/skinprobe` reads both formats |
| "detect a rotation", implying an announced event | Nobody publishes rotation start or end dates. A tracker snapshots the store daily and records every change, and explicitly refuses a countdown because it "would be making it up" | Rotation is **derived from a diff**, and a week label is "first seen by us", never "released by Facepunch" |
| "trademarked or copyrighted" as an output | Not determinable from pixels | The tool ships candidates plus sources for a human. Report language is "check this", never "this infringes" |
| "analyse brushes that carry a no-commercial-resale clause" as a detectable property | No registry of brush packs and their licence text exists | Requires a corpus you populate. Design for it, do not promise it |
| "reverse image search" as an API call | The Bing Image Search API was retired 2025-08-11, whole family, endpoints return 410. Replacements are metered accounts (SerpApi, TinEye, lenso) | Provider seam with a `manual` default and keys in env only |

## 2. Rotation detection

The authoritative, documented path, with a free Steam Web API key and no scraping:

1. `GET https://api.steampowered.com/IInventoryService/GetItemDefMeta/v1/?key=KEY&appid=252490`
   returns a `digest` for Rust's item definition catalog.
2. Digest unchanged: nothing to do, exit 0. Digest changed:
   `GET https://api.steampowered.com/IGameInventory/GetItemDefArchive/v1/?appid=252490&digest=DIGEST`
   returns the full item array.
3. Diff against the stored catalog by `itemdefid`. New ids are this rotation's skins.
4. Store membership and limited status come from the item's own fields: `store_tags` carries
   `time.limited` on rotating items, alongside `cat`/`subcat`, `steamcat`, and `tradable`.
5. Persist the digest in a one-line file so a run is idempotent and an interrupted run resumes.

That is precisely the reference pipeline's Stage 1 and its diff, so the approach is proven by
something already in production. Prices come from SCMM's free API in one request across 16 markets.

Do not build this on the Rust+ companion API: Facepunch removed vending-machine and event data from it
on 2026-08-06, which broke shop features in every companion app that relied on them.

A digest diff sees the **catalog**, which is wider than "this week's store rotation". Two things follow:
filter on store tags rather than treating any new itemdef as a rotation, and keep a `week` table built
from observed changes, because "which week a skin appeared" is a fact you generate, not one you receive.

## 3. Asset fetch

Skin files arrive via SteamCMD with anonymous login into
`steamapps/workshop/content/252490/<publishedfileid>/`. Ingest then decides the format: a `manifest.txt`
means modern, a `*.asset` with Unity meta means legacy import, neither means `unknown-format` as a
record with a note, not a silent skip. Icons and previews are already available as URLs from the item
definition itself (`icon_url`, `icon_url_large`, on `files.facepunch.com`), plus `name_color` and
`background_color`, which the dashboard should treat as **data about the item, never as palette
inputs** for the UI.

The render icon matters for more than thumbnails: a reverse image engine matches a rendered object far
better than an unwrapped UV texture. Search both, and label them differently in the evidence.

## 4. Screening stages, cheapest and most defensible first

1. **Local, deterministic, no network.** `tools/skinprobe`: decode, measure composition, seam ratio,
   blank and cutout flags, hashes. Every step is reproducible and citable.
2. **Ledger match.** dHash Hamming against a curated corpus of known artwork and non-commercial
   licensed packs, plus name matching against a marks ledger. Distance and crop bbox are recorded, so a
   reviewer sees *why* the item was flagged.
3. **Reverse image search.** On each logo crop and on the store render. `manual` writes a queue; keyed
   providers append hits to a cache so a skin is searched once, not once per run. Rate limit deliberately.
4. **Register lookups for names, done by a human with a link.** USPTO, EUIPO, WIPO's Global Brand
   Database. An automated "is this trademarked" answer is not something to ship: marks are class
   specific, and "ACOG" on a scope is a different question from "ACOG" on a rifle skin.
5. **Human decision.** The queue entry that clears a flag records who, when, and what they looked at,
   which is what makes the dashboard's badge defensible instead of merely noisy.

## 5. Storage

SQLite, four tables, no ORM needed at this size:

- `rotation(id, first_seen_at, last_seen_at, digest, itemdef_count)`
- `skin(id, name, item_shortname, store_tags, tradable, first_seen_rotation, last_seen_rotation, status, icon_url, price_cents, fetched_at)`
- `texture(skin_id, group_index, slot, path, width, height, md5, dhash, seam_ratio, blank, cut_fraction, notes)`
- `finding(id, skin_id, code, severity, detail_json, source_url, source_verified, decided_by, decided_at, decision_note)`

Two properties matter. `first_seen_rotation` is what makes the week selector in the dashboard honest.
And a `finding` keeps its decision, so next week's scan cannot re-flag a skin a person already cleared:
the dedupe key is `(skin_id, code, source_url)`.

## 6. Discord: two channels, one contract

- `#rotation`: one post per detected rotation. Item count, the week label, per-item price, a link to the
  filtered dashboard view. Edited, not re-posted, when prices refresh.
- `#ip-flags`: one post per skin whose flag a human has **approved for posting**, plus the evidence and
  the linked source.

Wording, and this is the one place the product can do real harm: an unapproved or unverified flag must
not name a creator or assert infringement. "Needs review: composition resembles X, source linked" is a
statement about your own measurement. "Skin by CREATOR infringes TRADEMARK" is an accusation that can
cost someone their income, and the tool's evidence does not support it. Public channel text goes through
the same human gate that the dashboard badge does not require.

## 7. The licence corpus, built by crawler

Chosen over hand-curation and over dropping the check. `tools/skinprobe` gained a `ledger` mode:

- **Per-site JSON config**, not hard-coded scrapers: start urls, item and skip patterns, licence-block
  selectors, image host allow-list, item cap, per-host interval. Selectors rot on the next redesign, and
  an editable file is cheaper than a patch. Pattern matching is a path glob or a plain substring, and
  `followListingPatterns` exists so a category page is never mistaken for a product.
- **Polite by construction**: `robots.txt` honoured by default, one request per host per interval with
  jitter, conditional GET against its own snapshot cache, `Retry-After` respected, a contact User-Agent,
  and every URL it touched logged including the ones it refused. `--max-items 1 --dry-run` is the first
  command you run against a new site.
- **No JS, no login, no paywall.** A site that renders its licence only after JavaScript gets its HTML
  saved and replayed through `--offline`, which is also how the crawler is tested without a network.
- **Verbatim over summarised.** A row stores the clause quote, its offsets, and the hash of the captured
  text, so re-verification is a string comparison rather than a memory. Offsets that no longer resolve
  drop the clause and mark the page `unclear` instead of trusting a drifted pointer.
- **No licence text is `unknown`, never permissive.** Absence of evidence is recorded as absence.
- **`watch.jsonl` plus `changes.jsonl` is the point of running it twice.** A pack whose licence gained
  "personal use only" after sales started is exactly the case that matters for skins already in a
  rotation, and only a diff against the previous capture can surface it.
- Output feeds the scanner directly: `scan --corpus ledger-out/ledger.jsonl`.

The honest limit stays in the README: this matches text against a known list of the ways a licence says
no. It is not a contract reader, and the clause patterns should grow from misses you actually hit.

## 8. Decisions taken 2026-10-10

| Topic | Decision | Effect |
|---|---|---|
| Reverse image search | Manual queue only, no paid key | `skinprobe` writes `reverse-search-queue.csv`; nothing claims a search ran. Provider seam stays for later |
| Licence corpus | Crawler, config-driven, run deliberately | Section 7. Needs your approval per site before the first live run |
| Audience | Internal tool, not public | No approval gate on Discord posting, no visitor-facing copy, no auth wall at first. Wording law in `DESIGN.md` section 7 still applies, because a Discord message is the artifact most likely to be quoted at a creator |
| Primary screen | Review queue, not the skin grid | `DESIGN.md` section 6a. Bento becomes the browse view, the queue is a three-region work surface |

Still open: retention of raw skin files versus hashes only; auth and watchlist ownership; the host that
runs SteamCMD plus a persistent digest and SQLite; and whether Discord can clear a flag, which decides
whether a decision row needs a Discord user id as its author.
