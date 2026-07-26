#!/usr/bin/env python3
"""Generate a benchmark chart comparing quickpack vs charmcraft pack speeds.

Usage:
    uvx --with matplotlib python make_chart.py [results.json] [output.png]
"""

import json
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np


def main() -> None:
    """Render the quickpack benchmark chart."""
    results_file = sys.argv[1] if len(sys.argv) > 1 else "results.json"
    output_file = sys.argv[2] if len(sys.argv) > 2 else "benchmark_chart.png"

    with open(results_file) as f:
        data = json.load(f)

    results = data["results"]

    labels = [
        "Quickpack\n(Rust)",
        "Quickpack\n(Python)",
        "charmcraft pack\n--destructive (warm)",
        "charmcraft pack\n--destructive (cold)",
        "charmcraft pack\n(warm LXD)",
        "charmcraft pack\n(clean LXD)",
    ]
    keys = [
        "rust_quickpack",
        "python_quickpack",
        "charmcraft_destructive_warm",
        "charmcraft_destructive_cold",
        "charmcraft_lxd_warm",
        "charmcraft_lxd_clean",
    ]
    best_times = [results[k]["best"] for k in keys]

    # Colours: green for quickpack, amber/red gradient for charmcraft.
    colours = ["#2ecc71", "#27ae60", "#f1c40f", "#e67e22", "#e74c3c", "#c0392b"]

    fig, ax = plt.subplots(figsize=(14, 7))
    fig.patch.set_facecolor("#1a1a2e")
    ax.set_facecolor("#16213e")

    y_pos = np.arange(len(labels))
    bars = ax.barh(
        y_pos,
        best_times,
        color=colours,
        height=0.55,
        edgecolor="#0f3460",
        linewidth=1.5,
        label="Best",
    )

    max_time = max(best_times)

    # Time labels on bars.
    for bar_obj, t in zip(bars, best_times, strict=True):
        width = bar_obj.get_width()

        if t >= 60:
            label = f"{t / 60:.1f}m"
        elif t >= 10:
            label = f"{t:.0f}s"
        else:
            label = f"{t:.2f}s"

        if width < max_time * 0.12:
            x_pos = width + max_time * 0.01
            ha = "left"
            colour = "white"
        else:
            x_pos = width - max_time * 0.01
            ha = "right"
            colour = "white"

        ax.text(
            x_pos,
            bar_obj.get_y() + bar_obj.get_height() / 2,
            label,
            ha=ha,
            va="center",
            color=colour,
            fontsize=14,
            fontweight="bold",
        )

    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels, fontsize=11, color="#e0e0e0")
    ax.invert_yaxis()

    ax.set_xlabel("Time (seconds) — lower is better", fontsize=12, color="#e0e0e0")
    ax.set_title(
        "Charm Pack Speed: Quickpack vs Charmcraft",
        fontsize=18,
        fontweight="bold",
        color="white",
        pad=20,
    )

    # Speedup annotations on right side.
    clean_time = results["charmcraft_lxd_clean"]["best"]
    for i, (key, t) in enumerate(zip(keys, best_times, strict=True)):
        if key != "charmcraft_lxd_clean":
            speedup = clean_time / t
            colour = "#2ecc71" if "quickpack" in key else "#f39c12"
            ax.text(
                max_time * 1.02,
                i,
                f"{speedup:.0f}x faster",
                ha="left",
                va="center",
                color=colour,
                fontsize=11,
                fontweight="bold",
            )

    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["bottom"].set_color("#0f3460")
    ax.spines["left"].set_color("#0f3460")
    ax.tick_params(colors="#e0e0e0")

    # Use appropriate x-axis formatting.
    if max_time > 120:
        ax.xaxis.set_major_formatter(
            ticker.FuncFormatter(lambda x, _: f"{x / 60:.0f}m" if x >= 60 else f"{x:.0f}s")
        )
    else:
        ax.xaxis.set_major_formatter(ticker.FormatStrFormatter("%.0fs"))

    fig.text(
        0.5,
        0.02,
        f"Best of {data['runs']} runs  ·  {data['repo']}  ·  {data.get('charmcraft_version', '')}",
        ha="center",
        fontsize=9,
        color="#666",
        style="italic",
    )

    plt.tight_layout()
    plt.subplots_adjust(right=0.82, bottom=0.10)
    fig.savefig(output_file, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    print(f"Chart saved to {output_file}")


if __name__ == "__main__":
    main()
