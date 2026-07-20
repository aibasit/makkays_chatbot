"""Replace the "UPS Solutions" category in the i-power catalog with the
normalised data in `UPS Data/` (UPS_Series.csv + UPS_Models.csv), supplied by
the user specifically to correct/refine the chatbot's UPS knowledge.

Unlike `ipower_products_standard.csv` (a raw per-page scrape), this source is
already relational and pre-verified: `UPS_Series.csv` is one row per product
series (with a `Series ID` that `UPS_Models.csv` joins on), its `kVA Min`/
`kVA Max` columns were spot-checked against every series' own model rows here
and matched exactly in all 34 series — no capacity-range/model-table mismatch
to fix this time, unlike the earlier standard-file rebuild. `UPS_Models.csv`
also carries an explicit `Review Flag` column (36 of 181 rows) noting
ambiguities the source spreadsheet itself couldn't resolve (a code decoding
to a capacity the datasheet text doesn't list, the same code appearing under
two different series, etc.) — these are preserved as a technical_details note
rather than silently dropped or silently trusted, since there's no way to
adjudicate them without the original datasheet.

Only rows with `category == "UPS Solutions"` in the existing products/models
CSVs are replaced; every other category (Automatic Voltage Regulators, Battery
Storage Power Solutions, Customized Power Solutions, Inverter Solutions,
Optional / Accessories) is carried over unchanged. All product IDs are
renumbered sequentially on write since nothing outside these two files depends
on a stable PROD-NNN value across a rebuild.

Run: python "RAG Knowledge/apply_ups_data_correction.py"
"""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).parent
UPS_DATA_DIR = ROOT.parent / "UPS Data"
PRODUCTS_CSV = ROOT / "makkays_ipower_products.csv"
MODELS_CSV = ROOT / "makkays_ipower_models.csv"
MD_PATH = ROOT / "makkays_ipower_products.md"
IPOWER_URL = "https://i-sol.co.uk/product-line-4"

PCOLS = [
    "product_id", "domain", "category", "subcategory", "title", "display_name",
    "capacity_range", "short_description", "product_info", "technical_details",
    "applications", "model_count", "spec_status", "source_type", "source_url",
]
MCOLS = [
    "product_id", "product_name", "category", "subcategory", "model_code",
    "capacity", "variant", "mapping_confidence", "resolution_method",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def num(value: str) -> float | None:
    value = value.strip()
    return float(value.replace(",", "")) if value else None


def fmt(value: float) -> str:
    return str(int(value)) if value == int(value) else str(value)


def build_ups_products() -> tuple[list[dict], list[dict]]:
    series_rows = read_csv(UPS_DATA_DIR / "UPS_Series.csv")
    model_rows = read_csv(UPS_DATA_DIR / "UPS_Models.csv")

    models_by_series: dict[str, list[dict]] = defaultdict(list)
    for row in model_rows:
        models_by_series[row["Series ID"]].append(row)

    products: list[dict] = []
    models: list[dict] = []

    for series in series_rows:
        sid = series["Series ID"]
        series_models = models_by_series.get(sid, [])
        titles = {m["Source Title (col D)"].strip() for m in series_models if m["Source Title (col D)"].strip()}
        title = sorted(titles)[0] if titles else series["Product Group"]

        kva_min, kva_max = num(series["kVA Min"]), num(series["kVA Max"])
        if kva_min is not None and kva_max is not None:
            capacity_range = f"{fmt(kva_min)}KVA" if kva_min == kva_max else f"{fmt(kva_min)}-{fmt(kva_max)}KVA"
        else:
            ratings = [num(m["Rating (A)"]) for m in series_models if m["Rating (A)"].strip()]
            ratings = [r for r in ratings if r is not None]
            if ratings:
                lo, hi = min(ratings), max(ratings)
                capacity_range = f"{fmt(lo)}A" if lo == hi else f"{fmt(lo)}-{fmt(hi)}A"
            else:
                capacity_range = ""

        flags = [
            f"{m['Model Code']}: {m['Review Flag'].strip()}"
            for m in series_models
            if m["Review Flag"].strip()
        ]
        technical_details = series["Features (raw text)"].replace("\n", " ").strip()
        if flags:
            technical_details = (technical_details + " | Data quality notes (unresolved in source): " + " ; ".join(flags)).strip(" |")

        pid_placeholder = f"UPS-{sid}"  # renumbered to PROD-NNN once merged with the rest of the catalog
        products.append(
            {
                "product_id": pid_placeholder,
                "domain": "i-power",
                "category": series["Category"],
                "subcategory": series["Sub-Category"],
                "title": title,
                "display_name": title,
                "capacity_range": capacity_range,
                "short_description": series["Short Description"].strip(),
                "product_info": series["Product Info"].strip(),
                "technical_details": technical_details,
                "applications": series["Applications"].strip(),
                "model_count": len(series_models),
                "spec_status": "verified" if series_models else "range_only",
                "source_type": "website",
                "source_url": IPOWER_URL,
            }
        )

        if series_models:
            for m in series_models:
                kva = m["Capacity (kVA)"].strip()
                kw = m["Capacity (kW)"].strip()
                rating = m["Rating (A)"].strip()
                if kva and kw:
                    capacity = f"{kva}KVA / {kw}KW"
                elif kva:
                    capacity = f"{kva}KVA"
                elif rating:
                    capacity = f"{rating}A"
                else:
                    capacity = ""
                models.append(
                    {
                        "product_id": pid_placeholder,
                        "product_name": title,
                        "category": series["Category"],
                        "subcategory": series["Sub-Category"],
                        "model_code": m["Model Code"],
                        "capacity": capacity,
                        "variant": "",
                        "mapping_confidence": "flagged_for_review" if m["Review Flag"].strip() else "verified",
                        "resolution_method": "ups_data_normalised",
                    }
                )
        else:
            models.append(
                {
                    "product_id": pid_placeholder,
                    "product_name": title,
                    "category": series["Category"],
                    "subcategory": series["Sub-Category"],
                    "model_code": "(not listed in source)",
                    "capacity": capacity_range,
                    "variant": "",
                    "mapping_confidence": "range_from_name",
                    "resolution_method": "ups_data_normalised",
                }
            )

    return products, models


def render_product_md(p: dict) -> list[str]:
    d = p["display_name"]
    capacity_suffix = f" ({p['capacity_range']})" if p["capacity_range"] else ""
    lines = [
        "---", "", f"## {d}", "",
        f"**{d}** is a *{p['subcategory']}* product in the **{p['category']}** category"
        f"{capacity_suffix}, part of the **i-power** product line.",
        "",
        f"**Category:** {p['category']} > {p['subcategory']}  ",
        f"**Capacity range:** {p['capacity_range']}  ",
        "**Product line:** i-power  ",
        "",
    ]
    if p["short_description"]:
        lines += ["**Summary:**  ", p["short_description"], ""]
    if p["product_info"]:
        lines += ["**Overview:**  ", p["product_info"], ""]
    if p["_pairs"]:
        lines += ["**Models & capacities:**", "", "| Model code | Capacity |", "|---|---|"]
        for model_code, capacity in p["_pairs"]:
            lines.append(f"| {model_code} | {capacity} |")
        lines.append("")
    else:
        lines += [
            "**Models & capacities:**  ",
            f"Capacity range: {p['capacity_range']}. *(No individual model codes are listed in "
            "the source text — refer to the datasheet for specific models.)*",
            "",
        ]
    if p["applications"]:
        lines += [f"**Typical applications:** {p['applications']}", ""]
    lines += [f"**Source:** {p['source_url']}", ""]
    return lines


def main() -> None:
    existing_products = read_csv(PRODUCTS_CSV)
    existing_models = read_csv(MODELS_CSV)

    kept_products = [p for p in existing_products if p["category"] != "UPS Solutions"]
    kept_ids = {p["product_id"] for p in kept_products}
    kept_models = [m for m in existing_models if m["product_id"] in kept_ids]

    new_products, new_models = build_ups_products()

    print(f"Replacing {len(existing_products) - len(kept_products)} old UPS Solutions products "
          f"with {len(new_products)} from UPS Data ({len(new_models)} model rows).")

    all_products = kept_products + new_products
    all_models = kept_models + new_models

    id_map: dict[str, str] = {}
    for index, product in enumerate(all_products, start=1):
        new_id = f"PROD-{index:03d}"
        id_map[product["product_id"]] = new_id
        product["product_id"] = new_id
    for model in all_models:
        model["product_id"] = id_map[model["product_id"]]

    with PRODUCTS_CSV.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=PCOLS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(all_products)

    with MODELS_CSV.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=MCOLS)
        writer.writeheader()
        writer.writerows(all_models)

    models_by_product: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for m in all_models:
        models_by_product[m["product_id"]].append((m["model_code"], m["capacity"]))

    md_lines = [
        "# Interconnect Solutions / i-Sol — i-Power Product Knowledge Base", "",
        f"Source: {IPOWER_URL}  ",
        f"Products: {len(all_products)}  ",
        "Each product is a self-contained chunk. Category, subcategory and capacity range are "
        "repeated in every entry so a retrieved chunk carries full context. UPS Solutions "
        "products were rebuilt from `UPS Data/` (a pre-verified series/models export); all "
        "other categories are unchanged from the prior rebuild.",
        "",
    ]
    for p in all_products:
        p["_pairs"] = [
            pair for pair in models_by_product.get(p["product_id"], [])
            if pair[0] != "(not listed in source)"
        ]
        md_lines += render_product_md(p)
    MD_PATH.write_text("\n".join(md_lines), encoding="utf-8")

    print(f"Total: {len(all_products)} products, {len(all_models)} model rows.")


if __name__ == "__main__":
    main()
