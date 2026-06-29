#!/usr/bin/env python3
"""Bryan's hunt — XL sweaters / jackets / outerwear from quality makers.

Reuses hunt.py's ShopGoodwill search engine + brand/fabric intelligence,
but applies XL body sizing instead of Adam's Small/34 profile.
"""
import csv
import json
import re
import time
from pathlib import Path

import requests

import hunt  # reuse search engine, brand sets, helpers

# ---------------------------------------------------------------------------
# Bryan profile: XL tops (sweaters, jackets, outerwear)
# ---------------------------------------------------------------------------
# Accept XL/XXL body sizes, plus tailored jacket equivalents (US 46-48 / IT 56-58).
ACCEPT_SIZE_RE = re.compile(
    r"\b("
    r"xl|x-large|x large|xxl|2xl|2x-large|2x large|"
    r"extra\s*large|"
    r"4[678]\s*[rl]?|"                       # US 46/47/48 jackets
    r"5[678]\b|it\s*5[678]|eu\s*5[678]"      # IT/EU 56/57/58
    r")\b",
    re.I,
)
# Reject clearly-wrong sizes in the title
REJECT_SIZE_RE = re.compile(
    r"\b("
    r"x?small|x-small|\bs\b|medium|\bm\b|"
    r"3[0-9]\s*[rl]?|4[0-4]\s*[rl]?|"        # US 30-44 jackets
    r"4[0-4]\b|it\s*4[0-4]|eu\s*4[0-4]|"     # IT/EU 40-44
    r"size\s*7|size\s*8|size\s*9|size\s*10"  # shoe sizes (not tops)
    r")\b",
    re.I,
)

# Search strings: quality makers × XL, for sweaters / jackets / outerwear
SEARCH_GROUPS = {
    "knitwear": {
        "category_id": 28, "category_level": 2,
        "strings": [
            "Loro Piana sweater XL", "Brunello Cucinelli sweater XL",
            "Zegna sweater XL", "Ermenegildo Zegna sweater XL",
            "Canali sweater XL", "Corneliani sweater XL",
            "Drumohr XL", "Inis Meain XL", "William Lockie XL",
            "Johnstons of Elgin XL", "N.Peal cashmere XL",
            "John Smedley XL", "Ballantyne cashmere XL",
            "Pringle Scotland XL", "Malo cashmere XL",
            "Begg & Co XL", "Inverallan XL",
            "Scott & Charters cashmere XL", "cashmere sweater XL",
            "Shetland wool sweater XL", "Aran sweater XL",
        ],
    },
    "tailoring_jackets": {
        "category_id": 28, "category_level": 2,
        "strings": [
            "Canali blazer 48", "Zegna blazer 48", "Brioni blazer 48",
            "Corneliani 48", "Isaia 48", "Boglioli 48", "Caruso 48",
            "Loro Piana jacket 48", "Brunello Cucinelli jacket 48",
            "Hickey Freeman 48", "Oxxford 48", "Samuelsohn 48",
            "Southwick 48", "Paul Stuart 48", "Hackett 48",
            "Ralph Lauren Purple Label 48",
            "Canali 56", "Zegna 56", "Brioni 56", "Isaia 56",
            "harris tweed jacket 48", "cashmere sport coat 48",
            "camel hair blazer 48",
        ],
    },
    "outerwear": {
        "category_id": 28, "category_level": 2,
        "strings": [
            "Barbour XL", "Barbour XXL", "Belstaff XL",
            "Private White VC XL", "Mackintosh coat XL", "Grenfell XL",
            "Crombie overcoat XL", "Aquascutum XL", "Daks coat XL",
            "Filson Mackinaw XL", "Filson cruiser XL",
            "Schott XL", "RRL XL", "Pendleton coat XL",
            "Woolrich wool XL", "Loro Piana coat XL",
            "Zegna overcoat XL", "Canali overcoat XL",
            "camel hair overcoat XL", "cashmere overcoat XL",
            "shearling jacket XL", "waxed cotton jacket XL",
            "harris tweed coat XL",
        ],
    },
}


def size_ok(title: str, description: str) -> tuple[bool, str]:
    """Accept if XL signal present and no strong wrong-size signal in title."""
    t = title.lower()
    if REJECT_SIZE_RE.search(t) and not ACCEPT_SIZE_RE.search(t):
        return False, "wrong size in title"
    blob = f"{title} {description}"
    if ACCEPT_SIZE_RE.search(blob):
        return True, "XL/XXL or 46-48/IT56 size match"
    return False, "no XL size signal"


def assess_bryan(detail: dict, category: str) -> dict:
    title = detail.get("title") or ""
    desc = hunt.clean_text(detail.get("description"))
    text = f"{title} {desc}".lower()

    brands = hunt.has_any(text, hunt.QUALITY_BRANDS)
    fabrics = hunt.has_any(text, hunt.FABRIC_TERMS)
    reject = hunt.has_any(text, hunt.REJECT_BRANDS)
    mall = hunt.has_any(text, hunt.MALL_BRANDS)

    ok, size_reason = size_ok(title, desc)

    maker = min(10, 2 + min(len(brands), 4) * 2)
    fabric = min(10, 2 + min(len(fabrics), 4) * 2)
    fit = 8 if ok else 2
    price = detail.get("currentPrice", {}).get("amount") if isinstance(detail.get("currentPrice"), dict) else None
    value = 8 if (price is not None and price <= 40) else 6 if (price is not None and price <= 90) else 4
    if reject:
        maker = min(maker, 2); fit = min(fit, 1)
    if mall:
        maker = min(maker, 4)

    scores = [fit, fabric, maker, value]
    avg = sum(scores) / len(scores)

    if reject or not ok:
        rec = "Skip"
    elif avg >= 7.0 and brands:
        rec = "Buy"
    elif avg >= 5.8:
        rec = "Watch"
    elif avg >= 4.8:
        rec = "Need measurements"
    else:
        rec = "Skip"

    reasons = []
    if brands: reasons.append("maker: " + ", ".join(brands[:4]))
    if fabrics: reasons.append("fabric: " + ", ".join(fabrics[:4]))
    reasons.append(size_reason)
    flags = []
    if reject: flags.append("reject brand: " + ", ".join(reject))
    if mall: flags.append("low-upside: " + ", ".join(mall))

    return {
        "total_score": round(avg, 2),
        "recommendation": rec,
        "match_reasons": " | ".join(reasons),
        "red_flags": " | ".join(flags),
        "size_ok": ok,
    }


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="runs/bryan_latest")
    parser.add_argument("--per-query", type=int, default=10)
    parser.add_argument("--pages-per-query", type=int, default=2)
    args = parser.parse_args()

    out = Path(args.output)
    if not out.is_absolute():
        out = Path(__file__).resolve().parent / out
    out.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers["User-Agent"] = hunt.USER_AGENT

    seen: set[int] = set()
    candidates: list[dict] = []
    total = sum(len(g["strings"]) for g in SEARCH_GROUPS.values())
    i = 0

    for category, group in SEARCH_GROUPS.items():
        for query in group["strings"]:
            i += 1
            try:
                items = hunt.search_items(
                    session, query, args.per_query, args.pages_per_query,
                    group["category_id"], group["category_level"],
                )
            except Exception as exc:
                print(f"[{i}/{total}] {category}: '{query}' ERROR {exc}")
                continue
            if items:
                print(f"[{i}/{total}] {category}: '{query}' → {len(items)} results")
            for item in items:
                iid = item.get("itemId")
                if not iid or iid in seen:
                    continue
                seen.add(iid)
                title = item.get("title", "")
                # Title-level brand reject (cheap)
                if any(b in title.lower() for b in hunt.REJECT_BRANDS):
                    continue
                try:
                    detail = hunt.get_detail(session, iid)
                except Exception:
                    continue
                a = assess_bryan(detail, category)
                if a["recommendation"] == "Skip":
                    continue
                cur = detail.get("currentPrice")
                price = cur.get("amount") if isinstance(cur, dict) else cur
                candidates.append({
                    "item_id": iid,
                    "category": category,
                    "query": query,
                    "title": detail.get("title", ""),
                    "url": f"https://shopgoodwill.com/item/{iid}",
                    "current_price": price,
                    "end_time": detail.get("endTime", "")[:19],
                    "recommendation": a["recommendation"],
                    "total_score": a["total_score"],
                    "match_reasons": a["match_reasons"],
                    "red_flags": a["red_flags"],
                })
                time.sleep(0.1)

    candidates.sort(key=lambda c: c["total_score"], reverse=True)
    (out / "candidates.json").write_text(json.dumps(candidates, indent=2))
    if candidates:
        with (out / "candidates.csv").open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(candidates[0].keys()))
            w.writeheader()
            w.writerows(candidates)
    print(f"\nDone. {len(candidates)} candidates → {out}")


if __name__ == "__main__":
    main()
