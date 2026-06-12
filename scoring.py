"""
Scoring and aggregation.

Weighted scores are computed on the fly from the stored criterion scores so they
can never go stale. The reviewer's (verified) scores take precedence over the
evaluator's once a row is verified.
"""
from __future__ import annotations

import pandas as pd

import config as C


# --------------------------------------------------------------------------- #
# Active scores: verified values win once a row is verified
# --------------------------------------------------------------------------- #
def active_scores(row: dict) -> dict:
    """Return the criterion scores + safety that count for this evaluation."""
    verified = row.get("status") == C.STATUS_VERIFIED
    out = {}
    for k in C.CRITERIA_KEYS:
        rv = row.get(f"rv_{k}")
        ev = row.get(f"ev_{k}")
        out[k] = rv if (verified and _is_num(rv)) else ev
    rv_safety = row.get("rv_safety")
    out["safety"] = rv_safety if (verified and rv_safety) else row.get("ev_safety", C.SAFETY_DEFAULT)
    return out


def _is_num(x) -> bool:
    try:
        return x is not None and not pd.isna(x) and float(x) == float(x)
    except (TypeError, ValueError):
        return False


# --------------------------------------------------------------------------- #
# Weighted score for a single evaluation
# --------------------------------------------------------------------------- #
def weighted_score(scores: dict) -> float | None:
    """Weighted mean of criterion scores, then capped by the safety level."""
    num = 0.0
    den = 0.0
    for c in C.CRITERIA:
        v = scores.get(c["key"])
        if _is_num(v):
            num += c["weight"] * float(v)
            den += c["weight"]
    if den == 0:
        return None
    score = num / den
    cap = C.SAFETY_LEVELS.get(scores.get("safety", C.SAFETY_DEFAULT), {}).get("cap")
    if cap is not None:
        score = min(score, cap)
    return round(score, 3)


def row_weighted(row: dict) -> float | None:
    return weighted_score(active_scores(row))


# --------------------------------------------------------------------------- #
# Aggregation across evaluations
# --------------------------------------------------------------------------- #
def enrich(df: pd.DataFrame) -> pd.DataFrame:
    """Add per-row active criterion scores + weighted score columns."""
    if df.empty:
        cols = ["weighted"] + [f"act_{k}" for k in C.CRITERIA_KEYS] + ["act_safety"]
        return df.assign(**{c: pd.Series(dtype="float") for c in cols})
    recs = df.to_dict("records")
    df = df.copy()
    for k in C.CRITERIA_KEYS:
        df[f"act_{k}"] = [active_scores(r)[k] for r in recs]
    df["act_safety"] = [active_scores(r)["safety"] for r in recs]
    df["weighted"] = [row_weighted(r) for r in recs]
    return df


def model_summary(df: pd.DataFrame, verified_only: bool = False) -> pd.DataFrame:
    """One row per model: mean weighted score, per-criterion means, coverage, flags."""
    if df.empty:
        return pd.DataFrame()
    df = enrich(df)
    if verified_only:
        df = df[df["status"] == C.STATUS_VERIFIED]
    if df.empty:
        return pd.DataFrame()

    df["model"] = df["model_name"].fillna("") + df["model_version"].fillna("").apply(
        lambda v: f" ({v})" if str(v).strip() else ""
    )

    rows = []
    for (model, category), g in df.groupby(["model", "category"], dropna=False):
        rec = {
            "model": model,
            "category": category,
            "n_prompts": g["prompt_id"].nunique(),
            "n_evals": len(g),
            "n_verified": int((g["status"] == C.STATUS_VERIFIED).sum()),
            "n_harmful": int((g["act_safety"] == "harmful").sum()),
            "n_major": int((g["act_safety"] == "major").sum()),
            "mean_weighted": round(g["weighted"].mean(), 3),
        }
        for k in C.CRITERIA_KEYS:
            rec[f"mean_{k}"] = round(pd.to_numeric(g[f"act_{k}"], errors="coerce").mean(), 3)
        rows.append(rec)

    out = pd.DataFrame(rows).sort_values("mean_weighted", ascending=False)
    # Rank within category and overall
    out["rank_in_category"] = (
        out.groupby("category")["mean_weighted"].rank(ascending=False, method="min").astype("Int64")
    )
    out["rank_overall"] = out["mean_weighted"].rank(ascending=False, method="min").astype("Int64")
    return out.reset_index(drop=True)


def category_summary(model_summary_df: pd.DataFrame) -> pd.DataFrame:
    """Mean of model mean-weighted scores per category (best/mean/n)."""
    if model_summary_df.empty:
        return pd.DataFrame()
    rows = []
    for cat, g in model_summary_df.groupby("category"):
        rows.append(
            {
                "category": cat,
                "n_models": len(g),
                "best_model": g.sort_values("mean_weighted", ascending=False).iloc[0]["model"],
                "best_score": g["mean_weighted"].max(),
                "category_mean": round(g["mean_weighted"].mean(), 3),
            }
        )
    order = {k: i for i, k in enumerate(C.CATEGORY_KEYS)}
    return pd.DataFrame(rows).sort_values("category", key=lambda s: s.map(order)).reset_index(drop=True)
