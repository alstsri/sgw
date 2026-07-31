#!/usr/bin/env python3
"""Overhaul sweep — prototype of the OVERHAUL.md architecture.

Pipeline (see OVERHAUL.md):
  broad search (newest-first, adaptive pages)
    -> classify item TYPE from SGW catFullName / title  (free, from list row)
    -> size verdict PER TYPE                            (free on the list row)
    -> detail GET only for kept items whose size is still unknown

Reuses hunt.py's constants + brand/fabric sets so the two stay in sync.
This is a measurement/comparison prototype, not yet wired to export_viewer.

Usage:  python3 overhaulsweep.py [--pages-cap 3] [--limit-terms N] [--output runs/overhaul]
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

import requests

import hunt  # reuse API layer, constants, brand/fabric sets, BUYER_PROFILE

ROOT = Path(__file__).resolve().parent
BP = hunt.BUYER_PROFILE

# ---------------------------------------------------------------------------
# 1. Search terms — organized by INTENT, not by our category buckets.
#    Brands and fabrics are just "what we search"; classification + sizing are
#    always per-result (one code path). No brand x size x garment permutations.
# ---------------------------------------------------------------------------
FABRIC_QUERIES = [
    "cashmere", "alpaca", "mohair", "merino", "vicuna", "guanaco", "qiviut",
    "camel hair", "harris tweed", "donegal tweed", "shetland", "sea island",
    "loro piana", "flannel", "moleskin", "cavalry twill",
]
# Brand queries come straight from the shared quality-brand set — one token each,
# no permutations. Most return < 70 results (probed), so cost is bounded.
BRAND_QUERIES = sorted(hunt.QUALITY_BRANDS)

# Men's Clothing (28) and Shoes (161). Searching the PARENT, never leaf
# subcategories, so Retro/Vintage (167, a child of 28) is included.
CLOTHING_CAT, CLOTHING_LEVEL = 28, 2
SHOES_CAT, SHOES_LEVEL = 161, 1

# ---------------------------------------------------------------------------
# 2. Classification — item TYPE from SGW taxonomy first, title as fallback.
#    catFullName examples seen: "Clothing > Men's Clothing > Blazers",
#    "... > Sweaters > Size XL", "... > Retro/Vintage", "... > Pants > Size 33".
# ---------------------------------------------------------------------------
def classify(cat_full_name: str, title: str) -> str:
    c = (cat_full_name or "").lower()
    # Ambiguous SGW buckets carry no garment type -> go straight to the title.
    ambiguous = any(w in c for w in ("retro", "vintage", "other", "mixed", "lot"))
    if c and not ambiguous:
        t = _type_from_keywords(c)
        if t:
            return t
    return _type_from_keywords(title.lower()) or "unknown"


def _type_from_keywords(s: str) -> str | None:
    # Accessories first — "cable-knit scarf" is an accessory, not knitwear.
    if re.search(r"\b(scarf|muffler|necktie|tie\b|bow\s*tie|belt|socks?|glove|"
                 r"pocket\s*square|wallet|cuff\s*link|suspender|hat|cap\b|beanie)\b", s):
        return "accessory"
    if re.search(r"\b(blazer|sport\s*coat|sportcoat|suit|tuxedo)\b", s):
        return "jacket"
    if re.search(r"\b(outerwear|overcoat|topcoat|peacoat|parka|coat|jacket)\b", s):
        return "jacket"
    if re.search(r"\b(sweater|cardigan|pullover|turtleneck|knit)\b", s):
        return "knit"
    if re.search(r"\bpolo\b", s):
        return "polo"
    if re.search(r"\b(t-shirt|tee|t shirt)\b", s):
        return "tee"
    if re.search(r"\b(dress\s*shirt|button|oxford|ocbd|flannel\s*shirt|shirt)\b", s):
        return "shirt"
    if re.search(r"\bshorts\b", s):
        return "shorts"
    if re.search(r"\b(trousers?|pants?|chinos?|slacks?|jeans|denim)\b", s):
        return "trouser"
    if re.search(r"\b(loafer|oxfords?|derby|boots?|sneakers?|shoes?|footwear)\b", s):
        return "shoes"
    if re.search(r"\b(blanket|throw)\b", s):
        return "blanket"
    if re.search(r"\bvest\b", s):
        return "vest"
    if re.search(r"\b(accessor|hat|cap\b|tie\b|belt|sock|glove|scarf|wallet)\b", s):
        return "accessory"
    return None


# Types we act on; everything else is skipped up front.
WEARABLE = {"jacket", "knit", "polo", "tee", "shirt", "shorts", "trouser", "shoes", "blanket", "vest"}

# ---------------------------------------------------------------------------
# 3. Size — extract the SGW size-leaf (free), then verdict PER TYPE.
#    Verdict: "in" | "out" | "unknown"  (only "unknown" earns a detail GET).
# ---------------------------------------------------------------------------
_SIZE_LEAF = re.compile(r">\s*size\s+([a-z0-9./\- ]+)$", re.I)


def size_leaf(cat_full_name: str) -> str:
    m = _SIZE_LEAF.search((cat_full_name or "").strip())
    return m.group(1).strip() if m else ""


def _alpha_big(s: str) -> bool:
    return bool(re.search(r"\b(medium|large|x-?large|xx-?large|xl|xxl|2xl|3xl)\b", s)) \
        or bool(re.search(r"\bsize\s+[ml]\b", s)) or bool(re.search(r"\b[ml]\s*$", s))


def _alpha_small(s: str) -> bool:
    return bool(re.search(r"\b(x-?small|xs|small)\b", s)) or bool(re.search(r"\bsize\s+s\b", s))


# US jacket sizes in range + "small". Deliberately does NOT accept bare 42/44:
# on a US listing "42" is a US chest (too big); IT 42/44 is only valid with an
# explicit IT/EU marker, which _it_eu_num() checks first.
_JACKET_US_IN = re.compile(r"\b(?:32r|34r|34s|32|33|34|small|xs)\b", re.I)


def _jacket_ok(s: str) -> bool:
    return bool(_JACKET_US_IN.search(s))


# Buyer's jacket measurements (inches), ~size 34. Ranges include tolerance.
# pit-to-pit ~17 & shoulders 17–17.75 ≈ a 34 jacket; sleeve ~24 (shoulder seam
# to cuff) / ~32 (center-back to cuff); full length ~30.
JACKET_MEAS = {
    "pit_to_pit": (15.75, 18.5),     # flat half-chest
    "chest_full": (32.5, 37.0),      # if given as circumference
    "shoulder":   (16.25, 18.5),
    "sleeve_ss":  (22.5, 25.5),      # shoulder seam -> cuff
    "sleeve_cb":  (30.5, 33.5),      # center back -> cuff
    "length":     (28.0, 31.5),
}


def _nums_for(label_re: str, text: str) -> list[float]:
    """Pull the number(s) attached to a measurement label, both orders:
    'pit to pit 17', '17 in pit to pit', 'chest: 22.5"'."""
    out = []
    # Separator stays within one measurement — spaces/colon/dash only, never a
    # comma/semicolon, so "pit to pit, 24 in sleeve" can't grab the sleeve's 24.
    for m in re.finditer(rf"(?:{label_re})[\s:=\-\"]{{0,4}}(\d{{1,2}}(?:\.\d)?)", text):
        out.append(float(m.group(1)))
    for m in re.finditer(rf"(\d{{1,2}}(?:\.\d)?)\s*(?:in|inch|\")?\.?\s*(?:{label_re})", text):
        out.append(float(m.group(1)))
    return out


def jacket_meas_verdict(text: str) -> tuple[str, str]:
    """Verdict for a jacket from labeled measurements. Width (pit-to-pit /
    chest / shoulder) is decisive; a single decisive out kills it."""
    t = text.lower()
    lo, hi = JACKET_MEAS["pit_to_pit"]
    for v in _nums_for(r"pit[\s-]*to[\s-]*pit|\bp2p\b|\bpit\b|armpit", t):
        return ("in", f"pit-to-pit {v}") if lo <= v <= hi else ("out", f"pit-to-pit {v} off")
    for v in _nums_for(r"chest|bust", t):
        if v < 25:  # flat half-chest measurement
            lo, hi = JACKET_MEAS["pit_to_pit"]
            return ("in", f"chest(flat) {v}") if lo <= v <= hi else ("out", f"chest(flat) {v} off")
        lo, hi = JACKET_MEAS["chest_full"]     # circumference
        return ("in", f"chest {v}") if lo <= v <= hi else ("out", f"chest {v} off")
    lo, hi = JACKET_MEAS["shoulder"]
    for v in _nums_for(r"shoulders?", t):
        return ("in", f"shoulder {v}") if lo <= v <= hi else ("out", f"shoulder {v} off")
    return "unknown", "no width measurement"


def _it_eu_num(s: str):
    m = (re.search(r"\b(?:it|ital(?:y|ian)?|eu|euro(?:pean)?)\s*-?\s*(\d{2})\b", s)
         or re.search(r"\b(\d{2})\s*(?:it\b|eu\b|euro)", s))
    return int(m.group(1)) if m else None


def size_verdict(item_type: str, sizes: str, title: str) -> tuple[str, str]:
    """`sizes` = the SGW size-leaf (authoritative when present); `title` is the
    secondary signal. Interpret every number IN THE CONTEXT of item_type."""
    leaf = (sizes or "").lower()
    t = title.lower()
    src = leaf if leaf else t          # prefer the authoritative leaf
    both = f"{leaf} {t}"

    if item_type == "blanket":
        return "in", "not body-fit"

    if item_type in ("knit", "polo", "tee", "vest"):
        if _alpha_small(src):
            return "in", "alpha S/XS"
        if _alpha_big(src):
            return "out", "alpha M/L/XL"
        return "unknown", "no alpha size on row"

    if item_type == "jacket":
        it = _it_eu_num(both)
        if it is not None:
            return ("in", f"IT/EU {it}") if 42 <= it <= 45 else ("out", f"IT/EU {it} too big")
        if _jacket_ok(both):
            return "in", "US 32-34 / small"
        if _alpha_big(src):
            return "out", "alpha M/L/XL"
        nums = [int(n) for n in re.findall(r"(?<!\d)(\d{2})(?![\d])", src)]
        if any(n >= 35 for n in nums):
            return "out", "US jacket >=35"
        return "unknown", "no jacket size on row"

    if item_type in ("trouser", "shorts"):
        w = BP["pants_waist"]
        if re.search(rf"(?<!\d){w}(?!\d)", both) or re.search(rf"\bw{w}\b|\b{w}x\d\d\b", both):
            return "in", f"waist {w}"
        if re.search(r"(?<!\d)(?:2[9]|3[0-9]|4[0-9]|5[0-9]|6[0-9])(?!\d)", src) \
                or re.search(r"\bw(?:2[9]|[3-6]\d)\b|\b(?:[3-6]\d)x\d\d\b", src):
            return "out", "waist 29-69"
        if item_type == "shorts" and _alpha_big(src):
            return "out", "alpha M/L/XL"
        if item_type == "shorts" and _alpha_small(src):
            return "in", "alpha S/XS"
        return "unknown", "no waist on row"

    if item_type == "shirt":
        if re.search(r"\b1[6-8](?:\.5)?\b", src) and not re.search(r"\b15(?:\.5)?\b", src):
            return "out", "neck 16+"
        if re.search(r"\b15(?:\.5)?\b", src):
            return "in", "neck 15/15.5"
        if _alpha_small(src):
            return "in", "alpha S/XS"
        if _alpha_big(src):
            return "out", "alpha M/L/XL"
        return "unknown", "no neck/alpha on row"

    if item_type == "shoes":
        if hunt._shoe_size_too_big(src):
            return "out", "shoe too big"
        if hunt._shoe_size_match(src):
            return "in", "shoe 7.5-8 / EU 40-41"
        return "unknown", "no shoe size on row"

    return "unknown", "unhandled type"


# ---------------------------------------------------------------------------
# 4. Search layer — newest-first, adaptive pagination by itemCount.
# ---------------------------------------------------------------------------
def search(session, query, cat, level, pages_cap, page_size=40):
    """Yield rows newest-first, paging only as deep as itemCount warrants."""
    rows, calls = [], 0
    for page in range(1, pages_cap + 1):
        body = hunt.default_query(query, page, page_size, cat, level)
        body["sortColumn"] = "1"          # newest-listed first (probed)
        body["sortDescending"] = "true"
        resp = session.post(f"{hunt.API_ROOT}/Search/ItemListing", json=body, timeout=30)
        resp.raise_for_status()
        calls += 1
        page_rows = resp.json().get("searchResults", {}).get("items", []) or []
        rows.extend(page_rows)
        total = page_rows[0].get("itemCount", 0) if page_rows else 0
        if len(rows) >= total or len(page_rows) < page_size:
            break
        time.sleep(0.1 + 0.1 * (page % 2))   # light jitter
    return rows, calls


def image_url(row) -> str:
    u = (row.get("imageURL") or "").replace("\\", "/")
    return u


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description="Overhaul sweep prototype.")
    ap.add_argument("--pages-cap", type=int, default=3)
    ap.add_argument("--limit-terms", type=int, default=0, help="0 = all")
    ap.add_argument("--output", default="runs/overhaul")
    ap.add_argument("--no-detail", action="store_true", help="skip detail confirm pass")
    args = ap.parse_args()

    out = ROOT / args.output
    out.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update({"User-Agent": hunt.USER_AGENT})

    terms = [("clothing", q, CLOTHING_CAT, CLOTHING_LEVEL) for q in FABRIC_QUERIES + BRAND_QUERIES]
    terms += [("shoes", q, SHOES_CAT, SHOES_LEVEL) for q in ("Alden", "Crockett Jones", "Edward Green", "goodyear welt")]
    if args.limit_terms:
        terms = terms[:args.limit_terms]

    seen: set[int] = set()
    kept: list[dict] = []
    stats = {"search_calls": 0, "detail_calls": 0, "rows": 0, "unique": 0,
             "drop_type": 0, "drop_reject_brand": 0, "drop_no_interest": 0,
             "drop_out_size": 0, "in_from_row": 0, "unknown_confirmed": 0,
             "unknown_still": 0}

    for scope, query, cat, level in terms:
        try:
            rows, calls = search(session, query, cat, level, args.pages_cap)
        except Exception as exc:
            print(f"  ! search '{query}' error: {exc}")
            continue
        stats["search_calls"] += calls
        stats["rows"] += len(rows)
        for row in rows:
            iid = int(row.get("itemId") or 0)
            if not iid or iid in seen:
                continue
            seen.add(iid)
            stats["unique"] += 1
            title = row.get("title") or ""
            cfn = row.get("catFullName") or ""
            low = f"{title} {cfn}".lower()

            # reject/mall brands out immediately
            if hunt.has_any(low, hunt.REJECT_BRANDS) or hunt.has_any(low, hunt.MALL_BRANDS):
                stats["drop_reject_brand"] += 1
                continue

            itype = classify(cfn, title)
            if itype not in WEARABLE:
                stats["drop_type"] += 1
                continue

            # interest gate: a quality brand or a fabric term must be present
            brands = hunt.has_any(low, hunt.QUALITY_BRANDS)
            fabrics = hunt.has_any(low, hunt.FABRIC_TERMS)
            if not brands and not fabrics:
                stats["drop_no_interest"] += 1
                continue

            leaf = size_leaf(cfn)
            verdict, note = size_verdict(itype, leaf, title)
            if verdict == "out":
                stats["drop_out_size"] += 1
                continue

            rec = {
                "item_id": iid, "type": itype, "title": title,
                "catFullName": cfn, "size_leaf": leaf,
                "url": f"{hunt.ITEM_ROOT}/{iid}",
                "price": row.get("currentPrice"), "bids": row.get("numBids", 0),
                "end_time": row.get("endTime", ""), "image": image_url(row),
                "brands": brands, "fabrics": fabrics,
                "size_verdict": verdict, "size_note": note,
            }

            if verdict == "in":
                stats["in_from_row"] += 1
                kept.append(rec)
            else:  # unknown -> detail confirm only when needed
                if args.no_detail:
                    rec["recommendation"] = "Need measurements"
                    stats["unknown_still"] += 1
                    kept.append(rec)
                    continue
                try:
                    detail = hunt.get_detail(session, iid)
                    stats["detail_calls"] += 1
                    time.sleep(0.15)
                except Exception:
                    kept.append({**rec, "recommendation": "Need measurements"})
                    stats["unknown_still"] += 1
                    continue
                # Confirm against the STRUCTURED size field only — not the
                # description ("small stain") and not measurements ("sleeve 34",
                # "length 33"), whose numbers collide with size numbers. Turning
                # a chest measurement into a jacket size is a separate, labeled
                # step (TODO); until then an unlabeled item stays "unknown".
                size, meas, material, _ = hunt.extract_fields(detail)
                conf = size.strip().lower()
                v2, n2 = size_verdict(itype, leaf, conf) if conf else ("unknown", "no structured size")
                # If size label was inconclusive, fall back to measurements.
                # Jackets have a real spec (buyer ~34); other types would need
                # their own measurement specs (TODO), so leave them unknown.
                if v2 == "unknown" and itype == "jacket" and meas:
                    v2, n2 = jacket_meas_verdict(meas)
                if v2 == "out":
                    stats["drop_out_size"] += 1
                    continue
                rec["size_verdict"], rec["size_note"] = v2, n2
                rec["recommendation"] = "Buy/Watch" if v2 == "in" else "Need measurements"
                stats["unknown_confirmed"] += 1 if v2 == "in" else 0
                stats["unknown_still"] += 1 if v2 != "in" else 0
                kept.append(rec)

    # rank: in-size first, then by presence of brand+fabric
    kept.sort(key=lambda r: (r["size_verdict"] != "in", -(len(r["brands"]) + len(r["fabrics"]))))
    (out / "candidates.json").write_text(json.dumps(kept, indent=2))
    (out / "stats.json").write_text(json.dumps(stats, indent=2))

    print("\n=== overhaul sweep stats ===")
    for k, v in stats.items():
        print(f"  {k:20} {v}")
    print(f"  {'kept':20} {len(kept)}")
    in_size = [r for r in kept if r["size_verdict"] == "in"]
    print(f"  {'in-size kept':20} {len(in_size)}")
    print("\n  top in-size finds:")
    for r in in_size[:15]:
        print(f"    [{r['type']:7}] ${r.get('price')} {r['title'][:60]}  · {r['size_note']}")


if __name__ == "__main__":
    main()
