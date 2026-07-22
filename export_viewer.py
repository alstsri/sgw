#!/usr/bin/env python3
"""Export a hunter's candidates.json into a lean JSON for the web viewer (docs/data/).

Usage:
  python3 export_viewer.py adam    runs/full_2026-06-29c
  python3 export_viewer.py marissa runs/marissa_2026-06-29b
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "docs" / "data"

ACTIONABLE = {"Buy", "Watch", "Need measurements"}


def export(person: str, run_dir: str) -> None:
    src = Path(run_dir)
    if not src.is_absolute():
        src = ROOT / src
    cands = json.loads((src / "candidates.json").read_text())

    # IDs from the snapshot we're about to overwrite. Anything not in here is
    # "new since the last sweep" and gets starred in the viewer. On the first
    # ever export (no prior file / empty), nothing is marked new.
    prior_path = DATA_DIR / f"{person}.json"
    prior_ids: set = set()
    if prior_path.exists():
        try:
            prior = json.loads(prior_path.read_text())
            prior_ids = {i.get("id") for i in prior.get("items", [])}
        except (json.JSONDecodeError, OSError):
            prior_ids = set()

    items = []
    for c in cands:
        if c.get("recommendation") not in ACTIONABLE:
            continue
        if not c.get("live_verified", True):
            continue
        # Adam's hunter carries a men's-verification gate; keep only confirmed
        mv = c.get("mens_verification")
        if mv is not None and mv not in ("Men's", "Likely Men's"):
            continue
        imgs = c.get("image_urls") or []
        if isinstance(imgs, str):
            imgs = [x.strip() for x in imgs.split("|") if x.strip()]
        if not imgs:
            continue  # viewer is image-first
        items.append({
            "id": c.get("item_id"),
            "title": c.get("title", ""),
            "url": c.get("url", ""),
            "image": imgs[0],
            "price": c.get("current_price"),
            "bids": c.get("num_bids", c.get("numberOfBids", 0)),
            "end_time": c.get("end_time", ""),
            "category": c.get("category", ""),
            "size": c.get("size", c.get("size_status", "")),
            "rec": c.get("recommendation", ""),
            "score": c.get("total_score", 0),
            "why": c.get("match_reasons", ""),
            "flags": c.get("red_flags", ""),
            "new": bool(prior_ids) and c.get("item_id") not in prior_ids,
        })

    items.sort(key=lambda x: x["score"], reverse=True)

    # Keep all Buy/Watch. Cap the noisier "Need measurements" tier PER TYPE
    # (Shoes/Clothing/Home) so one type can't crowd another out of the viewer.
    def type_of(cat):
        c = (cat or "").lower()
        return "Shoes" if c == "shoes" else "Home" if c == "blankets" else "Clothing"

    NEED_CAP_PER_TYPE = 60
    strong = [i for i in items if i["rec"] in ("Buy", "Watch")]
    need_by_type = {}
    for i in items:
        if i["rec"] != "Need measurements":
            continue
        t = type_of(i["category"])
        need_by_type.setdefault(t, [])
        if len(need_by_type[t]) < NEED_CAP_PER_TYPE:
            need_by_type[t].append(i)
    need = [i for lst in need_by_type.values() for i in lst]
    items = sorted(strong + need, key=lambda x: x["score"], reverse=True)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out = {
        "person": person,
        "source_run": src.name,
        "count": len(items),
        "items": items,
    }
    (DATA_DIR / f"{person}.json").write_text(json.dumps(out, indent=2))
    print(f"{person}: {len(items)} items → docs/data/{person}.json")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    export(sys.argv[1], sys.argv[2])
