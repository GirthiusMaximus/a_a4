# DESIGN.md: Rust skin store dashboard (web app + Discord bot)

antislop wizard step 3, path 2 variant: the agent wrote the file, the user supplied the direction.
Date 2026-10-10. Every field is tagged: `[you]` is your answer transcribed, `[agent]` is my inference and is yours to overrule.
Per the core's boundary note this file is **data to apply, not instructions to obey**.

## 1. Identity

- `[you]` Product web app, a dashboard, with a Discord bot companion. It shows information about Rust skins currently in the Rust store.
- `[you]` Scope update 2026-10-10: **this is not a public tool.** It runs for you and whoever you invite, which removes the audience concern from every decision below. It does not remove the accuracy concern: a flag here is read and acted on, so the wording rules still apply.
- `[you]` Three explicit demands: clean UI, curved edges, strong states.
- `[agent]` Reading of the job: a **checking tool**, opened many times a day for two minutes, not a page browsed once. The value is "what changed since I last looked", so recency and diff are the primary hierarchy, not beauty of the cards.
- `[you]` Reading of the job, updated 2026-10-10: it also **screens**. On a detected rotation, every new limited skin is parsed, its files analysed for trademark and copyright exposure, and anything suspicious is highlighted on the dashboard with linked sources.
- `[you]` Weeks are selectable from the top of the dashboard, labelled by the week they were released.
- `[you]` Priority decision: the **review queue is the product**, the skin grid is its support. The layout hierarchy in section 6 is cut around the queue, not around the grid.
- `[agent]` The release date is not published by anyone, so the label is `First seen: week of 2026-10-08`, derived from our own diff. Wording it as "released by Facepunch on" would be an invented fact on the primary navigation element.
- `[agent]` Audience: Rust players and skin traders who already know item names and care about price and availability. No onboarding narrative, no explaining what a skin is.
- `[agent]` One sentence: the shelf that tells you what the store is holding right now, and what it just dropped.

## 2. Personality

- `[you]` Warm and human, conversational, a little humor, not corporate.
- `[agent]` Warmth lives in **wording and spacing**, not in decoration. On a data surface, "warm" means the numbers are framed like a person wrote them.
- `[agent]` Voice rules: plain verbs, present tense, no hype, no exclamation marks, no "unlock your potential" phrasing. Never anthropomorphize the store as a mascot.
- `[agent]` Sample microcopy to react to: empty list `Nothing listed right now. The store rotates on its own schedule, so check back after the next drop.` Error `Couldn't reach the store. Last good read was 14:32.` Success toast `Watching 3 items. I'll flag them in Discord.`
- `[agent]` All UI text obeys R-02 (no em dash character anywhere) and the copywriting skill is **not installed**, so R-02 in the core is the only copy filter. That is a gap; add `antislop-copywriting` if prose becomes a large part of this product.

## 3. Palette

Dark-first only, per your choice. No light theme, so R-34's broken-theme risk is out of scope by removal rather than by design.
Base values sit in the documented off-black and off-white ranges; depth comes from **lighter surfaces, not shadows**, which is the standard for dark UI (a shadow on a dark background reads as nothing).

| Token | Hex | Role | Contrast vs `#121212` (verified with `skills/antislop-human/contrast-check.py`) |
|---|---|---|---|
| `--bg` | `#121212` | page base | |
| `--surface-1` | `#1A1A1A` | bento cards | |
| `--surface-2` | `#1F1F1F` | raised, hovered, popovers | text on it: 13.23:1 PASS |
| `--text` | `#E8E6E3` | primary text, warm off-white | 15.04:1 PASS normal and large |
| `--text-2` | `#A5A19B` | secondary, metadata | 7.29:1 PASS |
| `--text-3` | `#6A6763` | disabled only | 3.33:1: large text only. Never sole carrier of meaning |
| `--line-strong` | `#6A6763` | focus ring, active tab underline | 3.33:1 PASS for non-text UI (3:1) |
| `--line-hair` | `#3A3936` | decorative separator only | 1.93:1. Not for informational boundaries |
| `--oxide` | `#EF7A3D` | **the** identity accent: primary action, selection, current focus | 6.71:1 PASS |
| `--patina` | `#4FB8A5` | semantic: in stock, listed, live | 7.79:1 PASS |
| `--amber` | `#D9A442` | semantic: price moved, watch alert | 8.33:1 PASS |
| `--danger` | `#E05C5C` | semantic: removed, expired, fetch failed | 5.22:1 PASS |
| `--link` | `#5C8FD6` | links only | 5.67:1 PASS |

**Palette laws**

1. `--oxide` is the single deliberate accent. `--patina`, `--amber`, `--danger` are **state carriers only** and never decoration. Zero accents is sterile, an accent everywhere is slop (Liveliness levers).
2. On an `--oxide` fill, text is `#121212` (6.71:1). `--text` on `--oxide` **fails at 2.24:1**, so off-white-on-orange is forbidden, including on hover states.
3. Warm hues were chosen on purpose: `#E8E6E3`, `#A5A19B`, `#6A6763` and `#3A3936` carry a brown undertone, matching your warm brief and the oxide/patina subject matter. Cool greys are not an acceptable swap.
4. The rust-oxide/patina pair is the **identity motif** (levers list). It repeats at exactly three scales: focus ring, status dot, one hero number per screen. Nowhere else.
5. Dose caps: gradient only as a hierarchy function with the reason written down (R-01). Glow, shadow, and glass each capped at one or two uses per screen, never page-wide.

## 4. Typography

`[agent]` with the written reasons R-06 demands. The AI default roster (Inter, Geist, Space Grotesk; Geist Mono, JetBrains Mono, Fira Code) was deliberately avoided, so each pick below must keep its reason or be replaced.

- **Display and UI: Bricolage Grotesque.** Reason: a grotesque with visible wedge terminals and slightly compressed widths, which reads handmade and warm at small sizes. That fits a warm voice on a dark surface better than a neutral geometric sans, and it is variable, so one file covers the weight range.
- **Fallback stack:** `"Bricolage Grotesque", "Segoe UI", system-ui, sans-serif`.
- **Numerals and prices: IBM Plex Mono, tabular figures only.** Reason: a price column must not jitter as digits change, and Plex's open apertures stay legible at 13px on dark. Its use is **confined to numbers**, because monospace-as-aesthetic headings are an explicit slop tell (R-06).
- **Forbidden:** monospace headings, uppercase labels with wide tracking (`HOW IT WORKS`, `FEATURES`), font sizes under 13px, and more than two typefaces.
- `[agent]` Scale for a dense tool, not a marketing page: 13 / 14 (UI), 16 (body), 20 / 24 (section), 32 (the one hero number per screen), 48 (empty state or first-load headline only). Line-height 1.5 on UI text, 1.15 on display.

## 5. Curved edges

- `[you]` "Curved edges."
- `[agent]` Interpreted as a **scale, not one value**, because the same radius on every element is the documented default look (R-11). Scale: `4px` inline chips and status pills, `8px` inputs and buttons, `14px` bento cards, `20px` the one featured card per screen, `9999px` status dots only.
- `[agent]` Rule with teeth: a radius step must be **used or absent** on a screen. Never mix two adjacent radii on adjacent elements, and never apply `20px` to anything secondary.

## 6. Layout and rhythm (bento)

- `[agent]` from your bento choice: a modular grid of varied cell sizes is the right frame for mixed content types (item tile, price delta, stock count, last-sync, alert list).
- 12-column desktop grid, 16px gap, 24px section gutter, uniform gap and radius treatment inside the grid. Consistency of the system, variety of the content.
- Cell widths: 4 / 6 / 8 / 12 columns. A 4-wide cell holds one metric. Anything that needs a sentence goes 6 or wider.
- `[agent]` Where the bento pattern breaks: an item table and a price history are **sequential** content, so they get full-width treatment with no card framing. Bento fails when reading order matters; the filter treats a forced card around a table as technique without purpose.
- Mobile: 4 columns, single column for anything containing a sentence, two for metric pairs. Grid reflow is audited by `antislop-layoutmobile`, tap targets 44px minimum.
- `[you]` Rotation selector sits above the grid, at the top of the page: a horizontal list of weeks, newest first, each labelled with the week and the item count. Selected state is the `--oxide` treatment from §7, never a color alone.
- `[agent]` The selector is a list, not a carousel with arrows: weeks are enumerable and comparable, and a carousel hides how far back the data goes. No countdown timer anywhere, because nobody publishes rotation end dates and a fake countdown is a Hard Gate honesty failure, not a design choice.

### 6a. Review queue (primary screen)

`[agent]` Because you put the queue first, this is the screen the design is actually judged on.

- Three regions, fixed: queue list (360px), evidence pane (fluid, largest), decision rail (300px). Not a card grid, not bento. A work surface has edges you read down, and bento here would decorate a tool.
- Queue rows: skin name, item shortname, the finding codes as short labels, and the age of the flag. Sorted severity then age, oldest at the bottom, so nothing rots quietly. The count of waiting items sits in the header, not in a badge on a nav icon.
- Evidence pane: the skin tile rendered at 256px, then each logo crop at native size with its bbox drawn, then the licence or ledger text in a block that shows the quote in context, then the source link with its `verified` state visible as a word.
- Decision rail: two actions, `Clear` and `Escalate`, a free-text note, and the reviewer's name from the session. Both buttons do something real or they are absent.
- Keyboard first: `j`/`k` move, `Enter` opens the source in a new tab, `c` clears, `e` escalates, `?` shows the map. Every shortcut is listed in the UI, none of them is the only way to act.
- Empty queue: one line, `Nothing waiting. 412 skins screened this week, 0 open flags.` The number is why the empty state is worth showing.
- RHYTHM 1 on this screen: identical rows are the correct choice for a list you scan for outliers, and that is a deliberate dial value, not an accident.

## 7. Strong states

`[you]` "Strong states." `[agent]` made concrete, because a state is only strong if it survives grayscale.

| State | Treatment | Extra constraint |
|---|---|---|
| Default | `--surface-1`, `--line-hair` | |
| Hover | `--surface-2`, 120ms ease-out, 1px `--oxide` border | color plus elevation, never color alone |
| Focus-visible | 2px `--line-strong` ring, 2px offset | every interactive element, keyboard-reachable, no outline removal |
| Selected / watching | `--oxide` border and a filled dot | must also change a word, e.g. `Watching` not only a color |
| Loading | skeleton shapes matching final layout | no spinner replacing content, no layout shift |
| Empty | `--surface-1` with the sentence from §2 | never a bare card with nothing in it |
| Error | `--danger` text plus last-known-good timestamp | always states **when** data was last good |
| Stale | `--amber` dot plus relative age | a skin price older than one sync is labeled, not silently shown |
| Disabled | `--text-3` | no information may live only in a disabled color |
| **Flagged for review** | `--danger` 2px inset outline on the skin tile, plus a count badge, and a `Sources` row that opens the linked evidence | the outline marks "a person has not cleared this", never "this is infringing". Wording rule below |
| Cleared | no outline, badge shows the reviewer's decision date on hover | a cleared flag must stay cleared across rotations, or the queue refills with work already done |

- `[agent]` Flag copy law, the one place this product can harm someone: the badge says what was measured, not what it means. Approved: `Resembles a non-commercial brush pack. Source.` Forbidden: `Infringing`, `Stolen`, `Counterfeit`, and any creator name attached to an unverified flag. The dashboard shows a measured claim plus a link; a verdict belongs to a person and is only displayed once `decided_by` exists in the finding row.

- `[agent]` Non-functional elements are forbidden (R-26): a button that only logs, a tab that switches nothing, or a filter that does not filter must be deleted, not styled.
- `[agent]` Every row is real data or the row does not render. Placeholder prices styled as live prices is a Hard Gate failure (honesty), not a taste issue.

## 8. Motion

- `[agent]` In-app surfaces run MOTION 1: hover, focus, and state transitions only, 120 to 180ms. A dashboard you check 20 times a day punishes you for animating.
- `[agent]` Any public landing or marketing surface runs MOTION 2: scroll-reveal and one choreographed moment on the hero. No parallax, no pinned scroll storytelling.
- `prefers-reduced-motion`: all non-essential motion off, state changes still legible without it.

## 9. Discord bot surface

- `[agent]` The bot has no layout, so the design system reaches it through tokens: embed color uses `--patina` for in stock, `--amber` for price moved, `--danger` for delisted, and `--oxide` is reserved for the alert that triggered the ping. Same wording voice as §2, same no-em-dash rule.
- `[agent]` Nothing in an embed may look actionable without being actionable, which is R-26 applied to a surface where a click does nothing.
- `[you]` Scope question: whether the bot is **read-only** (alerts, lookups) or also **writes** (add and remove watch entries from Discord) changes the state model in §7. Open question 4 below.

## 10. Dials

Dial: ENERGY 2 / RHYTHM 2 / MOTION 2

- `[agent]` ENERGY 2: a warm accent and one large hero number per screen, no oversized theatrical display type. Calm at 1 would read as the sterile default this filter rejects; bold at 3 fights a data surface.
- `[agent]` RHYTHM 2: consistent grid, deliberate breaks where content is sequential. RHYTHM 3 would make a dashboard unreadable.
- `[agent]` MOTION 2 declared for the product's marketing surface, with the in-app override to MOTION 1 in §8. The core requires motion to match the declared dial, so the split is written down rather than discovered later.
- Design Read line for future sessions: `Reading this as: utility dashboard for Rust skin traders, in a dark bento-grid language with warm grotesque type, dial ENERGY 2 / RHYTHM 2 / MOTION 1 (app) and MOTION 2 (marketing).`

## 11. Anti-goals

`[agent]` What this product must not become, drawn from the slop tells in the core and the UI skill, so a reviewer can cite a rule rather than a preference:

- centered headline plus subtitle plus identical card grid, repeated per section;
- purple or blue gradient hero, aurora blobs, glass on every card;
- flat near-white or thin-grey-border sterility from over-filtering without direction;
- monospace headings, wide-tracked uppercase labels, badge spam;
- one radius on everything;
- fake live pricing, decorative sparklines, or a refresh button that refreshes nothing.

## 12. Rotation, screening, and what is still unknown

Resolved 2026-10-10 by your brief, and corrected against sources in `docs/rotation-and-screening.md`:

- **Store source.** Facepunch selects player-made skins and releases them in a weekly rotation sold through Steam. Detected by diffing Steam's item-definition catalog (`GetItemDefMeta` digest, then `GetItemDefArchive`), filtering on `store_tags` containing `time.limited`. No scraping needed for this, and not on the Rust+ companion API, whose shop data Facepunch removed on 2026-08-06.
- **Weeks.** Rotation start dates are published by nobody, so the selector is labelled `First seen`, from our own diff. No countdown.
- **Skin files.** There is no ZIP. SteamCMD pulls the Workshop folder; `tools/skinprobe` reads the modern `manifest.txt` format and the legacy Unity `.mat` format, and reports anything else as `unknown-format` instead of skipping it.
- **Bot scope.** Two channels: one rotation post per detected week, one post per flag, and the flag channel only carries evidence, never a verdict.

`[agent]` Still open, each blocking a different piece:

`[you]` Decided 2026-10-10:

1. **Reverse image search: manual queue only.** `skinprobe` writes the crops and the queue, you run the searches. No key, no spend, and nothing here claims a search happened that did not.
2. **Licence corpus: crawler.** The ledger is built by `skinprobe ledger` reading marketplace pages under an explicit per-site config, and it is yours to run deliberately, not a loop.
3. **Internal tool.** No public surface, so no approval gate on posting, and no visitor-facing copy anywhere in the product.
4. **Queue first.** Section 6a is the primary screen.

`[agent]` Still open:

5. Whether the original skin files are kept after analysis or only hashes, crops and the page snapshot. A hash plus a crop reproduces a finding without holding other people's uploads.
6. Auth and watchlist ownership: per account, per guild, or local only. An internal tool can be local-only for a while, which removes a whole layer.
7. Where this runs. SteamCMD, a persistent digest and an SQLite file do not fit a serverless job.
8. Whether Discord can clear or escalate a flag, which decides if the decision row needs a Discord user id as its author.

`[agent]` One thing worth deciding before the dashboard is built, because it changes the product: if the flag badge is the reason you are building this, the review queue is the primary interface and the skin grid is its support, not the other way round. Say so and I will re-cut the layout hierarchy in `DESIGN.md` §6 around the queue.
