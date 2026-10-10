# Writing a site config

One JSON file per marketplace. The crawler is config-driven rather than hard-coded because selectors
 rot the moment a site redesigns, and a file you can edit is cheaper than a patch.

## Matching rules

`itemUrlPatterns`, `skipUrlPatterns` and `followListingPatterns` share one matcher:

- a pattern containing `*`, `?` or `[` is a glob, tried against the URL **path** and against the full URL
- anything else is a plain substring of the full URL

So `/brushes/*` matches `https://shop.test/brushes/grunge-14` and does **not** match the category page
`https://shop.test/brushes`, which is what keeps a listing a listing. A URL that matches
`itemUrlPatterns` is treated as a product and never crawled further, so make the item pattern specific
before you raise `maxDepth`.

## Fields

| Field | Default | Meaning |
|---|---|---|
| `name` | required | becomes the `site` field on every row and the `id` prefix |
| `startUrls` | required | seeds for the walk |
| `itemUrlPatterns` | required | what counts as a product page |
| `skipUrlPatterns` | `[]` | cart, login, search, account: never fetch these |
| `followListingPatterns` | `[]` | if set, only these URLs are crawled for links |
| `maxDepth` | 2 | hops from a start url. 0 means start urls only |
| `maxItems` | 25 | product pages fetched per run, hard cap |
| `minIntervalSec` | 3.0 | delay between requests **per host** |
| `respectRobots` | true | set false only where you have written permission, and keep the proof |
| `licenceSelectors` | `[]` | CSS selectors for the licence block. First one that yields over 40 characters wins |
| `imageSelectors` | `[]` | extra selectors for sample images, beyond `og:image`, `img src/srcset`, `data-src` |
| `imageHostAllow` | `[]` | host suffix allow-list for image fetches. Empty means any host, which is rarely what you want |
| `maxImagesPerItem` | 3 | sample images hashed per product |

## Before the first live run

1. Read the site's terms of service, and its `robots.txt`. This crawler honours `robots.txt` by default
   and writes every blocked URL into `fetch-log.jsonl` with `source: "blocked"`.
2. Run one page: `--max-items 1 --dry-run`. You get a walk report and no files.
3. Check `watch.jsonl` for one product by hand. Confirm the recorded quote really is on that page, and
   that the status is right, before you let it run over a category.
4. Keep `minIntervalSec` at 3 or above. You are reading their shop, not your own disk.
5. Set a User-Agent with a contact address. Anonymous traffic that looks like nobody is the traffic
   that gets an IP block.

## What the crawler deliberately does not do

- It does not log in, run JavaScript, or use a headless browser. A site whose licence text only appears
  after JS execution needs a saved-HTML import instead: put the page in a directory and pass `--offline`.
- It does not fetch behind a paywall or download the product itself, only the page and its sample images.
- It does not decide anything. `licenceStatus` is a classification of text, `verified` stays `false`
  until a person sets it, and a page with no licence text is recorded as `unknown`, never as permissive.
