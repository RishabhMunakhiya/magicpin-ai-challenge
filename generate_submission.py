from __future__ import annotations

import json
from pathlib import Path
from bot import compose

DATASET_DIR = Path(__file__).parent / "dataset"
EXPANDED_DIR = DATASET_DIR / "expanded"


def main():
    # Load categories
    categories = {}
    for f in (DATASET_DIR / "categories").glob("*.json"):
        with open(f, encoding="utf-8") as fp:
            cat = json.load(fp)
            categories[cat["slug"]] = cat

    # Load merchants
    merchants = {}
    with open(DATASET_DIR / "merchants_seed.json", encoding="utf-8") as fp:
        m_seed = json.load(fp)["merchants"]
    for m in m_seed:
        merchants[m["merchant_id"]] = m
    if (EXPANDED_DIR / "merchants").exists():
        for f in (EXPANDED_DIR / "merchants").glob("*.json"):
            with open(f, encoding="utf-8") as fp:
                m = json.load(fp)
                merchants[m["merchant_id"]] = m

    # Load customers
    customers = {}
    with open(DATASET_DIR / "customers_seed.json", encoding="utf-8") as fp:
        c_seed = json.load(fp)["customers"]
    for c in c_seed:
        customers[c["customer_id"]] = c
    if (EXPANDED_DIR / "customers").exists():
        for f in (EXPANDED_DIR / "customers").glob("*.json"):
            with open(f, encoding="utf-8") as fp:
                c = json.load(fp)
                customers[c["customer_id"]] = c

    # Load triggers
    triggers = {}
    with open(DATASET_DIR / "triggers_seed.json", encoding="utf-8") as fp:
        t_seed = json.load(fp)["triggers"]
    for t in t_seed:
        triggers[t["id"]] = t
    if (EXPANDED_DIR / "triggers").exists():
        for f in (EXPANDED_DIR / "triggers").glob("*.json"):
            with open(f, encoding="utf-8") as fp:
                t = json.load(fp)
                triggers[t["id"]] = t

    # Load test pairs
    test_pairs_path = EXPANDED_DIR / "test_pairs.json"
    if not test_pairs_path.exists():
        print("test_pairs.json not found!")
        return

    with open(test_pairs_path, encoding="utf-8") as fp:
        pairs = json.load(fp)["pairs"]
    print(f"Generating submission for {len(pairs)} test pairs...")

    submission_rows = []
    for pair in pairs:
        tid = pair["test_id"]
        trg_id = pair["trigger_id"]
        mid = pair["merchant_id"]
        cid = pair.get("customer_id")

        trigger = triggers.get(trg_id)
        merchant = merchants.get(mid)
        customer = customers.get(cid) if cid else None

        if not merchant or not trigger:
            print(f"Warning: missing context for test {tid} (mid={mid}, trg={trg_id})")
            continue

        cat_slug = merchant.get("category_slug")
        category = categories.get(cat_slug)
        if not category:
            print(f"Warning: missing category {cat_slug} for test {tid}")
            continue

        msg = compose(category, merchant, trigger, customer)

        row = {
            "test_id": tid,
            "body": msg["body"],
            "cta": msg["cta"],
            "send_as": msg["send_as"],
            "suppression_key": msg["suppression_key"],
            "rationale": msg["rationale"],
        }
        submission_rows.append(row)

    out_file = Path(__file__).parent / "submission.jsonl"
    with open(out_file, "w", encoding="utf-8") as f:
        for row in submission_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"Wrote {len(submission_rows)} rows to {out_file}")


if __name__ == "__main__":
    main()
