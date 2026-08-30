"""Micro-benchmarks for the ttydiff pipeline (Task 3).

Runnable with the standard library only:

    python scripts/benchmark.py            # timing summary
    python scripts/benchmark.py --profile  # cProfile the diff hot path

Measures three things:
  1. Full diff (``diff_screens``, with scroll detection) vs. the incremental
     fast path (``diff_screens_incremental``) on a large screen with a small
     edit — the case the Task 3 optimization targets.
  2. Parser throughput on a large synthetic byte stream.
"""

from __future__ import annotations

import argparse
import cProfile
import pstats
import sys
import time
from pathlib import Path

# Allow `python scripts/benchmark.py` from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.contracts import ScreenState  # noqa: E402
from src.diff import diff_screens, diff_screens_incremental  # noqa: E402
from src.parser import ANSIParser  # noqa: E402
from src.screen import DirtyRows, apply_events  # noqa: E402


def _big_screen(rows: int, cols: int) -> ScreenState:
    state = ScreenState.blank(rows, cols)
    parser = ANSIParser()
    # Fill each row with a *distinct* repeated character so adjacent rows are
    # dissimilar — otherwise the scroll detector treats the uniform grid as a
    # scroll and the full/incremental results legitimately diverge.
    lines = []
    for r in range(rows):
        ch = bytes([33 + (r % 90)])  # printable ASCII, cycles 33..122
        lines.append(b"\x1b[%d;1H%s" % (r + 1, ch * (cols - 1)))
    apply_events(state, parser.parse(b"".join(lines)))
    return state


def _timed(label: str, fn, iterations: int) -> float:
    start = time.perf_counter()
    for _ in range(iterations):
        fn()
    elapsed = time.perf_counter() - start
    per = elapsed / iterations * 1e6
    print(f"  {label:<34} {per:9.1f} us/op  ({iterations} iters)")
    return elapsed


def bench_diff(rows: int = 80, cols: int = 250) -> None:
    # rows <= 90 keeps every row's fill character unique (printable ASCII 33..),
    # so no shift aligns and the scroll detector correctly reports no scroll.
    print(f"\nDiff ({rows}x{cols} screen, single-cell edit):")
    before = _big_screen(rows, cols)

    # One small edit on the last row, tracked incrementally.
    after = before.snapshot()
    dirty = DirtyRows()
    parser = ANSIParser()
    apply_events(after, parser.parse(b"\x1b[%d;1HZ" % rows), dirty=dirty)
    changed_rows = dirty.rows(after.rows)

    # Sanity: with dissimilar rows there is no scroll, so both agree.
    full_result = diff_screens(before, after)
    incr_result = diff_screens_incremental(before, after, changed_rows)
    assert not full_result.scrolled, "benchmark data unexpectedly scrolled"
    assert full_result.changes == incr_result.changes

    # Full diff is O(rows^2 * cols) via scroll detection — keep iterations low.
    full = _timed("diff_screens (full + scroll scan)", lambda: diff_screens(before, after), 5)
    incr = _timed(
        "diff_screens_incremental",
        lambda: diff_screens_incremental(before, after, changed_rows),
        200,
    )
    full_per = full / 5
    incr_per = incr / 200
    if incr_per > 0:
        print(f"  -> incremental is {full_per / incr_per:.0f}x faster on this edit")


def bench_parser(size_kb: int = 256, iterations: int = 20) -> None:
    print(f"\nParser throughput ({size_kb} KB stream):")
    data = (b"hello \x1b[31mworld\x1b[0m\n" * (size_kb * 1024 // 22))

    def run() -> None:
        list(ANSIParser().feed(data))

    elapsed = _timed("ANSIParser.feed", run, iterations)
    mb = (len(data) * iterations) / (1024 * 1024)
    if elapsed > 0:
        print(f"  -> {mb / elapsed:.1f} MB/s")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="ttydiff benchmarks")
    ap.add_argument("--profile", action="store_true", help="cProfile the full diff")
    args = ap.parse_args(argv)

    if args.profile:
        before = _big_screen(200, 200)
        after = before.snapshot()
        apply_events(after, ANSIParser().parse(b"\x1b[200;1HZ"))
        profiler = cProfile.Profile()
        profiler.enable()
        for _ in range(200):
            diff_screens(before, after)
        profiler.disable()
        pstats.Stats(profiler).sort_stats("cumulative").print_stats(12)
        return 0

    print("=" * 60)
    print("ttydiff benchmarks (stdlib only)")
    print("=" * 60)
    bench_diff()
    bench_parser()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
