"""Generate Figure 2: Latency distribution per decision path.

Uses the measured p50/p95 values reported in Table 5 of the paper:
  - Cache hit    : p50=71 ms,    p95=230 ms
  - Validation   : p50=99 ms,    p95=299 ms
  - LLM miss     : p50=2157 ms,  p95=2923 ms

Outputs: eval/latency_chart.png
"""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_PNG = REPO_ROOT / "eval" / "latency_chart.png"

# ----- data -----
PATHS = ["Cache hit\n(source: cache)", "Validation band\n(source: validation)", "LLM miss\n(source: llm)"]
P50  = [71,   99,   2157]
P95  = [230,  299,  2923]

COLORS_P50 = ["#1976D2", "#388E3C", "#E53935"]   # blue, green, red (dark)
COLORS_P95 = ["#90CAF9", "#A5D6A7", "#EF9A9A"]   # same hues, light

def main() -> None:
    fig, ax = plt.subplots(figsize=(8, 4.5))

    x = np.arange(len(PATHS))
    bar_w = 0.32
    offset = bar_w / 2

    bars_p50 = ax.bar(x - offset, P50, width=bar_w, color=COLORS_P50,
                      label="p50 (median)", zorder=3, edgecolor="white", linewidth=0.5)
    bars_p95 = ax.bar(x + offset, P95, width=bar_w, color=COLORS_P95,
                      label="p95", zorder=3, edgecolor="white", linewidth=0.5)

    ax.set_yscale("log")
    ax.set_ylim(10, 10_000)
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(
        lambda v, _: f"{int(v):,} ms"
    ))

    # value labels on bars
    for bar, val in zip(bars_p50, P50):
        ax.text(bar.get_x() + bar.get_width() / 2, val * 1.15,
                f"{val:,}", ha="center", va="bottom", fontsize=9, fontweight="bold")
    for bar, val in zip(bars_p95, P95):
        ax.text(bar.get_x() + bar.get_width() / 2, val * 1.15,
                f"{val:,}", ha="center", va="bottom", fontsize=9)

    # 30× annotation bracket between cache p50 and LLM p50
    ax.annotate(
        "", xy=(x[2] - offset, P50[2]), xytext=(x[0] - offset, P50[0]),
        arrowprops=dict(arrowstyle="<->", color="#555555", lw=1.4),
    )
    mid_x = (x[0] - offset + x[2] - offset) / 2
    mid_y = (P50[0] * P50[2]) ** 0.5   # geometric mean on log scale
    ax.text(mid_x, mid_y * 1.8, "30× median\nlatency reduction",
            ha="center", va="bottom", fontsize=9, color="#555555",
            bbox=dict(boxstyle="round,pad=0.3", facecolor="white", edgecolor="#BBBBBB", alpha=0.85))

    ax.set_xticks(x)
    ax.set_xticklabels(PATHS, fontsize=10)
    ax.set_ylabel("Latency (ms, log scale)", fontsize=11)
    ax.set_title(
        "Figure 2: End-to-end Latency by Decision Path\n"
        "(n=30 iterations per path, balanced mode, p50 and p95)",
        fontsize=11,
    )
    ax.legend(fontsize=10, loc="upper left")
    ax.grid(axis="y", which="both", alpha=0.3, zorder=0)
    ax.set_axisbelow(True)

    plt.tight_layout()
    fig.savefig(OUT_PNG, dpi=150, bbox_inches="tight")
    print(f"[saved] {OUT_PNG}")


if __name__ == "__main__":
    main()
