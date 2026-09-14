"""IndianLawGPT POC UI. Run with: streamlit run app.py"""
from dotenv import load_dotenv
load_dotenv()

import streamlit as st
from rag_chain import answer_question
from db import get_connection
import instrumentation

st.set_page_config(page_title="IndianLawGPT POC", page_icon="⚖️", layout="centered")

st.markdown("""
<style>
    .block-container { padding-top: 2rem; padding-bottom: 2rem; }
    div.stButton > button { border-radius: 6px; font-weight: 500; }
</style>
""", unsafe_allow_html=True)

st.title("⚖️ IndianLawGPT – Legal Research (POC)")
st.caption("Retrieval-augmented Q&A over ingested case law and legal PDFs.")
st.info("Citations shown as 'Verified' are checked against this app's local database "
        "of ingested documents — not the whole of Indian law. 'Unverified' may mean the "
        "citation was fabricated, or it may be a real source outside this small sample.")

query = st.text_area("Ask a legal question:", height=100,
                      placeholder="e.g. If a demand notice is returned undelivered, is the complaint still valid?")

ask = st.button("Ask", type="primary")

if ask and query.strip():
    instrumentation.reset()
    instrumentation.start("Total end-to-end")
    instrumentation.log("1", "REQUEST START")
    instrumentation.log("1", f"Question received: {query}")
    
    with st.spinner("Retrieving relevant judgments and generating answer..."):
        instrumentation.log("2", "Calling answer_question()")
        instrumentation.start("answer_question")
        result = answer_question(query)
        dur_aq = instrumentation.end("answer_question")
        instrumentation.log("2", "answer_question() returned")
        instrumentation.log("2", f"Duration: {dur_aq:.3f} sec")
        
        instrumentation.log("16", f"answer_question TOTAL: {dur_aq:.3f} sec")
        instrumentation.log("16", f"API calls made: {instrumentation.api_calls}")
        instrumentation.log("16", "REQUEST END")

    instrumentation.log("17", "Streamlit rendering START")
    instrumentation.start("Streamlit rendering")
    
    st.markdown("### Answer")
    import re
    # Remove ONLY the exact citation token pattern [SOURCE: <doc_id>]
    displayed_answer = re.sub(r"\[SOURCE:\s*[A-Za-z0-9_\-\.]+\]", "", result["clean_answer"])
    # Clean up stranded 'and' left over from multiple citations
    displayed_answer = re.sub(r"\s+and\s+(?=\s|$|\.)", " ", displayed_answer)
    displayed_answer = displayed_answer.replace("  ", " ").strip()

    st.write(displayed_answer)
    st.markdown("---")

    if result["verified"]:
        st.markdown("### Sources")
        for c in result["verified"]:
            if c.get("source_type") == "pdf":
                location = c.get("file_name") or "PDF document"
            elif c.get("source_type") == "statute":
                location = f"Act, enacted {c.get('date')}" if c.get("date") else "Act (enactment date unknown)"
            else:
                location = f"{c.get('court') or 'Unknown Court'} — {c.get('date') or 'Unknown Date'}"
            st.markdown(f"**✓ {c['title']}**\n\n&nbsp;&nbsp;&nbsp;&nbsp;{location}")

    if result["unverified"]:
        st.markdown("### ⚠️ Unverified citations")
        for did in result["unverified"]:
            st.markdown(f"&nbsp;&nbsp;&nbsp;&nbsp;{did}")

    badge = "🟢" if not result["unverified"] else "🔴"
    st.markdown(f"**{badge} Citation check:** {result['accuracy_note']}")

    with st.expander("Retrieved chunks used for this answer"):
        for rc in result["retrieved_documents"]:
            st.markdown(f"- {rc['title']} (`{rc['doc_id']}`) — via {rc['source']} search")

    dur_rend = instrumentation.end("Streamlit rendering")
    instrumentation.log("17", f"Streamlit rendering END: {dur_rend:.3f} sec")
    instrumentation.end("Total end-to-end")
    instrumentation.print_summary()
    instrumentation.print_model_summary()
    
    st.markdown("---")
    fcol1, fcol2 = st.columns(2)
    if fcol1.button("👍 Good answer"):
        conn = get_connection()
        conn.execute("INSERT INTO feedback (query, answer, rating) VALUES (?, ?, ?)",
                      (query, result["clean_answer"], "up"))
        conn.commit()
        conn.close()
        st.success("Thanks — feedback logged.")
    if fcol2.button("👎 Needs work"):
        conn = get_connection()
        conn.execute("INSERT INTO feedback (query, answer, rating) VALUES (?, ?, ?)",
                      (query, result["clean_answer"], "down"))
        conn.commit()
        conn.close()
        st.info("Thanks — feedback logged.")