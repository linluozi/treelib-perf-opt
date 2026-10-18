"""
Render the README figures from ``bench/results.json``.

Keeping the charts generated from the same JSON that the benchmark writes means
the numbers quoted in prose and the numbers drawn in the figures cannot drift
apart. Warm editorial palette, English labels (CJK glyphs are not guaranteed in a
matplotlib default font stack and would render as boxes on many machines).

Run:  python bench/make_charts.py
"""

from __future__ import annotations

import json
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ASSETS = os.path.join(ROOT, "assets")

# Palette shared with the rest of the project's figures.
INK = "#2b2119"
PAPER = "#faf6f0"
AMBER = "#c8892b"
TERRACOTTA = "#b4552f"
OLIVE = "#6b6b3a"
MUTED = "#8a7a68"
GRID = "#ddd2c2"

plt.rcParams.update(
    {
        "figure.facecolor": PAPER,
        "axes.facecolor": PAPER,
        "savefig.facecolor": PAPER,
        "axes.edgecolor": MUTED,
        "axes.labelcolor": INK,
        "text.color": INK,
        "xtick.color": MUTED,
        "ytick.color": MUTED,
        "font.family": "DejaVu Sans",
        "font.size": 9,
        "axes.titlesize": 12,
        "axes.titleweight": "bold",
    }
)


def load():
    with open(os.path.join(HERE, "results.json"), encoding="utf-8") as handle:
        return json.load(handle)["results"]


def pick(results, label):
    for entry in results:
        if entry["label"] == label:
            return entry
    return None


def fig_expand_tree(results):
    """Grouped bars: traversal speedup across shapes, DEPTH/WIDTH/ZIGZAG."""
    shapes = ["balanced_9k", "wide_5k", "balanced_1k"]
    modes = ["DEPTH", "WIDTH", "ZIGZAG"]

    fig, ax = plt.subplots(figsize=(7.4, 4.0))
    width = 0.26
    colors = {"DEPTH": AMBER, "WIDTH": TERRACOTTA, "ZIGZAG": OLIVE}

    for index, mode in enumerate(modes):
        values = []
        labels = []
        for shape in shapes:
            entry = pick(results, "%s: expand_tree %s" % (shape, mode))
            values.append(entry["median_ratio"] if entry and entry["median_ratio"] else 0)
            labels.append(shape)
        offsets = [pos + (index - 1) * width for pos in range(len(shapes))]
        bars = ax.bar(offsets, values, width, label=mode, color=colors[mode], edgecolor="none")
        for bar, value in zip(bars, values):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                value + 0.4,
                "%.1fx" % value,
                ha="center",
                va="bottom",
                fontsize=7.5,
                color=INK,
            )

    ax.set_xticks(range(len(shapes)))
    ax.set_xticklabels(["balanced\n9,331 nodes", "wide\n5,001 nodes", "balanced\n1,093 nodes"])
    ax.set_ylabel("Speedup  (baseline / optimized)")
    ax.set_title("expand_tree(): the frontier no longer copies itself")
    ax.axhline(1.0, color=MUTED, linewidth=0.9, linestyle=(0, (4, 3)))
    ax.set_ylim(0, max(30, ax.get_ylim()[1]))
    ax.grid(axis="y", color=GRID, linewidth=0.7)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    # Legend goes *below* the axis: inside the plot it covered the 23.4x bar.
    ax.legend(
        frameon=False,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.22),
        ncol=3,
        title="traversal mode  (dashed line = break-even)",
        title_fontsize=8,
    )
    # ``rect`` keeps room at the bottom for the relocated legend.
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    fig.savefig(os.path.join(ASSETS, "expand-tree-speedup.png"), dpi=200)
    plt.close(fig)


def fig_operations(results):
    """Horizontal bars: one representative case per optimized operation."""
    wanted = [
        ("save2file (9,331 nodes)", "balanced_9k: save2file"),
        ("size(level) (1,001-deep chain)", "deep_1k: size(level=2)"),
        ("size(level) (9,331 nodes)", "balanced_9k: size(level=2)"),
        ("depth() (1,093 nodes)", "balanced_1k: depth()"),
        ("str(tree) (9,331 nodes)", "balanced_9k: str(tree)"),
        ("ancestor() x1000 (1,001-deep)", "deep_1k: ancestor(deepest, 999) x1000"),
        ("paths_to_leaves (1,093 nodes)", "balanced_1k: paths_to_leaves()"),
        ("create_node x500", "balanced_9k: create_node x500"),
        ("level() (1,001-deep chain)", "deep_1k: level(deepest node)"),
    ]

    rows = []
    for title, label in wanted:
        entry = pick(results, label)
        if entry and entry["median_ratio"]:
            rows.append((title, entry["median_ratio"]))

    fig, ax = plt.subplots(figsize=(7.4, 4.2))
    names = [row[0] for row in rows][::-1]
    values = [row[1] for row in rows][::-1]

    # Log scale: the wins span three orders of magnitude, so a linear axis would
    # flatten everything below ~20x into invisible slivers.
    bars = ax.barh(names, values, color=AMBER, edgecolor="none", height=0.62)
    for bar, value in zip(bars, values):
        ax.text(
            value * 1.12,
            bar.get_y() + bar.get_height() / 2,
            "%.1fx" % value if value < 100 else "%.0fx" % value,
            va="center",
            ha="left",
            fontsize=8,
            color=INK,
        )
    ax.set_xscale("log")
    ax.set_xlim(0.8, max(values) * 4)
    ax.set_xlabel("Speedup  (baseline / optimized, log scale)")
    ax.set_title("Per-operation speedup, 1k-9k node trees")
    ax.axvline(1.0, color=TERRACOTTA, linewidth=0.9, linestyle=(0, (4, 3)))
    ax.grid(axis="x", color=GRID, linewidth=0.7)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    fig.tight_layout()
    fig.savefig(os.path.join(ASSETS, "operation-speedup.png"), dpi=200)
    plt.close(fig)


def fig_scaling(results):
    """Time vs. node count for WIDTH traversal: linear vs. quadratic growth."""
    # Absolute best-of-N times from the recorded run.
    points = []
    for shape, nodes in (("balanced_1k", 1093), ("wide_5k", 5001), ("balanced_9k", 9331)):
        base = pick(results, "%s: expand_tree WIDTH" % shape)
        if base:
            points.append((nodes, base["baseline_best_ms"], base["optimized_best_ms"]))

    points.sort()
    nodes = [p[0] for p in points]
    base = [p[1] for p in points]
    opt = [p[2] for p in points]

    fig, ax = plt.subplots(figsize=(7.4, 3.6))
    ax.plot(nodes, base, marker="o", color=TERRACOTTA, linewidth=2, label="upstream (list + queue[1:])")
    ax.plot(nodes, opt, marker="s", color=OLIVE, linewidth=2, label="optimized (deque)")

    for x, y in zip(nodes, base):
        ax.annotate(
            "%.0f ms" % y,
            (x, y),
            textcoords="offset points",
            xytext=(-10, 9),
            ha="right",
            fontsize=7.5,
            color=TERRACOTTA,
        )
    for x, y in zip(nodes, opt):
        ax.annotate(
            "%.1f ms" % y,
            (x, y),
            textcoords="offset points",
            xytext=(0, -16),
            ha="center",
            va="top",
            fontsize=7.5,
            color=OLIVE,
        )

    ax.set_xlabel("Nodes in tree")
    ax.set_ylabel("Wall time (ms, best of N)")
    ax.set_title("BFS traversal cost: quadratic vs. linear frontier")
    ax.grid(color=GRID, linewidth=0.7)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.legend(frameon=False, loc="upper left")
    # Negative lower bound so the "optimized" annotations sit inside the axes
    # instead of colliding with the x tick labels.
    ax.set_ylim(bottom=-14)
    ax.set_xlim(left=nodes[0] - 900, right=nodes[-1] + 500)
    fig.tight_layout()
    fig.savefig(os.path.join(ASSETS, "bfs-scaling.png"), dpi=200)
    plt.close(fig)


def fig_deep_trees(results):
    """Bar chart: render time on chains upstream cannot render at all."""
    depths = [1200, 3000, 6000]
    values = []
    for depth in depths:
        entry = pick(results, "deep%d: str(tree)" % depth)
        values.append(entry["optimized_best_ms"] if entry else 0)

    fig, ax = plt.subplots(figsize=(7.4, 3.2))
    bars = ax.bar(["depth %d" % d for d in depths], values, color=AMBER, width=0.5, edgecolor="none")
    for bar, value in zip(bars, values):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            value * 1.02,
            "%.0f ms" % value,
            ha="center",
            va="bottom",
            fontsize=8.5,
            color=INK,
        )
    # Explicit annotation: these are not "faster", they are "previously impossible".
    # Placed under the title (outside the plotting area) so it never sits on a bar.
    ax.set_title(
        "Rendering deep chains: a capability fix, not a speedup\n"
        "upstream raises RecursionError at every one of these depths",
        fontsize=11.5,
    )
    ax.set_ylabel("Wall time (ms)")
    ax.set_ylim(0, max(values) * 1.18)
    ax.grid(axis="y", color=GRID, linewidth=0.7)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    fig.tight_layout()
    fig.savefig(os.path.join(ASSETS, "deep-tree-support.png"), dpi=200)
    plt.close(fig)


def fig_architecture():
    """Before/after structural diagram of the traversal frontier."""
    fig, axes = plt.subplots(1, 2, figsize=(7.6, 3.2))

    def panel(ax, title, subtitle, color, rows):
        ax.set_xlim(0, 10)
        ax.set_ylim(0, 10)
        ax.axis("off")
        ax.set_title(title, fontsize=10.5, color=INK, pad=8)
        ax.text(5, 8.9, subtitle, ha="center", fontsize=7.6, color=MUTED, style="italic")

        for index, (text, note) in enumerate(rows):
            y = 7.4 - index * 1.55
            box = FancyBboxPatch(
                (0.4, y - 0.5),
                9.2,
                1.05,
                boxstyle="round,pad=0.02,rounding_size=0.18",
                linewidth=1.0,
                edgecolor=color,
                facecolor="#fffdf9",
            )
            ax.add_patch(box)
            ax.text(0.75, y + 0.16, text, fontsize=8.2, color=INK, va="center")
            ax.text(0.75, y - 0.24, note, fontsize=7.2, color=MUTED, va="center")

    panel(
        axes[0],
        "Before: list frontier",
        "every visited node copies the rest of the queue",
        TERRACOTTA,
        [
            ("queue = expansion + queue[1:]", "O(w) copy per node  ->  O(n*w) total"),
            ("queue[0], queue.pop(0)", "O(w) shift per node"),
            ("open(path, 'ab') per line", "O(n) descriptor opens"),
            ("recursive render / export", "RecursionError past ~1000 levels"),
        ],
    )
    panel(
        axes[1],
        "After: deque frontier",
        "pop from the front, extend at the back",
        OLIVE,
        [
            ("deque.popleft() / extend()", "O(1) per node  ->  O(n) total"),
            ("level-by-level ZIGZAG", "O(width) per level, no re-prepending"),
            ("one open(path, 'wb')", "1 descriptor, truncates on rewrite"),
            ("explicit stack traversal", "no depth limit, same output bytes"),
        ],
    )
    fig.tight_layout()
    fig.savefig(os.path.join(ASSETS, "frontier-structure.png"), dpi=200)
    plt.close(fig)


def main():
    os.makedirs(ASSETS, exist_ok=True)
    results = load()
    fig_architecture()
    fig_expand_tree(results)
    fig_operations(results)
    fig_scaling(results)
    fig_deep_trees(results)
    for name in sorted(os.listdir(ASSETS)):
        if name.endswith(".png"):
            path = os.path.join(ASSETS, name)
            print("%-28s %7.1f KB" % (name, os.path.getsize(path) / 1024))


if __name__ == "__main__":
    main()
