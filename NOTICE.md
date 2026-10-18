# NOTICE

This repository is a derivative work of **treelib** by Xiaming Chen and contributors.

- Upstream: https://github.com/caesar0301/treelib
- Upstream licence: Apache License 2.0 (see `LICENSE`, reproduced unmodified)
- Baseline commit used for all comparisons: `83b3b87eaa7c56c9c7b86d19b2eede5252a1b482`
  (2026-08-13)

## What was modified

Modifications were made to `treelib/tree.py` and `treelib/node.py`. The upstream test suite
under `tests/` is included unmodified. Files added by this repository:

- `treelib/tree.py` — rewritten `expand_tree`, `__get_iter`, `show`, `save2file`, `to_dict`,
  `size`, `depth`, `level`, `ancestor`, `paths_to_leaves`; added module-level helpers
  `_always_true` and `_child_ids`.
- `treelib/node.py` — rewritten `update_successors` (removed per-call closure construction
  and `locals()` dispatch).
- `tests/test_optimizations.py` — new regression tests.
- `bench/` — benchmark, differential-equivalence harness, mutation test, chart generator.
- `assets/` — figures referenced by the README.
- `README.md`, `NOTICE.md`, `pyproject.toml`, `requirements*.txt`, `.gitignore` — rewritten
  or added for this fork.

## What was not modified

- `treelib/__init__.py`, `treelib/exceptions.py`, `treelib/misc.py` are byte-identical to
  upstream.
- `bench/baseline/treelib/` is a verbatim copy of the upstream package at the commit above.
  It exists solely so the benchmark can time the original next to the rewrite, and is not
  part of the distributed package.
- The public API surface is unchanged; see the "Behaviour changes" section of the README for
  the two intentional fixes.

## Attribution

Original copyright notices are retained verbatim at the top of every source file.
