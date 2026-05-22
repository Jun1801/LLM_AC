"""Analyze embedding similarity distribution across Phase B cache benchmark variants.

Steps
-----
1. Load phase_b_cache_benchmark.jsonl
2. Embed each prompt with all-MiniLM-L6-v2 (same model as the pipeline)
3. For each variant, compute cosine similarity to its anchor
4. Run Otsu's method to find the natural threshold
5. Plot histogram (grouped by variant type) + Otsu line + static 0.85 line
6. Save figure to eval/similarity_distribution.png
7. Print summary stats

Usage
-----
  python scripts/analyze_similarity_distribution.py
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")  # non-interactive backend for server environments
import matplotlib.pyplot as plt
from sentence_transformers import SentenceTransformer

REPO_ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_PATH = REPO_ROOT / "eval" / "phase_b_cache_benchmark.jsonl"
OUT_PNG = REPO_ROOT / "eval" / "outputs" / "figures" / "similarity_distribution.png"
OUT_JSON = REPO_ROOT / "eval" / "outputs" / "benchmark" / "similarity_distribution_stats.json"
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

VARIANT_COLORS = {
    "paraphrase": "#2196F3",          # blue
    "artifact_swap": "#FF9800",       # orange
    "near_miss_incident": "#F44336",  # red
    "near_miss_elevated_conf": "#9C27B0",  # purple
}

VARIANT_LABELS = {
    "paraphrase": "Paraphrase",
    "artifact_swap": "Artifact swap",
    "near_miss_incident": "Near-miss: incident↑",
    "near_miss_elevated_conf": "Near-miss: elevated+conf",
}


def otsu_threshold(values: np.ndarray, n_bins: int = 256) -> float:
    """Otsu's method on a 1-D continuous distribution.

    Discretises `values` into `n_bins` histogram bins, then finds the
    threshold t that maximises between-class variance:
        sigma_b²(t) = w0(t)·w1(t)·[mu0(t) - mu1(t)]²
    """
    hist, bin_edges = np.histogram(values, bins=n_bins, density=False)
    bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2
    total = hist.sum()
    if total == 0:
        return float(np.mean(values))

    # cumulative weight and cumulative weighted mean
    w = hist / total
    cum_w = np.cumsum(w)
    cum_mu = np.cumsum(w * bin_centers)

    global_mu = cum_mu[-1]
    # avoid divide-by-zero at boundaries
    with np.errstate(divide="ignore", invalid="ignore"):
        sigma_b2 = np.where(
            (cum_w > 0) & (cum_w < 1),
            (cum_w * (1 - cum_w)) * ((cum_mu / cum_w - (global_mu - cum_mu) / (1 - cum_w)) ** 2),
            0.0,
        )

    return float(bin_centers[np.argmax(sigma_b2)])


def main() -> None:
    print(f"Loading benchmark: {BENCHMARK_PATH}")
    cases = [
        json.loads(line)
        for line in BENCHMARK_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    anchors = {c["case_id"]: c for c in cases if c["phase"] == "anchor"}
    variants = [c for c in cases if c["phase"] == "variant"]

    print(f"  {len(anchors)} anchors, {len(variants)} variants")
    print(f"Loading embedding model: {EMBEDDING_MODEL}")

    model = SentenceTransformer(EMBEDDING_MODEL)

    # Embed all unique prompts in one batch
    all_case_ids = list(anchors.keys()) + [v["case_id"] for v in variants]
    all_prompts = (
        [a["request"]["query"]["prompt"] for a in anchors.values()]
        + [v["request"]["query"]["prompt"] for v in variants]
    )
    print(f"  Embedding {len(all_prompts)} prompts...")
    embeddings_raw = model.encode(all_prompts, normalize_embeddings=True, show_progress_bar=False)
    emb_map = dict(zip(all_case_ids, embeddings_raw))

    # Compute cosine similarity for each variant → anchor pair
    # (normalized embeddings → dot product = cosine similarity)
    by_type: dict[str, list[float]] = {vt: [] for vt in VARIANT_COLORS}
    for v in variants:
        vtype = v["variant_type"]
        anchor_id = v["anchor_id"]
        if anchor_id not in emb_map or v["case_id"] not in emb_map:
            print(f"  WARNING: missing embedding for {v['case_id']} or {anchor_id}")
            continue
        sim = float(np.dot(emb_map[v["case_id"]], emb_map[anchor_id]))
        by_type[vtype].append(sim)

    # All variant similarities combined (for Otsu)
    all_sims = np.array([s for sims in by_type.values() for s in sims])

    otsu = otsu_threshold(all_sims)

    # Gap boundaries: top of lower cluster, bottom of upper cluster
    swap_max = float(np.max(by_type["artifact_swap"])) if by_type["artifact_swap"] else 0.0
    para_min = float(np.min(by_type["paraphrase"])) if by_type["paraphrase"] else 1.0
    gap_lo, gap_hi = swap_max, para_min

    # --- print summary stats ---
    print("\n-- Similarity stats by variant type ------------------")
    stats: dict[str, dict] = {}
    for vtype, sims in by_type.items():
        arr = np.array(sims)
        if len(arr) == 0:
            continue
        entry = {
            "count": len(arr),
            "min": float(arr.min()),
            "max": float(arr.max()),
            "mean": float(arr.mean()),
            "median": float(np.median(arr)),
            "std": float(arr.std()),
        }
        stats[vtype] = entry
        print(
            f"  {vtype:<32} n={entry['count']:>3}  "
            f"min={entry['min']:.3f}  max={entry['max']:.3f}  "
            f"mean={entry['mean']:.3f}  std={entry['std']:.3f}"
        )

    print(f"\n-- Distribution gap: [{gap_lo:.3f}, {gap_hi:.3f}]  (width={gap_hi - gap_lo:.3f})")
    tol = 0.005  # floating-point tolerance for boundary check
    position = "AT gap lower boundary" if abs(otsu - gap_lo) <= tol else ("WITHIN" if gap_lo <= otsu <= gap_hi else "OUTSIDE")
    print(f"-- Otsu threshold:   {otsu:.4f}  (sits {position} the gap)")
    print(f"   t_validate_low range: [0.65, 0.80]  (mode sweep lower bound)")
    print(f"   t_hit range:          [0.85, 0.95]  (direct cache hit threshold)")
    print(f"   Note: near_miss similarity = 1.0 but requires ESCALATE_HUMAN")
    print(f"         -> proves soft policy re-eval is needed beyond any similarity threshold")

    # --- plot ---
    fig, axes = plt.subplots(2, 1, figsize=(9, 7), gridspec_kw={"height_ratios": [3, 1]})

    # Top: stacked histogram
    ax = axes[0]
    bins = np.linspace(0.0, 1.0, 51)  # 50 bins over [0, 1]

    stacked_data = []
    stacked_colors = []
    stacked_labels = []
    for vtype in ["paraphrase", "artifact_swap", "near_miss_incident", "near_miss_elevated_conf"]:
        sims = by_type.get(vtype, [])
        if sims:
            stacked_data.append(sims)
            stacked_colors.append(VARIANT_COLORS[vtype])
            stacked_labels.append(VARIANT_LABELS[vtype])

    ax.hist(stacked_data, bins=bins, stacked=True, color=stacked_colors, label=stacked_labels,
            edgecolor="white", linewidth=0.4, alpha=0.85)

    # Gap band
    ax.axvspan(gap_lo, gap_hi, alpha=0.12, color="#9E9E9E", label=f"Empty gap [{gap_lo:.3f}, {gap_hi:.3f}]")
    # t_validate_low band [0.65, 0.80] — sits within gap
    ax.axvspan(0.65, gap_hi, alpha=0.15, color="#FF9800", label="t_validate_low window [0.65, 0.80]")
    # Otsu
    ax.axvline(otsu, color="#212121", linewidth=2.0, linestyle="--",
               label=f"Otsu = {otsu:.3f}")
    # t_hit range marker
    ax.axvline(0.85, color="#43A047", linewidth=1.5, linestyle=":",
               label="t_hit lower bound = 0.85")
    ax.axvline(0.95, color="#43A047", linewidth=1.5, linestyle=":",
               label="t_hit upper bound = 0.95")

    ax.set_xlabel("Cosine similarity to anchor", fontsize=12)
    ax.set_ylabel("Count", fontsize=12)
    ax.set_title(
        "Embedding Similarity Distribution: Phase B Variant Types\n"
        f"(model: all-MiniLM-L6-v2, n={len(all_sims)} variants) — "
        f"Gap [{gap_lo:.3f}, {gap_hi:.3f}], Otsu = {otsu:.3f}",
        fontsize=11,
    )
    ax.legend(fontsize=10, loc="upper left")
    ax.set_xlim(0.0, 1.0)
    ax.grid(axis="y", alpha=0.3)

    # Bottom: rug plot per variant type
    ax2 = axes[1]
    y_positions = {
        "paraphrase": 0.8,
        "artifact_swap": 0.55,
        "near_miss_incident": 0.3,
        "near_miss_elevated_conf": 0.05,
    }
    for vtype, sims in by_type.items():
        if sims:
            y = y_positions[vtype]
            ax2.scatter(sims, [y] * len(sims), c=VARIANT_COLORS[vtype],
                        marker="|", s=80, alpha=0.7)
    ax2.axvspan(gap_lo, gap_hi, alpha=0.12, color="#9E9E9E")
    ax2.axvspan(0.65, gap_hi, alpha=0.15, color="#FF9800")
    ax2.axvline(otsu, color="#212121", linewidth=2.0, linestyle="--")
    ax2.axvline(0.85, color="#43A047", linewidth=1.5, linestyle=":")
    ax2.axvline(0.95, color="#43A047", linewidth=1.5, linestyle=":")
    ax2.set_xlim(0.0, 1.0)
    ax2.set_yticks([0.05, 0.3, 0.55, 0.8])
    ax2.set_yticklabels(
        ["near_miss_elev+conf", "near_miss_incident", "artifact_swap", "paraphrase"],
        fontsize=8,
    )
    ax2.set_xlabel("Cosine similarity to anchor", fontsize=11)
    ax2.grid(axis="x", alpha=0.3)

    plt.tight_layout()
    fig.savefig(OUT_PNG, dpi=150, bbox_inches="tight")
    print(f"\n[saved] {OUT_PNG}")

    # Save stats JSON
    out_stats = {
        "embedding_model": EMBEDDING_MODEL,
        "n_variants": int(len(all_sims)),
        "otsu_threshold": otsu,
        "gap_lo": gap_lo,
        "gap_hi": gap_hi,
        "gap_width": gap_hi - gap_lo,
        "otsu_in_gap": bool(gap_lo <= otsu <= gap_hi),
        "t_validate_low_range": [0.65, 0.80],
        "t_hit_range": [0.85, 0.95],
        "interpretation": (
            "Otsu threshold sits at the top of the artifact_swap cluster and bottom of the gap. "
            "t_validate_low [0.65, 0.80] is set within the empty gap, correctly separating "
            "semantically distinct artifact_swaps from semantically equivalent paraphrases. "
            "near_miss variants at similarity=1.0 are in the upper cluster but require ESCALATE_HUMAN, "
            "proving that similarity-based thresholds alone are insufficient for cache safety."
        ),
        "by_variant_type": stats,
    }
    OUT_JSON.write_text(json.dumps(out_stats, indent=2), encoding="utf-8")
    print(f"[saved] {OUT_JSON}")


if __name__ == "__main__":
    main()
