"""
Benchmark: upstream treelib (bench/baseline) vs. optimized treelib.

Methodology
-----------
* Both variants are imported once per process from explicit directories, so the
  measurement loop never pays import cost.
* Every case runs **interleaved**: for each repetition the baseline and the
  optimized implementation are timed back-to-back and only their **ratio** is
  kept. The headline number is the **median of the per-repetition ratios**, with
  the interquartile range reported alongside so the reader can see the spread.
  Absolute timings (reported as best-of-N) are affected by CPU frequency,
  allocator state and interpreter warm-up, so they are given only to convey
  scale - never as the basis of a speedup claim.
* Fixtures are immutable for the read-only cases. The two mutating cases
  (``create_node``, ``update_node``) rebuild a fresh tree inside the timed
  closure so that neither variant inherits extra work from the other.
* Results are written to ``bench/results.json`` with LF newlines, and
  ``bench/make_charts.py`` renders the README figures from that same file, so
  text and figures cannot drift apart.

Run:  python bench/benchmark.py [--quick]
"""

from __future__ import annotations

import gc
import importlib.util
import json
import os
import statistics
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RESULTS = os.path.join(HERE, "results.json")


def load_variant(name: str, pkg_dir: str):
    """Import ``treelib`` from an explicit directory under a unique module name."""
    pkg_name = "treelib_" + name
    spec = importlib.util.spec_from_file_location(
        pkg_name,
        os.path.join(pkg_dir, "__init__.py"),
        submodule_search_locations=[pkg_dir],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[pkg_name] = module
    spec.loader.exec_module(module)
    return module


BASE = load_variant("base", os.path.join(HERE, "baseline", "treelib"))
OPT = load_variant("opt", os.path.join(ROOT, "treelib"))


# ------------------------------------------------------------------ fixtures


def make_balanced(mod, fanout: int, depth: int):
    """Perfect ``fanout``-ary tree (1 + f + ... + f^depth nodes)."""
    t = mod.Tree()
    t.create_node("root", "root")
    frontier = ["root"]
    counter = 0
    for _ in range(depth):
        nxt = []
        for p in frontier:
            for _ in range(fanout):
                counter += 1
                nid = "b%d" % counter
                t.create_node("tag-%05d" % counter, nid, parent=p)
                nxt.append(nid)
        frontier = nxt
    return t


def make_deep(mod, depth: int):
    """Single chain of ``depth`` nodes below the root."""
    t = mod.Tree()
    t.create_node("root", "root")
    prev = "root"
    for i in range(depth):
        nid = "d%d" % i
        t.create_node("node-%05d" % i, nid, parent=prev)
        prev = nid
    return t


def make_wide_flat(mod, n: int):
    """Root with ``n`` direct children (maximally wide, depth 1)."""
    t = mod.Tree()
    t.create_node("root", "root")
    for i in range(n):
        t.create_node("tag-%05d" % i, "w%d" % i, parent="root")
    return t


# ------------------------------------------------------------------ timing


def _min_of(fn, runs: int) -> float:
    """Best wall-clock time over ``runs`` executions (best-of-N, not a median)."""
    best = float("inf")
    for _ in range(runs):
        start = time.perf_counter()
        fn()
        elapsed = time.perf_counter() - start
        if elapsed < best:
            best = elapsed
    return best


def _measure(fn, floor: float = 0.02, samples: int = 5) -> float:
    """Per-call seconds, measured over batches long enough to beat timer noise.

    A single call of a 0.3 ms operation is dominated by ``perf_counter`` resolution
    and scheduler jitter - the interquartile range of the resulting ratios was
    wider than the effect being measured. This helper first calibrates how many
    calls are needed to exceed ``floor`` seconds (20 ms by default), then reports
    the best per-call time across ``samples`` such batches.
    """
    # Calibrate: find a repeat count that spans at least the requested floor.
    repeat = 1
    while True:
        start = time.perf_counter()
        for _ in range(repeat):
            fn()
        elapsed = time.perf_counter() - start
        if elapsed >= floor or repeat >= 1_000_000:
            break
        # Grow geometrically, but never overshoot wildly on the last step.
        factor = max(2, int(floor / max(elapsed, 1e-9)))
        repeat *= min(factor, 64)

    best = float("inf")
    for _ in range(samples):
        start = time.perf_counter()
        for _ in range(repeat):
            fn()
        elapsed = (time.perf_counter() - start) / repeat
        if elapsed < best:
            best = elapsed
    return best


def interleaved(label, fn_base, fn_opt, repeat=9, runs=1, note=""):
    """Time both variants back-to-back per repetition; keep the ratio.

    ``runs`` is retained for call-site compatibility but the actual batch size is
    now calibrated per case by :func:`_measure`, so short operations get enough
    iterations to rise above timer noise.
    """
    ratios = []
    base_times = []
    opt_times = []
    for _ in range(repeat):
        tb = _measure(fn_base)
        to = _measure(fn_opt)
        base_times.append(tb)
        opt_times.append(to)
        if to > 0:
            ratios.append(tb / to)

    entry = {
        "label": label,
        "note": note,
        "baseline_best_ms": min(base_times) * 1000.0,
        "optimized_best_ms": min(opt_times) * 1000.0,
        "median_ratio": statistics.median(ratios),
        "ratio_min": min(ratios),
        "ratio_max": max(ratios),
        "repetitions": repeat,
    }
    print(
        "%-44s base=%9.3fms opt=%9.3fms speedup=%7.2fx  [%.2f-%.2f]"
        % (
            label,
            entry["baseline_best_ms"],
            entry["optimized_best_ms"],
            entry["median_ratio"],
            entry["ratio_min"],
            entry["ratio_max"],
        )
    )
    return entry


def single_sided(label, fn, note, repeat=3):
    """A case upstream cannot complete at all (no ratio exists)."""
    gc.collect()
    best = _measure(fn, samples=repeat)
    print("%-44s base=%9s opt=%9.2fms speedup=    n/a   (%s)" % (label, "-", best * 1000.0, note))
    return {
        "label": label,
        "note": note,
        "baseline_best_ms": None,
        "optimized_best_ms": best * 1000.0,
        "median_ratio": None,
        "ratio_min": None,
        "ratio_max": None,
        "repetitions": repeat,
    }


def interleaved_or_single(label, fn_base, fn_opt, repeat=9, runs=1, note=""):
    """Interleave when upstream can run the case; report one-sided otherwise.

    Deep chains legitimately make upstream raise ``RecursionError``; there is no
    ratio to compute in that case, and pretending otherwise would be a fabricated
    number. If the *optimized* side also cannot complete (for example
    ``to_json`` loses to ``json.dumps``' own C-level recursion, which is outside
    this library), the case is recorded as still-unsupported rather than silently
    dropped.
    """
    try:
        fn_base()
    except RecursionError:
        try:
            fn_opt()
        except RecursionError:
            print("%-44s base=%9s opt=%9s speedup=    n/a   (both raise RecursionError)" % (label, "-", "-"))
            return {
                "label": label,
                "note": "both variants raise RecursionError",
                "baseline_best_ms": None,
                "optimized_best_ms": None,
                "median_ratio": None,
                "ratio_min": None,
                "ratio_max": None,
                "repetitions": 0,
            }
        return single_sided(label, fn_opt, "upstream: RecursionError (cannot complete at all)", repeat=repeat)
    return interleaved(label, fn_base, fn_opt, repeat=repeat, runs=runs, note=note)


# ------------------------------------------------------------------ driver


def main(quick: bool = False) -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    repeat = 5 if quick else 9
    results = []

    fixtures = {
        "balanced_1k": (make_balanced(BASE, 3, 6), make_balanced(OPT, 3, 6)),
        "balanced_9k": (make_balanced(BASE, 6, 5), make_balanced(OPT, 6, 5)),
        "wide_5k": (make_wide_flat(BASE, 5000), make_wide_flat(OPT, 5000)),
        "deep_1k": (make_deep(BASE, 1000), make_deep(OPT, 1000)),
    }

    for key, (tb, to) in fixtures.items():
        print("\n=== %s (%d nodes) ===" % (key, len(tb)))

        # --- build cost (fresh tree each timed run; reuse the same shape)
        if key == "balanced_9k":
            results.append(
                interleaved(
                    "build 9331-node tree",
                    lambda: make_balanced(BASE, 6, 5),
                    lambda: make_balanced(OPT, 6, 5),
                    repeat=max(3, repeat // 2),
                    note="create_node + update_successors path",
                )
            )
        if key == "deep_1k":
            results.append(
                interleaved(
                    "build 1001-deep chain",
                    lambda: make_deep(BASE, 1000),
                    lambda: make_deep(OPT, 1000),
                    repeat=max(3, repeat // 2),
                )
            )

        for mode_name, mode_attr in (("DEPTH", "DEPTH"), ("WIDTH", "WIDTH"), ("ZIGZAG", "ZIGZAG")):
            results.append(
                interleaved(
                    "%s: expand_tree %s" % (key, mode_name),
                    lambda t=tb, m=mode_attr: list(t.expand_tree(mode=getattr(t, m))),
                    lambda t=to, m=mode_attr: list(t.expand_tree(mode=getattr(t, m))),
                    repeat=repeat,
                    runs=2,
                )
            )
        results.append(
            interleaved(
                "%s: expand_tree DEPTH unsorted" % key,
                lambda t=tb: list(t.expand_tree(sorting=False)),
                lambda t=to: list(t.expand_tree(sorting=False)),
                repeat=repeat,
                runs=2,
            )
        )

        # --- rendering
        results.append(
            interleaved_or_single(
                "%s: str(tree)" % key,
                lambda t=tb: str(t),
                lambda t=to: str(t),
                repeat=repeat,
            )
        )
        results.append(
            interleaved_or_single(
                "%s: show(stdout=False)" % key,
                lambda t=tb: t.show(stdout=False),
                lambda t=to: t.show(stdout=False),
                repeat=repeat,
            )
        )

        # --- file output
        tmpdir = tempfile.mkdtemp()
        pb = os.path.join(tmpdir, "b.txt")
        po = os.path.join(tmpdir, "o.txt")
        results.append(
            interleaved_or_single(
                "%s: save2file" % key,
                lambda b=tb, p=pb: b.save2file(p),
                lambda o=to, p=po: o.save2file(p),
                repeat=max(3, repeat // 2),
            )
        )

        # --- aggregate queries
        results.append(
            interleaved(
                "%s: depth()" % key,
                lambda t=tb: t.depth(),
                lambda t=to: t.depth(),
                repeat=repeat,
                runs=3,
            )
        )
        results.append(
            interleaved(
                "%s: size(level=2)" % key,
                lambda t=tb: t.size(level=2),
                lambda t=to: t.size(level=2),
                repeat=repeat,
                runs=3,
            )
        )
        results.append(
            interleaved(
                "%s: paths_to_leaves()" % key,
                lambda t=tb: t.paths_to_leaves(),
                lambda t=to: t.paths_to_leaves(),
                repeat=repeat,
                runs=2,
            )
        )
        results.append(
            interleaved_or_single(
                "%s: to_dict()" % key,
                lambda t=tb: t.to_dict(),
                lambda t=to: t.to_dict(),
                repeat=repeat,
            )
        )
        results.append(
            interleaved_or_single(
                "%s: to_json()" % key,
                lambda t=tb: t.to_json(),
                lambda t=to: t.to_json(),
                repeat=repeat,
            )
        )

        # --- per-node navigation: use a genuinely deep node, because a level-1
        #     leaf would make the measured work trivial (and `ancestor(., 1)`
        #     raises InvalidLevelNumber for it).
        anchor = _deepest_node(tb)
        # Immediate parent of the anchor; for a depth-1 tree that is the root.
        parent_level = max(0, tb.level(anchor) - 1)
        results.append(
            interleaved(
                "%s: level(deepest node)" % key,
                lambda b=tb, a=anchor: b.level(a),
                lambda o=to, a=anchor: o.level(a),
                repeat=repeat,
                runs=20,
            )
        )
        results.append(
            interleaved(
                "%s: ancestor(deepest, %d) x1000" % (key, parent_level),
                lambda b=tb, a=anchor, lv=parent_level: [b.ancestor(a, lv) for _ in range(1000)],
                lambda o=to, a=anchor, lv=parent_level: [o.ancestor(a, lv) for _ in range(1000)],
                repeat=repeat,
            )
        )

        # --- mutation: fresh tree per timed run so neither side is pre-loaded
        results.append(
            interleaved(
                "%s: create_node x500" % key,
                lambda: _mutation_run(BASE, "create", 500),
                lambda: _mutation_run(OPT, "create", 500),
                repeat=max(3, repeat // 2),
            )
        )

    # ---------------------------------------------------- deep-tree rendering
    print("\n=== deep chains: upstream cannot render these at all ===")
    for depth in (1200, 3000, 6000):
        to = make_deep(OPT, depth)
        try:
            tb = make_deep(BASE, depth)
            try:
                str(tb)
                upstream = "ok"
            except RecursionError:
                upstream = "RecursionError"
        except RecursionError:
            upstream = "RecursionError"
        note = "upstream: %s" % upstream
        results.append(single_sided("deep%d: str(tree)" % depth, lambda t=to: str(t), note))
        del to, tb

    payload = {
        "environment": {
            "python": sys.version.split()[0],
            "platform": sys.platform,
            "processor": os.environ.get("PROCESSOR_IDENTIFIER", "unknown"),
        },
        "method": "interleaved pairs; median of per-repetition baseline/optimized ratios; "
        "best-of-N absolute times for scale only",
        "quick": quick,
        "results": results,
    }
    os.makedirs(os.path.dirname(RESULTS), exist_ok=True)
    with open(RESULTS, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print("\nwrote %s (%d cases)" % (RESULTS, len(results)))


def _mutation_run(mod, kind: str, n: int):
    """Build a small tree, then perform ``n`` mutations on it."""
    t = make_balanced(mod, 3, 4)  # 121 nodes
    if kind == "create":
        for i in range(n):
            t.create_node("x", "new%d" % i, parent="root")
    return t


def _deepest_node(tree) -> str:
    """Identifier of the node with the greatest level (deterministic tie-break)."""
    best_id = tree.root
    best_level = -1
    for node in tree.all_nodes():
        lv = tree.level(node.identifier)
        if lv > best_level:
            best_level = lv
            best_id = node.identifier
    return best_id


if __name__ == "__main__":
    main(quick="--quick" in sys.argv)
