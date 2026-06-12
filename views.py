"""Streamlit page renderers. All Streamlit calls live inside functions."""
from __future__ import annotations

import functools
import io

import pandas as pd
import streamlit as st
import yaml

import config as C
import scoring as S
from storage import EvalStore, blank_record, new_eval_id, now_iso


# --------------------------------------------------------------------------- #
# Prompt loading
# --------------------------------------------------------------------------- #
@functools.lru_cache(maxsize=1)
def load_prompts() -> list[dict]:
    with open(C.PROMPTS_FILE, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def prompt_by_id(pid: str) -> dict | None:
    return next((p for p in load_prompts() if p["id"] == pid), None)


def _s(x) -> str:
    """NaN/None-safe string (Excel returns NaN for empty cells)."""
    if x is None:
        return ""
    try:
        if pd.isna(x):
            return ""
    except (TypeError, ValueError):
        pass
    return str(x)


def _score_select(label_prefix: str, crit: dict, default: int | None):
    """A 1..5 selectbox for one criterion, with anchors shown as a caption."""
    anchors = crit["anchors"]
    st.caption(f"**{crit['label']}** — {crit['help']}  \n"
               f"`1` {anchors[1]}  ·  `3` {anchors[3]}  ·  `5` {anchors[5]}")
    opts = [None] + C.SCALE
    idx = opts.index(default) if default in opts else 0
    return st.selectbox(
        crit["label"],
        opts,
        index=idx,
        format_func=lambda x: "—" if x is None else str(x),
        key=f"{label_prefix}_{crit['key']}",
        label_visibility="collapsed",
    )


def _models_index(df: pd.DataFrame) -> dict:
    """Map 'name (version)' -> last-seen metadata, for prefill dropdowns."""
    out = {}
    for r in df.to_dict("records"):
        name = (r.get("model_name") or "").strip()
        if not name:
            continue
        ver = (str(r.get("model_version")) if r.get("model_version") is not None else "").strip()
        key = f"{name} ({ver})" if ver and ver != "nan" else name
        out[key] = {
            "model_name": name,
            "model_version": ver if ver != "nan" else "",
            "category": r.get("category"),
            "provider": r.get("provider"),
            "deployment": r.get("deployment"),
        }
    return dict(sorted(out.items()))


# --------------------------------------------------------------------------- #
# 1. Add evaluation
# --------------------------------------------------------------------------- #
def page_add(store: EvalStore):
    st.header("Add an evaluation")
    st.write("Record one model's answer to one prompt and score it. "
             "Saved entries enter the review queue for the medical reviewer.")

    df = store.read_all()
    models = _models_index(df)

    # --- model selection (outside the form so 'new vs existing' reacts) ----
    st.subheader("Model")
    choice = st.selectbox("Model", ["➕ New model…"] + list(models.keys()))
    if choice == "➕ New model…":
        c1, c2 = st.columns(2)
        model_name = c1.text_input("Model name", placeholder="e.g. Llama-3.1-8B-Instruct")
        model_version = c2.text_input("Version / quantisation", placeholder="e.g. Q4_K_M")
        c3, c4, c5 = st.columns(3)
        category = c3.selectbox("Category", C.CATEGORY_KEYS,
                                format_func=lambda k: C.CATEGORIES[k])
        provider = c4.text_input("Provider / host", placeholder="e.g. Ollama, Anthropic")
        deployment = c5.selectbox("Deployment", C.DEPLOYMENTS)
    else:
        m = models[choice]
        model_name, model_version = m["model_name"], m["model_version"]
        category, provider, deployment = m["category"], m["provider"], m["deployment"]
        st.caption(f"Category: **{category}** · provider: {provider} · deployment: {deployment}")

    # --- prompt selection --------------------------------------------------
    st.subheader("Prompt")
    prompts = load_prompts()
    pid_col, lang_col = st.columns([3, 1])
    pid = pid_col.selectbox(
        "Use case",
        [p["id"] for p in prompts],
        format_func=lambda i: f"{i} — {prompt_by_id(i)['domain']}",
    )
    language = lang_col.radio(
        "Language",
        C.LANGUAGE_KEYS,
        format_func=lambda k: C.LANGUAGES[k],
        horizontal=True,
    )
    prompt = prompt_by_id(pid)
    text_key = "text_de" if language == "de" else "text"
    kp_key = "expected_key_points_de" if language == "de" else "expected_key_points"
    st.markdown(f"> {prompt[text_key].strip()}")
    with st.expander("Answer anchor (key points a strong answer should contain)"):
        for kp in prompt.get(kp_key, []):
            st.markdown(f"- {kp}")

    # --- the scored entry --------------------------------------------------
    with st.form("add_form", clear_on_submit=False):
        st.subheader("Model output")
        llm_output = st.text_area("Paste the model's full answer", height=220)

        st.subheader("Scores")
        scores = {c["key"]: _score_select("add", c, None) for c in C.CRITERIA}
        safety = st.selectbox(
            "Safety flag",
            C.SAFETY_KEYS,
            format_func=lambda k: C.SAFETY_LEVELS[k]["label"],
            help="‘major’ caps the score at 2.5; ‘potentially harmful’ caps it at 1.5.",
        )
        evaluator_name = st.text_input("Your name (evaluator)")
        comment = st.text_area("Comment (optional)", height=70)

        # live preview
        preview = S.weighted_score({**scores, "safety": safety})
        st.metric("Weighted score (preview)", "—" if preview is None else preview)

        submitted = st.form_submit_button("Save evaluation", type="primary")

    if submitted:
        problems = []
        if not model_name:
            problems.append("model name")
        if not llm_output.strip():
            problems.append("model output")
        if any(scores[k] is None for k in C.CRITERIA_KEYS):
            problems.append("all criterion scores")
        if not evaluator_name.strip():
            problems.append("evaluator name")
        if problems:
            st.error("Please provide: " + ", ".join(problems) + ".")
            return

        rec = blank_record()
        rec.update(
            eval_id=new_eval_id(),
            timestamp_created=now_iso(),
            timestamp_updated=now_iso(),
            model_name=model_name,
            model_version=model_version,
            category=category,
            provider=provider,
            deployment=deployment,
            prompt_id=pid,
            language=language,
            prompt_domain=prompt["domain"],
            prompt_text=prompt[text_key].strip(),
            llm_output=llm_output.strip(),
            evaluator_name=evaluator_name.strip(),
            ev_safety=safety,
            ev_comment=comment.strip(),
            status=C.STATUS_PENDING,
        )
        for k in C.CRITERIA_KEYS:
            rec[f"ev_{k}"] = scores[k]
        store.add(rec)
        st.success(f"Saved. ‘{model_name}’ × ‘{pid}’ is now pending review "
                   f"(weighted {preview}).")


# --------------------------------------------------------------------------- #
# 2. Review / verify
# --------------------------------------------------------------------------- #
def page_review(store: EvalStore):
    st.header("Review & verify")
    st.write("The medical reviewer checks each evaluation, adjusts scores if "
             "needed, and marks it **verified**.")

    df = store.read_all()
    if df.empty:
        st.info("No evaluations yet.")
        return

    only_pending = st.toggle("Show only pending review", value=True)
    view = df[df["status"] == C.STATUS_PENDING] if only_pending else df
    if view.empty:
        st.success("Nothing pending — all caught up.")
        return

    def _lbl(r):
        ver = f" ({r['model_version']})" if str(r.get("model_version") or "").strip() not in ("", "nan") else ""
        tag = "🟡" if r["status"] == C.STATUS_PENDING else "✅"
        return f"{tag} {r['model_name']}{ver} · {r['prompt_id']}"

    options = {_lbl(r): r["eval_id"] for r in view.to_dict("records")}
    pick = st.selectbox("Evaluation", list(options.keys()))
    eid = options[pick]
    row = store.get(eid)

    st.divider()
    row_lang = row.get("language") or C.LANGUAGE_DEFAULT
    lang_label = C.LANGUAGES.get(row_lang, row_lang.upper())
    st.markdown(f"**Model:** {row['model_name']} · **Category:** {row['category']} "
                f"· **Prompt:** {row['prompt_id']} ({row['prompt_domain']}) · **Language:** {lang_label}")
    st.markdown(f"> {row['prompt_text']}")
    prompt = prompt_by_id(row["prompt_id"])
    if prompt:
        kp_key = "expected_key_points_de" if row_lang == "de" else "expected_key_points"
        with st.expander("Answer anchor"):
            for kp in prompt.get(kp_key, []):
                st.markdown(f"- {kp}")

    st.subheader("Model output")
    st.text_area("Model output", value=_s(row.get("llm_output")), height=220, disabled=True,
                 label_visibility="collapsed")

    # evaluator's scores for reference
    ev_pretty = ", ".join(
        f"{C.CRITERIA_BY_KEY[k]['label']}: {row.get('ev_'+k)}" for k in C.CRITERIA_KEYS
    )
    st.caption(f"**Evaluator** ({row.get('evaluator_name')}): {ev_pretty} · "
               f"safety: {row.get('ev_safety')}")
    if _s(row.get("ev_comment")).strip():
        st.caption(f"Evaluator comment: {row['ev_comment']}")

    with st.form("review_form"):
        st.subheader("Reviewer scores")
        st.caption("Pre-filled with the evaluator's scores — adjust where you disagree.")
        defaults = {}
        for k in C.CRITERIA_KEYS:
            rv, ev = row.get(f"rv_{k}"), row.get(f"ev_{k}")
            base = rv if S._is_num(rv) else ev
            defaults[k] = int(base) if S._is_num(base) else None
        scores = {c["key"]: _score_select("rev", c, defaults[c["key"]]) for c in C.CRITERIA}

        cur_safety = row.get("rv_safety") or row.get("ev_safety") or C.SAFETY_DEFAULT
        safety = st.selectbox(
            "Safety flag",
            C.SAFETY_KEYS,
            index=C.SAFETY_KEYS.index(cur_safety) if cur_safety in C.SAFETY_KEYS else 0,
            format_func=lambda k: C.SAFETY_LEVELS[k]["label"],
        )
        reviewer_name = st.text_input("Reviewer name", value=_s(row.get("reviewer_name")))
        rv_comment = st.text_area("Reviewer comment", value=_s(row.get("rv_comment")), height=70)

        ev_w = S.weighted_score({**{k: row.get("ev_"+k) for k in C.CRITERIA_KEYS},
                                 "safety": row.get("ev_safety")})
        rv_w = S.weighted_score({**scores, "safety": safety})
        c1, c2 = st.columns(2)
        c1.metric("Evaluator weighted", "—" if ev_w is None else ev_w)
        c2.metric("Verified weighted", "—" if rv_w is None else rv_w,
                  delta=None if (ev_w is None or rv_w is None) else round(rv_w - ev_w, 2))

        col_a, col_b = st.columns(2)
        save_only = col_a.form_submit_button("Save changes (keep pending)")
        verify = col_b.form_submit_button("Save & mark verified ✅", type="primary")

    if save_only or verify:
        if any(scores[k] is None for k in C.CRITERIA_KEYS):
            st.error("Please set all criterion scores before saving.")
            return
        if verify and not reviewer_name.strip():
            st.error("Reviewer name is required to verify.")
            return
        changes = {f"rv_{k}": scores[k] for k in C.CRITERIA_KEYS}
        changes.update(
            rv_safety=safety,
            rv_comment=rv_comment.strip(),
            reviewer_name=reviewer_name.strip(),
            timestamp_updated=now_iso(),
        )
        if verify:
            changes["status"] = C.STATUS_VERIFIED
            changes["timestamp_verified"] = now_iso()
        store.update(eid, changes)
        st.success("Verified ✅" if verify else "Changes saved (still pending).")
        st.rerun()


# --------------------------------------------------------------------------- #
# 3. Results
# --------------------------------------------------------------------------- #
def page_results(store: EvalStore):
    st.header("Results")
    df = store.read_all()
    if df.empty:
        st.info("No evaluations yet.")
        return

    verified_only = st.toggle("Use verified scores only", value=False,
                              help="Off: include pending evaluations using the evaluator's scores.")
    ms = S.model_summary(df, verified_only=verified_only)
    if ms.empty:
        st.warning("No evaluations match the current filter.")
        return

    n_prompts = len(load_prompts())

    # category headline
    st.subheader("Best per category")
    cat = S.category_summary(ms)
    cols = st.columns(len(cat))
    for col, r in zip(cols, cat.to_dict("records")):
        col.metric(f"{r['category']} — best", r["best_model"],
                   help=f"score {r['best_score']} · category mean {r['category_mean']} "
                        f"· {r['n_models']} model(s)")

    # overall ranking chart
    st.subheader("Overall ranking")
    try:
        import plotly.express as px
        fig = px.bar(ms.sort_values("mean_weighted"), x="mean_weighted", y="model",
                     color="category", orientation="h",
                     category_orders={"category": C.CATEGORY_KEYS},
                     labels={"mean_weighted": "Mean weighted score", "model": ""},
                     range_x=[0, C.SCALE_MAX])
        fig.update_layout(height=80 + 32 * len(ms), margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig, width='stretch')
    except Exception:
        st.bar_chart(ms.set_index("model")["mean_weighted"])

    # coverage warning
    incomplete = ms[ms["n_prompts"] < n_prompts]
    if not incomplete.empty:
        st.caption("⚠️ Incomplete coverage (fewer than "
                   f"{n_prompts} prompts evaluated): "
                   + ", ".join(f"{r['model']} ({r['n_prompts']}/{n_prompts})"
                               for r in incomplete.to_dict("records")))

    # language comparison
    st.subheader("Language comparison (EN vs DE)")
    has_lang_col = "language" in df.columns
    has_de = has_lang_col and (df["language"] == "de").any()
    has_en = has_lang_col and (df["language"].fillna("en") == "en").any()

    if has_de and has_en:
        df_en = df[df["language"].fillna("en") == "en"]
        df_de = df[df["language"] == "de"]
        ms_en = S.model_summary(df_en, verified_only=verified_only)
        ms_de = S.model_summary(df_de, verified_only=verified_only)

        cmp = ms[["model", "category", "mean_weighted"]].rename(
            columns={"mean_weighted": "combined_mean"}
        ).copy()
        if not ms_en.empty:
            cmp = cmp.merge(
                ms_en[["model", "mean_weighted", "n_prompts"]].rename(
                    columns={"mean_weighted": "en_mean", "n_prompts": "en_n_prompts"}),
                on="model", how="left",
            )
        if not ms_de.empty:
            cmp = cmp.merge(
                ms_de[["model", "mean_weighted", "n_prompts"]].rename(
                    columns={"mean_weighted": "de_mean", "n_prompts": "de_n_prompts"}),
                on="model", how="left",
            )
        if "en_mean" in cmp.columns and "de_mean" in cmp.columns:
            cmp["delta_en_minus_de"] = (cmp["en_mean"] - cmp["de_mean"]).round(3)

        st.dataframe(cmp, width='stretch', hide_index=True)

        try:
            import plotly.express as px
            import plotly.graph_objects as go

            fig_lang = go.Figure()
            fig_lang.add_trace(go.Bar(
                name="English",
                y=cmp["model"], x=cmp.get("en_mean"),
                orientation="h", offsetgroup=0,
            ))
            fig_lang.add_trace(go.Bar(
                name="Deutsch",
                y=cmp["model"], x=cmp.get("de_mean"),
                orientation="h", offsetgroup=1,
            ))
            fig_lang.update_layout(
                barmode="group",
                xaxis=dict(title="Mean weighted score", range=[0, C.SCALE_MAX]),
                height=80 + 52 * len(cmp),
                margin=dict(l=0, r=0, t=10, b=0),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            )
            st.plotly_chart(fig_lang, width='stretch')
        except Exception:
            pass
    elif has_de and not has_en:
        st.info("Only German evaluations so far — add English evaluations to enable the comparison.")
    elif has_en and not has_de:
        st.info("Only English evaluations so far — add German evaluations to enable the comparison.")
    else:
        st.info("Add evaluations in both languages to enable the comparison.")

    # detailed table
    st.subheader("Per-model detail")
    show = ms.copy()
    show.columns = [c.replace("mean_", "") for c in show.columns]
    st.dataframe(show, width='stretch', hide_index=True)

    # per-criterion heatmap
    st.subheader("Per-criterion profile")
    try:
        import plotly.express as px
        hm = ms.set_index("model")[[f"mean_{k}" for k in C.CRITERIA_KEYS]]
        hm.columns = [C.CRITERIA_BY_KEY[k]["label"] for k in C.CRITERIA_KEYS]
        fig2 = px.imshow(hm, text_auto=".1f", aspect="auto",
                         color_continuous_scale="RdYlGn", zmin=C.SCALE_MIN, zmax=C.SCALE_MAX)
        fig2.update_layout(height=80 + 34 * len(ms), margin=dict(l=0, r=0, t=10, b=0),
                           coloraxis_showscale=False)
        st.plotly_chart(fig2, width='stretch')
    except Exception:
        st.dataframe(ms.set_index("model")[[f"mean_{k}" for k in C.CRITERIA_KEYS]])

    # downloads
    st.subheader("Export")
    c1, c2 = st.columns(2)
    c1.download_button("Model summary (CSV)", ms.to_csv(index=False).encode(),
                       "model_summary.csv", "text/csv")
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        S.enrich(df).to_excel(xw, index=False, sheet_name="evaluations")
        ms.to_excel(xw, index=False, sheet_name="model_summary")
    c2.download_button("Full export (Excel)", buf.getvalue(),
                       "llm_eval_export.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
