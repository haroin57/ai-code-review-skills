#!/usr/bin/env python3
"""Parallel multi-reviewer code review runner.

Runs Security / Performance / SRE / Coverage reviewers in parallel against a
diff, then synthesizes the outputs via a Coordinator. Backed by either
`claude -p` (Claude Code CLI) or `codex exec` (Codex CLI).

Progress is streamed to:
- stderr (line-buffered) — visible via BashOutput when run in background
- --log-file (line-buffered, default: <output-dir>/run.log) — tail-able from
  another shell or Claude Code
- per-reviewer XML files in --output-dir, written as each reviewer finishes
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TextIO

ROOT = Path(__file__).resolve().parent.parent
PROMPTS = ROOT / "prompts"
REVIEWERS = ["security", "performance", "sre", "coverage"]


def render(template: str, variables: dict[str, str]) -> str:
    out = template
    for key, value in variables.items():
        out = out.replace("{{" + key + "}}", value)
    return out


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


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--backend", choices=["claude", "codex"], required=True)
    p.add_argument("--diff", default="-", help="path to diff file, or '-' for stdin")
    p.add_argument(
        "--reviewers",
        default=",".join(REVIEWERS),
        help="comma-separated subset of: " + ",".join(REVIEWERS),
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

    selected = [r.strip() for r in args.reviewers.split(",") if r.strip()]
    unknown = [r for r in selected if r not in REVIEWERS]
    if unknown:
        print(f"error: unknown reviewer(s): {unknown}", file=sys.stderr)
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
