"""
Offline routing check (no API calls, no cost): where does every prompt go?

    python scripts/check_routes.py                 # summary of rules hit per dataset
    python scripts/check_routes.py --rule R1-attack   # list prompts hitting one rule

Run this after changing a cue list or rule. It shows which rule fires for
every prompt in the datasets, so if a new cue starts catching normal requests
by mistake you see it before spending anything on API calls.
"""
import argparse
import collections
import json
import pathlib
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from router.classify import classify, mask_pii  # noqa: E402
from router.rules import route  # noqa: E402

DATASETS = ["data/tuning_v2.jsonl", "data/test.jsonl", "data/dev.jsonl"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rule", default=None)
    args = ap.parse_args()
    ten = {f.stem: yaml.safe_load(open(f, encoding="utf8")) for f in (ROOT / "config/tenants").glob("*.yaml")}
    for name in DATASETS:
        counts = collections.Counter()
        for l in open(ROOT / name, encoding="utf8"):
            r = json.loads(l)
            c = classify(mask_pii(r["prompt"])[0])
            d = route(r, c, ten[r["tenant"]])
            counts[d.rule_id] += 1
            if args.rule and d.rule_id == args.rule:
                print(f"{name:20s} {r['id']:4s} [{r['category']}] {r['prompt'][:80]!r}")
                if d.template:
                    print(f"{'':25s} reply: {d.template[:90]}")
        if not args.rule:
            print(name, dict(sorted(counts.items())))


if __name__ == "__main__":
    main()
