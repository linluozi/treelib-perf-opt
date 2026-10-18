"""
Regression tests for the performance-oriented rewrite.

These tests pin the *behavioural guarantees* that the optimizations rely on, so a
future refactor cannot silently reintroduce the defects that were fixed:

* deep trees must render / export without ``RecursionError``;
* ``save2file`` must overwrite, not append, when called twice;
* traversal order and rendering output must stay stable;
* the traversal frontier must not be quadratic in width.
"""

from __future__ import annotations

import os
import tempfile
import time

import pytest

from treelib import Tree
from treelib.exceptions import InvalidLevelNumber, NodeIDAbsentError


# --------------------------------------------------------------------- helpers


def chain(depth: int) -> Tree:
    """A single root-to-leaf chain of ``depth + 1`` nodes."""
    tree = Tree()
    tree.create_node("root", "root")
    parent = "root"
    for index in range(depth):
        node_id = "d%d" % index
        tree.create_node("n%d" % index, node_id, parent=parent)
        parent = node_id
    return tree


def balanced(fanout: int, depth: int) -> Tree:
    """A perfect ``fanout``-ary tree of the given depth."""
    tree = Tree()
    tree.create_node("root", "root")
    frontier = ["root"]
    counter = 0
    for _ in range(depth):
        nxt = []
        for parent in frontier:
            for _ in range(fanout):
                counter += 1
                node_id = "b%d" % counter
                tree.create_node("t%03d" % counter, node_id, parent=parent)
                nxt.append(node_id)
        frontier = nxt
    return tree


# ------------------------------------------------------------- deep-tree support


@pytest.mark.parametrize("depth", [1200, 3000])
def test_deep_tree_renders_without_recursion_error(depth):
    """Upstream raised RecursionError above ~1000 frames; rendering must work."""
    tree = chain(depth)
    rendered = str(tree)
    assert rendered.count("\n") == depth + 1
    assert rendered.startswith("root\n")


@pytest.mark.parametrize("depth", [1200, 3000])
def test_deep_tree_show_matches_str(depth):
    tree = chain(depth)
    assert tree.show(stdout=False) == str(tree)


@pytest.mark.parametrize("depth", [1200, 3000])
def test_deep_tree_to_dict_is_iterative(depth):
    tree = chain(depth)
    exported = tree.to_dict()
    # Walk down the nested dict to confirm every level is present.
    level = 0
    current = exported
    while isinstance(current, dict):
        tag, payload = next(iter(current.items()))
        if not payload:
            break
        current = payload["children"][0]
        level += 1
    assert level == depth


def test_deep_tree_to_json_reports_documented_limitation():
    """``to_json`` still overflows: json.dumps itself is recursive.

    This is upstream's documented behaviour and explicitly *not* claimed as fixed.
    The test pins the current contract so a future change is a conscious decision.
    """
    tree = chain(2000)
    with pytest.raises(RecursionError):
        tree.to_json()


def test_deep_tree_operations_are_level_correct():
    tree = chain(1500)
    assert tree.depth() == 1500
    assert tree.level("d1499") == 1500
    assert tree.size(level=1500) == 1
    assert tree.ancestor("d1499", 0).identifier == "root"
    assert tree.paths_to_leaves() == [["root"] + ["d%d" % i for i in range(1500)]]


# ----------------------------------------------------------------- save2file


def test_save2file_overwrites_on_second_call():
    """Writing twice to one path must not duplicate the tree (upstream appended)."""
    tree = balanced(2, 3)
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "tree.txt")
        tree.save2file(path)
        with open(path, "rb") as handle:
            first = handle.read()

        tree.save2file(path)
        with open(path, "rb") as handle:
            second = handle.read()

    assert first == second
    assert first.count(b"\n") == len(tree)


def test_save2file_matches_show_bytes():
    tree = balanced(3, 2)
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "tree.txt")
        tree.save2file(path)
        with open(path, "rb") as handle:
            on_disk = handle.read()
    assert on_disk == tree.show(stdout=False).encode("utf-8")


def test_save2file_does_not_leak_file_handles():
    """The old implementation opened one descriptor per rendered line."""
    tree = balanced(4, 2)
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "tree.txt")
        before = _open_fd_count()
        for _ in range(5):
            tree.save2file(path)
        after = _open_fd_count()
    assert after <= before + 2, "file descriptors leaked: %d -> %d" % (before, after)


def _open_fd_count() -> int:
    """Best-effort count of open file descriptors for the current process."""
    try:
        import psutil  # optional dependency, not required for the library

        return psutil.Process().num_handles() if os.name == "nt" else psutil.Process().num_fds()
    except Exception:  # noqa: BLE001 - absence of psutil just skips the check
        try:
            proc_fd = "/proc/self/fd"
            return len(os.listdir(proc_fd))
        except OSError:
            pytest.skip("cannot count open file descriptors on this platform")


# ------------------------------------------------------------ traversal order


def test_expand_tree_orders_are_stable():
    tree = Tree()
    tree.create_node("root", "root")
    for tag, node_id, parent in (
        ("c", "c", "root"),
        ("a", "a", "root"),
        ("b", "b", "root"),
        ("a1", "a1", "a"),
        ("a2", "a2", "a"),
        ("c1", "c1", "c"),
    ):
        tree.create_node(tag, node_id, parent=parent)

    # Unsorted DEPTH is a true stack: "c" is pushed last, so its subtree comes out
    # first. This is upstream's documented "depth-first by insertion order".
    assert list(tree.expand_tree(sorting=False)) == ["root", "c", "c1", "a", "a1", "a2", "b"]
    assert list(tree.expand_tree()) == ["root", "a", "a1", "a2", "b", "c", "c1"]
    assert list(tree.expand_tree(mode=Tree.WIDTH)) == ["root", "a", "b", "c", "a1", "a2", "c1"]
    assert list(tree.expand_tree(mode=Tree.WIDTH, sorting=False)) == ["root", "c", "a", "b", "c1", "a1", "a2"]


def test_zigzag_ignores_sorting_like_upstream():
    """Documented quirk: ZIGZAG never applies ``sorting``/``key``/``reverse``."""
    tree = Tree()
    tree.create_node("root", "root")
    for tag, node_id in (("c", "c"), ("a", "a"), ("b", "b")):
        tree.create_node(tag, node_id, parent="root")

    unsorted = list(tree.expand_tree(mode=Tree.ZIGZAG, sorting=False))
    sorted_attempt = list(tree.expand_tree(mode=Tree.ZIGZAG, sorting=True, reverse=True))
    assert sorted_attempt == unsorted


@pytest.mark.parametrize("mode", [Tree.DEPTH, Tree.WIDTH, Tree.ZIGZAG])
def test_expand_tree_visits_every_node_once(mode):
    tree = balanced(4, 3)
    visited = list(tree.expand_tree(mode=mode))
    assert len(visited) == len(tree)
    assert len(set(visited)) == len(tree)


def test_expand_tree_width_is_not_quadratic():
    """A 4k-wide root used to cost O(w^2) because of ``queue[1:]`` copies.

    The assertion is deliberately loose (a hard ratio would be machine dependent);
    what matters is that the cost is linear, i.e. ten times more children does not
    cost a hundred times more time.
    """
    small = Tree()
    small.create_node("root", "root")
    for index in range(400):
        small.create_node("t%d" % index, "s%d" % index, parent="root")

    large = Tree()
    large.create_node("root", "root")
    for index in range(4000):
        large.create_node("t%d" % index, "l%d" % index, parent="root")

    def best(tree: Tree, runs: int = 5) -> float:
        timings = []
        for _ in range(runs):
            start = time.perf_counter()
            list(tree.expand_tree(mode=Tree.WIDTH))
            timings.append(time.perf_counter() - start)
        return min(timings)

    small_time = best(small)
    large_time = best(large)
    # Linear would be ~10x. Quadratic would be ~100x. Allow generous slack.
    assert large_time < small_time * 40, "WIDTH traversal looks super-linear: %.4f -> %.4f" % (
        small_time,
        large_time,
    )


# --------------------------------------------------------------- navigation


def test_ancestor_matches_level_walk():
    tree = balanced(3, 4)
    for node in tree.all_nodes():
        node_id = node.identifier
        level = tree.level(node_id)
        for target in range(0, level):
            found = tree.ancestor(node_id, target)
            assert found is not None
            assert tree.level(found.identifier) == target
        if level > 0:
            # Asking for the node's own level is out of range by contract.
            with pytest.raises(InvalidLevelNumber):
                tree.ancestor(node_id, level)


def test_ancestor_of_root():
    tree = balanced(2, 2)
    assert tree.ancestor("root") is None
    assert tree.ancestor("root", 0).identifier == "root"


def test_ancestor_unknown_node_raises():
    tree = balanced(2, 2)
    with pytest.raises(NodeIDAbsentError):
        tree.ancestor("nope")


def test_level_with_filter_skips_filtered_nodes():
    """``level(filter=...)`` counts only nodes the filter keeps (upstream contract)."""
    tree = balanced(2, 3)
    leaf = tree.leaves()[0].identifier
    unfiltered = tree.level(leaf)
    # Excluding the root removes one step from the counted chain.
    assert tree.level(leaf, filter=lambda node: node.tag != "root") == unfiltered - 1


def test_size_of_each_level_sums_to_node_count():
    tree = balanced(3, 4)
    total = sum(tree.size(level=lv) for lv in range(tree.depth() + 1))
    assert total == len(tree)


def test_size_rejects_non_integer_level():
    tree = balanced(2, 2)
    with pytest.raises(TypeError):
        tree.size(level="invalid")


def test_size_out_of_range_level_is_zero():
    tree = balanced(2, 2)
    assert tree.size(level=99) == 0
    assert tree.size(level=-1) == 0


# ------------------------------------------------------------------ exports


def test_paths_to_leaves_preserves_insertion_order():
    tree = Tree()
    tree.create_node("root", "root")
    tree.create_node("a", "a", parent="root")
    tree.create_node("b", "b", parent="root")
    tree.create_node("a1", "a1", parent="a")
    # Leaves follow self._nodes insertion order: "b" was registered before "a1".
    assert tree.paths_to_leaves() == [["root", "b"], ["root", "a", "a1"]]


def test_paths_to_leaves_single_leaf_chain():
    tree = chain(50)
    paths = tree.paths_to_leaves()
    assert len(paths) == 1
    assert paths[0][0] == "root"
    assert len(paths[0]) == 51


def test_paths_to_leaves_empty_tree():
    assert Tree().paths_to_leaves() == []


def test_to_dict_and_to_json_agree_with_structure():
    tree = balanced(2, 3)
    as_dict = tree.to_dict()
    assert list(as_dict.keys()) == ["root"]
    # Root has two children, so the payload must nest them.
    assert len(as_dict["root"]["children"]) == 2

    import json

    assert json.loads(tree.to_json()) == as_dict


def test_to_dict_carries_data_and_identifier():
    tree = Tree()
    tree.create_node("root", "root", data={"k": 1})
    tree.create_node("kid", "kid", parent="root", data={"k": 2})
    exported = tree.to_dict(with_data=True, with_identifier=True)
    assert exported["root"]["id"] == "root"
    assert exported["root"]["data"] == {"k": 1}
    assert exported["root"]["children"][0]["kid"]["data"] == {"k": 2}


def test_to_dict_respects_collapsed_nodes():
    tree = Tree()
    tree.create_node("root", "root")
    tree.create_node("kid", "kid", parent="root")
    tree["root"].expanded = False
    # A collapsed node is exported as a bare tag string, exactly like upstream.
    assert tree.to_dict() == "root"


# --------------------------------------------------------------- rendering


def test_render_prefixes_are_well_formed():
    tree = Tree()
    tree.create_node("root", "root")
    tree.create_node("a", "a", parent="root")
    tree.create_node("b", "b", parent="root")
    tree.create_node("a1", "a1", parent="a")
    assert tree.show(stdout=False) == "root\n├── a\n│   └── a1\n└── b\n"


def test_render_handles_all_line_types():
    tree = balanced(2, 2)
    for line_type in ("ascii", "ascii-ex", "ascii-exr", "ascii-em", "ascii-emv", "ascii-emh"):
        rendered = tree.show(line_type=line_type, stdout=False)
        assert rendered.count("\n") == len(tree)
