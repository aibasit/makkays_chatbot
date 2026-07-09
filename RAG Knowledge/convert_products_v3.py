"""
Makkays / i-Sol i-Power -> RAG-ready files (v3)
- Auto-parses clean 1:1 model/capacity tables from source
- Merges curated manual resolutions for the 8 previously-flagged products (resolve_flagged.py)
- Emits full provenance (resolution_method) for every model row
"""
import pandas as pd, re
from resolve_flagged import RESOLVED

SRC="/mnt/user-data/uploads/i-power_product_details_for_web.xlsx"
IPOWER_URL="https://i-sol.co.uk/product-line-4"
MODEL_PATS=[r"(?:O[HL]|IH|MH|H[0-9])[0-9X][0-9A-Z]{3,}[SBLCM]", r"\b[RT][0-9]{9}[A-Z]\b", r"RB-LI-[0-9]+-[0-9]+", r"STS[0-9]{5,}"]
CAP_PAT=r"[0-9]+(?:\.[0-9]+)?\s*[kK]?VA(?:\s*/\s*`?[0-9]+(?:\.[0-9]+)?\s*[kK]?W)?"

def clean(v,keep=False):
    if pd.isna(v): return ""
    t=str(v).replace("\r","\n")
    if keep: t=re.sub(r"[ \t]+"," ",t); t=re.sub(r"\n[ \t]*","\n",t); t=re.sub(r"\n{2,}","\n",t)
    else: t=re.sub(r"\s+"," ",t)
    return t.strip()
def models_in(t):
    h=[]
    for p in MODEL_PATS:
        for m in re.finditer(p,t): h.append((m.start(),m.group(0)))
    h.sort(); o=[]
    for _,c in h:
        if c not in o: o.append(c)
    return o
def caps_in(t):
    return [re.sub(r"\s*/\s*","/",re.sub(r"\s+"," ",c)).replace("`","") for c in re.findall(CAP_PAT,t)]
def name_range(n):
    m=re.search(r"\(([^)]*)\)",str(n)); return m.group(1) if m else ""
def extract(raw):
    t=re.sub(r"[ \t]+"," ",str(raw)).replace("\r"," ").replace("\n"," "); tail=t
    for kw in ["Model / Rating","Model Rating","Models:","Model:","Model"]:
        p=t.find(kw)
        if p!=-1 and re.search(r"(O[HL][0-9]|[RT][0-9]{9}|RB-LI)",t[p:p+250]): tail=t[p:]; break
    models=models_in(tail); capseg=tail
    for ck in ["Capacity KVA","Power Rating","Capacity","Rating"]:
        cp=tail.find(ck)
        if cp!=-1: capseg=tail[cp:]; break
    caps=caps_in(capseg)
    if not caps:
        mk=re.search(r"(?i)capacity\s*kva\s*:?\s*([0-9 ]+)",tail)
        if mk: caps=[f"{n}KVA" for n in mk.group(1).split()]
    return models,caps

df=pd.read_excel(SRC,sheet_name="Prodcut")
df=df.drop(columns=[c for c in df.columns if c.startswith("Unnamed: 9")]).rename(columns={"Unnamed: 8":"Applications"})
df=df[df["Domain"].notna()].reset_index(drop=True)

products=[]; model_rows=[]
for i,r in df.iterrows():
    pid=f"PROD-{i+1:03d}"; domain=clean(r["Domain"]); rng=name_range(r["New Name"])
    disp=clean(r["New Name"]) or clean(r["ProdcutName/Title"])
    # spec resolution
    if pid in RESOLVED:
        specs=[(m,c,var) for (m,c,var,meth) in RESOLVED[pid]]
        methods=[meth for (_,_,_,meth) in RESOLVED[pid]]
        has_variants=any(v for _,_,v in specs)
        status="verified"; source_of_specs="manual_resolution"
    else:
        models,caps=extract(r["Full Detail as per the datasheet"])
        if models and len(models)==len(caps):
            specs=[(m,c,"") for m,c in zip(models,caps)]; methods=["source_1to1"]*len(specs)
            status="verified"; has_variants=False; source_of_specs="auto"
        else:
            specs=[]; methods=[]; has_variants=False
            status="range_only"; source_of_specs="none"

    p=dict(product_id=pid,domain=domain,category=clean(r["Category"]),subcategory=clean(r["SubCategory"]),
           title=clean(r["ProdcutName/Title"]),display_name=disp,capacity_range=rng,
           short_description=clean(r["Short Description"]),product_info=clean(r["Prodcut Info"]),
           technical_details=clean(r["Full Detail as per the datasheet"],keep=True),
           applications=clean(r["Applications"]),model_count=len(specs),spec_status=status,
           source_type="website",source_url=(IPOWER_URL if domain=="i-power" else ""))
    p["_specs"]=specs; p["_hasvar"]=has_variants; p["_src"]=source_of_specs
    products.append(p)

    if specs:
        for (m,c,var),meth in zip(specs,methods):
            model_rows.append(dict(product_id=pid,product_name=disp,category=p["category"],
                subcategory=p["subcategory"],model_code=m,capacity=c,variant=var,
                mapping_confidence="verified",resolution_method=meth))
    else:
        model_rows.append(dict(product_id=pid,product_name=disp,category=p["category"],
            subcategory=p["subcategory"],model_code="(not listed in source)",capacity=rng,
            variant="",mapping_confidence="range_from_name",resolution_method="product_name"))

# ---- write one clean file set per product line (domain) ----
DOMAINS={
 "i-power":  {"prefix":"makkays_ipower",  "label":"i-Power",  "url":IPOWER_URL},
 "i-connect":{"prefix":"makkays_iconnect","label":"i-Connect","url":""},
}
pcols=["product_id","domain","category","subcategory","title","display_name","capacity_range",
       "short_description","product_info","technical_details","applications","model_count",
       "spec_status","source_type","source_url"]

def render_product_md(p):
    d=p["display_name"] or p["title"]
    L=["---","",f"## {d}","",
       f"**{d}** is a *{p['subcategory']}* product in the **{p['category']}** category "
       f"({p['capacity_range']}), part of the **{p['domain']}** product line.",""]
    if p["title"] and p["title"]!=d: L+=[f"**Full model / title:** {p['title']}",""]
    L+=[f"**Category:** {p['category']} > {p['subcategory']}  ",
        f"**Capacity range:** {p['capacity_range']}  ",f"**Product line:** {p['domain']}  ",""]
    if p["short_description"]: L+=["**Summary:**  ",p["short_description"],""]
    if p["product_info"]: L+=["**Overview:**  ",p["product_info"],""]
    if p["_specs"]:
        L+=["**Models & capacities:**",""]
        if p["_hasvar"]:
            caps=[]; table={}
            for m,c,var in p["_specs"]:
                if c not in caps: caps.append(c); table[c]={}
                table[c][var]=m
            variants=sorted({v for _,_,v in p["_specs"]})
            L.append("| Capacity | "+" | ".join(f"Model ({v})" for v in variants)+" |")
            L.append("|---|"+ "|".join("---" for _ in variants)+"|")
            for c in caps:
                L.append("| "+c+" | "+" | ".join(table[c].get(v,"—") for v in variants)+" |")
        else:
            L+=["| Model code | Capacity |","|---|---|"]
            for m,c,_ in p["_specs"]: L.append(f"| {m} | {c} |")
        L.append("")
    else:
        L+=["**Models & capacities:**  ",
            f"Capacity range: {p['capacity_range']}. *(No individual model codes are listed in "
            f"the source text — refer to the datasheet for specific models.)*",""]
    if p["applications"]: L+=[f"**Typical applications:** {p['applications']}",""]
    if p["source_url"]: L+=[f"**Source:** {p['source_url']}",""]
    return L

for dom,meta in DOMAINS.items():
    dprods=[p for p in products if p["domain"]==dom]
    if not dprods: continue
    pids={p["product_id"] for p in dprods}
    drows=[r for r in model_rows if r["product_id"] in pids]
    px=meta["prefix"]

    # products CSV
    pdf=pd.DataFrame(dprods)[pcols].copy()
    for c in ["short_description","product_info","technical_details","applications"]:
        pdf[c]=pdf[c].str.replace("\n"," ",regex=False)
    pdf.to_csv(f"/home/claude/{px}_products.csv",index=False)
    # models CSV
    pd.DataFrame(drows)[["product_id","product_name","category","subcategory","model_code",
        "capacity","variant","mapping_confidence","resolution_method"]].to_csv(
        f"/home/claude/{px}_models.csv",index=False)
    # markdown
    src=f"Source: {meta['url']}  " if meta["url"] else "Source: (i-Connect product-line page — add URL)  "
    L=[f"# Makkays / i-Sol — {meta['label']} Product Knowledge Base","",src,
       f"Products: {len(dprods)}  ",
       "Each product is a self-contained chunk. Category, subcategory and capacity range are "
       "repeated in every entry so a retrieved chunk carries full context. Every model/capacity "
       "table is verified — either as a direct 1:1 match in the source, from source-labelled "
       "variants, or via the confirmed model-code capacity convention.",""]
    for p in dprods: L+=render_product_md(p)
    open(f"/home/claude/{px}_products.md","w").write("\n".join(L))

    print(f"[{meta['label']}] {len(dprods)} products, {len(drows)} model rows -> "
          f"{px}_products.md / .csv, {px}_models.csv | "
          f"spec_status={pdf['spec_status'].value_counts().to_dict()}")
