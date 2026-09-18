"""
Look up every client address of the challenge data in the Swiss federal register of buildings and
dwellings (GWR), through the public geo.admin.ch API. No names are sent, only street, number, postcode.

The addresses of data/individual.csv are real Swiss building addresses (15/15 exact matches on a
random sample), so the building attributes the original DATABASE_AGENT_GUIDE.md relies on (year of
construction, heating system, energy source) can be taken from the official register instead of
being invented.

One call per address: MapServer/find on layer ch.bfs.gebaeude_wohnungs_register, field
strname_deinr, filtered on the postcode. When that finds nothing (spelling variants), a second
call goes through the address search (SearchServer) and reads the building by its feature id.

Resumable: every answer is appended to data/gwr_cache.jsonl, and a rerun only queries the
addresses that are not in the cache yet. Throttled to --rate requests per second overall.

Usage:  uv run python scripts/gwr_lookup.py [--data data] [--rate 5] [--limit N]
Output: data/gwr_cache.jsonl (raw, one line per address), read by build_marketplace_db.py
"""
from __future__ import annotations

import argparse
import csv
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

API = "https://api3.geo.admin.ch/rest/services"
LAYER = "ch.bfs.gebaeude_wohnungs_register"
KEEP = ["egid", "edid", "egrid", "strname_deinr", "dplz4", "dplzname", "gdekt", "ggdenr", "ggdename", "gstat",
        "gkat", "gklas", "gbauj", "gbaup", "gabbj", "garea", "gastw", "ganzwhg", "gwaerzh1", "genh1",
        "gwaerdath1", "gwaerzh2", "genh2", "gwaerzw1", "genw1", "gkode", "gkodn", "gexpdat"]


def address_key(street: str, number: str, plz: str) -> str:
    return f"{plz}|{street.strip().lower()}|{number.strip().lower()}"


class Throttle:
    def __init__(self, rate: float):
        self.interval = 1.0 / rate
        self.lock = threading.Lock()
        self.next = time.monotonic()

    def wait(self) -> None:
        with self.lock:
            now = time.monotonic()
            if self.next > now:
                time.sleep(self.next - now)
            self.next = max(now, self.next) + self.interval


def get_json(url: str, throttle: Throttle, tries: int = 4) -> dict:
    for attempt in range(tries):
        throttle.wait()
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < tries - 1:
                time.sleep(2 ** attempt * 2)
                continue
            raise
        except (urllib.error.URLError, TimeoutError):
            if attempt < tries - 1:
                time.sleep(2 ** attempt * 2)
                continue
            raise
    return {}


def lookup(street: str, number: str, plz: str, throttle: Throttle) -> dict:
    """Return {status, attributes} for one address."""
    if not number:
        # named places without a house number ("Schloss Heidegg"): accepted only if one building matches
        q = urllib.parse.urlencode({"layer": LAYER, "searchField": "strname_deinr", "searchText": street,
                                    "contains": "false", "returnGeometry": "false"})
        res = get_json(f"{API}/ech/MapServer/find?{q}", throttle).get("results", [])
        hits = [r for r in res if str(r["attributes"].get("dplz4")) == str(plz)]
        if len({r["attributes"].get("egid") for r in hits}) == 1:
            a = hits[0]["attributes"]
            return {"status": "exact_no_number", "attributes": {k: a.get(k) for k in KEEP}}
        if hits:
            return {"status": "ambiguous_no_number", "attributes": None}
        # the address search labels such places "Schloss Heidegg # 6284 Gelfingen"
        q = urllib.parse.urlencode({"searchText": f"{street} {plz}", "type": "locations", "origins": "address",
                                    "limit": 5})
        for f in get_json(f"{API}/api/SearchServer?{q}", throttle).get("results", []):
            label = f["attrs"].get("label", "").replace("<b>", "").replace("</b>", "")
            if label.lower().startswith(f"{street.lower()} #") and str(plz) in label:
                try:
                    feat = get_json(f"{API}/ech/MapServer/{LAYER}/{f['attrs']['featureId']}?returnGeometry=false",
                                    throttle)
                except urllib.error.HTTPError as e:
                    if e.code != 404:
                        raise
                    feat = {}
                if feat.get("feature"):
                    a = feat["feature"]["attributes"]
                    return {"status": "via_search_no_number", "attributes": {k: a.get(k) for k in KEEP}}
        return {"status": "not_found", "attributes": None}
    q = urllib.parse.urlencode({"layer": LAYER, "searchField": "strname_deinr", "searchText": f"{street} {number}",
                                "contains": "false", "returnGeometry": "false"})
    res = get_json(f"{API}/ech/MapServer/find?{q}", throttle).get("results", [])
    hits = [r for r in res if str(r["attributes"].get("dplz4")) == str(plz)]
    status = "exact"
    if not hits:
        q = urllib.parse.urlencode({"searchText": f"{street} {number} {plz}", "type": "locations",
                                    "origins": "address", "limit": 1})
        found = get_json(f"{API}/api/SearchServer?{q}", throttle).get("results", [])
        label = found[0]["attrs"].get("label", "").replace("<b>", "").replace("</b>", "") if found else ""
        if found and str(plz) in label and number.lower() in label.lower():
            fid = found[0]["attrs"]["featureId"]
            try:
                feat = get_json(f"{API}/ech/MapServer/{LAYER}/{fid}?returnGeometry=false", throttle)
            except urllib.error.HTTPError as e:   # an address point without a GWR building record
                if e.code != 404:
                    raise
                feat = {}
            hits = [feat["feature"]] if feat.get("feature") else []
            status = "via_search"
    if not hits:
        return {"status": "not_found", "attributes": None}
    # several entrances of the same building share the EGID: prefer entrance 0
    hits.sort(key=lambda r: str(r["attributes"].get("edid", "9")))
    a = hits[0]["attributes"]
    return {"status": status, "attributes": {k: a.get(k) for k in KEEP}}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--rate", type=float, default=5.0, help="requests per second, overall")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit", type=int, default=None, help="only the first N missing addresses")
    args = ap.parse_args()
    data = Path(args.data)
    cache_path = data / "gwr_cache.jsonl"

    addresses: dict[str, tuple[str, str, str]] = {}
    with open(data / "individual.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            a = json.loads(row["attributes"])
            if a.get("street") and a.get("plz"):
                k = address_key(a["street"], a.get("house_number") or "", a["plz"])
                addresses[k] = (a["street"], a.get("house_number") or "", a["plz"])

    done = set()
    if cache_path.exists():
        with open(cache_path, encoding="utf-8") as f:
            done = {json.loads(line)["address_key"] for line in f if line.strip()}
    todo = [(k, v) for k, v in addresses.items() if k not in done][: args.limit]
    print(f"{len(addresses)} distinct addresses, {len(done)} cached, {len(todo)} to query", flush=True)

    throttle, lock = Throttle(args.rate), threading.Lock()
    counts = {"exact": 0, "via_search": 0, "exact_no_number": 0, "via_search_no_number": 0,
              "ambiguous_no_number": 0, "not_found": 0,
              "error": 0}
    t0 = time.time()

    def work(item):
        k, (street, number, plz) = item
        try:
            out = lookup(street, number, plz, throttle)
        except Exception as e:  # noqa: BLE001 - recorded, retried on the next run
            with lock:
                counts["error"] += 1
            return
        rec = {"address_key": k, "street": street, "house_number": number, "plz": plz, **out,
               "queried_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        with lock:
            with open(cache_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            counts[out["status"]] += 1
            n = sum(counts.values())
            if n % 250 == 0:
                print(f"{n}/{len(todo)} {counts} {time.time() - t0:.0f}s", flush=True)

    with ThreadPoolExecutor(args.workers) as pool:
        list(pool.map(work, todo))
    print(f"done: {counts} in {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
