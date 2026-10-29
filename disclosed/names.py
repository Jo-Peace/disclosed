import re
HONORIFICS = {"mr", "mrs", "ms", "miss", "hon", "dr", "md", "facs", "phd", "esq"}
ALIASES = {"tracey robert mann": "Tracey Mann"}   # legal-name variant -> common display name

def normalize_name(s: str) -> str:
    """Clean a PTR filer name: drop honorifics/credentials (Mr, Hon., Dr, MD, FACS...), commas, and duplicated adjacent tokens."""
    toks = [t for t in re.split(r"[\s,]+", s or "") if t]
    toks = [t for t in toks if t.lower().strip(".") not in HONORIFICS]
    out = []
    for t in toks:
        if not out or out[-1].lower() != t.lower(): out.append(t)
    n = " ".join(out)
    return ALIASES.get(n.lower(), n)

def name_key(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", normalize_name(s).lower())

def member_id(f) -> str:
    s = f"{f['last']}-{f['first']}-{f['state_dst']}"
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
def member_name(f) -> str:
    return normalize_name(" ".join(x for x in (f["first"], f["last"], f["suffix"]) if x))
