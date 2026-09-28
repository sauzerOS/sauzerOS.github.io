#!/usr/bin/env python3
"""One-off: bring logs/ in line with hokuto's log retention.

hokuto now stores build logs gzip-compressed (.txt.gz) and keeps the newest
three per package, recorded newest first in packages.json ("logs"). This
converts the existing plain-text logs to that layout:

  * each log file is assigned to the package it belongs to: the longest
    recipe name (from repo.json and packages.json) that prefixes the
    filename;
  * per package, the three most recently added logs (by git history) are kept,
    always including the one packages.json currently links;
  * kept logs are gzip-compressed, all others and unassignable ones deleted.

Deleted logs remain in git history. Nothing is committed; review with
`git status`, then commit with `git add -A packages.json logs`.
Run from the repository root: scripts/migrate_logs.py
"""

import gzip
import json
import os
import subprocess
import sys

KEEP = 3


def added_times():
    """logs/<file> -> commit time it was first added."""
    out = subprocess.run(
        ["git", "log", "--diff-filter=A", "--name-only", "--format=%x00%ct", "--", "logs"],
        capture_output=True, text=True, check=True).stdout
    times = {}
    for block in out.split("\0")[1:]:
        lines = block.strip().splitlines()
        if not lines:
            continue
        stamp = int(lines[0])
        for path in lines[1:]:
            # git log is newest first: the last entry seen is the first add.
            times[path.strip()] = stamp
    return times


def owner(filename, names):
    base = filename.removesuffix(".gz").removesuffix(".txt")
    best = None
    for name in names:
        if base.startswith(name + "-") and (best is None or len(name) > len(best)):
            best = name
    return best


def main():
    if not os.path.isfile("packages.json") or not os.path.isdir("logs"):
        sys.exit("run this from the root of the sauzerOS.github.io checkout")
    with open("packages.json") as f:
        packages = json.load(f)
    by_name = {p["pkgname"]: p for p in packages}
    # Match against every recipe name, not only built ones: otherwise a
    # qt-5compat log would be taken for a qt log.
    names = set(by_name)
    if os.path.isfile("repo.json"):
        with open("repo.json") as f:
            for pkg in json.load(f)["packages"]:
                names.add(pkg["name"])
                names.update(pkg.get("splits", []))
    times = added_times()

    groups, orphans = {}, []
    for filename in sorted(os.listdir("logs")):
        path = "logs/" + filename
        name = owner(filename, names)
        if name is not None and name not in by_name:
            # A recipe that has logs but no packages.json entry.
            orphans.append(path)
            continue
        if name is None:
            orphans.append(path)
        else:
            groups.setdefault(name, []).append(path)

    kept_count = removed = 0
    before = sum(os.path.getsize("logs/" + f) for f in os.listdir("logs"))
    for name, paths in groups.items():
        current = by_name[name].get("log", "")
        paths.sort(key=lambda p: (p == current, times.get(p, 0), p), reverse=True)
        keep, drop = paths[:KEEP], paths[KEEP:]
        history = []
        for path in keep:
            if path.endswith(".gz"):
                history.append(path)
                continue
            with open(path, "rb") as src, gzip.GzipFile(path + ".gz", "wb", compresslevel=9, mtime=0) as dst:
                dst.write(src.read())
            os.remove(path)
            history.append(path + ".gz")
        for path in drop:
            os.remove(path)
        by_name[name]["logs"] = history
        by_name[name]["log"] = history[0]
        kept_count += len(keep)
        removed += len(drop)
    for path in orphans:
        os.remove(path)

    # Entries whose log file is gone keep no link rather than a dead one.
    for entry in packages:
        if entry.get("log") and not os.path.exists(entry["log"]):
            entry.pop("log", None)
            entry.pop("logs", None)

    with open("packages.json", "w") as f:
        json.dump(packages, f, indent=2)
        f.write("\n")
    after = sum(os.path.getsize("logs/" + f) for f in os.listdir("logs"))
    print(f"kept {kept_count} logs for {len(groups)} packages, removed {removed} older and "
          f"{len(orphans)} unassignable logs; logs/ {before / 1e6:.0f} MB -> {after / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
