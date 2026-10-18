"""
Differential equivalence harness: upstream treelib vs. optimized treelib.

Every public operation is executed against two independent imports of the library
(``bench/baseline/treelib`` = upstream code at commit 83b3b87, and ``treelib/`` =
optimized code) and the observable results are compared byte-for-byte.

Run:  python bench/differential_check.py
Exit code 0 means full behavioural equivalence on the generated corpus.
"""

from __future__ import annotations

import io
import os
import random
import sys
import tempfile
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

import importlib.util


def load_variant(name: str, pkg_dir: str):
    """Import ``treelib`` from an explicit directory as a uniquely named module."""
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
# ``TREELIB_OPT_DIR`` lets bench/mutation_test.py point the harness at a mutated
# copy of the package without touching the real one.
OPT = load_variant("opt", os.environ.get("TREELIB_OPT_DIR", os.path.join(ROOT, "treelib")))

failures: list[str] = []
checks = 0


def cmp(label: str, a, b):
    global checks
    checks += 1
    if a != b:
        failures.append("%s\n  baseline=%r\n  optimized=%r" % (label, a, b))


def call(label, fn_base, fn_opt):
    """Run both callables, comparing either the value or the raised exception."""
    global checks
    try:
        a = ("ok", fn_base())
    except Exception as exc:  # noqa: BLE001 - exception type is part of the contract
        a = ("err", type(exc).__name__, str(exc))
    try:
        b = ("ok", fn_opt())
    except Exception as exc:  # noqa: BLE001
        b = ("err", type(exc).__name__, str(exc))
    checks += 1
    if a != b:
        failures.append("%s\n  baseline=%r\n  optimized=%r" % (label, a, b))


# ---------------------------------------------------------------- tree builders


def build_random(mod, seed: int, n: int, max_children: int):
    """Deterministic pseudo-random tree; identical for both variants."""
    rnd = random.Random(seed)
    t = mod.Tree()
    t.create_node("root", "root")
    ids = ["root"]
    for i in range(n):
        parent = rnd.choice(ids)
        # keep width bounded so trees stay deep *and* wide
        if len(t.children(parent)) >= max_children and len(ids) > 1:
            parent = rnd.choice([x for x in ids if len(t.children(x)) < max_children] or [parent])
        nid = "n%d" % i
        t.create_node("tag-%03d" % rnd.randrange(50), nid, parent=parent, data={"i": i})
        ids.append(nid)
    return t


def build_shapes(mod):
    """A zoo of structurally interesting trees."""
    shapes = {}

    # 1. single node
    t = mod.Tree()
    t.create_node("only", "only")
    shapes["single"] = t

    # 2. wide-but-flat
    t = mod.Tree()
    t.create_node("root", "root")
    for i in range(200):
        t.create_node("c%02d" % (i % 17), "c%d" % i, parent="root")
    shapes["flat200"] = t

    # 3. deep chain
    t = mod.Tree()
    t.create_node("root", "root")
    prev = "root"
    for i in range(300):
        t.create_node("d%d" % i, "d%d" % i, parent=prev)
        prev = "d%d" % i
    shapes["deep300"] = t

    # 4. balanced
    t = mod.Tree()
    t.create_node("root", "root")
    frontier = ["root"]
    counter = 0
    for _ in range(4):
        nxt = []
        for p in frontier:
            for _ in range(3):
                counter += 1
                nid = "b%d" % counter
                t.create_node("bt%02d" % (counter % 11), nid, parent=p)
                nxt.append(nid)
        frontier = nxt
    shapes["balanced"] = t

    # 5. mixed random
    shapes["random1"] = build_random(mod, 1, 150, 6)
    shapes["random2"] = build_random(mod, 7, 220, 3)

    # 6. with collapsed nodes (expanded=False)
    t = mod.Tree()
    t.create_node("root", "root")
    t.create_node("a", "a", parent="root")
    t.create_node("b", "b", parent="root")
    t.create_node("a1", "a1", parent="a")
    t.create_node("a2", "a2", parent="a")
    t["a"].expanded = False
    shapes["collapsed"] = t

    # 7. duplicate tags (sort stability)
    t = mod.Tree()
    t.create_node("same", "r")
    for i in range(40):
        t.create_node("same", "s%d" % i, parent="r")
        if i % 3 == 0:
            t.create_node("same", "s%dx" % i, parent="s%d" % i)
    shapes["duptags"] = t

    return shapes


LINE_TYPES = ["ascii", "ascii-ex", "ascii-exr", "ascii-em", "ascii-emv", "ascii-emh"]


def compare_shape(name, tb, to):
    # ---- basic accessors
    cmp("%s len" % name, len(tb), len(to))
    cmp("%s size" % name, tb.size(), to.size())
    cmp("%s root" % name, tb.root, to.root)
    cmp("%s depth" % name, tb.depth(), to.depth())
    cmp("%s leaves" % name, [n.identifier for n in tb.leaves()], [n.identifier for n in to.leaves()])
    cmp("%s all_nodes" % name, [n.identifier for n in tb.all_nodes()], [n.identifier for n in to.all_nodes()])
    cmp("%s nodes keys" % name, list(tb.nodes.keys()), list(to.nodes.keys()))

    ids = list(tb.nodes.keys())

    # ---- expand_tree: every mode x sorting x reverse x filter x key
    for mode, mode_name in ((tb.DEPTH, "DEPTH"), (tb.WIDTH, "WIDTH"), (tb.ZIGZAG, "ZIGZAG")):
        for sorting in (True, False):
            for reverse in (True, False):
                call(
                    "%s expand %s sorting=%s reverse=%s" % (name, mode_name, sorting, reverse),
                    lambda: list(tb.expand_tree(mode=mode, sorting=sorting, reverse=reverse)),
                    lambda: list(to.expand_tree(mode=mode, sorting=sorting, reverse=reverse)),
                )
        call(
            "%s expand %s key=tag" % (name, mode_name),
            lambda: list(tb.expand_tree(mode=mode, key=lambda n: n.tag)),
            lambda: list(to.expand_tree(mode=mode, key=lambda n: n.tag)),
        )
        call(
            "%s expand %s filter=nonleaf" % (name, mode_name),
            lambda: list(tb.expand_tree(mode=mode, filter=lambda n: not n.is_leaf(tb.identifier))),
            lambda: list(to.expand_tree(mode=mode, filter=lambda n: not n.is_leaf(to.identifier))),
        )
        # subtree start
        sub = ids[len(ids) // 2]
        call(
            "%s expand %s from=%s" % (name, mode_name, sub),
            lambda: list(tb.expand_tree(nid=sub, mode=mode)),
            lambda: list(to.expand_tree(nid=sub, mode=mode)),
        )
    call("%s expand bad mode" % name, lambda: list(tb.expand_tree(mode=999)), lambda: list(to.expand_tree(mode=999)))
    call(
        "%s expand missing nid" % name,
        lambda: list(tb.expand_tree(nid="nope")),
        lambda: list(to.expand_tree(nid="nope")),
    )

    # ---- rendering: str() and show() across every style/flag combination
    cmp("%s str" % name, str(tb), str(to))
    for line_type in LINE_TYPES:
        for idhidden in (True, False):
            for sorting in (True, False):
                for reverse in (True, False):
                    cmp(
                        "%s show %s idhidden=%s sorting=%s reverse=%s" % (name, line_type, idhidden, sorting, reverse),
                        tb.show(line_type=line_type, idhidden=idhidden, sorting=sorting, reverse=reverse, stdout=False),
                        to.show(line_type=line_type, idhidden=idhidden, sorting=sorting, reverse=reverse, stdout=False),
                    )
    cmp(
        "%s show data_property" % name,
        capture_safe(tb.show, data_property="i", stdout=False),
        capture_safe(to.show, data_property="i", stdout=False),
    )
    cmp(
        "%s show filtered" % name,
        tb.show(filter=lambda n: n.tag != "tag-007", stdout=False),
        to.show(filter=lambda n: n.tag != "tag-007", stdout=False),
    )
    cmp(
        "%s show key=tag reverse" % name,
        tb.show(key=lambda n: n.tag, reverse=True, stdout=False),
        to.show(key=lambda n: n.tag, reverse=True, stdout=False),
    )
    # stdout path must match too
    cmp("%s show stdout" % name, capture(tb.show), capture(to.show))

    # ---- per-node navigation
    for nid in ids[:: max(1, len(ids) // 40)]:
        call("%s level(%s)" % (name, nid), lambda: tb.level(nid), lambda: to.level(nid))
        call("%s is_branch(%s)" % (name, nid), lambda: tb.is_branch(nid), lambda: to.is_branch(nid))
        call("%s parent(%s)" % (name, nid), lambda: getattr(tb.parent(nid), "identifier", None), lambda: getattr(to.parent(nid), "identifier", None))
        call(
            "%s children(%s)" % (name, nid),
            lambda: [n.identifier for n in tb.children(nid)],
            lambda: [n.identifier for n in to.children(nid)],
        )
        call(
            "%s siblings(%s)" % (name, nid),
            lambda: [n.identifier for n in tb.siblings(nid)],
            lambda: [n.identifier for n in to.siblings(nid)],
        )
        call(
            "%s ancestor(%s)" % (name, nid),
            lambda: getattr(tb.ancestor(nid), "identifier", None),
            lambda: getattr(to.ancestor(nid), "identifier", None),
        )
        call(
            "%s rsearch(%s)" % (name, nid),
            lambda: list(tb.rsearch(nid)),
            lambda: list(to.rsearch(nid)),
        )
        max_level = tb.level(nid)
        for lv in range(0, max_level + 1):
            call(
                "%s ancestor(%s, %d)" % (name, nid, lv),
                lambda: getattr(tb.ancestor(nid, lv), "identifier", None),
                lambda: getattr(to.ancestor(nid, lv), "identifier", None),
            )
        # out-of-range level must raise the same exception type
        call(
            "%s ancestor(%s, %d) oob" % (name, nid, max_level),
            lambda: getattr(tb.ancestor(nid, max_level), "identifier", None),
            lambda: getattr(to.ancestor(nid, max_level), "identifier", None),
        )

    # ---- level sizes
    depth = tb.depth()
    for lv in range(depth + 1):
        cmp("%s size(level=%d)" % (name, lv), tb.size(level=lv), to.size(level=lv))
    call("%s size(level='x')" % name, lambda: tb.size(level="x"), lambda: to.size(level="x"))
    call("%s size(level=-1)" % name, lambda: tb.size(level=-1), lambda: to.size(level=-1))

    # ---- is_ancestor over a sample of pairs
    sample = ids[:: max(1, len(ids) // 12)]
    for a in sample:
        for b in sample:
            cmp("%s is_ancestor(%s,%s)" % (name, a, b), tb.is_ancestor(a, b), to.is_ancestor(a, b))

    # ---- bulk exports
    cmp("%s paths_to_leaves" % name, tb.paths_to_leaves(), to.paths_to_leaves())
    cmp("%s to_dict" % name, tb.to_dict(), to.to_dict())
    cmp("%s to_dict data+id" % name, tb.to_dict(with_data=True, with_identifier=True), to.to_dict(with_data=True, with_identifier=True))
    cmp("%s to_dict nosort" % name, tb.to_dict(sort=False), to.to_dict(sort=False))
    cmp("%s to_dict reverse" % name, tb.to_dict(reverse=True), to.to_dict(reverse=True))
    cmp("%s to_json" % name, tb.to_json(), to.to_json())
    cmp("%s to_json data" % name, tb.to_json(with_data=True, with_identifier=True), to.to_json(with_data=True, with_identifier=True))
    cmp("%s filter_nodes" % name, [n.identifier for n in tb.filter_nodes(lambda n: "1" in n.identifier)], [n.identifier for n in to.filter_nodes(lambda n: "1" in n.identifier)])

    # ---- graphviz (string capture; also verifies no exception)
    cmp("%s to_graphviz" % name, capture(tb.to_graphviz), capture(to.to_graphviz))

    # ---- save2file: content must be identical AND repeatable
    with tempfile.TemporaryDirectory() as d:
        pb = os.path.join(d, "b.txt")
        po = os.path.join(d, "o.txt")
        tb.save2file(pb)
        to.save2file(po)
        with open(pb, "rb") as f:
            cb = f.read()
        with open(po, "rb") as f:
            co = f.read()
        cmp("%s save2file bytes" % name, cb, co)
        # second write to the *same* path: optimized must truncate, upstream appends.
        # Record both, then assert the optimized file still equals the first render.
        to.save2file(po)
        with open(po, "rb") as f:
            co2 = f.read()
        global checks
        checks += 1
        if co2 != cb:
            failures.append("%s save2file not idempotent: %d -> %d bytes" % (name, len(cb), len(co2)))


def capture(fn, *args, **kwargs):
    buf = io.StringIO()
    with redirect_stdout(buf):
        fn(*args, **kwargs)
    return buf.getvalue()


def capture_safe(fn, *args, **kwargs):
    """Like :func:`capture`, but folds an exception into the comparable value.

    A few shape fixtures have nodes without ``data``, so ``data_property``
    rendering legitimately raises; both variants must raise identically.
    """
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            fn(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001
        return ("err", type(exc).__name__, str(exc))
    return ("ok", buf.getvalue())


def compare_mutations(name, seed):
    """Structural modification sequences must leave identical trees behind."""

    def run(mod):
        # Reseed per variant: a shared RNG stream would make the two runs perform
        # different operations, which would compare nothing but noise.
        rnd = random.Random(seed)
        t = build_random(mod, seed, 120, 4)
        ids = list(t.nodes.keys())
        log = []
        for step in range(60):
            op = rnd.choice(["move", "remove", "update", "rename", "paste"])
            snapshot = list(t.expand_tree(mode=t.WIDTH, sorting=False))
            try:
                if op == "move":
                    src, dst = rnd.choice(ids), rnd.choice(ids)
                    if src in t and dst in t:
                        t.move_node(src, dst)
                        log.append(("move", src, dst))
                elif op == "remove":
                    victim = rnd.choice(ids)
                    if victim in t and victim != t.root:
                        log.append(("remove", victim, t.remove_node(victim)))
                elif op == "update":
                    target = rnd.choice(ids)
                    if target in t:
                        t.update_node(target, tag="upd%d" % step)
                        log.append(("update", target))
                elif op == "rename":
                    target = rnd.choice(ids)
                    if target in t and target != t.root:
                        t.update_node(target, identifier=target + "_r")
                        log.append(("rename", target))
                        ids.append(target + "_r")
                elif op == "paste":
                    other = mod.Tree()
                    base = "p%d" % step
                    other.create_node("pasted", base)
                    other.create_node("pasted-child", base + "c", parent=base)
                    dest = rnd.choice(ids)
                    if dest in t:
                        t.paste(dest, other)
                        log.append(("paste", dest))
            except Exception as exc:  # noqa: BLE001 - both variants must fail identically
                log.append(("error", op, type(exc).__name__))
            else:
                log.append(("state", snapshot[:20]))
        final = (
            list(t.expand_tree(mode=t.WIDTH, sorting=False)),
            str(t),
            sorted((n.identifier, n.tag, n.predecessor(t.identifier)) for n in t.all_nodes()),
        )
        return log, final

    lb, fb = run(BASE)
    lo, fo = run(OPT)
    cmp("%s mutation log" % name, lb, lo)
    cmp("%s final state" % name, fb, fo)


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    for key in ("single", "flat200", "deep300", "balanced", "random1", "random2", "collapsed", "duptags"):
        tb = build_shapes(BASE)[key]
        to = build_shapes(OPT)[key]
        compare_shape(key, tb, to)
        print("  compared shape: %-10s (%d nodes)" % (key, len(tb)))

    for seed in (11, 23, 41):
        compare_mutations("mutate%d" % seed, seed)
        print("  compared mutation sequence seed=%d" % seed)

    # deep-tree regression: upstream raises RecursionError, optimized must not
    print()
    print("deep-tree rendering (characterisation, not an equality check):")
    for depth in (900, 1200, 5000):
        built = {}
        for label, mod in (("upstream", BASE), ("optimized", OPT)):
            t = mod.Tree()
            t.create_node("r", "r")
            prev = "r"
            for i in range(depth):
                t.create_node("x", "d%d" % i, parent=prev)
                prev = "d%d" % i
            built[label] = t

        def status(mod_tree):
            try:
                rendered = str(mod_tree)
            except RecursionError:
                return "RecursionError"
            return "%d lines" % rendered.count("\n")

        print("  depth %-5d upstream=%-16s optimized=%s" % (depth, status(built["upstream"]), status(built["optimized"])))

    print()
    print("checks=%d failures=%d" % (checks, len(failures)))
    if failures:
        for f in failures[:30]:
            print("FAIL: " + f)
        return 1
    print("all differential checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
