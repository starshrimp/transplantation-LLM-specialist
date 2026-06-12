"""
Transplantation-Medicine LLM Evaluation
=======================================

Run locally:        streamlit run app.py
Storage backend:    set in .streamlit/secrets.toml (default = local Excel)
"""
import streamlit as st

from storage import make_store_from_secrets
import views


@st.cache_resource
def get_store():
    return make_store_from_secrets(st.secrets)


def main():
    st.set_page_config(page_title="Transplant LLM Eval", page_icon="🫀", layout="wide")
    store = get_store()

    with st.sidebar:
        st.title("🫀 Transplant LLM Eval")
        page = st.radio(
            "Section",
            ["Add evaluation", "Review & verify", "Results"],
            label_visibility="collapsed",
        )
        st.divider()
        st.caption(f"Storage: **{store.backend_name}**")
        try:
            n = len(store.read_all())
            st.caption(f"{n} evaluation(s) recorded")
        except Exception as e:
            st.error(f"Storage error: {e}")
        if st.button("↻ Refresh data"):
            st.cache_resource.clear()
            st.rerun()

    if page == "Add evaluation":
        views.page_add(store)
    elif page == "Review & verify":
        views.page_review(store)
    else:
        views.page_results(store)


if __name__ == "__main__":
    main()
