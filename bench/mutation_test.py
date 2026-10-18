"""
Mutation test: does the differential harness actually catch broken optimizations?

A green test suite proves nothing on its own. This script copies the optimized
package into a temporary directory, injects one deliberate bug at a time, and
checks that ``bench/differential_check.py`` *fails* against that copy. Any
surviving mutant is a blind spot in the harness and is reported as such.

Run:  python bench/mutation_test.py
Exit code 0 means every mutant was caught.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "treelib")

# (name, file, old_snippet, new_snippet) - each one is a bug a careless rewrite
# could plausibly introduce.
MUTANTS = [
    (
        "expand_tree: DEPTH pushes children in wrong order",
        "tree.py",
        """                stack: List[Node] = root_children[::-1]""",
        """                stack: List[Node] = list(root_children)""",
    ),
    (
        "expand_tree: WIDTH behaves like DEPTH",
        "tree.py",
        """                queue.extend(expand(head))""",
        """                queue.extendleft(reversed(expand(head)))""",
    ),
    (
        "expand_tree: DEPTH ignores reverse=True",
        "tree.py",
        """                if sorting:
                    kids.sort(key=key, reverse=reverse)
                return kids""",
        """                if sorting:
                    kids.sort(key=key)
                return kids""",
    ),
    (
        "renderer: corner glyph for last child replaced by box glyph",
        "tree.py",
        """            prefix += dt_line_corner if flags[-1] else dt_line_box""",
        """            prefix += dt_line_box""",
    ),
    (
        "renderer: vertical guide dropped from the prefix",
        "tree.py",
        """            prefix = "".join(dt_vertical_line + "   " if not flag else "    " for flag in flags[0:-1])""",
        """            prefix = "".join("    " for flag in flags[0:-1])""",
    ),
    (
        "level(): off-by-one on the returned level",
        "tree.py",
        """            return count - 1""",
        """            return count""",
    ),
    (
        "size(level): uses '<' instead of '<=' for the descent bound",
        "tree.py",
        """            if lv < target:
                for child in nodes[nid].successors(tree_id):
                    stack.append((child, lv + 1))""",
        """            if lv < target - 1:
                for child in nodes[nid].successors(tree_id):
                    stack.append((child, lv + 1))""",
    ),
    (
        "depth(): forgets the +1 when descending",
        "tree.py",
        """                stack.append((child, lv + 1))""",
        """                stack.append((child, lv))""",
    ),
    (
        "ancestor(): returns the wrong end of the chain",
        "tree.py",
        """        return nodes[chain[target_index]]""",
        """        return nodes[chain[len(chain) - 1 - target_index]]""",
    ),
    (
        "paths_to_leaves(): drops the root from every path",
        "tree.py",
        """            res.append(path_of(nid))""",
        """            res.append(path_of(nid)[1:])""",
    ),
    (
        "save2file: reopens in append mode (reintroduces duplication)",
        "tree.py",
        """        with open(filename, "wb") as stream:

            def handler(x):
                stream.write(x + b"\\n")""",
        """        if True:

            def handler(x):
                open(filename, "ab").write(x + b"\\n")
            stream = None""",
    ),
    (
        "update_successors: DELETE no longer removes anything",
        "node.py",
        """            try:
                successors.remove(nid)
            except ValueError:
                warn("Nid %s wasn't present in fpointer" % nid)""",
        """            if nid not in successors:
                warn("Nid %s wasn't present in fpointer" % nid)""",
    ),
    (
        "to_dict: drops the data/identifier payload",
        "tree.py",
        """        if with_data:
            node_dict["data"] = node.data
        if children:""",
        """        if children:""",
    ),
]


def run_harness(pkg_parent: str) -> int:
    """Run the differential harness against ``pkg_parent/treelib``."""
    env = dict(os.environ)
    env["TREELIB_OPT_DIR"] = os.path.join(pkg_parent, "treelib")
    proc = subprocess.run(
        [sys.executable, os.path.join(HERE, "differential_check.py")],
        capture_output=True,
        text=True,
        env=env,
        cwd=ROOT,
    )
    return proc.returncode, proc.stdout + proc.stderr


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    # Sanity: the unmutated copy must pass, otherwise a "caught" verdict is meaningless.
    code, out = run_harness(ROOT)
    if code != 0:
        print("BASELINE BROKEN: the unmutated package already fails the harness")
        print(out[-2000:])
        return 2
    print("baseline: harness passes on the unmutated package\n")

    survivors = []
    for name, filename, old, new in MUTANTS:
        with tempfile.TemporaryDirectory() as tmp:
            pkg = os.path.join(tmp, "treelib")
            shutil.copytree(SRC, pkg)
            target = os.path.join(pkg, filename)
            with open(target, encoding="utf-8") as f:
                source = f.read()
            if old not in source:
                print("SKIP (snippet not found): %s" % name)
                survivors.append(name + " [snippet not found]")
                continue
            with open(target, "w", encoding="utf-8", newline="\n") as f:
                f.write(source.replace(old, new, 1))

            code, out = run_harness(tmp)
            if code == 0:
                print("SURVIVED: %s" % name)
                survivors.append(name)
            else:
                first = next((ln for ln in out.splitlines() if ln.startswith("FAIL")), "non-zero exit")
                print("caught:   %s  -> %s" % (name, first[:110]))

    print("\n%d/%d mutants caught" % (len(MUTANTS) - len(survivors), len(MUTANTS)))
    if survivors:
        print("blind spots:")
        for item in survivors:
            print("  - " + item)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
