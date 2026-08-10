#!/usr/bin/env python3
"""Download the latest game file list from GBFRDataTools into data/.

The file list maps internal file paths to their xxh64 hashes; it is
maintained upstream by the GBFRDataTools project at
https://github.com/Nenkai/GBFRDataTools.

Usage:
    python3 update_filelist.py [--out <file.gz>] [--url <url>]
"""
import argparse
import gzip
import os
import urllib.request

DEFAULT_URL = ("https://raw.githubusercontent.com/Nenkai/GBFRDataTools/"
               "master/GBFRDataTools/filelist.txt")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "data", "filelist.txt.gz"))
    ap.add_argument("--url", default=DEFAULT_URL)
    args = ap.parse_args()

    print(f"Downloading {args.url} ...")
    with urllib.request.urlopen(args.url, timeout=60) as r:
        raw = r.read()
    lines = [ln for ln in raw.decode("utf-8").splitlines() if ln]
    print(f"Got {len(lines)} paths ({len(raw):,} bytes)")

    out = args.out
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with gzip.open(out, "wt", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"Wrote {out} ({os.path.getsize(out):,} bytes)")


if __name__ == "__main__":
    main()
