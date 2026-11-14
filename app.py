"""Veritas: Streamlit UI.  Run: streamlit run app.py"""

from __future__ import annotations

import html

import streamlit as st

from veritas import cache
from veritas.llm import MODEL
from veritas.schema import VERDICTS, Report

DEMO = (
    "Tesla's revenue increased by 40% last year. The company is headquartered in Texas. "
    "Analysts expect its stock price to double next year."
)

STYLE = {  # verdict -> (streamlit colour, hex, icon)
    "supported": ("green", "#1a7f37", "✅"),
    "contradicted": ("red", "#cf222e", "❌"),
    "misleading": ("orange", "#bf8700", "⚠️"),
    "insufficient": ("gray", "#6e7781", "❔"),
    "not_verifiable": ("gray", "#6e7781", "💭"),
    None: ("gray", "#6e7781", "⏳"),
}

st.set_page_config(page_title="Veritas", page_icon="🔎", layout="wide")


def md(s: str) -> str:
    """Escape text for Streamlit markdown ($ would otherwise start LaTeX)."""
    return s.replace("\\", "\\\\").replace("$", "\\$").replace("*", "\\*").replace("_", "\\_")


def summary_bar(report: Report) -> None:
    counts = {v: sum(c.verdict == v for c in report.claims) for v in VERDICTS}
    cells = "".join(
        f"<div style='flex:1;min-width:110px;border-top:4px solid {STYLE[v][1]};padding:6px 10px;"
        f"background:rgba(127,127,127,.07);border-radius:4px'>"
        f"<div style='font-size:1.6rem;font-weight:700'>{n}</div>"
        f"<div style='font-size:.8rem;opacity:.8'>{STYLE[v][2]} {v.replace('_', ' ')}</div></div>"
        for v, n in counts.items()
    )
    st.markdown(f"<div style='display:flex;gap:8px;flex-wrap:wrap'>{cells}</div>", unsafe_allow_html=True)


def claim_card(i: int, c) -> None:
    colour, hexc, icon = STYLE[c.verdict]
    label = f"{icon} :{colour}[**{(c.verdict or 'pending').upper().replace('_', ' ')}**] — {md(c.text)}"
    with st.expander(label, expanded=c.verdict in ("contradicted", "misleading")):
        st.markdown(
            f"<div style='border-left:4px solid {hexc};padding:2px 10px;margin-bottom:8px'>"
            f"<small>kind: <b>{c.kind}</b></small><br>{html.escape(c.explanation)}</div>",
            unsafe_allow_html=True,
        )
        if c.evidence:
            st.markdown("**Evidence**")
            for ev in c.evidence:
                mark = "✓" if ev.quote_verified else "✗ unverified"
                st.markdown(
                    f"- {mark} *{ev.stance}*: “{md(ev.quote)}”  \n  [{md(ev.title or ev.url)}]({ev.url})"
                )
        elif c.kind == "factual":
            st.caption("No verified evidence quotes.")
        if c.trace:
            st.markdown("**Agent trace**")
            for n, s in enumerate(c.trace, 1):
                st.markdown(f"{n}. 🔎 `{s.query}`  \n{md(s.finding)}  \n→ _{md(s.next_action)}_")


def show(report: Report) -> None:
    summary_bar(report)
    st.write("")
    for i, c in enumerate(report.claims):
        claim_card(i, c)


# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.header("Veritas")
    st.caption(f"Model: `{MODEL}` · search: Linkup")
    from_cache = st.toggle("Load results from cache (offline demo)", value=False)
    cached = cache.list_cached() if from_cache else []
    picked = None
    if from_cache:
        if cached:
            opts = {f"{r.input_text[:60]}… ({r.pub_date or 'no date'})": r for r in cached}
            picked = opts[st.selectbox("Cached runs", list(opts))]
        else:
            st.info("No cached runs yet. Run a verification online first.")

# ---------------------------------------------------------------- main
st.title("🔎 Veritas")
st.caption("Paste a news excerpt, a financial claim or an AI answer. Every quote shown is checked against the source text.")

text = st.text_area("Text to fact-check", value=picked.input_text if picked else DEMO, height=140)
col1, col2 = st.columns([1, 3])
pub = col1.date_input("Publication date (optional)", value=None, format="YYYY-MM-DD")
pub_date = pub.isoformat() if pub else None
go = col2.button("Verify", type="primary", disabled=not text.strip())

if from_cache and picked and not go:
    show(picked)
elif go:
    hit = cache.get(text, pub_date) if from_cache else None
    if hit:
        st.success("Loaded from cache.")
        show(hit)
    else:
        from veritas.pipeline import run

        with st.status("Extracting claims…", expanded=True) as status:
            state = {"total": 0, "done": 0}
            bar = st.progress(0.0)

            def on_progress(event, payload):
                if event == "extracted":
                    state["total"] = len(payload)
                    st.write(f"Found {len(payload)} claim(s):")
                    for c in payload:
                        st.write(f"• [{c.kind}] {c.text}")
                    status.update(label=f"Investigating {len(payload)} claim(s)…")
                else:
                    i, c = payload
                    state["done"] += 1
                    bar.progress(state["done"] / max(1, state["total"]))
                    st.write(f"{STYLE[c.verdict][2]} {c.verdict}: {c.text}")

            try:
                report = run(text, pub_date, on_progress=on_progress)
                status.update(label="Done", state="complete", expanded=False)
            except Exception as e:
                status.update(label="Failed", state="error")
                st.error(f"{type(e).__name__}: {e}")
                st.stop()
        show(report)
