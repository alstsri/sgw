# sgw-hunter

A Python script that searches for quality men's clothing and home goods using the site's buyer API. No scraping, no browser automation — plain HTTP against the same JSON endpoints the site itself uses.

## What it does

`hunt.py` runs a large library of atomic search strings across categories (shoes, tailoring, outerwear, workwear, knitwear, shirts, pants, accessories, blankets), filters results against your size profile and a reject list, fetches detail data for promising candidates, scores each item across multiple dimensions, and writes ranked output files.

## Requirements

- Python 3.10+
- [requests](https://pypi.org/project/requests/)
- [openpyxl](https://pypi.org/project/openpyxl/)

```
pip install requests openpyxl
```

## Quick start

```bash
git clone https://github.com/alstsri/sgw.git
cd sgw
pip install requests openpyxl
# Edit BUYER_PROFILE in hunt.py to match your sizes
python hunt.py
```

The script creates a `runs/` directory next to `hunt.py` automatically — no setup needed. Each run writes to a new `runs/full_YYYY-MM-DD/` subfolder. You can override the output path:

```bash
python hunt.py --output /path/to/my/results
```

## Buyer profile

At the top of `hunt.py` is a single config block. Edit this before your first run.

```python
BUYER_PROFILE = {
    # Footwear
    "shoe_sizes": ["10", "10.5", "11"],          # US men's sizes to match against listings

    # Tailoring
    "jacket_sizes_us": ["40R", "40L", "42R"],    # US coat/jacket sizes
    "jacket_sizes_it": ["50", "52"],             # Italian/European suit sizing equivalents
    "shirt_neck": ["15.5", "16"],                # Dress shirt neck sizes in inches

    # Pants
    "pants_waist": ["32", "33"],                 # Waist in inches; inseam matched loosely

    # General
    "body_size": ["L", "XL"],                    # Casualwear size labels for knitwear, shirts, etc.
}
```

The script uses these values to gate search strings before making detail API calls. If a listing title contains none of your valid sizes for its category, it is rejected pre-fetch.

## APIs used

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `buyerapi.shopgoodwill.com/api/Search/ItemListing` | Search by keyword, returns paginated listing summaries |
| GET | `buyerapi.shopgoodwill.com/api/itemDetail/GetItemDetailModelByItemId/{id}` | Full item detail including description, condition, images |

No authentication is required. The script adds a 150ms delay between requests.

## Search string philosophy

Searches use brand-plus-size atomic queries rather than broad category browsing. For example: `"Canali 42R"`, `"Alden 10.5"`, `"Barbour L"`. This keeps result sets small and precise, avoids sifting through thousands of irrelevant listings, and works well with how sellers title items on the platform.

Searches run against the broad **Men's Clothing** category rather than subcategories, since seller categorization on Goodwill sites is inconsistent. A pre-fetch title filter (`REJECT_BRANDS` list plus size gates) drops obvious misses before the more expensive detail API call is made.

Categories covered: shoes, tailoring and outerwear, workwear, knitwear, shirts, pants, accessories, blankets (the last category writes to a separate output file).

## Scoring

Each candidate that passes the pre-fetch filter and detail fetch is scored on:

- **Fit** — size match quality against your profile
- **Fabric quality** — material signals from title and description
- **Maker quality** — brand tier
- **Condition** — listed condition grade and description language
- **Value** — current bid vs. estimated retail
- **Rarity** — how often this item category/brand appears on the site
- **Taste fit** — style alignment with the configured aesthetic targets

Scores feed the ranked sections of `report.md`.

## Output files

All output writes to `runs/<ISO-timestamp>/`.

| File | Contents |
|------|----------|
| `candidates.csv` | All scored clothing candidates, one row per item |
| `blankets.csv` | Home goods / blankets scored separately |
| `candidates.json` | Full scored candidate data as JSON |
| `candidates.xlsx` | Color-coded spreadsheet: green = Top Pick, yellow = Maybe, gray = Rejected |
| `report.md` | Human-readable ranked report: Top Picks, Maybe, Rejected sections with item links |

The `runs/` directory is listed in `.gitignore` — it contains personal shopping data and should not be committed.
