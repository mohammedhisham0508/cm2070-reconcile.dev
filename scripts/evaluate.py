"""
Reconcile.dev — Precision / Recall Evaluation

Usage:
  python scripts/evaluate.py

"""

import os
import sys
import time
import random
import json

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://postgres:postgres@localhost:5432/reconcile_dev"
)

# Add project root to path so we can import matcher
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.matcher import reconcile

# ── Configuration ──────────────────────────────────────────────────────────────

SAMPLE_SIZE  = 500
RANDOM_SEED  = 42
THRESHOLDS   = [0.70, 0.75, 0.80, 0.85, 0.90, 0.95]
TOP_K        = 5


# ── Distortion functions ───────────────────────────────────────────────────────

def distort_typo(name: str) -> str:
    """Swap two adjacent characters at a random interior position."""
    if len(name) < 3:
        return name
    chars = list(name)
    pos = random.randint(1, len(chars) - 2)
    chars[pos], chars[pos + 1] = chars[pos + 1], chars[pos]
    return "".join(chars)


def distort_delete(name: str) -> str:
    """Delete one random interior character."""
    if len(name) < 4:
        return name
    pos = random.randint(1, len(name) - 2)
    return name[:pos] + name[pos + 1:]


def distort_double(name: str) -> str:
    """Double one random character."""
    if len(name) < 2:
        return name
    pos = random.randint(0, len(name) - 1)
    return name[:pos] + name[pos] + name[pos:]


def distort_truncate(name: str) -> str:
    """Remove last word if multi-word, else remove last 2 characters."""
    words = name.strip().split()
    if len(words) > 1:
        return " ".join(words[:-1])
    if len(name) > 5:
        return name[:-2]
    return name


DISTORTIONS      = [distort_typo, distort_delete, distort_double, distort_truncate]
DISTORTION_NAMES = ["Typo (swap)", "Delete char", "Double char", "Truncate word"]


# ── Metrics ────────────────────────────────────────────────────────────────────

def compute_metrics(results: list, threshold: float) -> dict:
    """
    Compute precision, recall, F1, MRR at a given score threshold.

    Precision = TP / (TP + FP)
      — of everything we returned above threshold, how many were correct?

    Recall = TP / (TP + FN)
      — of all correct answers, how many did we find?

    F1 = harmonic mean of precision and recall

    MRR = mean reciprocal rank of the correct answer
    """
    tp = fp = fn = 0
    reciprocal_ranks = []

    for r in results:
        correct_id = str(r["correct_id"])
        candidates = r["candidates"]

        above     = [c for c in candidates if c["final_score"] >= threshold]
        correct_in_above   = any(c["id"] == correct_id for c in above)
        returned_something = len(above) > 0

        if correct_in_above:
            tp += 1
        elif returned_something:
            fp += 1
        else:
            fn += 1

        # MRR over full ranked list regardless of threshold
        for rank, c in enumerate(candidates, start=1):
            if c["id"] == correct_id:
                reciprocal_ranks.append(1.0 / rank)
                break
        else:
            reciprocal_ranks.append(0.0)

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall    = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1        = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    mrr       = sum(reciprocal_ranks) / len(reciprocal_ranks) if reciprocal_ranks else 0.0

    return {
        "threshold": threshold,
        "precision": round(precision, 3),
        "recall":    round(recall, 3),
        "f1":        round(f1, 3),
        "mrr":       round(mrr, 3),
        "tp": tp, "fp": fp, "fn": fn,
        "total": len(results),
    }


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    print("=" * 62)
    print("  Reconcile.dev — Precision / Recall Evaluation")
    print("=" * 62)

    random.seed(RANDOM_SEED)

    # ── Connect ────────────────────────────────────────────────────────────────
    print("\nConnecting to database...")
    engine = create_engine(DATABASE_URL)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("  Connected successfully")
    except Exception as e:
        print(f"\n  ERROR: Could not connect — {e}")
        print("  Make sure PostgreSQL is running and reconcile_dev database exists.")
        sys.exit(1)

    # ── Sample places ──────────────────────────────────────────────────────────
    print(f"\nSampling {SAMPLE_SIZE} places (population > 100,000, ASCII names only)...")
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT geonameid, name, country_code
            FROM   places
            WHERE  population > 100000
              AND  length(name) >= 4
              AND  name ~ '^[A-Za-z][A-Za-z \\-]+$'
            ORDER  BY RANDOM()
            LIMIT  :n
        """), {"n": SAMPLE_SIZE}).fetchall()

    places = [{"id": str(r.geonameid), "name": r.name, "country": r.country_code}
              for r in rows]
    print(f"  Got {len(places)} places")

    Session = sessionmaker(bind=engine)

    # ── Exact match baseline ───────────────────────────────────────────────────
    print("\n" + "-" * 62)
    print("  PART 1 — Exact Match Baseline (n=100)")
    print("-" * 62)

    exact_results = []
    exact_times   = []
    db = Session()

    for p in places[:100]:
        t0 = time.perf_counter()
        candidates = reconcile(db, p["name"], limit=TOP_K)
        ms = (time.perf_counter() - t0) * 1000
        exact_times.append(ms)
        exact_results.append({
            "correct_id": p["id"],
            "query":      p["name"],
            "candidates": candidates,
        })

    db.close()

    exact_correct = sum(
        1 for r in exact_results
        if r["candidates"] and r["candidates"][0]["id"] == r["correct_id"]
    )

    print(f"  Total queries:       {len(exact_results)}")
    print(f"  Correct (top-1):     {exact_correct} / {len(exact_results)}")
    print(f"  Accuracy:            {exact_correct / len(exact_results) * 100:.1f}%")
    print(f"  Avg response time:   {sum(exact_times)/len(exact_times):.1f} ms")
    print(f"  Min response time:   {min(exact_times):.1f} ms")
    print(f"  Max response time:   {max(exact_times):.1f} ms")

    # ── Fuzzy match by distortion type ────────────────────────────────────────
    print("\n" + "-" * 62)
    print(f"  PART 2 — Fuzzy Match by Distortion Type (125 per type)")
    print("-" * 62)

    all_fuzzy   = []
    dist_summary = []
    fuzzy_times  = []
    db = Session()

    per_dist = len(places) // len(DISTORTIONS)

    for i, (dist_fn, dist_name) in enumerate(zip(DISTORTIONS, DISTORTION_NAMES)):
        subset   = places[i * per_dist: (i + 1) * per_dist]
        d_results = []
        d_times   = []

        for p in subset:
            distorted = dist_fn(p["name"])
            if distorted.lower() == p["name"].lower():
                continue   # skip if distortion had no effect

            t0 = time.perf_counter()
            candidates = reconcile(db, distorted, limit=TOP_K)
            ms = (time.perf_counter() - t0) * 1000

            d_times.append(ms)
            fuzzy_times.append(ms)
            entry = {
                "correct_id": p["id"],
                "query":      distorted,
                "original":   p["name"],
                "candidates": candidates,
            }
            d_results.append(entry)
            all_fuzzy.append({"correct_id": p["id"],
                               "query": distorted,
                               "candidates": candidates})

        correct_1 = sum(1 for r in d_results
                        if r["candidates"] and r["candidates"][0]["id"] == r["correct_id"])
        correct_k = sum(1 for r in d_results
                        if any(c["id"] == r["correct_id"] for c in r["candidates"]))
        avg_ms    = sum(d_times) / len(d_times) if d_times else 0

        dist_summary.append({
            "name": dist_name, "total": len(d_results),
            "top1": correct_1, "topk": correct_k, "avg_ms": avg_ms,
        })

        acc1 = correct_1 / len(d_results) * 100 if d_results else 0
        acck = correct_k / len(d_results) * 100 if d_results else 0
        print(f"  {dist_name:22}  "
              f"top-1={correct_1:3}/{len(d_results)} ({acc1:5.1f}%)  "
              f"top-{TOP_K}={correct_k:3}/{len(d_results)} ({acck:5.1f}%)  "
              f"avg={avg_ms:5.1f}ms")

    db.close()

    avg_fuzzy = sum(fuzzy_times) / len(fuzzy_times) if fuzzy_times else 0
    print(f"\n  Overall fuzzy avg response time: {avg_fuzzy:.1f} ms")

    # ── Precision / Recall at 6 thresholds ────────────────────────────────────
    print("\n" + "-" * 62)
    print(f"  PART 3 — Precision / Recall / F1 / MRR (n={len(all_fuzzy)})")
    print("-" * 62)
    print(f"\n  {'Threshold':>9}  {'Precision':>9}  {'Recall':>7}  "
          f"{'F1':>7}  {'MRR':>7}  {'TP':>5}  {'FP':>5}  {'FN':>5}")
    print("  " + "-" * 58)

    thresh_results = []
    for t in THRESHOLDS:
        m = compute_metrics(all_fuzzy, t)
        thresh_results.append(m)
        marker = " *" if m == max(thresh_results, key=lambda x: x["f1"]) else ""
        print(f"  {m['threshold']:>9.2f}  {m['precision']:>9.3f}  "
              f"{m['recall']:>7.3f}  {m['f1']:>7.3f}  {m['mrr']:>7.3f}  "
              f"{m['tp']:>5}  {m['fp']:>5}  {m['fn']:>5}{marker}")

    best = max(thresh_results, key=lambda x: x["f1"])
    print(f"\n  * Best F1 = {best['f1']:.3f} at threshold {best['threshold']}")

    # ── Save results ───────────────────────────────────────────────────────────
    output = {
        "config": {
            "sample_size": SAMPLE_SIZE,
            "random_seed": RANDOM_SEED,
            "top_k": TOP_K,
        },
        "exact_match": {
            "total": len(exact_results),
            "correct": exact_correct,
            "accuracy": round(exact_correct / len(exact_results), 3),
            "avg_ms": round(sum(exact_times) / len(exact_times), 2),
            "min_ms": round(min(exact_times), 2),
            "max_ms": round(max(exact_times), 2),
        },
        "fuzzy_by_distortion": dist_summary,
        "threshold_results": thresh_results,
        "best_threshold": best["threshold"],
        "best_f1": best["f1"],
        "fuzzy_avg_ms": round(avg_fuzzy, 2),
    }

    out_dir  = os.path.join(os.path.dirname(__file__), "..", "data")
    out_path = os.path.join(out_dir, "eval_results.json")
    os.makedirs(out_dir, exist_ok=True)

    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, default=str)

    print(f"\n  Full results saved to: data/eval_results.json")
    print("\n" + "=" * 62)
    print("  Evaluation complete. Paste the tables above into your report.")
    print("=" * 62 + "\n")


if __name__ == "__main__":
    main()
