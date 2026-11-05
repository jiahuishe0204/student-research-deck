"""Build a Tencent SCF deployment ZIP from tracked source and Linux dependencies.

Run on Linux with the same Python minor version as the target SCF runtime.
Dependencies must already be installed into --deps-dir with pip --target.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile


ROOT = Path(__file__).resolve().parents[1]
REQUIRED = {
    "intent_http_entrypoint.py", "preauth_intent_ticket.py",
    "delivery_http_entrypoint.py", "task_scf_entrypoint.py",
    "workflow_service.py", "production_task_queue.py",
    "config/model-routing.json", "config/prompt-stages.json",
    "prompts/P1-intent.md", "schemas/P1-intent.schema.json",
}


def tracked_source():
    raw = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
    names = {Path(item.decode("utf-8")) for item in raw.split(b"\0") if item}
    selected = sorted(path for path in names if
                      (len(path.parts) == 1 and path.suffix == ".py")
                      or (path.parts[0] in {"config", "prompts", "schemas"}
                          and path.suffix in {".json", ".md"}))
    missing = REQUIRED - {path.as_posix() for path in selected}
    if missing:
        raise RuntimeError("SCF source is incomplete: " + ", ".join(sorted(missing)))
    return selected


def build(deps_dir, output):
    deps_dir = Path(deps_dir).resolve()
    output = Path(output).resolve()
    if not deps_dir.is_dir() or not any(deps_dir.iterdir()):
        raise ValueError("Dependency directory is missing or empty")
    source = tracked_source()
    files = {path.as_posix(): ROOT / path for path in source}
    for path in sorted(deps_dir.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        if path.is_symlink():
            raise ValueError("Symlink in dependency directory")
        name = path.relative_to(deps_dir).as_posix()
        if name in files or name == "bundle-manifest.json":
            raise ValueError("Dependency collides with source: " + name)
        files[name] = path
    if len(files) == len(source):
        raise ValueError("Dependency directory has no package files")
    source_hashes = {path.as_posix(): hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
                     for path in source}
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    manifest = json.dumps({"source_commit": commit, "source_sha256": source_hashes},
                          ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name, path in sorted(files.items()):
            archive.write(path, name)
        archive.writestr("bundle-manifest.json", manifest)
    with zipfile.ZipFile(output) as archive:
        if archive.testzip() is not None or not REQUIRED.issubset(archive.namelist()):
            raise RuntimeError("SCF bundle validation failed")
    print(f"SCF bundle ready: {output.name}; source commit {commit[:12]}; {len(files)} files")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--deps-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    build(args.deps_dir, args.output)
