# ShopGoodwill Hunter — Algorithm Overhaul (design)

Status: **draft / planning** · Branch: `algorithm-overhaul` · Author started: 2026-07-31

This document is the design brief for reworking `hunt.py`. It is written to be
picked up cold in a future session (likely with a stronger model). Read it top to
bottom before touching code. Nothing here is implemented yet.

---

## 1. Goals, in priority order

1. **API-call efficiency.** Fewer HTTP requests per sweep → faster sweeps and a
   much lower chance of being rate-limited or flagged by the SGW backend. This is
   the top priority.
2. **Correct sizing.** Stop surfacing items in the wrong size. Today's recurring
   bug class is size tokens interpreted against the wrong garment type (e.g. "34"
   read as a jacket chest when the item is a pair of pants; EU trouser sizes 50+;
   "short sleeve" misrouted into the trouser branch).
3. **Elegance.** A small, legible pipeline: broad search → classify by item type →
   filter by size-for-that-type. Brands/fabrics become *filters*, not *queries*.

Everything below serves those three, in that order.

---

## 2. How it works today (baseline to replace)

**Shape:** `SEARCH_GROUPS` is a dict of ~9 hand-curated categories (`shoes`,
`tailoring_outerwear`, `workwear`, `knitwear`, `accessories`, `shirts`,
`loungewear_basics`, `pants`, `blankets`). Each group hard-codes a `category_id`,
`category_level`, and a long list of literal query `strings` (~372 total, many of
them `"<Brand> 34"` permutations).

**Loop** (`main()`, ~line 1609):
```
for group in SEARCH_GROUPS:
  for query in group.strings:                     # ~372 searches
    items = search_items(query, cat_id, pages=2)  # POST /api/Search/ItemListing
    for item in items:
      dedup on itemId
      pre_fetch_reject(group_category, title)     # cheap title filter
      if survives: get_detail(itemId)             # GET per survivor
                   build_candidate → assess
```

**Measured cost per sweep** (derive exact numbers from `runs/local_adam/search_log.json`):
- ~372 search POSTs × up to 2 pages ≈ **400–500 search calls**.
- **~350–600 detail GETs** (one per unique item surviving `pre_fetch_reject`;
  last sweep produced 357 candidates).
- Plus evidence fetches. **≈ 850–1000 requests per sweep**, sequential, fixed
  `time.sleep(0.1–0.2)`, single static User-Agent, no jitter, no incremental
  state. This is the pattern that is slow and easy to fingerprint.

**Root problems:**

- **P1 — Query fan-out.** Hundreds of brand+size permutation queries. Most rare
  brands return 0–2 results, so we spend a full request to learn nothing. This is
  the dominant, most fingerprint-able cost.
- **P2 — Category is assigned by the query, not the item.** An item's size gate is
  chosen from *which group's query found it*. A dress shirt pulled in by a
  tailoring brand query is scored as `tailoring_outerwear` and gets the jacket
  size gate. **This is the direct cause of the sizing bugs fixed piecemeal on
  `main` (RL bottoms, EU designer pants, "short sleeve" misroute).**
- **P3 — A detail GET for every survivor.** We fetch the full item detail before
  we've used everything the *list* payload already gives us.
- **P4 — No adaptivity.** `pages-per-query` is a fixed constant: rare queries
  waste a page-2 call; high-yield queries ("cashmere sweater" = 80+ results) are
  truncated at 2 pages and miss inventory.
- **P5 — No incremental state.** Every sweep re-fetches the same standing
  inventory from scratch. Nothing remembers what was already seen yesterday.

---

## 3. SGW search architecture — what we actually get (verified 2026-07-31)

Probed `POST /api/Search/ItemListing` (`search_items`) with one broad query. Each
returned **list item** already contains (no detail call needed):

| field | example | use |
|---|---|---|
| `title` | `Men's Mantovani Studio Large Gray Pure Italian Cashmere Crew` | brand/fabric/size-token matching |
| `catFullName` | `Clothing > Men's Clothing > Sweaters` | **authoritative item type** |
| `categoryId` / `categoryName` | `149` / `Sweaters` | **authoritative item type** |
| `catLevelNum` | `3` | taxonomy depth |
| `currentPrice`, `buyNowPrice`, `minimumBid`, `startingPrice`, `discountedBuyNowPrice` | | price scoring, no detail needed |
| `numBids`, `endTime`, `remainingTime`, `startTime` | | urgency + **incremental "new since last sweep"** |
| `imageURL` | | viewer (image-first) |
| `itemId`, `sellerId`, `itemCount` | `itemCount: 179` | dedup, seller rules, **adaptive pagination** |
| `description` | **`None`** | ⚠️ NOT in list payload — size-in-description still needs a detail GET |

**Consequences that drive the redesign:**

- **Item *type* is free.** `categoryId` / `catFullName` come from SGW's own
  taxonomy on every list row. Classify by that, and P2 disappears — type no longer
  depends on which query found the item.
- **Title-level filtering is free.** Brand, fabric, and any size token *in the
  title* can be matched on the list row. Only items that pass type+size on the
  title AND still need description-confirmation should cost a detail GET → attacks
  P3.
- **`itemCount` enables adaptive pagination** → attacks P4.
- **`startTime`/`endTime` enable incremental sweeps** (only process rows newer
  than the last run) → attacks P5.
- Request knobs available in `default_query` we under-use: `sortColumn` /
  `sortDescending` (sort newest or ending-soonest), `lowPrice`/`highPrice`,
  `searchBuyNowOnly`, `searchDescriptions` (currently `false` = title-only search).

**To verify next session (cheap probes, 1 call each):**
- Full category-id map for Men's Clothing (28) children and Shoes (161), Blankets.
  Build `categoryId → item_type` from real ids (we know 149=Sweaters; enumerate
  the rest). **Explicitly locate the Vintage bucket(s)** — is there a
  `Men's Clothing > Vintage` child under 28, and/or a separate top-level Vintage
  category? Note their ids and whether a 28-parent sweep already includes them.
- Max `pageSize` the endpoint honors (we use 10; if 40–100 works, far fewer calls).
- What `sortColumn` values mean (newest-listed vs ending-soonest) — needed for the
  incremental sweep.
- Whether `searchText` supports any OR/quoting (assume **AND-only** until proven;
  it dictates that brands can't be OR-ed into one query → reinforces "brands are
  filters, not queries").

---

## 4. Target architecture

Core idea: **decouple the *search axis* from the *classification axis* from the
*size axis*.** Today all three are collapsed into the query string. Split them.

```
BROAD SEARCH  →  CLASSIFY (by SGW category)  →  SIZE-FILTER (per type)  →  confirm
  (few calls)      (free, from list row)         (free on title;           (detail GET
                                                  detail only if needed)     only here)
```

### 4.1 Search layer — broad, adaptive, incremental

- **Replace ~372 brand queries with a small set of broad, high-yield sweeps.**
  Two complementary sources:
  1. **Category sweeps** — for each target top-level category (Men's Clothing 28,
     Shoes 161, Blankets/Home), page through *newest-listed* rows incrementally.
     **Search at the parent level (28), never scoped to leaf subcategories** — a
     vintage cashmere sweater filed under *Men's Clothing > Vintage* would be
     invisible to a Sweaters-only sweep. We read the item's real type from its
     `categoryId` *after* the broad search, which is the right place to narrow.
     (If a top-level Vintage area sits *outside* 28, add it as its own sweep.)
  2. **Fabric/generic term queries** — a short curated list (`cashmere`, `alpaca`,
     `mohair`, `merino`, `vicuna`, `linen`, `tweed`, `flannel`, `corduroy`, …) to
     catch quality items whose category is generic but whose title signals value.
- **Brands stop being queries.** The `QUALITY_BRANDS` set becomes purely a
  client-side *filter/scorer* over titles we already fetched. This removes the
  bulk of the fan-out (P1) and the flagging surface, and it *increases* recall for
  brands whose listings don't put the brand in a size-permuted phrasing.
- **Adaptive pagination** using `itemCount`: pull `ceil(min(itemCount, cap)/pageSize)`
  pages. Rare term → 1 page. High-yield term → several, capped. `log()` when a cap
  truncates so we never silently under-cover.
- **Incremental state** (biggest anti-flag + speed win): persist a small
  `state.json` (last-run timestamp + rolling seen-set of itemIds). Each sweep sorts
  newest-first and **stops paging once it reaches rows older than last run**. Day
  two only touches genuinely new inventory → an order-of-magnitude fewer requests.
- **Politeness:** jittered sleeps (randomized, not fixed 0.15s), a realistic UA,
  optional cap on total requests/sweep. (`Math.random`/`Date.now` caveats are for
  Workflow scripts, not this standalone Python — real jitter is fine here.)

### 4.2 Classification layer — by SGW taxonomy, free

- Build `ITEM_TYPE` from `categoryId` / `catFullName` first (authoritative),
  falling back to title keywords only when the category is too generic.
- **Type-ambiguous categories are common and matter:** `Men's Clothing > Vintage`,
  `> Other`, `> Mixed Lots`, and any top-level Vintage area carry no garment type.
  A vintage cashmere sweater is often filed under *Vintage*, not *Sweaters*. For
  these rows the **title-keyword classifier is the primary path**, not a rare
  fallback — so it must be robust, not an afterthought.
- Canonical types: `jacket` (blazer/sportcoat/suit/coat/outerwear), `trouser`,
  `shorts`, `shirt` (dress/button), `polo`, `tee`, `knit` (sweater/cardigan),
  `shoes`, `blanket`, `accessory`. Each maps to exactly one size gate.
- This single change retires the whole family of "wrong query → wrong gate" bugs.

### 4.3 Size layer — interpret tokens *within* the resolved type

- Restructure `BUYER_PROFILE` into a **per-type size spec** (single source of
  truth), e.g.:
  ```
  jacket:  US {32R, 34S, 32, 34}  · IT {42, 44}          reject US≥35 / IT≥46
  trouser: waist 28 (US) ≈ IT 44                          reject any 30–69 waist
  shorts:  waist 28                                       (same as trouser)
  shirt:   neck 15 (15.5 exceptional makers only)         reject ≥16 neck
  knit/polo/tee: alpha S / XS                             reject M/L/XL/2XL
  shoes:   US 7.5 & 8                                     reject <7 / >8.5
  blanket: n/a (not body-fit)
  ```
  (Values consolidate the notes in `sgw-hunter.md` — jacket 32R/34S, IT42/44;
  pants waist 28; neck 15; shoes 7.5–8. Confirm before coding.)
- **One size parser** that extracts candidate tokens (`34`, `34R`, `15.5`,
  `34x32`, `IT 52`, `Large`, `M`) and interprets each **in the context of the
  item type** — so "34" is a chest number for a `jacket` and a waist number for a
  `trouser`/`shorts`. This is the crux of priority #2 and is exactly the ad-hoc
  logic currently smeared across `pre_fetch_reject` / `assess`.
- **Measurements are a distinct, labeled path — never raw number matching.**
  A jacket's "sleeve 34" / "length 33" must not be read as a size 34/33; a
  description's "small stain" must not be read as size Small. Parse *labeled*
  measurements and compare to the buyer's spec. **Buyer jacket spec (≈ size 34):**
  - pit-to-pit (flat half-chest) **~17"** (accept ~15.75–18.5)
  - shoulder seam-to-seam **17–17.75"** (accept ~16.25–18.5)
  - sleeve **~24"** (shoulder seam → cuff) or **~32"** (center-back → cuff)
  - full length **~30"**
  Width (pit-to-pit / chest / shoulder) is decisive. A "chest 22" is a *flat*
  half-measure (= 44" round = too big); "chest 35" is a circumference (in range).
  Other item types will each need their own measurement spec (TODO).
- **Three-way size verdict per item:** `in_size` / `out_of_size` /
  `unknown_needs_detail`. Only `unknown_needs_detail` earns a detail GET.

### 4.4 Detail layer — confirmation only

- Fetch detail **only** for items that (a) pass type + brand/fabric interest AND
  (b) are size-`unknown` from the title/category alone. Everything decidable from
  the list row skips the GET entirely. This is the main lever on P3.
- Detail is then used for: size in description, measurements, men's-vs-women's
  verification, condition/red-flags — the checks that genuinely need the body text.

### 4.5 Query tiers (the "rare vs high-result" ask)

Formalize three tiers so each query type is handled by cost:
- **Sweep** (category, newest-first, incremental): the workhorse; adaptive depth.
- **Broad term** (fabric/generic/brand): 1–N pages by `itemCount`, capped.
- **Targeted** (only for a niche broad sweeps provably miss): single page, kept
  deliberately tiny. Prefer promoting a brand to the client-side filter over
  adding a targeted query.

### 4.6 Organize search terms by *intent*, not by our category buckets

Today's `SEARCH_GROUPS` organizes queries by *our* category (`knitwear`,
`shirts`, …), and that bucket then wrongly stamps each result's type (P2). Reorganize
around what the term *means* — because different intents want different breadth and
different type-handling:

- **Brand intent** — "I want *any* men's item from this maker, in my size."
  A brand is one entry that searches the maker across *all* men's categories and
  returns mixed types (a Sandro search yields sweaters, shirts, blazers, trousers).
  We then classify each result by SGW type (§4.2) and apply that type's size gate
  (§4.3). No `"<Brand> sweater"` / `"<Brand> 34"` permutations — those both
  under-recall (miss other garments) and mis-size (stamp one gate on everything).
  This is the generalization of the earlier "just search `Sandro` and filter"
  decision. In practice most brands can live purely as **client-side filters** over
  the category/fabric sweeps; reserve an actual per-brand *query* only for makers
  whose inventory the broad sweeps provably miss (niche brand, generic-category
  listings, brand-in-title-only). Either way the item's type and size come from the
  item, never from the brand term.

- **Fabric intent** — "I want this material in a garment I wear." Broad term query;
  classify + size-filter per result. (`cashmere`, `alpaca`, `vicuña`, `linen`, …)

- **Garment intent** — "I want this specific garment type." Naturally scoped to one
  type; still confirm size within that type. (`cashmere sweater`, `OCBD shirt 15`)

- **Category intent** — "everything newly listed in this category," incremental.

Concretely, the term registry becomes something like
`{ term, intent, category_scope, page_cap }` with intent driving breadth and cost,
while **classification and sizing are always per-result** — one code path, not one
per bucket. A brand entry and a fabric entry differ only in *what they search*, not
in *how results are typed or sized*.

---

## 5. Expected outcome

- Requests/sweep from ~850–1000 down to **low hundreds on day one and tens on
  subsequent incremental sweeps** (exact numbers depend on category volume + caps —
  measure and record).
- Sizing correctness handled *structurally* (type-first) instead of by accreting
  reject regexes.
- `hunt.py` shrinks: the giant `SEARCH_GROUPS` string lists collapse into a short
  sweep spec + the existing `QUALITY_BRANDS`/`FABRIC_TERMS` sets reused as filters.

---

## 6. Phased plan (keep `main` shippable throughout)

1. **Probe & map** (§3 open questions). Write findings back into this doc. Cheap.
2. **Classifier** `categoryId/catFullName → item_type`, unit-tested against a saved
   sample of list rows. No behavior change yet.
3. **Per-type size spec + one size parser**, with a `in/out/unknown` verdict.
   Port the today's-fixes test cases (RL bottoms, EU pants, short-sleeve, 15.5
   necks) as regression tests — they must all still pass.
4. **Broad+incremental search layer** behind a flag; run side-by-side with the old
   path and diff candidate sets before switching over.
5. **Cut detail calls** to size-`unknown` only; measure request counts before/after.
6. Delete the brand-permutation queries; keep brands as filters. Retire dead code.

Each phase is independently commit-able and testable; `run_sweep.sh` stays the
entry point.

---

## 7. Risks / watch-items

- **Broad sweep volume**: category 28 may list many hundreds/day. Incremental
  (newest-first, stop-at-last-run) is what keeps this bounded — build it early.
- **Coverage regressions**: a brand previously found by a dedicated query must
  still surface via broad sweep + client filter. Phase 4's side-by-side diff is
  the guard; `log()` every cap/truncation (no silent under-coverage).
- **Category taxonomy gaps / Vintage**: many good items sit in `Vintage`, `Other`,
  or `Mixed Lots` categories that carry no garment type. Two consequences: (a)
  never scope searches to leaf subcategories or we miss them; (b) the title-keyword
  classifier is a *primary* path for these rows, not a fallback — invest in it.
- **Anti-flag balance**: broader queries return more rows but far fewer *requests*;
  keep jitter + a per-sweep request cap so we never spike.
- **Sizing edge cases**: EU vs US number collisions (IT 44 trouser = US 28) — the
  type-aware parser must treat an explicit IT/EU marker differently from a bare
  number. Carry the today's-fixes tests forward.

---

## 8. Prototype results — `overhaulsweep.py` (2026-07-31)

A first working prototype of §4 exists as `overhaulsweep.py` (reuses `hunt.py`'s
API layer + brand/fabric sets). It implements: broad term search (newest-first,
adaptive pages) → classify by `catFullName`/title → per-type size verdict
(in/out/unknown) → detail GET only for `unknown` → confirm via structured **size**
field, then **jacket measurements**.

**Measured (full run, `--pages-cap 3`, brand+fabric terms):**
- **272 search + 448 detail = ~720 requests** — ≈ parity with the old ~730, **but
  over 2,104 unique items (~2× coverage)** and with correct per-item sizing.
- The detail calls are the remaining cost: **407 items stayed `unknown` even after
  a detail fetch** (no structured size, no labeled measurements) → those GETs were
  unproductive.

**Lessons that sharpen the plan:**
- Classifying type from `catFullName` works well; **the size-leaf (`… > Size 34R`)
  gives many verdicts with zero detail calls** — lean on it hard.
- **Never verdict off freeform description or raw measurements.** Confirmed bugs
  found & fixed in the prototype: "sleeve 34"/"length 33" read as size 34;
  "small stain" read as Small; bare `42/44` read as IT (valid only with an
  explicit IT/EU marker). Size must come from the size-leaf, the structured size
  field, or *labeled* measurements — nothing else.
- **The two big remaining efficiency levers (not yet built):**
  1. **Incremental state** — persist seen-ids + last-run time; sort newest-first
     and stop at the last-run boundary. This is what turns the daily ~720 into
     *tens*. Highest priority next.
  2. **Don't spend a detail GET on an item that will stay `unknown`.** Prefer
     items whose size is decidable from the row; for the rest, either rank-limit
     how many `unknown`s we confirm, or gate detail on stronger interest signals.
- Brand-as-query still fans out (~235 terms). Moving brands fully to client-side
  filters over incremental category sweeps (§4.1/§4.6) is the way to shrink that.

Run it: `python3 overhaulsweep.py --pages-cap 3` (add `--limit-terms N` /
`--no-detail` for quick trials). Output: `runs/overhaul/{candidates,stats}.json`.

## 9. Reference — current code map (`hunt.py`)

- `SEARCH_GROUPS` (~227) — to be replaced by the sweep spec.
- `QUALITY_BRANDS` (~125), `FABRIC_TERMS` (~193), `MALL_BRANDS`/`REJECT_BRANDS`
  (~202) — reuse as client-side filters.
- `BUYER_PROFILE` (~top) — restructure into the per-type size spec (§4.3).
- `default_query` (944), `search_items` (1002), `get_detail` (1027) — API layer;
  add adaptive pagination + incremental sort here.
- `pre_fetch_reject` (690), `_reject_alpha_size` (650), `_reject_shirt_neck` (681),
  `assess` (1159) — the size/sizing logic to consolidate into the type-aware parser.
- `main()` (1585) — the loop to rewrite as sweep → classify → size → (detail).
- Outputs (`save_outputs`, `export_viewer.py`) — unchanged contract:
  `docs/data/adam.json` is the tracked artifact served via GitHub Pages.
