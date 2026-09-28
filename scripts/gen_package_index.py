#!/usr/bin/env python3
"""Generate repo.json, the package index behind packages.html.

Usage: gen_package_index.py OUTPUT NAME=PATH [NAME=PATH ...]

Each NAME=PATH is a checkout of one sauzerOS recipe repository, e.g.
sauzeros=recipes/sauzeros. A recipe is any directory containing a `version`
file; split packages come from `depends.<name>` files and `split/<name>/`
directories, as in hokuto. Only the standard library is used, so the GitHub
workflow needs nothing installed.
"""

import datetime
import json
import os
import re
import subprocess
import sys

FLAGS = {"make", "makeopt", "cross", "crossnative", "nocross", "optional",
         "rebuild", "runtime", "post-install", "postinstall", "suggest"}
CONSTRAINT = re.compile(r"(==|<=|>=|<|>)")


def dep_name(token):
    """pkg==1.* -> pkg"""
    return CONSTRAINT.split(token, 1)[0]


def parse_depends(text):
    """Split a depends file into runtime, build and suggested dependencies.

    Cross-build lines and post-install helpers are left out: the index
    describes the installed native package. Alternatives stay together as
    "a | b".
    """
    runtime, build, suggests = [], [], []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        words = line.split()
        if "suggest" in words:
            # "<names> suggest <text>", the text quoted or not.
            at = words.index("suggest")
            names = [w for w in words[:at] if w not in FLAGS and w != "|"]
            text = " ".join(words[at + 1:]).strip().strip('"')
            if names:
                suggests.append({"name": " | ".join(dep_name(n) for n in names), "text": text})
            continue
        flags = {w for w in words if w in FLAGS}
        names = [w for w in words if w not in FLAGS and w != "|"]
        # Cross-build lines and post-install helpers are not dependencies of
        # the installed native package.
        if not names or flags & {"cross", "crossnative", "post-install", "postinstall"}:
            continue
        entry = " | ".join(dep_name(n) for n in names)
        if flags & {"make", "makeopt"}:
            build.append(entry)
        else:
            runtime.append(entry)
    return runtime, build, suggests


def read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def split_names(recipe_dir):
    names = set()
    for entry in os.listdir(recipe_dir):
        if entry.startswith("depends.") and os.path.isfile(os.path.join(recipe_dir, entry)):
            names.add(entry[len("depends."):])
    split_dir = os.path.join(recipe_dir, "split")
    if os.path.isdir(split_dir):
        for entry in os.listdir(split_dir):
            if os.path.isfile(os.path.join(split_dir, entry, "depends")):
                names.add(entry)
    return sorted(names)


def git_commit(path):
    try:
        return subprocess.run(["git", "-C", path, "rev-parse", "HEAD"], capture_output=True,
                              text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def scan(repo_name, root):
    packages = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith(".") and d != "split")
        if "version" not in filenames or dirpath == root:
            continue
        # A recipe never contains another recipe.
        dirnames[:] = []
        fields = read(os.path.join(dirpath, "version")).split()
        if not fields:
            continue
        rel = os.path.relpath(dirpath, root)
        try:
            meta = json.loads(read(os.path.join(dirpath, "metadata.json")) or "{}")
        except json.JSONDecodeError:
            meta = {}
        license_ = meta.get("license", "")
        if isinstance(license_, str) and license_.startswith("["):
            # Some recipes store the license as a JSON-encoded list.
            try:
                license_ = ", ".join(json.loads(license_))
            except json.JSONDecodeError:
                pass
        elif isinstance(license_, list):
            license_ = ", ".join(license_)
        runtime, build, suggests = parse_depends(read(os.path.join(dirpath, "depends")))
        packages.append({
            "name": os.path.basename(dirpath),
            "version": fields[0],
            "revision": fields[1] if len(fields) > 1 else "1",
            "repo": repo_name,
            "path": rel,
            "description": meta.get("description", ""),
            "url": meta.get("url", ""),
            "license": license_,
            "tags": meta.get("tags") or [],
            "depends": runtime,
            "makedepends": build,
            "suggests": suggests,
            "splits": split_names(dirpath),
        })
    return packages


def main(argv):
    if len(argv) < 3:
        sys.exit(__doc__)
    output = argv[1]
    packages, repos = [], {}
    for spec in argv[2:]:
        name, _, path = spec.partition("=")
        if not path or not os.path.isdir(path):
            sys.exit(f"not a directory: {spec}")
        repos[name] = git_commit(path)
        packages.extend(scan(name, path))
    packages.sort(key=lambda p: (p["name"], p["repo"]))
    index = {
        "generated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "repos": repos,
        "packages": packages,
    }
    with open(output, "w", encoding="utf-8") as f:
        json.dump(index, f, separators=(",", ":"), ensure_ascii=False)
        f.write("\n")
    print(f"{output}: {len(packages)} packages from {', '.join(repos)}")


if __name__ == "__main__":
    main(sys.argv)
