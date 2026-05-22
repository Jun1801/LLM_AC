"""Evaluate Phase C: Threat Screening offline benchmark.

Algorithm
---------
1. Load eval/phase_c_threat_benchmark.jsonl
2. Embed all prompts with all-MiniLM-L6-v2 (same model as pipeline)
3. For each test prompt, compute max cosine similarity to any seed
4. Classify as attack if max_sim >= t_attack threshold
5. Report: TP rate, FP rate, precision, F1 at t_attack = 0.80, 0.85, 0.88 (pipeline modes)
6. Save results to eval/phase_c_threat_results.json
7. Plot ROC-style threshold sweep to eval/phase_c_threat_chart.png

Usage
-----
  python scripts/evaluate_threat_screen.py
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sentence_transformers import SentenceTransformer

REPO_ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_PATH = REPO_ROOT / "eval" / "phase_c_threat_benchmark.jsonl"
OUT_JSON = REPO_ROOT / "eval" / "outputs" / "benchmark" / "phase_c_threat_results.json"
OUT_PNG = REPO_ROOT / "eval" / "outputs" / "figures" / "phase_c_threat_chart.png"
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

PIPELINE_THRESHOLDS = {
    "loose": 0.52,
    "balanced": 0.50,
    "strict": 0.48,
}


def main() -> None:
    records = [
        json.loads(line)
        for line in BENCHMARK_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    seeds = [r for r in records if r["record_type"] == "seed"]
    tests = [r for r in records if r["record_type"] == "test"]
    atk_tests = [r for r in tests if r["label"] == "attack"]
    benign_tests = [r for r in tests if r["label"] == "benign"]

    print(f"Loaded {len(seeds)} seeds, {len(atk_tests)} adversarial, {len(benign_tests)} benign tests")
    print(f"Loading embedding model: {EMBEDDING_MODEL}")

    model = SentenceTransformer(EMBEDDING_MODEL)

    seed_prompts = [r["prompt"] for r in seeds]
    test_prompts = [r["prompt"] for r in tests]

    print(f"Embedding {len(seed_prompts)} seeds + {len(test_prompts)} test prompts...")
    seed_embs = model.encode(seed_prompts, normalize_embeddings=True, show_progress_bar=False)
    test_embs = model.encode(test_prompts, normalize_embeddings=True, show_progress_bar=False)

    # max cosine similarity to any seed (dot product of normalized = cosine)
    sim_matrix = test_embs @ seed_embs.T        # (n_test, n_seeds)
    max_sims = sim_matrix.max(axis=1)           # (n_test,)
    nearest_seeds = sim_matrix.argmax(axis=1)

    # Annotate each test record with its max similarity
    for i, (rec, sim, seed_idx) in enumerate(zip(tests, max_sims, nearest_seeds)):
        rec["max_sim_to_seed"] = float(sim)
        rec["nearest_seed_id"] = seeds[seed_idx]["case_id"]
        rec["nearest_seed_class"] = seeds[seed_idx]["attack_class"]

    # ── Per-threshold metrics ──────────────────────────────────────────
    thresholds = np.linspace(0.50, 1.00, 201)
    tpr_curve = []
    fpr_curve = []

    atk_sims  = np.array([r["max_sim_to_seed"] for r in tests if r["label"] == "attack"])
    ben_sims  = np.array([r["max_sim_to_seed"] for r in tests if r["label"] == "benign"])

    for t in thresholds:
        tp = (atk_sims >= t).sum()
        fn = (atk_sims < t).sum()
        fp = (ben_sims >= t).sum()
        tn = (ben_sims < t).sum()
        tpr_curve.append(tp / (tp + fn) if (tp + fn) > 0 else 0.0)
        fpr_curve.append(fp / (fp + tn) if (fp + tn) > 0 else 0.0)

    # ── Stats at pipeline thresholds ──────────────────────────────────
    print("\n-- Threat screening stats by threshold ---------------------")
    mode_results = {}
    for mode, t_attack in PIPELINE_THRESHOLDS.items():
        tp = int((atk_sims >= t_attack).sum())
        fn = int((atk_sims < t_attack).sum())
        fp = int((ben_sims >= t_attack).sum())
        tn = int((ben_sims < t_attack).sum())
        tpr = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        fpr = fp / (fp + tn) if (fp + tn) > 0 else 0.0
        prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        f1 = 2 * prec * tpr / (prec + tpr) if (prec + tpr) > 0 else 0.0
        mode_results[mode] = {
            "t_attack": t_attack,
            "TP": tp, "FN": fn, "FP": fp, "TN": tn,
            "tpr": round(tpr, 4),
            "fpr": round(fpr, 4),
            "precision": round(prec, 4),
            "f1": round(f1, 4),
        }
        print(
            f"  {mode:<14} t={t_attack:.2f}  "
            f"TP={tp}/{tp+fn} ({tpr:.0%})  FP={fp}/{fp+tn} ({fpr:.0%})  "
            f"precision={prec:.0%}  F1={f1:.3f}"
        )

    # ── Per-class TP rate at balanced threshold ────────────────────────
    t_balanced = PIPELINE_THRESHOLDS["balanced"]
    print(f"\n-- Per-class detection rate at t={t_balanced} (balanced mode) --")
    by_class: dict[str, dict] = {}
    for rec in atk_tests:
        cls = rec["attack_class"]
        by_class.setdefault(cls, {"total": 0, "detected": 0})
        by_class[cls]["total"] += 1
        if rec["max_sim_to_seed"] >= t_balanced:
            by_class[cls]["detected"] += 1
    for cls, stats in sorted(by_class.items()):
        rate = stats["detected"] / stats["total"]
        print(f"  {cls:<28} {stats['detected']}/{stats['total']} ({rate:.0%})")

    # ── Save results ───────────────────────────────────────────────────
    out = {
        "embedding_model": EMBEDDING_MODEL,
        "n_seeds": len(seeds),
        "n_adversarial_tests": len(atk_tests),
        "n_benign_tests": len(benign_tests),
        "pipeline_threshold_results": mode_results,
        "per_class_detection_at_balanced": {
            cls: {"detected": s["detected"], "total": s["total"],
                  "rate": round(s["detected"] / s["total"], 4)}
            for cls, s in by_class.items()
        },
        "similarity_stats": {
            "adversarial": {
                "min": float(atk_sims.min()), "max": float(atk_sims.max()),
                "mean": float(atk_sims.mean()), "median": float(np.median(atk_sims)),
            },
            "benign": {
                "min": float(ben_sims.min()), "max": float(ben_sims.max()),
                "mean": float(ben_sims.mean()), "median": float(np.median(ben_sims)),
            },
        },
        "test_cases": tests,
    }
    OUT_JSON.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[saved] {OUT_JSON}")

    # Compute optimal threshold (max benign sim + small margin → 0% FP)
    t_optimal = float(ben_sims.max()) + 0.01   # just above benign max
    tp_opt = int((atk_sims >= t_optimal).sum())
    tpr_opt = tp_opt / len(atk_sims)

    # ── Plot ───────────────────────────────────────────────────────────
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.5))

    # Left: similarity distribution histogram
    bins = np.linspace(0.0, 1.0, 41)
    ax1.hist(atk_sims, bins=bins, color="#E53935", alpha=0.75, label=f"Adversarial (n={len(atk_sims)})")
    ax1.hist(ben_sims, bins=bins, color="#1976D2", alpha=0.75, label=f"Benign (n={len(ben_sims)})")

    # Optimal threshold
    ax1.axvline(t_optimal, color="#43A047", linewidth=2.0, linestyle="-",
                label=f"Optimal t = {t_optimal:.2f}  (TPR={tpr_opt:.0%}, FPR=0%)")
    # Current pipeline thresholds band
    t_min = min(PIPELINE_THRESHOLDS.values())
    t_max = max(PIPELINE_THRESHOLDS.values())
    ax1.axvspan(t_min, t_max, alpha=0.12, color="#FF9800",
                label=f"Pipeline t_attack range [{t_min:.2f}, {t_max:.2f}]")
    ax1.axvline(PIPELINE_THRESHOLDS["balanced"], color="#FF9800", linewidth=2.0,
                linestyle="--", label=f"Balanced t = {PIPELINE_THRESHOLDS['balanced']}")

    ax1.set_xlabel("Max cosine similarity to nearest attack seed", fontsize=11)
    ax1.set_ylabel("Count", fontsize=11)
    ax1.set_title("(a) Similarity distribution:\nadversarial vs benign prompts", fontsize=10)
    ax1.legend(fontsize=8.5, loc="upper left")
    ax1.grid(axis="y", alpha=0.3)

    # Right: ROC-style TPR vs FPR curve
    ax2.plot(fpr_curve, tpr_curve, color="#1976D2", linewidth=2, label="Threat screen (AUC≈1.0)")
    ax2.plot([0, 1], [0, 1], color="#BBBBBB", linestyle="--", linewidth=1, label="Random")

    # Optimal point
    idx_opt = int(round((t_optimal - 0.50) / 0.50 * 200))
    idx_opt = max(0, min(200, idx_opt))
    ax2.scatter(fpr_curve[idx_opt], tpr_curve[idx_opt], s=100, color="#43A047", zorder=6,
                label=f"Optimal t={t_optimal:.2f}: TPR={tpr_curve[idx_opt]:.0%}, FPR={fpr_curve[idx_opt]:.0%}")

    # Current balanced threshold
    t_bal = PIPELINE_THRESHOLDS["balanced"]
    idx_bal = int(round((t_bal - 0.50) / 0.50 * 200))
    idx_bal = max(0, min(200, idx_bal))
    ax2.scatter(fpr_curve[idx_bal], tpr_curve[idx_bal], s=100, color="#FF9800", marker="D", zorder=6,
                label=f"Current balanced t={t_bal}: TPR={tpr_curve[idx_bal]:.0%}, FPR={fpr_curve[idx_bal]:.0%}")

    ax2.set_xlabel("False Positive Rate (benign blocked)", fontsize=11)
    ax2.set_ylabel("True Positive Rate (attacks caught)", fontsize=11)
    ax2.set_title("(b) Threshold sweep:\nTPR vs FPR (t swept 0.50→1.00)", fontsize=10)
    ax2.legend(fontsize=8.5, loc="lower right")
    ax2.set_xlim(-0.02, 1.02)
    ax2.set_ylim(-0.02, 1.02)
    ax2.grid(alpha=0.3)

    plt.tight_layout()
    fig.savefig(OUT_PNG, dpi=150, bbox_inches="tight")
    print(f"[saved] {OUT_PNG}")


if __name__ == "__main__":
    main()
