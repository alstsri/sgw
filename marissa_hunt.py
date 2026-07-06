#!/usr/bin/env python3
"""Marissa's hunt — women's quiet-luxury / avant-garde / textile-forward finds.

Reuses hunt.py's ShopGoodwill search engine. Women's Clothing (cat 27) and
Women's Shoes (cat 162). Sizing: shoes US 7.5 / EU 38; clothing XS/S (M/L when
oversized/boxy/artwear). Prioritizes obscure makers, natural fibers, and
textile terms (tapestry, gobelin, jacquard, brocade, chenille, velvet).
"""
import argparse
import csv
import json
import re
import time
from pathlib import Path

import requests

import hunt  # reuse search engine + helpers

WOMENS_CLOTHING = (27, 2)   # (category_id, category_level)
WOMENS_SHOES = (162, 3)

# ---------------------------------------------------------------------------
# Marissa profile
# ---------------------------------------------------------------------------
BUYER_PROFILE = {
    "shoe_accept": ["7.5", "38", "37.5", "38.5"],
    "shoe_maybe": ["8", "39"],          # boots / narrow / if measures smaller
    "shoe_reject_eu": [40, 41, 42, 43], # ~US 9+ unless proven 7.5
    "shoe_reject_us": [9, 9.5, 10, 10.5, 11],
    "clothing_accept": ["xs", "small", "s", "petite", "p"],
    "clothing_oversize_ok": ["medium", "m", "large", "l"],  # only if oversized/boxy/artwear
}

# Oversized-silhouette signals that make M/L acceptable for jackets
OVERSIZE_SIGNALS = {
    "oversized", "oversize", "boxy", "kimono", "haori", "lagenlook", "artwear",
    "art to wear", "art-to-wear", "drapey", "draped", "cocoon", "tent",
    "relaxed", "swing", "duster", "caftan", "kaftan", "tunic", "structured",
}

# ---------------------------------------------------------------------------
# Brand intelligence
# ---------------------------------------------------------------------------
QUALITY_BRANDS = {
    # shoes — European / artisan
    "thierry rabotin", "arche", "pas de rouge", "la canadienne", "aquatalia",
    "chie mihara", "pedro garcia", "robert clergerie", "clergerie", "trippen",
    "officine creative", "marsell", "marsèll", "guidi", "moma", "pikolinos",
    "wonders", "hispanitas", "lodi", "unisa", "camper",
    "gabor", "ara", "beautifeel", "l'amour des pieds",
    "aeyde", "atp atelier", "dear frances", "freda salvador", "labucq",
    "emme parsons", "coclico", "repetto", "pretty ballerinas", "anniel",
    "bobbies", "jonak", "miista", "intentionally blank", "paloma wool",
    "hereu", "adieu", "jacques soloviere", "jacques solovière", "no. 6",
    "troentorp", "sanita", "sven", "kork-ease", "kork ease", "beek",
    "diemme", "fracap", "danner", "lowa", "hanwag", "zamberlan", "scarpa",
    "aigle", "le chameau", "dubarry", "penelope chilvers", "rancourt",
    "yuketen", "russell moccasin", "steger", "manitobah", "quoddy",
    "carmina", "meermin", "tricker", "cheaney", "grenson", "church",
    "crockett", "paraboot", "weston",
    # japanese / avant-garde clothing
    "y's", "yohji yamamoto", "comme des garcons", "comme des garçons",
    "tricot comme des garcons", "junya watanabe", "issey miyake",
    "pleats please", "plantation", "zucca", "tsumori chisato", "kapital",
    "45r", "45rpm", "jurgen lehl", "babaghuri", "sensounico", "m.&kyoko",
    "moyuru", "hiroko koshino", "kenzo",
    # european quiet luxury / art-fashion
    "dries van noten", "ann demeulemeester", "haider ackermann", "lemaire",
    "margaret howell", "toast", "marni", "jil sander", "max mara",
    "sportmax", "alberto biani", "forte forte", "aspesi", "massimo alba",
    "daniela gregis", "kristensen du nord",
    # architectural / lagenlook / textile
    "rundholz", "oska", "sarah pacini", "ivan grundahl", "eskandar",
    "album di famiglia", "arts and science", "arts & science", "casey casey",
    "sofie d'hoore", "hannoh wessel", "pas de calais", "mes demoiselles",
    # minimalist / quiet-luxury (commonly on SGW)
    "eileen fisher", "vince", "theory", "cos", "filippa k", "toteme",
    "totême", "the row", "nili lotan", "acne studios", "frank & eileen",
    "frank and eileen", "elizabeth suzann", "jenni kayne", "babaton",
    "wilfred", "cuyana", "everlane", "grana", "samuji", "hope stockholm",
    # american / indie
    "zero maria cornejo", "maria cornejo", "rachel comey", "raquel allegra",
    "apiece apart", "ace and jig", "ace & jig", "ulla johnson",
    "isabel marant", "bode",
    # vintage art-to-wear textile brands
    "citron santa monica", "komarov", "babette", "sun kim", "flax",
    "cut loose", "gudrun sjoden", "gudrun sjödén", "koret", "painted pony",
}

# Textile / fiber signals — these drive Marissa's taste score
TEXTILE_TERMS = {
    "tapestry", "gobelin", "jacquard", "brocade", "chenille", "velvet",
    "embroidered", "embroidery", "quilted", "crinkle", "crinkled",
    "silk", "wool", "cashmere", "mohair", "alpaca", "linen", "cotton",
    "boiled wool", "felted", "woven", "upholstery", "damask",
}
FLORAL_TERMS = {
    "floral", "dark floral", "black floral", "muted floral", "botanical",
    "rose", "tapestry floral",
}
# Minimalist / architectural / quiet-line signals — the other half of her taste
MINIMALIST_SIGNALS = {
    "minimalist", "architectural", "column", "shift", "boxy", "clean line",
    "clean-line", "structured", "tunic", "drapey", "draped", "cocoon",
    "boiled wool", "merino", "cashmere", "raw silk", "japanese cotton",
    "wool gauze", "cupro", "solid", "monochrome", "lagenlook", "oversized",
    "kimono", "haori", "boro", "sashiko", "indigo", "made in japan",
}
ORIGIN_TERMS = {
    "made in japan", "made in italy", "made in france", "made in england",
    "made in scotland", "made in ireland", "made in spain", "made in portugal",
}

# Deprioritize (mall / logo bait) — lowers score, not a hard reject
DEPRIORITIZE = {
    "coach", "tory burch", "cole haan", "michael kors", "kate spade",
    "calvin klein", "zara", "h&m", "shein", "forever 21", "steve madden",
    "sam edelman", "vince camuto", "nine west", "jessica simpson", "guess",
    "express", "old navy", "gap", "banana republic", "ann taylor", "loft",
}

# ---------------------------------------------------------------------------
# Search library (from handoff)
# ---------------------------------------------------------------------------
SHOE_BRANDS = [
    "Thierry Rabotin", "Arche", "Pas de Rouge", "La Canadienne", "Aquatalia",
    "Chie Mihara", "Pedro Garcia", "Robert Clergerie", "Clergerie", "Trippen",
    "Officine Creative", "Marsell", "Marsèll", "Pikolinos", "Wonders",
    "Hispanitas", "Lodi", "Camper", "Gabor",
    "Ara", "Beautifeel", "L'Amour Des Pieds", "Aeyde", "ATP Atelier",
    "Dear Frances", "Freda Salvador", "Labucq", "Emme Parsons", "Coclico",
    "Repetto", "Pretty Ballerinas", "Anniel", "Bobbies", "Jonak", "Miista",
    "Intentionally Blank", "Troentorp", "Sanita", "Kork-Ease", "Beek",
    "Danner women", "Lowa women", "Hanwag women", "Zamberlan women",
    "Scarpa women", "Penelope Chilvers", "Carmina women", "Quoddy women",
    "Rancourt women", "Yuketen women",
]
SHOE_GENERIC = [
    "women 7.5 made in Italy leather", "women 7.5 made in Spain leather",
    "women 7.5 made in Portugal leather", "women 7.5 made in France leather",
    "women 7.5 suede boots", "women 7.5 leather ankle boots",
    "women 7.5 leather Mary Jane", "women 7.5 leather loafers",
    "women 7.5 handsewn", "women 7.5 Goodyear welt", "women 7.5 leather sole",
    "women 38 made in Italy leather", "women 38 made in Spain leather",
    "women 38 suede boots", "women 38 Mary Jane leather",
    "women 38 leather loafers", "women 38 leather sole", "women 38 handsewn",
]
LOST_JACKET = [
    "gobelin jacket", "gobelin floral jacket", "floral gobelin jacket",
    "gobelin tapestry jacket", "tapestry jacket", "floral tapestry jacket",
    "dark floral tapestry jacket", "black floral tapestry jacket",
    "green floral tapestry jacket", "muted floral tapestry jacket",
    "tapestry mandarin collar jacket", "mandarin collar tapestry jacket",
    "stand collar tapestry jacket", "floral mandarin collar jacket",
    "jacquard floral jacket", "floral jacquard jacket",
    "dark floral jacquard jacket", "brocade floral jacket",
    "floral brocade jacket", "dark floral brocade jacket",
    "chenille tapestry jacket", "chenille floral jacket",
    "upholstery floral jacket", "art to wear tapestry jacket",
    "artwear tapestry jacket", "frog closure jacket",
    "Chinese collar floral jacket", "kimono jacket floral",
    "quilted floral jacket", "structured floral jacket",
    "boxy floral jacket", "oversized floral jacket",
]
JAPANESE = [
    "Y's women", "Y's jacket", "Y's blouse", "Yohji Yamamoto women",
    "Yohji Yamamoto jacket", "Comme des Garcons women",
    "Comme des Garçons jacket", "Tricot Comme des Garcons",
    "Junya Watanabe women", "Issey Miyake women", "Issey Miyake jacket",
    "Pleats Please", "Pleats Please jacket", "Plantation Japan",
    "Plantation jacket", "Zucca Japan", "Tsumori Chisato", "Kapital women",
    "45R women", "45rpm women", "Jurgen Lehl", "Babaghuri", "Sensounico",
    "M.&KYOKO", "Moyuru", "Hiroko Koshino", "Kenzo floral jacket",
]
EUROPEAN = [
    "Dries Van Noten women", "Dries Van Noten jacket", "Dries Van Noten floral",
    "Ann Demeulemeester women", "Ann Demeulemeester jacket",
    "Haider Ackermann women", "Lemaire women", "Lemaire blouse",
    "Margaret Howell women", "Margaret Howell jacket", "Toast women",
    "Toast linen", "Marni women", "Marni blouse", "Marni jacket",
    "Jil Sander women", "Jil Sander jacket", "Max Mara jacket",
    "Sportmax jacket", "Alberto Biani", "Forte Forte blouse",
    "Forte Forte jacket", "Aspesi women", "Massimo Alba women",
    "Daniela Gregis", "Kristensen du Nord",
]
ARCHITECTURAL = [
    "Rundholz women", "Rundholz jacket", "Oska women", "Oska jacket",
    "Oska linen", "Sarah Pacini", "Sarah Pacini jacket", "Ivan Grundahl",
    "Eskandar women", "Eskandar linen", "Album di Famiglia",
    "Arts and Science women", "Arts & Science jacket", "Casey Casey women",
    "Sofie D'Hoore", "Hannoh Wessel", "Pas de Calais women",
    "Mes Demoiselles",
]
AMERICAN_INDIE = [
    "Zero Maria Cornejo", "Maria Cornejo jacket", "Rachel Comey",
    "Rachel Comey blouse", "Raquel Allegra silk", "Apiece Apart",
    "Ace and Jig", "Ace & Jig jacket", "Ulla Johnson silk",
    "Ulla Johnson embroidered", "Isabel Marant Etoile",
    "Isabel Marant jacket", "Bode women", "Bode embroidered",
    "Paloma Wool top",
]
VINTAGE_ARTWEAR = [
    "Citron Santa Monica", "Citron Santa Monica silk",
    "Citron Santa Monica floral", "Komarov jacket", "Komarov floral",
    "Babette jacket", "Babette wool", "Sun Kim crinkle", "Sun Kim artwear",
    "Flax linen jacket", "Cut Loose linen", "Gudrun Sjoden jacket",
    "Gudrun Sjödén floral", "Koret tapestry jacket", "Painted Pony tapestry",
    "White Stag tapestry jacket", "Tudor Court tapestry jacket",
]
HIGH_SIGNAL = [
    "small black floral silk blouse", "small dark floral silk blouse",
    "small floral jacquard jacket", "small black brocade jacket",
    "small tapestry mandarin collar jacket", "small gobelin floral jacket",
    "small embroidered silk jacket", "small made in Japan jacket",
    "small made in Italy silk blouse", "small mohair cardigan made in Italy",
    "small alpaca wool cardigan", "medium oversized tapestry jacket",
    "large oversized artwear jacket", "black floral embroidered jacket",
    "dark floral tapestry jacket", "mandarin collar floral jacket",
    "art to wear floral jacket",
]
TEXTILE_BASICS = [
    "women small silk blouse", "women small velvet jacket",
    "women small brocade jacket", "women small jacquard jacket",
    "women small embroidered jacket", "women small silk jacket",
    "women small wool jacket", "women small cashmere cardigan",
    "women small mohair cardigan", "women small alpaca sweater",
    "women small linen jacket", "women small made in Japan jacket",
    "women small made in Italy jacket", "oversized tapestry jacket",
    "oversized brocade jacket", "oversized embroidered jacket",
    "boxy wool jacket", "boxy silk jacket",
]
# Modern kimono / haori — structured Japanese-textile open-front jackets.
# Quality-signal terms only (silk/velvet/embroidered/haori) to avoid the
# boho-rayon "kimono cardigan" flood.
KIMONO = [
    "haori jacket", "haori", "vintage haori", "silk haori",
    "silk kimono jacket", "silk kimono robe", "modern kimono jacket",
    "embroidered kimono jacket", "velvet kimono jacket",
    "quilted kimono jacket", "wool kimono jacket", "kimono duster coat",
    "kimono wrap coat", "tapestry kimono jacket", "brocade kimono",
    "jacquard kimono jacket", "kimono style blazer",
    "vintage kimono jacket", "boro jacket", "sashiko jacket",
    "indigo kimono jacket", "made in Japan kimono jacket",
]

# Minimalist / quiet-luxury makers — common enough on SGW to be worth searching
MINIMALIST_BRANDS = [
    "Eileen Fisher small", "Eileen Fisher petite", "Eileen Fisher linen",
    "Eileen Fisher silk", "Eileen Fisher merino", "Eileen Fisher wool",
    "Eileen Fisher jacket", "Eileen Fisher cardigan", "Eileen Fisher box",
    "Vince small", "Vince cashmere", "Vince silk", "Vince wool", "Vince linen",
    "Theory small", "Theory wool", "Theory silk", "Theory linen",
    "COS women small", "COS wool", "COS architectural",
    "Filippa K small", "Toteme small", "Totême small", "The Row women",
    "Nili Lotan small", "Acne Studios women", "Frank & Eileen small",
    "Frank and Eileen linen", "Elizabeth Suzann", "Jenni Kayne small",
    "Babaton small", "Wilfred small", "Cuyana", "Samuji",
]
# Minimalist fabric / silhouette searches (solid natural fibers, no floral)
MINIMALIST_FABRIC = [
    "merino wool sweater small", "boiled wool jacket small",
    "cashmere turtleneck small", "cashmere sweater small minimalist",
    "raw silk top small", "silk minimalist blouse small",
    "japanese cotton jacket small", "minimalist linen jacket small",
    "architectural wool coat small", "wool gauze jacket",
    "cupro blouse small", "boiled wool cardigan small",
    "alpaca minimalist sweater small", "linen column dress small",
    "minimalist wool jacket small", "boxy linen jacket small",
    "structured wool jacket small", "quiet luxury wool small",
]

SEARCH_GROUPS = {
    "shoes": {"cat": WOMENS_SHOES, "strings": (
        [f"{b} 7.5" for b in SHOE_BRANDS] + [f"{b} 38" for b in SHOE_BRANDS] + SHOE_GENERIC
    )},
    "lost_jacket": {"cat": WOMENS_CLOTHING, "strings": LOST_JACKET},
    "japanese": {"cat": WOMENS_CLOTHING, "strings": JAPANESE},
    "european": {"cat": WOMENS_CLOTHING, "strings": EUROPEAN},
    "architectural": {"cat": WOMENS_CLOTHING, "strings": ARCHITECTURAL},
    "american_indie": {"cat": WOMENS_CLOTHING, "strings": AMERICAN_INDIE},
    "vintage_artwear": {"cat": WOMENS_CLOTHING, "strings": VINTAGE_ARTWEAR},
    "minimalist": {"cat": WOMENS_CLOTHING, "strings": MINIMALIST_BRANDS + MINIMALIST_FABRIC},
    "kimono": {"cat": WOMENS_CLOTHING, "strings": KIMONO},
    "high_signal": {"cat": WOMENS_CLOTHING, "strings": HIGH_SIGNAL + TEXTILE_BASICS},
}

# ---------------------------------------------------------------------------
# Size logic
# ---------------------------------------------------------------------------
def shoe_size_ok(text: str) -> tuple[str, str]:
    t = text.lower()
    # Reject obvious wrong EU/US first
    if re.search(r'\beu(?:r)?\s*(?:40|41|42|43)\b', t) or re.search(r'\b(?:size\s*)?(?:9\.5|10|10\.5|11)\b', t):
        # unless an explicit 7.5/38 also present
        if not re.search(r'\b(?:7\.5|38|37\.5|38\.5)\b', t):
            return "reject", "EU40+/US9+ — too large"
    if re.search(r'\b(?:7\.5|38(?!\.5)|37\.5|38\.5)\b', t) or re.search(r'\beu(?:r)?\s*38\b', t):
        return "accept", "US 7.5 / EU 38 match"
    if re.search(r'\b(?:8(?!\.5)|39)\b', t):
        return "maybe", "US 8 / EU 39 — ok for boots/narrow"
    return "unknown", "size not found in title"


def clothing_size_ok(title: str, desc: str = "") -> tuple[str, str]:
    """Read garment size from the TITLE first (reliable on SGW); fall back to
    description only if the title carries no size token. Avoids matching the
    word 'small' inside descriptions ('runs small', 'small flaw')."""
    t = title.lower()
    oversized = any(s in f"{title} {desc}".lower() for s in OVERSIZE_SIGNALS)

    # Size tokens as they appear in SGW titles, biggest-first so XL beats L beats S
    if re.search(r'\b(?:xx-?large|xxl|2xl|3xl|plus size|1x|2x|3x)\b', t):
        return ("accept" if oversized else "maybe",
                "XXL+ — only as oversized/artwear" if not oversized else "XXL+ acceptable as artwear")
    if re.search(r'\b(?:x-?large|xl|large|\bl\b|medium|\bm\b)\b', t):
        return ("accept", "M/L/XL acceptable — oversized/boxy/artwear") if oversized \
            else ("maybe", "M/L/XL — only if oversized (verify measurements)")
    if re.search(r'\b(?:x-?small|xs|petite|\bps\b|\bsp\b|\bs\b|small)\b', t):
        return "accept", "XS/S match"
    # Numeric women's sizes (0-8 small-ish, 10+ larger)
    if re.search(r'\bsize\s*(?:0|2|4|6|8)\b', t):
        return "accept", "numeric size 0-8 (small range)"
    if re.search(r'\bsize\s*(?:10|12|14|16|18)\b', t):
        return ("accept", "numeric 10-16 acceptable — oversized") if oversized \
            else ("maybe", "numeric 10-16 — only if oversized")
    return "unknown", "size not in title (check listing)"


def assess(detail: dict, category: str) -> dict:
    title = detail.get("title") or ""
    desc = hunt.clean_text(detail.get("description"))
    text = f"{title} {desc}".lower()

    brands = hunt.has_any(text, QUALITY_BRANDS)
    textiles = hunt.has_any(text, TEXTILE_TERMS)
    florals = hunt.has_any(text, FLORAL_TERMS)
    origins = hunt.has_any(text, ORIGIN_TERMS)
    minimal = hunt.has_any(text, MINIMALIST_SIGNALS)
    deprio = hunt.has_any(text, DEPRIORITIZE)

    if category == "shoes":
        size_status, size_reason = shoe_size_ok(title + " " + desc)
    else:
        size_status, size_reason = clothing_size_ok(title, desc)

    fit = {"accept": 8, "maybe": 5, "unknown": 4, "reject": 1}[size_status]
    maker = min(10, 3 + min(len(brands), 3) * 2)
    # Taste: textile + (floral OR minimalist, balanced) + origin. Floral no longer
    # dominates — a solid natural-fiber minimalist piece scores as well as a brocade.
    aesthetic = min(3, len(florals)) + min(3, len(minimal))   # two paths to taste
    taste = min(10, 3 + min(len(textiles), 3) + aesthetic + min(len(origins), 1))
    fabric = min(10, 2 + min(len(textiles), 4) * 2)
    cur = detail.get("currentPrice")
    price = cur.get("amount") if isinstance(cur, dict) else cur
    value = 8 if (price is not None and price <= 40) else 6 if (price is not None and price <= 90) else 4

    flags = []
    if deprio:
        # Deprioritize unless cheap+beautiful: penalize maker, but textile pieces survive
        maker = min(maker, 3)
        flags.append("deprioritize: " + ", ".join(deprio))
    if size_status == "reject":
        flags.append(size_reason)

    scores = [fit, maker, taste, fabric, value]
    avg = sum(scores) / len(scores)

    # Recommendation
    if size_status == "reject":
        rec = "Skip"
    elif avg >= 7.0 and (brands or len(textiles) >= 2 or len(minimal) >= 2):
        rec = "Buy"
    elif avg >= 5.6:
        rec = "Watch"
    elif avg >= 4.6:
        rec = "Need measurements"
    else:
        rec = "Skip"

    reasons = []
    if brands: reasons.append("maker: " + ", ".join(brands[:4]))
    if textiles: reasons.append("textile: " + ", ".join(textiles[:5]))
    if florals: reasons.append("floral: " + ", ".join(florals[:3]))
    if minimal: reasons.append("minimalist: " + ", ".join(minimal[:4]))
    if origins: reasons.append(", ".join(origins[:2]))
    reasons.append(size_reason)

    return {
        "recommendation": rec,
        "total_score": round(avg, 2),
        "size_status": size_status,
        "match_reasons": " | ".join(reasons),
        "red_flags": " | ".join(flags),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="runs/marissa_latest")
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
        cat_id, cat_level = group["cat"]
        for query in group["strings"]:
            i += 1
            try:
                items = hunt.search_items(session, query, args.per_query,
                                          args.pages_per_query, cat_id, cat_level)
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
                try:
                    detail = hunt.get_detail(session, iid)
                except Exception:
                    continue
                a = assess(detail, category)
                if a["recommendation"] == "Skip":
                    continue
                cur = detail.get("currentPrice")
                price = cur.get("amount") if isinstance(cur, dict) else cur
                img_server = detail.get("imageServer") or ""
                img_paths = (detail.get("imageUrlString") or "").split(";")
                images = [hunt.normalize_image_url(img_server, p) for p in img_paths
                          if hunt.normalize_image_url(img_server, p)]
                candidates.append({
                    "item_id": iid, "category": category, "query": query,
                    "title": detail.get("title", ""),
                    "url": f"https://shopgoodwill.com/item/{iid}",
                    "current_price": price,
                    "num_bids": detail.get("numberOfBids", 0),
                    "end_time": (detail.get("endTime") or "")[:19],
                    "image_urls": images[:3],
                    "recommendation": a["recommendation"],
                    "total_score": a["total_score"],
                    "size_status": a["size_status"],
                    "match_reasons": a["match_reasons"],
                    "red_flags": a["red_flags"],
                })
                time.sleep(0.1)

    candidates.sort(key=lambda c: c["total_score"], reverse=True)
    (out / "candidates.json").write_text(json.dumps(candidates, indent=2))
    if candidates:
        with (out / "candidates.csv").open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(candidates[0].keys()))
            w.writeheader(); w.writerows(candidates)
    print(f"\nDone. {len(candidates)} candidates → {out}")


if __name__ == "__main__":
    main()
