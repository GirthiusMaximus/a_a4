# skinprobe

Reads a Rust item skin's files and scores them for trademark / copyright exposure. It is a
measurement tool: it decodes what a skin actually contains, finds candidate marks, and compares
against a ledger you populate. It never asserts ownership, and its output is written so a person
can decide with sources open.

## Install and run

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m skinprobe selftest          # 27 checks incl. the crawler, synthetic fixtures, no network
.venv/bin/python -m skinprobe scan path/to/skin_or_root --out out --corpus ledger.jsonl
```

Exit codes follow the reference pipeline: `0` nothing to look at, `1` findings need review,
`2` the scan itself failed.

## What a Rust skin actually is (verified)

There is no per-skin ZIP. A skin is a **folder**, and it comes in two formats:

**modern**: `manifest/manifest.txt`, a JSON document:

```json
{
  "ItemType": "rifle.ak",
  "Groups": [
    {
      "Textures": { "_MainTex": "_MainTex0.png", "_BumpMap": "none" },
      "Floats":   { "_Glossiness": 0.7, "_Cutoff": 0.0, "_BumpScale": 1.0, "_OcclusionStrength": 1.0 },
      "Colors":   { "_Color": {"r": 1, "g": 1, "b": 1}, "_EmissionColor": {"r": 0, "g": 0, "b": 0} }
    }
  ]
}
```

One entry per material group. `"none"` means the slot is unused. Texture files sit in folders named
after the lowercased slot key plus group index (`_maintex0/`). An exporter that re-encodes to PNG
leaves a manifest naming a `.jpg` beside a `.png` on disk, which is why resolution falls back from
exact name, to case-insensitive, to stem, to slot folder.

**legacy**: a raw Unity project upload, `.mat` + `.meta` + `.tga/.jpg/.png/.psd`, sometimes
`meta.asset`. Texture references are Unity GUIDs in the `.mat`, resolved through each file's
`.meta`. Two YAML dialects have to be read at once: Unity 5.x writes `name: _MainTex` /
`second:` blocks, Unity 2017+ writes `- _MainTex:`. Raw normal maps are plain RGB and need repacking
to the DXT5nm layout, which `measure()` reports instead of silently consuming.

Slot vocabulary is Unity's: `_MainTex`, `_BumpMap`, `_SpecGlossMap`, `_MetallicGlossMap`,
`_OcclusionMap`, `_EmissionMap`. Group flags follow the same derivation the reference pipeline uses:
glow means an `_EmissionMap` with a non-black `_EmissionColor`; cutout means `_Cutoff` between 0 and
1 with real see-through pixels in `_MainTex`.

`ItemType` is the item shortname. A new item type breaks the mesh mapping in the viewer pipeline; it does not break this parse.

## What the scan measures

Per texture: dimensions, power-of-two compliance against the published PoT guideline, mode, size,
unique colours, entropy, dominant-colour share (flatness), mean RGB, alpha coverage, cut fraction
at the group's `_Cutoff`, blank-texture detection, edge energy, **seam ratio**, normal packing,
a contrast-boost hint, MD5, and a 64-bit dHash.

Seam ratio is the most useful number here for your use case. A hand-painted tiling pattern closes
across the UV wrap, so its border discontinuity is near its interior contrast. A photograph dropped
onto UVs does not close, and scores several times higher. It is an indicator of "this is somebody
else's image, pasted", measured in one pass with no network.

Then: colour-island crops (marks drawn in a palette the base pattern never uses), ledger matching on
those crops and on whole textures at Hamming distance 6 by default, and skin-name matching against a
marks ledger.

## The licence ledger crawler

The non-commercial clause check has no registry to query, so the corpus is built by hand-configured
crawling. `skinprobe ledger` reads marketplace product pages, extracts the licence block, classifies
it, and hashes each sample image so `--corpus` has something to match.

```bash
.venv/bin/python -m skinprobe ledger --site sites/example-shop.json --out ledger-out --max-items 1 --dry-run
.venv/bin/python -m skinprobe ledger --site sites/example-shop.json --out ledger-out --user-agent "skinprobe-ledger/0.1 (+https://your.site/contact)"
.venv/bin/python -m skinprobe ledger --site sites/example-shop.json --out ledger-out --offline saved-html/
.venv/bin/python -m skinprobe scan skins/ --corpus ledger-out/ledger.jsonl
```

Three files come out of it. `ledger.jsonl` is the rows the scanner consumes, one per sample image that
carried a blocking or conditional clause. `watch.jsonl` is every item visited, with `textSha1`, the
clause labels, and the verbatim quote plus offsets into the captured text. `changes.jsonl` is what
makes the second run worth doing: an item whose `textSha1` moved since last time, which is how a
"personal use only" term added after people already bought the pack becomes visible instead of silent.

A clause is only evidence if it can be re-checked without re-fetching, so every row keeps
`{quote, start, end, textSha1}`. `extract()` discards a clause whose offsets do not resolve inside the
stored text and marks the page `unclear` rather than keeping a pointer that drifted. Absent licence text
is `unknown`, never permissive.

The crawler honours `robots.txt`, spaces requests per host (default 3s plus jitter), uses conditional
GET against its own cache so a repeat run costs nothing, sends a User-Agent you are told to put a
contact address in, and writes every URL it touched to `fetch-log.jsonl` including the ones it was told
not to read. `--offline <dir>` reads saved HTML from a directory instead of the network, which is how the
selftest exercises it and how you can run it on a machine with no route to the shop.

## Limits, stated rather than discovered later

- DDS / KTX are listed, not decoded. A GPU texture decoder is a dependency decision.
- No mesh is read, so UV island placement, rotation and stretch are unmeasured. A mark can hide in a
  stretched island this pass cannot see. Full fidelity needs the item's mesh plus its UV layout.
- A perceptual hash of a whole texture agrees only on gross composition. Distance 6 on a 1024 map is
  a lead, not a match. Crop-level distance is the stronger signal.
- **The non-commercial brush-pattern check is only as good as its ledger.** There is no registry of
  brush packs and their licence clauses, and licence text lives on marketplace pages. Nothing in this
  tool finds a "no commercial resale" clause automatically; it matches against entries you or a
  crawler put in `ledger.jsonl`, each with `sourceUrl` and a `verified` flag. An empty ledger means
  only anomalies are reported. Designing a corpus collector is a separate decision, and it is
  scraping, so it needs your approval.
- Reverse image search is behind a provider seam. `manual` (default) writes a queue of crops to run in
  a browser. The SerpApi and TinEye classes read keys from the environment and raise rather than
  pretend: the Bing Image Search API that this would have used was retired 2025-08-11, and both
  remaining options are metered accounts. Their request shapes are written from published parameters
  and were not exercised from this sandbox.
- The crawler matches text, not contracts. A clause in a page it cannot reach, or one phrased outside
  the built-in patterns, is simply absent from `watch.jsonl`. The pattern list is the current known set
  of ways a licence says no, not a complete one, and it should grow from misses you actually hit.
- dHash is 8x9 difference hashing, 64 bits. Distance 6 is a starting threshold tuned on nothing but
  judgement; measure your own false-positive rate on a few hundred known-clean pairs before you trust
  a cut-off, and record it in the ledger so the threshold is not folklore.
- OCR is not wired. A logo with text is the easiest case to catch and the current build does not do
  it; adding `pytesseract` plus a tesseract binary is roughly 20 lines in `imaging.py`.

## Output

`out/findings.json`, one record per skin: parsed skin (format, item, groups, resolved files, notes),
`textures[]` with every metric above, `logoCandidates[]` with bbox and dHash of each crop file, and
`findings[]` carrying `code`, `severity`, `needsHuman`, and `sources[]` with `verified: false` until a
person opens the link. `out/report.md` is the same content for reading, sorted by severity, closing
with the limits above. Finding codes: `LIC-NC-HIT`, `TM-PIXEL-HIT`, `TM-NAME-HIT`, `COPY-AUTHOR-META`,
`IP-PASTE-SEAM`, `IP-LOGO-CANDIDATE`, `TEC-*`.

## Ledger entry shape

```json
{"id":"nc-brush-14","kind":"nc-license","title":"Grunge Brush Pack 14","owner":"Example Brushes",
 "sourceUrl":"https://example.test/nc-brush-14","licenseClause":"Personal use only, no resale",
 "dhash":"a55aa54c2da35aa5","verified":false}
{"id":"mark-acog","kind":"trademark","mark":"ACOG","sourceUrl":"https://tmdn.example/ACOG","verified":false}
```

`kind` decides the finding code. `verified` decides whether the report says the source was checked.

## Sources for the format facts

`tsgsOFFICIAL/rust-skin-archives` at `main`, cloned from GitHub: `pipeline/RustSkinToGlb/` files
`Program.Weekly.cs` (catalog, diff, SteamCMD ingest, statuses, exit codes), `Program.cs` lines 1536
to 1576 (`ParseManifest`, the field names above), `LegacyImporter.cs` (legacy layout, slot keywords,
GUID rules, 2048 cap), `Program.Flags.cs` (glow and cutout derivation). Facepunch's own
`Creating Skins` wiki page for the texture guidance. Verified 2026-10-10.
