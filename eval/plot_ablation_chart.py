"""Generate Figure 4: Ablation study comparison chart.

Two-panel layout:
  Left  — Phase A metrics: accuracy + reason-code accuracy for Baseline / A2 / A3
  Right — A1 Phase B cache precision: precision by variant type (true vs false allows)

Outputs: eval/ablation_chart.png
"""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_PNG = REPO_ROOT / "eval" / "outputs" / "figures" / "ablation_chart.png"

# ----- Phase A data -----
VARIANTS_A = ["Baseline\n(full pipeline)", "A2: no cache", "A3: no hard-rule\npre-gate"]
ACCURACY   = [98.01, 95.05, 94.00]
RC_ACC     = [47.8,  48.0,  23.0]
LLM_CALLS  = [129,   130,   179]

# ----- A1 Phase B data (per variant type) -----
A1_TYPES   = ["Paraphrase", "Artifact\nswap", "Near-miss:\nincident", "Near-miss:\nelev+conf"]
A1_TRUE    = [24, 24, 0,  0]   # correct (true allows, precision=1.0)
A1_FALSE   = [0,  0,  24, 15]  # false allows (should be escalated)

COLOR_BASE  = "#1976D2"   # blue  – baseline
COLOR_A2    = "#388E3C"   # green – A2
COLOR_A3    = "#E53935"   # red   – A3
COLOR_TRUE  = "#43A047"   # green – correct
COLOR_FALSE = "#E53935"   # red   – false allow


def main() -> None:
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5),
                                    gridspec_kw={"width_ratios": [3, 2]})

    # ── Left panel: Phase A grouped bars ──────────────────────────────
    x = np.arange(len(VARIANTS_A))
    bar_w = 0.32
    colors = [COLOR_BASE, COLOR_A2, COLOR_A3]

    bars_acc = ax1.bar(x - bar_w / 2, ACCURACY, width=bar_w,
                       color=colors, label="_nolegend_",
                       edgecolor="white", linewidth=0.5, zorder=3)
    bars_rc  = ax1.bar(x + bar_w / 2, RC_ACC,   width=bar_w,
                       color=colors, alpha=0.45, label="_nolegend_",
                       edgecolor="white", linewidth=0.5, zorder=3,
                       hatch="//")

    # value labels
    for bar, val in zip(bars_acc, ACCURACY):
        ax1.text(bar.get_x() + bar.get_width() / 2, val + 0.4,
                 f"{val:.1f}%", ha="center", va="bottom", fontsize=8.5, fontweight="bold")
    for bar, val in zip(bars_rc, RC_ACC):
        ax1.text(bar.get_x() + bar.get_width() / 2, val + 0.4,
                 f"{val:.1f}%", ha="center", va="bottom", fontsize=8.5)

    ax1.set_ylim(0, 116)
    ax1.set_yticks(range(0, 101, 20))
    ax1.set_yticklabels([f"{v}%" for v in range(0, 101, 20)])
    ax1.set_xticks(x)
    ax1.set_xticklabels(VARIANTS_A, fontsize=9.5)
    ax1.set_ylabel("Accuracy (%)", fontsize=11)
    ax1.set_title("(a) Phase A: decision accuracy\nand reason-code accuracy by ablation variant", fontsize=10)
    ax1.grid(axis="y", alpha=0.3, zorder=0)
    ax1.set_axisbelow(True)

    # legend for bar types
    patch_acc = mpatches.Patch(facecolor="#888888", label="Decision accuracy")
    patch_rc  = mpatches.Patch(facecolor="#888888", alpha=0.45, hatch="//",
                                label="Reason-code accuracy")
    ax1.legend(handles=[patch_acc, patch_rc], fontsize=9, loc="lower left")

    # LLM call count: small grey text above each accuracy value label
    for xi, (acc, llm) in enumerate(zip(ACCURACY, LLM_CALLS)):
        ax1.text(xi - bar_w / 2, acc + 4.5, f"({llm} LLM calls)",
                 ha="center", va="bottom", fontsize=7.5, color="#555555")

    # ── Right panel: A1 stacked bar by variant type ───────────────────
    y = np.arange(len(A1_TYPES))
    bar_h = 0.5

    ax2.barh(y, A1_TRUE,  height=bar_h, color=COLOR_TRUE,
             label="Correct (soft re-eval guards)", zorder=3)
    ax2.barh(y, A1_FALSE, height=bar_h, left=A1_TRUE, color=COLOR_FALSE,
             label="False allow (re-eval disabled)", zorder=3)

    for i, (t, f) in enumerate(zip(A1_TRUE, A1_FALSE)):
        total = t + f
        if f > 0:
            ax2.text(total + 0.3, i, f"{f} false allows\n(100%)",
                     va="center", fontsize=8, color=COLOR_FALSE, fontweight="bold")
        elif t > 0:
            ax2.text(t + 0.3, i, f"0 false allows",
                     va="center", fontsize=8, color=COLOR_TRUE)

    # cache precision annotation
    ax2.axvline(24 * 0.552, color="#212121", linewidth=1.5, linestyle="--",
                label=f"Precision = 0.552 (A1 overall)")

    ax2.set_xlim(0, 36)
    ax2.set_yticks(y)
    ax2.set_yticklabels(A1_TYPES, fontsize=9.5)
    ax2.set_xlabel("Cases", fontsize=11)
    ax2.set_title("(b) A1: cache precision breakdown\n(soft re-evaluation disabled, Phase B)", fontsize=10)
    ax2.legend(fontsize=8.5, loc="lower right")
    ax2.grid(axis="x", alpha=0.3, zorder=0)
    ax2.set_axisbelow(True)

    plt.tight_layout(pad=2.0)
    fig.savefig(OUT_PNG, dpi=150, bbox_inches="tight")
    print(f"[saved] {OUT_PNG}")


if __name__ == "__main__":
    main()
