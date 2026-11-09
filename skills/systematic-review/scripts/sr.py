#!/usr/bin/env python3
"""sr.py - stdlib-only plumbing for the systematic-review skill.

Every subcommand prints one JSON object to stdout and optionally writes it to --out:

    search --db openalex|s2|epmc|arxiv --query Q --limit N [--out FILE]
    (--version prints metadata.version from ../SKILL.md)
    oa DOI                     Unpaywall: is it open access, where is the PDF
    cites DOI --dir back|fwd   S2 references (back) / citations (fwd)
    verify DOI|URL [--title T] [--out verified.json]  exit != 0 unless resolved
    dedupe search/*.json --out records.csv
    screen-diff A.csv B.csv [--arbitrated t1.csv]   counts, % agreement, disagreeing ids
    prisma REVIEW_DIR [--stage 1|2]   PRISMA counts + arithmetic check

The orchestrator reads the JSON counts; raw records are file artefacts. Network calls are
polite: one shared backoff door, S2 gets Retry-After, arXiv calls are serialised 3 s apart
across processes because its API asks for it globally.
"""

import argparse
import csv
import difflib
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

UA = "llm-toolbox-systematic-review/0.1 (+https://github.com/brenozd/llm-toolbox)"
TITLE_MATCH = 0.90  # normalised title similarity `verify` demands
NEAR_TITLE = 0.95  # dedupe auto-links study_id only at/above this; below it a human decides
SKILL_MD = Path(__file__).resolve().parent.parent / "SKILL.md"
STATE = Path(os.environ.get("SR_STATE_DIR") or "/tmp")  # arXiv lock/stamp live here


class HttpStatusError(RuntimeError):
    pass


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def skill_version():
    """metadata.version from ../SKILL.md, so the skill declares its version once."""
    try:
        front = SKILL_MD.read_text().split("---")[1]
    except (OSError, IndexError):
        die(f"no readable frontmatter in {SKILL_MD}")
    found = re.search(r"^\s+version:\s*[\"']?([^\s\"']+)", front, re.M)
    if not found:
        die(f"no metadata.version in {SKILL_MD}")
    return found.group(1)


def die(msg, code=2):
    print(f"sr.py: {msg}", file=sys.stderr)
    sys.exit(code)


# --- network ---------------------------------------------------------------

def _retry_after(exc, cap=30.0):
    try:
        return min(max(float((exc.headers or {}).get("Retry-After")), 0.0), cap)
    except (AttributeError, TypeError, ValueError):
        return None


def _transient(exc):
    """429/5xx (and non-HTTP transport errors) are waits; a 404/422 is final - retrying it
    only delays a failure the caller must hear about at once."""
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code == 429 or exc.code >= 500
    return True


def http_get(url, *, tries=4, timeout=30, headers=None):
    """The one network door (tests replace it). 429/5xx are waits, not answers: honour
    Retry-After, else exponential backoff. Exhausted retries raise - never a fake empty page."""
    hdrs = {"User-Agent": UA, "Accept": "*/*"}
    hdrs.update(headers or {})
    err = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", "replace")
        except Exception as exc:  # noqa: BLE001 - retry only what is transient
            err = exc
            if not _transient(exc) or i + 1 == tries:
                break
            asked = _retry_after(exc) if isinstance(exc, urllib.error.HTTPError) else None
            time.sleep(asked if asked is not None else 1.5 * 2 ** i)
    raise HttpStatusError(f"{url}: {err}")


def get_json(url, **kw):
    return json.loads(http_get(url, **kw))


def s2_get(url):
    """Every Semantic Scholar call (search and cites) goes through here: the free pool 429s
    hard, so give it more tries; S2_API_KEY raises the quota when the user has one."""
    key = os.environ.get("S2_API_KEY")
    return get_json(url, tries=6, headers={"x-api-key": key} if key else None)


def arxiv_get(url):
    """arXiv asks for 3 s between calls globally, so serialise on a lock file and stamp the
    last call there (SR_STATE_DIR, /tmp by default)."""
    lock = STATE / "sr-arxiv.lock"
    stamp = STATE / "sr-arxiv.stamp"
    with open(lock, "a") as fh:
        try:
            import fcntl

            fcntl.flock(fh, fcntl.LOCK_EX)
        except ImportError:  # no fcntl (Windows): unthrottled is better than broken
            pass
        try:
            gap = 3.0 - (time.time() - float(stamp.read_text()))
            if gap > 0:
                time.sleep(gap)
        except (OSError, ValueError):
            pass
        text = http_get(url)
        stamp.write_text(str(time.time()))
    return text


# --- record shape ----------------------------------------------------------

def norm_doi(doi):
    doi = (doi or "").strip().lower()
    doi = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:)", "", doi)
    return doi.strip(" .;")


def norm_title(title):
    title = re.sub(r"<[^>]+>", " ", title or "")
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def stable_id(doi, title):
    """Same paper from any source keeps one id: hash of the DOI, else of the title."""
    key = norm_doi(doi) or norm_title(title)
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def record(doi="", title="", year=None, abstract="", url="", cited_by=None, source=""):
    doi = norm_doi(doi)
    return {
        "id": stable_id(doi, title),
        "doi": doi,
        "title": re.sub(r"\s+", " ", (title or "")).strip(),
        "year": year,
        "abstract": re.sub(r"\s+", " ", abstract or "").strip(),
        "url": url or (f"https://doi.org/{doi}" if doi else ""),
        "cited_by": cited_by,
        "source": source,
    }


def envelope(source, query, total, records, **extra):
    out = {
        "source": source,
        "query": query,
        "run_at": now(),
        "total": total,
        "returned": len(records),
        "records": records,
    }
    out.update(extra)
    return out


def emit(payload, out=None):
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(text + "\n")
    print(text)


# --- search sources --------------------------------------------------------

def inverted_index_to_text(index):
    """OpenAlex stores abstracts as {word: [positions]}. Rebuild the sentence."""
    if not index:
        return ""
    slots = {}
    for word, positions in index.items():
        for pos in positions:
            slots[pos] = word
    return " ".join(slots[i] for i in sorted(slots))


def search_openalex(query, limit):
    params = {"search": query, "per-page": str(min(limit, 200))}
    if os.environ.get("SR_EMAIL"):
        params["mailto"] = os.environ["SR_EMAIL"]
    data = get_json("https://api.openalex.org/works?" + urllib.parse.urlencode(params))
    records = [
        record(
            doi=w.get("doi") or "",
            title=w.get("title") or w.get("display_name") or "",
            year=w.get("publication_year"),
            abstract=inverted_index_to_text(w.get("abstract_inverted_index")),
            url=((w.get("best_oa_location") or {}).get("pdf_url") or (w.get("open_access") or {}).get("oa_url") or ""),
            cited_by=w.get("cited_by_count"),
            source="openalex",
        )
        for w in data.get("results", [])
    ]
    return data["meta"]["count"], records


def search_s2(query, limit):
    params = {
        "query": query,
        "limit": str(min(limit, 100)),
        "fields": "title,abstract,year,citationCount,externalIds,openAccessPdf",
    }
    data = s2_get("https://api.semanticscholar.org/graph/v1/paper/search?" + urllib.parse.urlencode(params))
    records = [
        record(
            doi=(p.get("externalIds") or {}).get("DOI") or "",
            title=p.get("title") or "",
            year=p.get("year"),
            abstract=p.get("abstract") or "",
            url=((p.get("openAccessPdf") or {}).get("url") or ""),
            cited_by=p.get("citationCount"),
            source="s2",
        )
        for p in data.get("data", [])
    ]
    return data.get("total", 0), records


def search_epmc(query, limit):
    params = {
        "query": query,
        "format": "json",
        "pageSize": str(min(limit, 1000)),
        "resultType": "core",
        "cursorMark": "*",
    }
    data = get_json("https://www.ebi.ac.uk/europepmc/webservices/rest/search?" + urllib.parse.urlencode(params))
    records = [
        record(
            doi=r.get("doi") or "",
            title=r.get("title") or "",
            year=int(r["pubYear"]) if str(r.get("pubYear", "")).isdigit() else r.get("pubYear"),
            abstract=r.get("abstractText") or "",
            cited_by=r.get("citedByCount"),
            source="epmc",
        )
        for r in data.get("resultList", {}).get("result", [])
    ]
    return data.get("hitCount", 0), records


NS = {"a": "http://www.w3.org/2005/Atom", "o": "http://a9.com/-/spec/opensearch/1.1/", "x": "http://arxiv.org/schemas/atom"}


def search_arxiv(query, limit):
    params = {"search_query": f"all:{query}", "start": "0", "max_results": str(min(limit, 2000))}
    root = ET.fromstring(arxiv_get("https://export.arxiv.org/api/query?" + urllib.parse.urlencode(params)))
    total = int(root.findtext("o:totalResults", "0", NS))
    records = []
    for e in root.findall("a:entry", NS):
        records.append(
            record(
                doi=e.findtext("x:doi", "", NS),
                title=re.sub(r"\s+", " ", e.findtext("a:title", "", NS)),
                year=(e.findtext("a:published", "") or "")[:4],
                abstract=re.sub(r"\s+", " ", e.findtext("a:summary", "", NS)),
                url=e.findtext("a:id", "", NS),
                source="arxiv",
            )
        )
    return total, records


SOURCES = {"openalex": search_openalex, "s2": search_s2, "epmc": search_epmc, "arxiv": search_arxiv}


# --- subcommands -----------------------------------------------------------

def cmd_search(args):
    total, records = SOURCES[args.db](args.query, args.limit)
    emit(envelope(args.db, args.query, total, records), args.out)


def cmd_oa(args):
    email = os.environ.get("SR_EMAIL", "").strip()
    if not email:
        die("oa needs SR_EMAIL: Unpaywall returns 422 without a real contact email")
    doi = norm_doi(args.doi)
    data = get_json(f"https://api.unpaywall.org/v2/{urllib.parse.quote(doi)}?email={urllib.parse.quote(email)}")
    best = data.get("best_oa_location") or {}
    rec = record(doi=data.get("doi") or doi, title=data.get("title") or "", year=data.get("year"), source="unpaywall")
    rec.update(
        is_oa=bool(data.get("is_oa")),
        oa_status=data.get("oa_status"),
        host_type=best.get("host_type"),
        version=best.get("version"),
        pdf_url=best.get("url_for_pdf") or "",
        oa_locations=len(data.get("oa_locations") or []),
    )
    emit(envelope("unpaywall", doi, 1, [rec]), args.out)


def cmd_cites(args):
    """S2 has no count for neighbours: total is what one page returned (max 100)."""
    doi = norm_doi(args.doi)
    direction, field = ("references", "citedPaper") if args.dir == "back" else ("citations", "citingPaper")
    url = (
        f"https://api.semanticscholar.org/graph/v1/paper/{urllib.parse.quote(doi)}/{direction}"
        "?fields=title,year,externalIds,citationCount&limit=100"
    )
    data = s2_get(url)
    records = [
        record(
            doi=(d[field].get("externalIds") or {}).get("DOI") or "",
            title=d[field].get("title") or "",
            year=d[field].get("year"),
            cited_by=d[field].get("citationCount"),
            source="snowball",
        )
        for d in data.get("data", [])
        if d.get(field)
    ]
    emit(envelope("snowball", doi, len(records), records, dir=args.dir), args.out)


def resolve(ident):
    """One resolver, no fallback chain: any failure raises and `verify` fails closed."""
    if re.match(r"^https?://(?!doi\.org/)", ident):
        title = re.search(r"<title[^>]*>(.*?)</title>", http_get(ident), re.S | re.I)
        text = re.sub(r"\s+", " ", title.group(1)).strip() if title else ""
        # arXiv/HTML titles carry their own id prefix ("[2408.04646v2] Real title")
        return {"title": re.sub(r"^\[[^\]]*\]\s*", "", text), "id": ident}
    doi = norm_doi(ident)
    if not doi.startswith("10."):
        raise ValueError(f"not a DOI or http(s) URL: {ident}")
    w = get_json(f"https://api.openalex.org/works/https://doi.org/{urllib.parse.quote(doi)}")
    return {"title": w.get("title") or w.get("display_name") or "", "id": w.get("doi") or doi}


def cmd_verify(args):
    try:
        found = resolve(args.id)
    except Exception as exc:  # noqa: BLE001 - fail closed on any lookup/network error
        die(f"verify: {args.id} could not be resolved ({exc})")
    expected = (args.title or "").strip()
    got = found["title"]
    ratio = difflib.SequenceMatcher(None, norm_title(expected), norm_title(got)).ratio() if expected else 1.0
    ok = bool(got) and ratio >= TITLE_MATCH
    is_url = bool(re.match(r"^https?://", args.id))
    entry = {
        "id": args.id,
        "doi": "" if is_url else norm_doi(args.id),
        "url": args.id if is_url else "",
        "title": got,
        "expected_title": expected,
        "title_similarity": round(ratio, 3),
        "ok": ok,
        "verified_at": now(),
    }
    log = Path(args.out)
    entries = json.loads(log.read_text()) if log.exists() else []
    entries.append(entry)
    log.write_text(json.dumps(entries, indent=2, ensure_ascii=False) + "\n")
    emit(envelope("verify", args.id, 1, [entry]))
    if not ok:
        die(f"verify: {args.id} title mismatch ({ratio:.2f} < {TITLE_MATCH}) or empty title", code=1)


def load_records(paths):
    """One row per distinct paper; `sources` remembers every database that returned it."""
    records, by_key = [], {}
    for path in paths:
        data = json.loads(Path(path).read_text())
        for rec in data.get("records", []):
            key = rec.get("doi") or norm_title(rec.get("title"))
            if key in by_key:
                kept = by_key[key]
                kept["sources"] = ",".join(sorted({*kept["sources"].split(","), rec.get("source", "")} - {""}))
                kept["abstract"] = kept["abstract"] or rec.get("abstract", "")
                continue
            rec["sources"] = rec.get("source", "")
            by_key[key] = rec
            records.append(rec)
    return records


def cmd_dedupe(args):
    """Drop exact DOI/title repeats; then link titles matching at >= NEAR_TITLE (preprint vs
    published) into one study_id. Every such pair is printed so the human can confirm it."""
    records = load_records(args.files)
    raw = sum(len(json.loads(Path(p).read_text()).get("records", [])) for p in args.files)
    parent = list(range(len(records)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    near = []
    titles = [norm_title(r["title"]) for r in records]
    for i in range(len(records)):
        for j in range(i + 1, len(records)):
            if not titles[i] or not titles[j]:
                continue
            ratio = difflib.SequenceMatcher(None, titles[i], titles[j]).ratio()
            if ratio >= NEAR_TITLE:
                near.append([records[i]["id"], records[j]["id"], round(ratio, 3)])
                parent[find(j)] = find(i)

    for i, rec in enumerate(records):
        rec["study_id"] = records[find(i)]["id"]

    cols = ["id", "study_id", "doi", "title", "year", "source", "sources", "url", "cited_by", "abstract"]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)

    emit(
        {
            "source": "dedupe",
            "query": " ".join(str(p) for p in args.files),
            "run_at": now(),
            "total": raw,
            "returned": len(records),
            "duplicates_removed": raw - len(records),
            "studies": len({r["study_id"] for r in records}),
            "near_duplicates": near,
        }
    )


def read_screen(path):
    with Path(path).open(newline="") as fh:
        return {row["id"].strip(): (row.get("decision") or "").strip().lower() for row in csv.DictReader(fh)}


def cmd_screen_diff(args):
    a, b = read_screen(args.a), read_screen(args.b)
    common = sorted(set(a) & set(b))
    disagree = [i for i in common if a[i] != b[i]]
    # arbitrated ids are already human-decided; anything still missing is unarbitrated work
    resolved = read_screen(args.arbitrated) if args.arbitrated else {}
    unarbitrated = [i for i in disagree if i not in resolved]
    counts = {name: {d: sum(1 for v in dec.values() if v == d) for d in sorted(set(dec.values()))} for name, dec in (("a", a), ("b", b))}
    emit(
        {
            "source": "screen-diff",
            "query": f"{args.a} {args.b}",
            "run_at": now(),
            "total": len(common),
            "returned": len(disagree),
            "agreement_pct": round(100 * (len(common) - len(disagree)) / len(common), 1) if common else 0.0,
            "only_in_a": sorted(set(a) - set(b)),
            "only_in_b": sorted(set(b) - set(a)),
            "disagreeing_ids": disagree,
            "unarbitrated_ids": unarbitrated,
            "counts": counts,
        }
    )


def stage_decisions(directory, prefix):
    """t1-A.csv + t1-B.csv are two passes over the same records: include if either says
    include (a false negative is the expensive error), exclude only on unanimity.
    The human-arbitrated t1.csv/t2.csv is final and overrides both passes."""
    directory = Path(directory)
    merged = {}
    for path in sorted(directory.glob(f"{prefix}*.csv")):
        if path.name == f"{prefix}.csv":  # arbitrated, applied last
            continue
        for rid, decision in read_screen(path).items():
            if decision in ("include", "in"):
                merged[rid] = "include"
            else:
                merged.setdefault(rid, decision)
    arbitrated = directory / f"{prefix}.csv"
    if arbitrated.exists():
        merged.update(read_screen(arbitrated))
    return merged


def cmd_prisma(args):
    review = Path(args.dir)
    if not review.is_dir():
        die(f"prisma: {review} is not a directory")

    identified = 0
    per_source = {}
    per_source_total = {}
    for path in sorted((review / "search").glob("*.json")):
        data = json.loads(path.read_text())
        src = data.get("source") or path.stem
        per_source[src] = per_source.get(src, 0) + int(data.get("returned") or 0)
        per_source_total[src] = per_source_total.get(src, 0) + int(data.get("total") or 0)
        identified += int(data.get("returned") or 0)

    records_csv = review / "records.csv"
    unique = sum(1 for _ in csv.DictReader(records_csv.open(newline=""))) if records_csv.exists() else identified
    study_of = {  # included studies are counted per study, not per report
        row["id"]: row.get("study_id") or row["id"]
        for row in (csv.DictReader(records_csv.open(newline="")) if records_csv.exists() else [])
    }
    identified = identified or unique
    duplicates = max(identified - unique, 0)

    t1 = stage_decisions(review / "screening", "t1")
    excluded_t1 = sum(1 for v in t1.values() if v not in ("include", "in"))
    sought = unique - excluded_t1

    t2 = stage_decisions(review / "screening", "t2")
    not_retrieved_csv = review / "screening" / "not-retrieved.csv"  # phase 4 owns this file
    for rid, decision in (read_screen(not_retrieved_csv) if not_retrieved_csv.exists() else {}).items():
        t2.setdefault(rid, decision)  # arbitration still wins
    reasons = {}  # from the arbitrated t2.csv only; per-pass t2-A/t2-B are for screen-diff
    t2_csv = review / "screening" / "t2.csv"
    for row in csv.DictReader(t2_csv.open(newline="")) if t2_csv.exists() else []:
        if (row.get("decision") or "").strip().lower() == "exclude":
            reason = (row.get("reason") or "unspecified").strip()
            reasons[reason] = reasons.get(reason, 0) + 1

    not_retrieved = sum(1 for v in t2.values() if v == "not-retrieved")
    assessed = sum(1 for v in t2.values() if v in ("include", "exclude"))
    included = sum(1 for v in t2.values() if v == "include")
    included_studies = len({study_of.get(rid, rid) for rid, v in t2.items() if v == "include"})
    excluded_t2 = assessed - included
    balanced = assessed + not_retrieved == sought and included + excluded_t2 == assessed
    if args.stage == 1:  # stage-2 files are not due yet: only the stage-1 flow is checked
        balanced = True

    counts = {
        "identified": identified,
        "duplicates_removed": duplicates,
        "screened": unique,
        "excluded_stage1": excluded_t1,
        "sought_full_text": sought,
        "not_retrieved": not_retrieved,
        "full_text_assessed": assessed,
        "excluded_stage2": excluded_t2,
        "included": included,
        "included_studies": included_studies,
    }
    emit(
        {
            "source": "prisma",
            "query": str(review),
            "run_at": now(),
            "total": identified,
            "returned": included,
            "stage": args.stage,
            "counts": counts,
            "per_source": per_source,
            "per_source_total": per_source_total,
            "excluded_reasons": reasons,
            "balanced": balanced,
        }
    )
    if not balanced:
        die(f"prisma: counts do not add up: {counts}", code=1)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="sr.py", description="systematic-review plumbing (JSON on stdout)")
    parser.add_argument("--version", action="version", version=skill_version())
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("search", help="search one academic database")
    p.add_argument("--db", required=True, choices=sorted(SOURCES), help="openalex | s2 | epmc | arxiv")
    p.add_argument("--query", required=True)
    p.add_argument("--limit", type=int, default=25)
    p.add_argument("--out")
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("oa", help="open-access location for a DOI (needs SR_EMAIL)")
    p.add_argument("doi")
    p.add_argument("--out")
    p.set_defaults(func=cmd_oa)

    p = sub.add_parser("cites", help="snowball: references (back) or citations (fwd)")
    p.add_argument("doi")
    p.add_argument("--dir", required=True, choices=["back", "fwd"])
    p.add_argument("--out")
    p.set_defaults(func=cmd_cites)

    p = sub.add_parser("verify", help="resolve an id; non-zero exit if it does not exist")
    p.add_argument("id")
    p.add_argument("--title", default="", help=f"expected title; similarity must reach {TITLE_MATCH:.2f}")
    p.add_argument("--out", default="verified.json")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("dedupe", help="merge search JSONs into records.csv")
    p.add_argument("files", nargs="+")
    p.add_argument("--out", default="records.csv")
    p.set_defaults(func=cmd_dedupe)

    p = sub.add_parser("screen-diff", help="compare two screening CSVs")
    p.add_argument("a")
    p.add_argument("b")
    p.add_argument("--arbitrated", help="t1.csv/t2.csv: ids already decided by the human")
    p.set_defaults(func=cmd_screen_diff)

    p = sub.add_parser("prisma", help="counts from a review dir (+ arithmetic check)")
    p.add_argument("dir")
    p.add_argument("--stage", type=int, default=2, choices=[1, 2], help="1 = stop after stage-1 screening (partial checkpoint)")
    p.set_defaults(func=cmd_prisma)

    args = parser.parse_args(argv)
    try:
        args.func(args)
    except (HttpStatusError, urllib.error.URLError, OSError, ValueError, KeyError) as exc:
        die(f"{type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
