"""Rebuild the i-power RAG Knowledge files from `ipower_products_standard.csv`
(the corrected, ground-truth catalog export from i-sol.co.uk) instead of the
original Excel-derived source used by `convert_products_v3.py`.

Fixes relative to the old makkays_ipower_* files:
- `display_name` is always the full, unique product name — the old data used a
  generic "{series} {phase} ({capacity})" label that several genuinely different
  variants (battery config, PF rating, parallel feature) shared verbatim.
- `capacity_range` is computed from each row's own Model/Capacity columns, so it
  can never drift out of sync with the model table the way the old curated label
  sometimes did (e.g. one product was tagged "1-10KVA" but its table listed a
  single 5kVA model).
- Adds every category the old data was missing entirely: Line Interactive Series,
  Lithium Battery UPS Series, Inverter Solutions as its own product line (not an
  "Inverters" subcategory of UPS Solutions), Customized Power Solutions, and the
  full Battery Storage Power Solutions / Optional-Accessories ranges.
- Narrative fields (short_description/product_info/applications) are carried over
  from the old products.csv wherever a product shares model codes with an old row;
  products with no old counterpart (the newly-added categories) get a short
  factual description built from structured fields instead, since the standard
  source has no marketing copy at all.

Run: python "RAG Knowledge/build_ipower_from_standard.py"
"""

from __future__ import annotations

import csv
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).parent
STANDARD_CSV = ROOT.parent / "ipower_products_standard.csv"
OLD_PRODUCTS_CSV = ROOT / "makkays_ipower_products.csv"
OLD_MODELS_CSV = ROOT / "makkays_ipower_models.csv"
OUT_PRODUCTS_CSV = ROOT / "makkays_ipower_products.csv"
OUT_MODELS_CSV = ROOT / "makkays_ipower_models.csv"
OUT_MD = ROOT / "makkays_ipower_products.md"
IPOWER_URL = "https://i-sol.co.uk/product-line-4"

ADMIN_COLUMNS = {
    "Category", "Product Name", "Price", "URL", "Model", "Capacity",
    "Model (2)", "Capacity (2)", "Model (3)", "Capacity (3)", "Model (4)", "Capacity (4)",
}
SERIES_TOKEN_RE = re.compile(r"^[A-Z]{1,4}-?\d")
CAP_TOKEN_RE = re.compile(r"([\d.]+)\s*(KVA|KW|Ah|A)\b", re.IGNORECASE)
RANGE_WITH_UNIT_RE = re.compile(
    r"([\d.]+)\s*(KVA|Ah|A|kW|K)\s*[-–—]\s*([\d.]+)\s*(KVA|Ah|A|kW|K)", re.IGNORECASE
)
PAREN_RANGE_RE = re.compile(r"\(([\d.]+)\s*[-–—]\s*([\d.]+)\s*(kVA|kW|K|A|Ah)\)", re.IGNORECASE)
PAREN_SINGLE_RE = re.compile(r"\(([\d.]+)\s*(kVA|kW|K)\)", re.IGNORECASE)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def split_pipe(value: str) -> list[str]:
    return [p.strip() for p in value.split("|") if p.strip()] if value else []


def parse_category(path_str: str) -> tuple[str, str]:
    segments = [s.strip() for s in path_str.split(">")]
    rest = segments[2:]  # drop "i-power", "Product Line"
    category = rest[0] if rest else "Uncategorized"
    subcategory = " > ".join(rest[1:]) if len(rest) > 1 else category
    return category, subcategory


def leading_token(segment: str) -> str:
    match = re.match(r"^[A-Za-z0-9][A-Za-z0-9\-]*", segment)
    return match.group(0) if match else segment


def build_display_name(product_name: str, subcategory: str) -> str:
    if SERIES_TOKEN_RE.match(product_name):
        return product_name
    last_segment = subcategory.split(">")[-1].strip()
    token = leading_token(last_segment)
    return f"{token} {product_name}".strip()


def _num(value: float) -> str:
    return str(int(value)) if value == int(value) else str(value)


def _fmt_range(lo: float, hi: float, unit: str) -> str:
    return f"{_num(lo)}{unit}" if lo == hi else f"{_num(lo)}-{_num(hi)}{unit}"


def _normalize_unit(unit: str) -> str:
    unit = unit.upper()
    return "KVA" if unit in {"KW", "K"} else unit


def expand_capacity_segment(segment: str) -> list[str]:
    """A segment with no sibling pipe-values can itself be a combined "X-Y UNIT"
    range (e.g. "10KVA-3000KVA") rather than a single figure — split it into its
    two endpoints so range detection downstream sees both numbers."""
    match = RANGE_WITH_UNIT_RE.fullmatch(segment.strip())
    if match:
        unit = match.group(4)
        return [f"{match.group(1)}{unit}", f"{match.group(3)}{unit}"]
    return [segment]


def capacity_range_from_values(capacity_values: list[str], product_name: str) -> str:
    tokens: list[tuple[float, str]] = []
    for value in capacity_values:
        match = CAP_TOKEN_RE.search(value)
        if match:
            tokens.append((float(match.group(1)), _normalize_unit(match.group(2))))
    if tokens:
        unit = tokens[0][1]
        values = [v for v, u in tokens if u == unit]
        return _fmt_range(min(values), max(values), unit)

    match = re.search(
        r"Range:\s*([\d.]+)\s*(KVA|Ah|A)\s*[-–—]\s*([\d.]+)\s*(KVA|Ah|A)",
        product_name,
        re.IGNORECASE,
    )
    if match:
        return _fmt_range(float(match.group(1)), float(match.group(3)), _normalize_unit(match.group(2)))
    match = RANGE_WITH_UNIT_RE.search(product_name)
    if match:
        return _fmt_range(float(match.group(1)), float(match.group(3)), _normalize_unit(match.group(4)))
    match = PAREN_RANGE_RE.search(product_name)
    if match:
        return _fmt_range(float(match.group(1)), float(match.group(2)), _normalize_unit(match.group(3)))
    match = PAREN_SINGLE_RE.search(product_name)
    if match:
        return f"{_num(float(match.group(1)))}KVA"
    return ""


def build_model_rows(row: dict[str, str], capacity_lookup: dict[str, str]) -> list[tuple[str, str]]:
    models = split_pipe(row.get("Model", ""))
    capacities: list[str] = []
    for segment in split_pipe(row.get("Capacity", "")):
        capacities.extend(expand_capacity_segment(segment))

    if models and capacities and len(models) == len(capacities):
        pairs = list(zip(models, capacities))
    elif models and not capacities:
        pairs = [(m, capacity_lookup.get(m, "")) for m in models]
    elif capacities and not models:
        pairs = [("(model code not listed)", c) for c in capacities]
    elif models and capacities:
        n = min(len(models), len(capacities))
        pairs = list(zip(models[:n], capacities[:n])) + [
            ("(model code not listed)", c) for c in capacities[n:]
        ]
    else:
        pairs = []

    # "Model (2)"/"Capacity (2)" is usually a redundant re-scrape of the same
    # spec table (near-identical codes with a stray character difference) — but
    # for a few products it's a genuine second tier the primary table doesn't
    # cover at all (e.g. T-4101 "(1-15KVA)" only lists 1/2/3/6kVA in Model, with
    # 8/10/15kVA in Model (2)). Only merge it in when the codes are completely
    # disjoint from the primary list, which rules out the re-scrape-noise case.
    models_2 = split_pipe(row.get("Model (2)", ""))
    capacities_2 = split_pipe(row.get("Capacity (2)", ""))
    if models_2 and len(models_2) == len(capacities_2) and not (set(models_2) & set(models)):
        pairs = pairs + list(zip(models_2, capacities_2))
    return pairs


def build_technical_details(row: dict[str, str]) -> str:
    parts = []
    for key, value in row.items():
        if key in ADMIN_COLUMNS:
            continue
        value = (value or "").strip()
        if value:
            parts.append(f"{key}: {value}")
    return " | ".join(parts)


def load_old_narrative() -> tuple[dict[str, dict[str, str]], dict[str, str], dict[str, str]]:
    if not OLD_PRODUCTS_CSV.exists():
        return {}, {}, {}
    old_products = {r["product_id"]: r for r in read_csv(OLD_PRODUCTS_CSV)}
    old_models = read_csv(OLD_MODELS_CSV) if OLD_MODELS_CSV.exists() else []
    model_to_pid: dict[str, str] = {}
    capacity_lookup: dict[str, str] = {}
    for r in old_models:
        code = r["model_code"].strip()
        if code and code != "(not listed in source)":
            model_to_pid[code] = r["product_id"]
            if r["capacity"].strip():
                capacity_lookup[code] = r["capacity"].strip()
    return old_products, model_to_pid, capacity_lookup


def find_narrative(
    model_codes: list[str],
    old_products: dict[str, dict[str, str]],
    model_to_pid: dict[str, str],
) -> dict[str, str] | None:
    counter = Counter(model_to_pid[m] for m in model_codes if m in model_to_pid)
    if not counter:
        return None
    pid, _ = counter.most_common(1)[0]
    old = old_products.get(pid)
    if old is None:
        return None
    return {
        "short_description": old["short_description"],
        "product_info": old["product_info"],
        "applications": old["applications"],
    }


def render_product_md(p: dict) -> list[str]:
    d = p["display_name"]
    capacity_suffix = f" ({p['capacity_range']})" if p["capacity_range"] else ""
    lines = [
        "---", "", f"## {d}", "",
        f"**{d}** is a *{p['subcategory']}* product in the **{p['category']}** category"
        f"{capacity_suffix}, part of the **i-power** product line.",
        "",
    ]
    if p["title"] and p["title"] != d:
        lines += [f"**Full model / title:** {p['title']}", ""]
    lines += [
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


# `ipower_products_standard.csv`'s "Battery Storage Power Solutions > Lithium
# Battery Pack" rows only cover 2 real variants (RB-LI-192-100, RB-LI-48-25) —
# it drops 3 higher-voltage packs (512VDC/100Ah, 480VDC/100Ah, 512VDC/200Ah)
# that a prior, richer source captured and that were live in the catalog before
# this rebuild. A user question about a 512VDC battery came back empty because
# of this gap. Restored here from that prior source rather than silently
# dropped, since the standard export is a partial snapshot for this one
# sub-range, not a correction of it.
_LEGACY_BATTERY_SUPPLEMENT: list[dict] = [
    {
        "title": "RB-LI-48VDC-100Ah",
        "display_name": "Li-ion Battery 48VDC-100Ah",
        "category": "Battery Storage Power Solutions",
        "subcategory": "Lithium-ion Battery Packs",
        "capacity_range": "",
        "short_description": (
            "The ENERGEN Lithium Iron Phosphate Battery Module is designed for storage and "
            "power supply application systems featuring an intelligent Battery Management "
            "System (BMS) that ensures enhanced safety, long cycle life, high energy density, "
            "wide temperature adaptability, and environmental protection."
        ),
        "product_info": (
            "This specification outlines the module's type, size, structure, electro-mechanical "
            "performance, service life, and BMS characteristics and may be updated according to "
            "specific customer requirements."
        ),
        "applications": "Storage Energy UPS Inverters Back-up Power Solutions Industrial Applications",
        "source_url": "https://i-sol.co.uk/product-line-4",
        "pairs": [("RB-LI-48-100", "48VDC / 100Ah")],
    },
    {
        "title": "RB-LI-409.8-512VDC-50Ah-100Ah",
        "display_name": "Li-ion Battery 512VDC-100Ah",
        "category": "Battery Storage Power Solutions",
        "subcategory": "Lithium-ion Battery Packs",
        "capacity_range": "",
        "short_description": (
            "The ENERGEN Lithium Iron Phosphate Battery system is designed for 3-Phase online "
            "UPS applications guaranteeing safety and reliability. It supports a high 6C "
            "discharge current for 10 minutes and is compatible with a wide range of "
            "high-voltage UPS systems."
        ),
        "product_info": (
            "Available in configurations up to 51.2KWH and scalable up to 8 cabinets, the "
            "battery system is protected by a BMS and Circuit Breaker, and offers a maximum "
            "supported UPS capacity up to 250KW."
        ),
        "applications": (
            "3-Phase UPS Systems Data Centers Industrial & Commercial Applications "
            "Renewable Energy Storage Systems"
        ),
        "source_url": "https://i-sol.co.uk/product-line-4",
        "pairs": [
            ("RB-LI-410-50", "409.8VDC / 50Ah"),
            ("RB-LI-512-50", "512VDC / 50Ah"),
            ("RB-LI-410-100", "409.8VDC / 100Ah"),
            ("RB-LI-512-100", "512VDC / 100Ah"),
        ],
    },
    {
        "title": "RB-LI-480VDC-40-100Ah",
        "display_name": "Li-ion Battery 480VDC-100Ah",
        "category": "Battery Storage Power Solutions",
        "subcategory": "Lithium-ion Battery Packs",
        "capacity_range": "",
        "short_description": (
            "A modular parallel-design lithium-ion battery system compatible with the full "
            "range of i-power UPS units, power ranging from 6kW to 1200kW, built on a "
            "nuclear-grade safety design concept."
        ),
        "product_info": (
            "DC/DC isolated design with physical isolation; a faulted battery module exits "
            "automatically without expanding the fault range; module fire protection; "
            "PBMU-SBMU-MBMU three-tier architecture; on-line array insulation detection; "
            "module design supports on-line expansion of capacity."
        ),
        "applications": (
            "3-Phase UPS Systems Data Centers Industrial & Commercial Applications "
            "Renewable Energy Storage Systems"
        ),
        "source_url": "https://i-sol.co.uk/product-line-4",
        "pairs": [],
    },
    {
        "title": "RB-LI-512VDC-200Ah",
        "display_name": "Li-ion Battery 512VDC-200Ah",
        "category": "Battery Storage Power Solutions",
        "subcategory": "Lithium-ion Battery Packs",
        "capacity_range": "",
        "short_description": (
            "The Energen RB-LI-512-200 is a high-voltage lithium iron phosphate (LFP) battery "
            "system purpose-built for resilient data center energy storage, delivering a rated "
            "energy of 102.4kWh and a maximum discharge power of 184kW."
        ),
        "product_info": (
            "Features a three-level BMS architecture (BMU, BCU, BAU) for real-time monitoring "
            "and hardware protection, independent charging circuits, integrated "
            "perfluorohexane fire protection, up to 16 cabinets in parallel, and a 10-year "
            "calendar life."
        ),
        "applications": (
            "3-Phase UPS Systems Data Centers Industrial & Commercial Applications "
            "Renewable Energy Storage Systems"
        ),
        "source_url": "https://i-sol.co.uk/product-line-4",
        "pairs": [("RB-LI-512-200", "512VDC / 200Ah")],
    },
]


def main() -> None:
    old_products, model_to_pid, capacity_lookup = load_old_narrative()
    standard_rows = read_csv(STANDARD_CSV)

    # Drop exact-duplicate rows (same category, same non-empty model list, same
    # non-empty capacity list) — the source has at least one literal scrape
    # artifact ("... - copy", duplicated model/capacity table verbatim).
    seen_keys: set[tuple[str, str, str]] = set()
    deduped_rows = []
    skipped = 0
    for row in standard_rows:
        model = row.get("Model", "").strip()
        capacity = row.get("Capacity", "").strip()
        if model and capacity:
            key = (row["Category"], model, capacity)
            if key in seen_keys:
                skipped += 1
                continue
            seen_keys.add(key)
        deduped_rows.append(row)
    if skipped:
        print(f"Skipped {skipped} exact-duplicate row(s) from the source (e.g. a '- copy' scrape artifact).")
    standard_rows = deduped_rows

    products: list[dict] = []
    model_rows: list[dict] = []

    for index, row in enumerate(standard_rows, start=1):
        pid = f"PROD-{index:03d}"
        category, subcategory = parse_category(row["Category"])
        title = row["Product Name"].strip()
        display_name = build_display_name(title, subcategory)
        pairs = build_model_rows(row, capacity_lookup)
        capacity_range = capacity_range_from_values([c for _, c in pairs if c], title)
        model_codes = [m for m, _ in pairs if m != "(model code not listed)"]

        narrative = find_narrative(model_codes, old_products, model_to_pid)
        if narrative:
            short_description = narrative["short_description"]
            product_info = narrative["product_info"]
            applications = narrative["applications"]
        else:
            span = f", spanning {capacity_range}" if capacity_range else ""
            short_description = (
                f"{display_name} is a {subcategory} product in the {category} category "
                f"from Interconnect Solutions' i-power line{span}."
            )
            product_info = ""
            applications = ""

        product = {
            "product_id": pid,
            "domain": "i-power",
            "category": category,
            "subcategory": subcategory,
            "title": title,
            "display_name": display_name,
            "capacity_range": capacity_range,
            "short_description": short_description,
            "product_info": product_info,
            "technical_details": build_technical_details(row),
            "applications": applications,
            "model_count": len(pairs),
            "spec_status": "verified" if pairs else "range_only",
            "source_type": "website",
            "source_url": row.get("URL", "").strip(),
            "_pairs": pairs,
        }
        products.append(product)

        if pairs:
            for model_code, capacity in pairs:
                model_rows.append(
                    {
                        "product_id": pid,
                        "product_name": display_name,
                        "category": category,
                        "subcategory": subcategory,
                        "model_code": model_code,
                        "capacity": capacity,
                        "variant": "",
                        "mapping_confidence": "verified" if model_code != "(model code not listed)" else "capacity_only",
                        "resolution_method": "source_1to1" if model_code != "(model code not listed)" else "capacity_list",
                    }
                )
        else:
            model_rows.append(
                {
                    "product_id": pid,
                    "product_name": display_name,
                    "category": category,
                    "subcategory": subcategory,
                    "model_code": "(not listed in source)",
                    "capacity": capacity_range,
                    "variant": "",
                    "mapping_confidence": "range_from_name",
                    "resolution_method": "product_name",
                }
            )

    for supplement in _LEGACY_BATTERY_SUPPLEMENT:
        pid = f"PROD-{len(products) + 1:03d}"
        pairs = supplement["pairs"]
        capacity_range = capacity_range_from_values([c for _, c in pairs], supplement["title"])
        product = {
            "product_id": pid,
            "domain": "i-power",
            "category": supplement["category"],
            "subcategory": supplement["subcategory"],
            "title": supplement["title"],
            "display_name": supplement["display_name"],
            "capacity_range": capacity_range,
            "short_description": supplement["short_description"],
            "product_info": supplement["product_info"],
            "technical_details": "",
            "applications": supplement["applications"],
            "model_count": len(pairs),
            "spec_status": "verified" if pairs else "range_only",
            "source_type": "website",
            "source_url": supplement["source_url"],
            "_pairs": pairs,
        }
        products.append(product)
        if pairs:
            for model_code, capacity in pairs:
                model_rows.append(
                    {
                        "product_id": pid,
                        "product_name": supplement["display_name"],
                        "category": supplement["category"],
                        "subcategory": supplement["subcategory"],
                        "model_code": model_code,
                        "capacity": capacity,
                        "variant": "",
                        "mapping_confidence": "verified",
                        "resolution_method": "legacy_source_restored",
                    }
                )
        else:
            model_rows.append(
                {
                    "product_id": pid,
                    "product_name": supplement["display_name"],
                    "category": supplement["category"],
                    "subcategory": supplement["subcategory"],
                    "model_code": "(not listed in source)",
                    "capacity": "",
                    "variant": "",
                    "mapping_confidence": "range_from_name",
                    "resolution_method": "legacy_source_restored",
                }
            )
    if _LEGACY_BATTERY_SUPPLEMENT:
        print(f"Restored {len(_LEGACY_BATTERY_SUPPLEMENT)} legacy battery product(s) missing from the standard export.")

    pcols = [
        "product_id", "domain", "category", "subcategory", "title", "display_name",
        "capacity_range", "short_description", "product_info", "technical_details",
        "applications", "model_count", "spec_status", "source_type", "source_url",
    ]
    with OUT_PRODUCTS_CSV.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=pcols, extrasaction="ignore")
        writer.writeheader()
        for p in products:
            writer.writerow(p)

    mcols = [
        "product_id", "product_name", "category", "subcategory", "model_code",
        "capacity", "variant", "mapping_confidence", "resolution_method",
    ]
    with OUT_MODELS_CSV.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=mcols)
        writer.writeheader()
        writer.writerows(model_rows)

    md_lines = [
        "# Interconnect Solutions / i-Sol — i-Power Product Knowledge Base", "",
        f"Source: {IPOWER_URL}  ",
        f"Products: {len(products)}  ",
        "Each product is a self-contained chunk. Category, subcategory and capacity range are "
        "repeated in every entry so a retrieved chunk carries full context. Rebuilt from "
        "`ipower_products_standard.csv` — capacity ranges are derived directly from each "
        "product's own model/capacity data, not a separately curated label.",
        "",
    ]
    for p in products:
        md_lines += render_product_md(p)
    OUT_MD.write_text("\n".join(md_lines), encoding="utf-8")

    narrative_matches = sum(1 for p in products if p["product_info"] or (
        p["short_description"] and "is a" not in p["short_description"][:40]
    ))
    print(f"{len(products)} products written, {len(model_rows)} model rows.")
    print(f"Categories: {sorted({p['category'] for p in products})}")


if __name__ == "__main__":
    main()
