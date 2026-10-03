#!/usr/bin/env python3
"""One-time migration of packages.json to per-architecture builds.

Until hokuto 0.4.21-15 every build with --index wrote one entry per recipe,
and its log to logs/<pkg>-<version>.txt.gz, whatever it built. A cross,system
build (the aarch64-foo sysroot package) therefore replaced the status of the
native x86_64 build and overwrote its log when the version was the same.

This script, run from the website checkout:
  - drops entries of sysroot packages (aarch64-*, x86_64-*);
  - drops logs of cross,system builds (the cross toolchain, aarch64-gcc, is
    among their installed build dependencies) and, where such a log had
    overwritten the native build's log of the same version, restores the
    native log from git history;
  - for an entry left without a native log, restores the newest native log
    of the package that git history has;
  - rewrites each entry as {"pkgname", "builds": {"x86_64": {...}}}, the
    format hokuto now writes, taking version, status, date and build time of
    the newest native log from the log itself.

Usage: scripts/migrate_arch_builds.py [--dry-run]
"""

import datetime
import email.utils
import gzip
import json
import os
import re
import subprocess
import sys

ANSI = re.compile(r"\x1b\[[0-9;]*m")
COMPLETE = re.compile(r">>> \S+: Build (complete|failed) at (.+?) elapsed time (\S+)")
DURATION = re.compile(r"(\d+(?:\.\d+)?)(h|ms|m|s|us|µs|ns)")


def git(*args, text=True):
    return subprocess.run(["git", *args], capture_output=True, check=True, text=text).stdout


def decompress(data):
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    return ANSI.sub("", data.decode("utf-8", "replace"))


def is_cross_system(text):
    """A cross,system build installs the cross toolchain for itself."""
    header = text.split("\n", 6)[:6]
    return any("build dependencies:" in line and "aarch64-gcc-" in line for line in header)


def seconds(duration):
    """Go's time.Duration text (1h2m3.5s) in whole seconds."""
    scale = {"h": 3600, "m": 60, "s": 1, "ms": 1e-3, "us": 1e-6, "µs": 1e-6, "ns": 1e-9}
    total = sum(float(n) * scale[u] for n, u in DURATION.findall(duration))
    return int(round(total))


def parse_log(text):
    """Status, RFC 3339 date and build time from hokuto's closing line."""
    for line in reversed(text.splitlines()):
        m = COMPLETE.search(line)
        if m:
            status = "success" if m.group(1) == "complete" else "failed"
            try:
                when = email.utils.parsedate_to_datetime(m.group(2)).astimezone(datetime.timezone.utc)
                built = when.strftime("%Y-%m-%dT%H:%M:%SZ")
            except (TypeError, ValueError):
                built = ""
            return status, built, seconds(m.group(3))
    return "", "", 0


def native_from_history(path):
    """The newest committed version of path that is not a cross,system log."""
    for commit in git("log", "--format=%H", "--", path).split():
        try:
            data = git("show", f"{commit}:{path}", text=False)
        except subprocess.CalledProcessError:
            continue  # deleted in that commit
        if not is_cross_system(decompress(data)):
            return data
    return None


_history = None


def logs_in_history():
    """Every log path ever committed, the most recently changed first."""
    global _history
    if _history is None:
        seen, _history = set(), []
        for path in git("log", "--format=", "--name-only", "--", "logs/").split("\n"):
            if path.endswith(".txt.gz") and path not in seen:
                seen.add(path)
                _history.append(path)
    return _history


def deleted_native_log(name):
    """The newest native log of name in git history: (path, data) or None."""
    prefix = re.compile(re.escape(f"logs/{name}-") + r"[0-9]")
    first = f">>> {name}: Building {name} "
    for path in logs_in_history():
        if not prefix.match(path):
            continue
        data = native_from_history(path)
        if data is not None and decompress(data).startswith(first):
            return path, data
    return None


def main():
    dry = "--dry-run" in sys.argv[1:]
    with open("packages.json") as f:
        entries = json.load(f)

    out, removed, restored, dropped_entries = [], [], [], []
    for entry in entries:
        name = entry["pkgname"]
        logs = entry.get("logs") or ([entry["log"]] if entry.get("log") else [])
        if "builds" in entry:
            out.append(entry)  # already migrated
            continue
        if name.startswith(("aarch64-", "x86_64-")):
            dropped_entries.append(name)
            removed += [l for l in logs if os.path.exists(l)]
            continue

        native = []
        for log in logs:
            if not os.path.exists(log):
                continue
            with open(log, "rb") as f:
                text = decompress(f.read())
            if not is_cross_system(text):
                native.append((log, text))
                continue
            data = native_from_history(log)
            if data is None:
                removed.append(log)
                continue
            restored.append((log, data))
            native.append((log, decompress(data)))

        if not native:
            # Every kept log is a cross,system one. The native build's log
            # fell out of the kept window earlier; git history has it.
            found = deleted_native_log(name)
            if found is None:
                dropped_entries.append(name)
                continue
            restored.append(found)
            native.append((found[0], decompress(found[1])))
        newest, text = native[0]
        status, built, buildtime = parse_log(text)
        version = os.path.basename(newest)[len(name) + 1:].split(".txt")[0]
        if newest == entry.get("log"):
            # The entry described this very build: trust what it recorded.
            status = entry.get("status") or status
            built = entry.get("built") or built
        build = {"version": version, "status": status or "success"}
        if built:
            build["built"] = built
        if buildtime:
            build["buildtime"] = buildtime
        build["log"] = newest
        build["logs"] = [log for log, _ in native]
        out.append({"pkgname": name, "builds": {"x86_64": build}})

    print(f"{len(entries)} entries: {len(out)} kept, {len(dropped_entries)} dropped "
          f"(sysroot packages or only cross,system logs)")
    print(f"{len(restored)} native logs restored from git history, {len(removed)} cross,system logs removed")
    if dry:
        for name in dropped_entries:
            print("  drop", name)
        for log, _ in restored:
            print("  restore", log)
        for log in removed:
            print("  remove", log)
        return

    for log, data in restored:
        with open(log, "wb") as f:
            f.write(data)
    for log in removed:
        os.remove(log)
    with open("packages.json", "w") as f:
        json.dump(out, f, indent=2)
        f.write("\n")


if __name__ == "__main__":
    main()
