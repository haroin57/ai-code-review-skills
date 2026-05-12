#!/usr/bin/env python3
"""Parallel multi-reviewer code review runner.

Runs a configurable set of specialist reviewers in parallel against a diff,
then synthesizes the outputs via a Coordinator. Backed by either `claude -p`
(Claude Code CLI) or `codex exec` (Codex CLI).

Reviewer dispatch:
- DEFAULT_REVIEWERS run on every invocation.
- CONDITIONAL_REVIEWERS run only when the diff touches files matching their
  glob patterns. Use `--force <name>` to override.
- OPT_IN_REVIEWERS never run unless explicitly listed in `--reviewers` (or
  via `--reviewers all`).

Progress is streamed to:
- stderr (line-buffered) — visible via BashOutput when run in background
- --log-file (line-buffered, default: <output-dir>/run.log) — tail-able
- per-reviewer XML files in --output-dir, written as each reviewer finishes
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TextIO

ROOT = Path(__file__).resolve().parent.parent
PROMPTS = ROOT / "prompts"

# Registry of all known reviewers. Phase 1 ships 4. Phase 2 will add
# api-contract and dependencies; Phase 3 will add architecture and
# maintainability. The dispatch machinery is in place from Phase 1 so the
# additions in later phases are just registry edits.
ALL_REVIEWERS: list[str] = [
    "security", "performance", "sre", "coverage",
]
DEFAULT_REVIEWERS: list[str] = [
    "security", "performance", "sre", "coverage",
]
# reviewer name -> list of glob patterns (matched against changed file paths).
# Conditional reviewers are auto-included when at least one changed file
# matches. They can be forced on via --force, or off via --skip.
CONDITIONAL_REVIEWERS: dict[str, list[str]] = {}
# Opt-in reviewers never run by default. They run only when listed in
# --reviewers (or via --reviewers all).
OPT_IN_REVIEWERS: list[str] = []


def render(template: str, variables: dict[str, str]) -> str:
    out = template
    for key, value in variables.items():
        out = out.replace("{{" + key + "}}", value)
    return out


# --- diff parsing / glob matching -------------------------------------------

def extract_changed_files(diff_text: str) -> list[str]:
    """Return the list of changed file paths from a unified diff.

    Reads `+++ b/<path>` lines. /dev/null (file deletion target) is excluded.
    """
    paths: list[str] = []
    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            p = line[len("+++ b/"):].strip()
            if p and p != "/dev/null":
                paths.append(p)
    return paths


_GLOB_CACHE: dict[str, re.Pattern[str]] = {}


def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Translate a git-style glob (supports `**`, `*`, `?`, `{a,b}`) to regex."""
    if pattern in _GLOB_CACHE:
        return _GLOB_CACHE[pattern]
    out: list[str] = []
    i = 0
    while i < len(pattern):
        c = pattern[i]
        if c == "*":
            if i + 1 < len(pattern) and pattern[i + 1] == "*":
                # `**/` matches any number of leading path segments (incl. zero)
                if i + 2 < len(pattern) and pattern[i + 2] == "/":
                    out.append("(?:.*/)?")
                    i += 3
                else:
                    out.append(".*")
                    i += 2
            else:
                out.append("[^/]*")
                i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        elif c == "/":
            out.append("/")
            i += 1
        elif c == "{":
            end = pattern.find("}", i)
            if end == -1:
                out.append(re.escape(c))
                i += 1
            else:
                alts = pattern[i + 1 : end].split(",")
                out.append("(?:" + "|".join(re.escape(a) for a in alts) + ")")
                i = end + 1
        else:
            out.append(re.escape(c))
            i += 1
    rx = re.compile("^" + "".join(out) + "$")
    _GLOB_CACHE[pattern] = rx
    return rx


def any_changed_file_matches(diff_text: str, patterns: list[str]) -> bool:
    paths = extract_changed_files(diff_text)
    for p in paths:
        for pat in patterns:
            if _glob_to_regex(pat).match(p):
                return True
    return False


def select_reviewers(
    diff_text: str,
    requested: list[str] | None,
    force: list[str],
    skip: list[str],
) -> list[str]:
    """Resolve the final reviewer list.

    Rules:
    - requested is None → DEFAULT_REVIEWERS + conditionals whose patterns match.
    - requested == ["all"] → DEFAULT_REVIEWERS + OPT_IN + conditionals (each
      conditional still requires a file match unless in `force`).
    - requested is an explicit list → take that exactly; conditionals still
      need dispatch unless in `force`.
    `force` adds reviewers regardless of dispatch; `skip` removes them.
    """
    if requested is None:
        selected = list(DEFAULT_REVIEWERS)
        for name, patterns in CONDITIONAL_REVIEWERS.items():
            if any_changed_file_matches(diff_text, patterns):
                selected.append(name)
    elif requested == ["all"]:
        selected = list(DEFAULT_REVIEWERS) + list(OPT_IN_REVIEWERS)
        for name, patterns in CONDITIONAL_REVIEWERS.items():
            if name in force or any_changed_file_matches(diff_text, patterns):
                selected.append(name)
    else:
        selected = []
        for name in requested:
            if name in CONDITIONAL_REVIEWERS and name not in force:
                if any_changed_file_matches(diff_text, CONDITIONAL_REVIEWERS[name]):
                    selected.append(name)
                # else: skipped silently (no matching files in diff)
            else:
                selected.append(name)

    for name in force:
        if name not in selected and name in ALL_REVIEWERS:
            selected.append(name)

    selected = [r for r in selected if r not in skip]

    unknown = [r for r in selected if r not in ALL_REVIEWERS]
    if unknown:
        raise ValueError(f"unknown reviewer(s): {unknown}")

    seen: set[str] = set()
    out: list[str] = []
    for r in selected:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


# --- logging ----------------------------------------------------------------

class Logger:
    """Line-buffered logger that fans out to stderr and an optional file."""

    def __init__(self, log_path: Path | None) -> None:
        self.log_path = log_path
        self._file: TextIO | None = None
        if log_path is not None:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            self._file = open(log_path, "a", buffering=1, encoding="utf-8")
        self.t0 = time.monotonic()

    def log(self, msg: str) -> None:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        elapsed = time.monotonic() - self.t0
        line = f"{ts} +{elapsed:6.1f}s  {msg}"
        print(line, file=sys.stderr, flush=True)
        if self._file is not None:
            self._file.write(line + "\n")
            self._file.flush()

    def close(self) -> None:
        if self._file is not None:
            self._file.close()


# --- backend dispatch -------------------------------------------------------

async def run_cli(backend: str, prompt: str, model: str | None) -> str:
    if backend == "claude":
        cmd = ["claude", "-p"]
        if model:
            cmd += ["--model", model]
    elif backend == "codex":
        cmd = ["codex", "exec"]
        if model:
            cmd += ["-m", model]
        cmd += ["-"]
    else:
        raise ValueError(f"unknown backend: {backend}")

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate(prompt.encode())
    if proc.returncode != 0:
        raise RuntimeError(
            f"{backend} exited {proc.returncode}: {stderr.decode(errors='replace')[:1000]}"
        )
    return stdout.decode(errors="replace")


# --- CLI --------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--backend", choices=["claude", "codex"], required=True)
    p.add_argument("--diff", default="-", help="path to diff file, or '-' for stdin")
    p.add_argument(
        "--reviewers",
        default=None,
        help=(
            "comma-separated reviewer subset, or 'all'. "
            f"Available: {','.join(ALL_REVIEWERS)}. "
            "Omit to use defaults + dispatched conditionals."
        ),
    )
    p.add_argument(
        "--force",
        default="",
        help="comma-separated reviewers to force on regardless of dispatch",
    )
    p.add_argument(
        "--skip",
        default="",
        help="comma-separated reviewers to skip even if otherwise selected",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="print the resolved reviewer list and exit (no API calls)",
    )
    p.add_argument("--model", default=None, help="model override (CLI-specific)")
    p.add_argument("--output-dir", default=None, help="save per-reviewer XML + summary")
    p.add_argument(
        "--log-file",
        default=None,
        help="append progress log here (default: <output-dir>/run.log if --output-dir is set)",
    )
    p.add_argument(
        "--no-coordinator",
        action="store_true",
        help="skip Coordinator merge; print each reviewer's raw output",
    )
    # context variables (all optional)
    p.add_argument("--language", default="unknown")
    p.add_argument("--framework", default="unknown")
    p.add_argument("--environment", default="unknown")
    p.add_argument("--trust-boundary", default="unknown")
    p.add_argument("--auth-method", default="unknown")
    p.add_argument("--data-scale", default="unknown")
    p.add_argument("--is-hot-path", default="unknown")
    p.add_argument("--observability-stack", default="unknown")
    p.add_argument("--slo", default="unknown")
    p.add_argument("--test-framework", default="unknown")
    p.add_argument("--current-coverage", default="unknown")
    return p.parse_args()


async def main() -> int:
    args = parse_args()

    if args.diff == "-":
        diff_text = sys.stdin.read()
    else:
        diff_text = Path(args.diff).read_text()
    if not diff_text.strip():
        print("error: empty diff", file=sys.stderr)
        return 2

    requested: list[str] | None
    if args.reviewers is None:
        requested = None
    else:
        raw = [r.strip() for r in args.reviewers.split(",") if r.strip()]
        requested = raw  # 'all' is a single-element list here
    force = [r.strip() for r in args.force.split(",") if r.strip()]
    skip = [r.strip() for r in args.skip.split(",") if r.strip()]

    try:
        selected = select_reviewers(diff_text, requested, force, skip)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    if args.dry_run:
        print(",".join(selected))
        return 0

    if not selected:
        print("error: no reviewers selected", file=sys.stderr)
        return 2

    out_dir: Path | None = Path(args.output_dir) if args.output_dir else None
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)

    log_path: Path | None
    if args.log_file:
        log_path = Path(args.log_file)
    elif out_dir is not None:
        log_path = out_dir / "run.log"
    else:
        log_path = None
    logger = Logger(log_path)

    logger.log(
        f"start backend={args.backend} model={args.model or 'default'} "
        f"reviewers={','.join(selected)} diff_chars={len(diff_text)} "
        f"output_dir={out_dir} log_file={log_path} pid={os.getpid()}"
    )

    common_vars = {
        "language": args.language,
        "framework": args.framework,
        "environment": args.environment,
        "trust_boundary": args.trust_boundary,
        "auth_method": args.auth_method,
        "data_scale": args.data_scale,
        "is_hot_path": args.is_hot_path,
        "observability_stack": args.observability_stack,
        "slo": args.slo,
        "test_framework": args.test_framework,
        "current_coverage": args.current_coverage,
        "diff": diff_text,
    }

    async def run_one(name: str) -> tuple[str, str]:
        template = (PROMPTS / f"{name}.md").read_text()
        prompt = render(template, common_vars)
        start = time.monotonic()
        logger.log(f"[{name}] dispatched ({len(prompt)} chars)")
        try:
            out = await run_cli(args.backend, prompt, args.model)
            dur = time.monotonic() - start
            logger.log(f"[{name}] done in {dur:.1f}s ({len(out)} chars)")
            if out_dir is not None:
                (out_dir / f"{name}.xml").write_text(out)
                logger.log(f"[{name}] wrote {out_dir / f'{name}.xml'}")
            return name, out
        except Exception as e:
            dur = time.monotonic() - start
            logger.log(f"[{name}] FAILED in {dur:.1f}s: {e}")
            stub = f"<{name}_review><!-- failed: {e} --></{name}_review>"
            if out_dir is not None:
                (out_dir / f"{name}.xml").write_text(stub)
            return name, stub

    results = await asyncio.gather(*(run_one(r) for r in selected))
    logger.log(f"all reviewers finished ({len(results)} of {len(selected)})")

    if args.no_coordinator:
        logger.log("coordinator skipped (--no-coordinator)")
        for name, content in results:
            print(f"\n=== {name} ===\n{content}")
        logger.close()
        return 0

    reviews_block = "\n\n".join(content for _, content in results)
    coord_template = (PROMPTS / "coordinator.md").read_text()
    coord_prompt = render(coord_template, {"reviews": reviews_block})
    start = time.monotonic()
    logger.log(f"[coordinator] dispatched ({len(coord_prompt)} chars)")
    try:
        summary = await run_cli(args.backend, coord_prompt, args.model)
        dur = time.monotonic() - start
        logger.log(f"[coordinator] done in {dur:.1f}s ({len(summary)} chars)")
    except Exception as e:
        dur = time.monotonic() - start
        logger.log(f"[coordinator] FAILED in {dur:.1f}s: {e}")
        logger.close()
        return 1

    if out_dir is not None:
        (out_dir / "summary.xml").write_text(summary)
        logger.log(f"[coordinator] wrote {out_dir / 'summary.xml'}")
    print(summary)
    logger.log("done")
    logger.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
