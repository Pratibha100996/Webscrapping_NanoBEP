import argparse
import sys
import json
import urllib.error
import urllib.request
from collections import defaultdict
from typing import Dict, List, Set, Tuple

RCSB_GRAPHQL_URL = "https://data.rcsb.org/graphql"


def build_query(pdb_id: str) -> str:
    return (
        "query($id:String!){"
        "entry(entry_id:$id){"
        "polymer_entities{"
        "rcsb_polymer_entity_container_identifiers{auth_asym_ids}"
        "rcsb_polymer_entity{pdbx_description}"
        "uniprots{rcsb_id}"
        "}"
        "}"
        "}"
    )


def fetch_entry(pdb_id: str, timeout: int = 30) -> dict:
    payload = {
        "query": build_query(pdb_id),
        "variables": {"id": pdb_id.upper()},
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        RCSB_GRAPHQL_URL,
        data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def parse_chain_uniprot(entry: dict) -> List[Tuple[str, str, str]]:
    data = entry.get("data", {}).get("entry")
    if not data:
        errors = entry.get("errors")
        if errors:
            raise ValueError(f"RCSB returned errors: {errors}")
        raise ValueError("No entry found for the provided PDB ID")

    out: List[Tuple[str, str, str]] = []
    for entity in data.get("polymer_entities", []):
        ids = entity.get("rcsb_polymer_entity_container_identifiers", {}) or {}
        chain_ids = ids.get("auth_asym_ids") or []
        desc = (entity.get("rcsb_polymer_entity", {}) or {}).get("pdbx_description") or "UNKNOWN"
        uniprots = entity.get("uniprots") or []

        uni_ids = [u.get("rcsb_id") for u in uniprots if u.get("rcsb_id")]
        if not uni_ids:
            uni_ids = ["NOT_MAPPED"]

        for chain in chain_ids:
            for uni in uni_ids:
                out.append((chain, desc, uni))

    return sorted(out, key=lambda x: (x[0], x[2]))


def summarize_two_partners(rows: List[Tuple[str, str, str]]) -> Dict[str, Set[str]]:
    by_chain: Dict[str, Set[str]] = defaultdict(set)
    for chain, _desc, uni in rows:
        by_chain[chain].add(uni)
    return by_chain


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Given a PDB ID, print UniProt IDs mapped to each chain in the complex."
    )
    parser.add_argument("--pdb-id", required=True, help="PDB ID, e.g. 1BRS")
    parser.add_argument("--timeout", type=int, default=30, help="HTTP timeout in seconds")
    args = parser.parse_args()

    try:
        result = fetch_entry(args.pdb_id, timeout=args.timeout)
        rows = parse_chain_uniprot(result)
    except urllib.error.HTTPError as exc:
        print(f"Error: HTTP error from RCSB: {exc.code} {exc.reason}", file=sys.stderr)
        raise SystemExit(1)
    except urllib.error.URLError as exc:
        print(f"Error: Network error while contacting RCSB: {exc.reason}", file=sys.stderr)
        raise SystemExit(1)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)

    if not rows:
        print(f"PDB: {args.pdb_id.upper()}")
        print("No polymer chain to UniProt mapping found.")
        return

    print(f"PDB: {args.pdb_id.upper()}")
    print("Chain -> UniProt mapping:")
    for chain, desc, uni in rows:
        print(f"  {chain}: {uni} ({desc})")

    by_chain = summarize_two_partners(rows)
    chains = sorted(by_chain.keys())
    if len(chains) >= 2:
        print("\nFirst two detected chains (potential complex partners):")
        print(f"  Partner 1 chain {chains[0]} -> {', '.join(sorted(by_chain[chains[0]]))}")
        print(f"  Partner 2 chain {chains[1]} -> {', '.join(sorted(by_chain[chains[1]]))}")


if __name__ == "__main__":
    main()
