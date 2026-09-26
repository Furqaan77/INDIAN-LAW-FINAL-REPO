#!/usr/bin/env python3
"""
Generates slides.html (all 1920x1080 scene frames) and timeline.json for the
IndianLawGPT explainer video.

Design system is taken from the product itself: the app's own Newsreader / Geist /
Geist Mono faces (loaded from the repo's node_modules) and its oxblood accent,
verify-green, caution-amber and statute-slate data colours.

Every figure on these slides comes from the project's own reports:
  data/distill/final_readiness_report.md, data/distill/pilot_lora/summary.md,
  docs/DEMO.md and the live /api/stats endpoint.

Run:  python3 build/make_slides.py
Then: node build/shoot_slides.mjs   (renders each .slide to build/slides/*.png)
"""
import json
import os
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
FONTS = pathlib.Path("/Users/furqaanahmed/LAW LLM/LegalPOC/frontend/node_modules/@fontsource-variable")
SCREENS = ROOT / "assets" / "screens"

# --------------------------------------------------------------------------- scenes
# (start_seconds, slide_id, avatar_state)  — avatar states defined in AVATAR_STATES
SCENES = [
    (0.00,   "hero_problem",        "br_lg"),
    (8.00,   "title_card",          "br_lg"),
    (12.00,  "agenda",              "br"),
    (18.00,  "goal",                "br"),
    (28.00,  "not_chatbot",         "br"),
    (33.00,  "research_requires",   "br"),
    (43.00,  "core_principle",      "br"),
    (50.00,  "foreshadow_models",   "br"),
    (57.00,  "four_components",     "br"),
    (67.00,  "shot_home",           "br"),
    (76.00,  "corpus_a",            "bl"),
    (90.00,  "corpus_b",            "bl"),
    (99.00,  "corpus_indexed",      "br"),
    (105.00, "coverage",            "br"),
    (114.00, "coverage_caveat",     "br"),
    (121.00, "search_gap",          "br"),
    (129.00, "search_needs",        "br"),
    (138.00, "hybrid_paths",        "br"),
    (149.00, "rrf_fusion",          "br"),
    (160.00, "retrieval_why",       "br"),
    (166.00, "retrieval_result",    "bl"),
    (174.00, "retrieval_caveat",    "bl"),
    (178.00, "citation_risk",       "br"),
    (189.00, "verify_flow",         "br"),
    (201.00, "verify_match",        "br"),
    (208.00, "verify_docid",        "br"),
    (215.00, "verify_inspect",      "br"),
    (221.00, "verify_caveat",       "br"),
    (230.00, "tech_stack",          "br"),
    (237.00, "shot_progress",       "br"),
    (243.00, "shot_answer",         "bl"),
    (246.50, "shot_evidence",       "bl"),
    (250.00, "shot_reader",         "br"),
    (256.00, "shot_lawmap",         "br"),
    (263.00, "shot_history",        "br"),
    (268.16, "explore_why",         "br"),
    (276.96, "finetune_question",   "br"),
    (288.00, "rag_vs_ft",           "br"),
    (304.64, "test_not_assume",     "br"),
    (312.72, "dataset_pipeline",    "br"),
    (327.36, "reviewer_gates",      "br"),
    (338.80, "example_statuses",    "br"),
    (343.20, "qc_why",              "br"),
    (351.36, "lora_setup",          "br"),
    (364.88, "three_engine_test",   "br"),
    (375.84, "identical_evidence",  "br"),
    (383.52, "metrics_measured",    "br"),
    (396.32, "results_mixed",       "br"),
    (400.00, "chart_citation",      "bl"),
    (413.44, "chart_correctness",   "bl"),
    (422.88, "malformed",           "br"),
    (427.84, "blended_caveat",      "br"),
    (441.04, "lesson_format",       "br"),
    (446.80, "engines_integrated",  "br"),
    (455.52, "evidence_frozen",     "br"),
    (465.44, "shot_three_engines",  "br"),
    (476.72, "why_compare_env",     "br"),
    (485.20, "still_experimental",  "br"),
    (492.72, "demo_panels",         "br"),
    (505.04, "curated_questions",   "br"),
    (520.56, "tested_shipped",      "br"),
    (533.84, "status_intro",        "br"),
    (536.55, "status_live",         "bl"),
    (551.47, "status_paused",       "bl"),
    (566.75, "status_hosting",      "bl"),
    (579.03, "demo_not_prod",       "br"),
    (581.71, "recap",               "br"),
    (596.03, "lesson_tradeoff",     "br"),
    (607.47, "next_steps",          "br"),
    (616.00, "goal_philosophy",     "br"),
    (625.79, "closing",             "br_lg"),
    (635.20, "thank_you",           "br_lg"),
]
END = 638.20  # narration ends ~636.7s; hold the final frame briefly

AVATAR_STATES = {
    "br":    dict(size=380, x=1920-380-70,  y=1080-380-70),
    "br_sm": dict(size=300, x=1920-300-60,  y=1080-300-60),
    "br_lg": dict(size=470, x=1920-470-90,  y=1080-470-90),
    "bl":    dict(size=380, x=70,           y=1080-380-70),
    "bl_sm": dict(size=300, x=60,           y=1080-300-60),
}

# --------------------------------------------------------------------------- css
CSS = """
@font-face{font-family:'Newsreader';src:url('FONTS/newsreader/files/newsreader-latin-wght-normal.woff2')format('woff2-variations');font-weight:200 800;font-style:normal;}
@font-face{font-family:'Newsreader';src:url('FONTS/newsreader/files/newsreader-latin-wght-italic.woff2')format('woff2-variations');font-weight:200 800;font-style:italic;}
@font-face{font-family:'Geist';src:url('FONTS/geist/files/geist-latin-wght-normal.woff2')format('woff2-variations');font-weight:100 900;}
@font-face{font-family:'GeistMono';src:url('FONTS/geist-mono/files/geist-mono-latin-wght-normal.woff2')format('woff2-variations');font-weight:100 900;}

*{box-sizing:border-box;margin:0;padding:0;}
body{background:#000;}
.slide{
  position:relative;width:1920px;height:1080px;overflow:hidden;
  background:
    radial-gradient(1200px 780px at 18% 12%, #23201a 0%, rgba(35,32,26,0) 62%),
    radial-gradient(1000px 900px at 92% 88%, #241b18 0%, rgba(36,27,24,0) 60%),
    linear-gradient(160deg,#131210 0%,#17150f 55%,#121110 100%);
  color:#efe9db;font-family:'Geist',system-ui,sans-serif;
  padding:96px 110px;display:flex;flex-direction:column;
}
.slide::after{ /* fine grain so large flats don't band on compression */
  content:"";position:absolute;inset:0;pointer-events:none;opacity:.035;
  background-image:repeating-linear-gradient(0deg,#fff 0 1px,transparent 1px 3px);
}
.slide.light{
  background:
    radial-gradient(1100px 760px at 20% 10%, #fffdf7 0%, rgba(255,253,247,0) 60%),
    linear-gradient(160deg,#f4f1e9 0%,#efeade 100%);
  color:#1a1814;
}
.slide.light .eyebrow{color:#7d2e24;}
.slide.light .rule{background:#d9d2c0;}
.slide.light .sub{color:#4b473e;}
.slide.light .card{background:#fffdf8;border-color:#ded6c4;}
.slide.light .mono-note{color:#6b6558;}

.eyebrow{font-family:'GeistMono',monospace;font-size:24px;letter-spacing:.18em;
  text-transform:uppercase;color:#e2917d;font-weight:600;}
h1{font-family:'Newsreader',serif;font-weight:500;font-size:112px;line-height:1.02;
  letter-spacing:-.022em;text-wrap:balance;}
h1.sm{font-size:86px;}
h1.xl{font-size:132px;}
h2{font-family:'Newsreader',serif;font-weight:500;font-size:74px;line-height:1.08;
  letter-spacing:-.018em;text-wrap:balance;}
.sub{font-size:34px;line-height:1.5;color:#b9b1a1;max-width:1180px;font-weight:350;}
.sub.narrow{max-width:900px;}
.rule{height:2px;background:#3a3429;width:180px;}
.mono-note{font-family:'GeistMono',monospace;font-size:20px;color:#8d8578;letter-spacing:.02em;}
.spacer{flex:1;}
.safe{padding-right:520px;}      /* keep bottom-right avatar clear */
.diagram{max-width:1330px;}
.safe-l{padding-left:500px;flex:1;display:flex;flex-direction:column;justify-content:center;}
.accent{color:#e2917d;}
.green{color:#92c19e;}
.amber{color:#e1b562;}
.slate{color:#a2bad8;}

/* ---- generic blocks ---- */
.card{background:rgba(255,255,255,.045);border:1px solid rgba(255,255,255,.1);
  border-radius:18px;padding:30px 34px;}
.stack{display:flex;flex-direction:column;gap:22px;}
.row{display:flex;gap:24px;}
.chips{display:flex;flex-wrap:wrap;gap:16px;}
.chip{font-family:'GeistMono',monospace;font-size:26px;padding:14px 24px;border-radius:999px;
  border:1px solid rgba(226,145,125,.45);background:rgba(226,145,125,.1);color:#f0c3b4;}

/* bullets */
ul.big{list-style:none;display:flex;flex-direction:column;gap:26px;}
ul.big li{font-size:40px;line-height:1.35;display:flex;gap:26px;align-items:flex-start;color:#e6dfd0;}
ul.big li .bullet{width:14px;height:14px;border-radius:50%;background:#e2917d;margin-top:18px;flex:none;}
ul.big li.dim{color:#8d8578;}

/* stats */
.stats{display:flex;gap:26px;flex-wrap:wrap;}
.stat{background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.1);
  border-radius:20px;padding:32px 34px;min-width:300px;}
.stat .v{font-family:'GeistMono',monospace;font-size:92px;font-weight:600;line-height:1;
  font-variant-numeric:tabular-nums;color:#fff;}
.stat .v.sm{font-size:64px;}
.stat .l{font-size:24px;color:#a89f90;margin-top:14px;line-height:1.3;}

/* flow diagram */
.flow{display:flex;align-items:center;gap:20px;flex-wrap:wrap;}
.node{border:1px solid rgba(255,255,255,.16);background:rgba(255,255,255,.055);
  border-radius:18px;padding:28px 32px;min-width:200px;}
.node .t{font-size:30px;font-weight:500;color:#f0ebdf;line-height:1.22;}
.node .d{font-family:'GeistMono',monospace;font-size:19px;color:#8d8578;margin-top:10px;}
.node.hot{border-color:rgba(226,145,125,.6);background:rgba(226,145,125,.13);}
.node.ok{border-color:rgba(146,193,158,.55);background:rgba(146,193,158,.12);}
.arrow{color:#6b6353;font-size:40px;}

/* bars */
.bars{display:flex;flex-direction:column;gap:30px;max-width:1150px;}
.bar-row{display:grid;grid-template-columns:330px 1fr 170px;align-items:center;gap:26px;}
.bar-lab{font-size:33px;color:#cdc5b5;}
.bar-track{height:60px;background:rgba(255,255,255,.07);border-radius:10px;overflow:hidden;}
.bar-fill{height:100%;border-radius:10px;}
.bar-val{font-family:'GeistMono',monospace;font-size:34px;text-align:right;font-variant-numeric:tabular-nums;}

/* screenshot frames */
.shot-wrap{flex:1;display:flex;align-items:stretch;justify-content:flex-start;min-height:0;}
.shot{border-radius:16px;overflow:hidden;border:1px solid rgba(255,255,255,.16);
  box-shadow:0 40px 90px rgba(0,0,0,.55);background:#0e0d0b;}
.shot img{display:block;height:100%;width:auto;}
h2.shot-title{font-size:62px;}
.callout{position:absolute;border:3px solid #e2917d;border-radius:12px;
  box-shadow:0 0 0 6px rgba(226,145,125,.18);}
.tagline{position:absolute;font-family:'GeistMono',monospace;font-size:22px;
  background:#e2917d;color:#1a120f;padding:10px 18px;border-radius:9px;font-weight:600;}

/* status board */
.status{display:flex;flex-direction:column;gap:18px;max-width:1240px;}
.st{display:grid;grid-template-columns:38px 1fr;gap:22px;align-items:start;
  border-bottom:1px solid rgba(255,255,255,.09);padding-bottom:16px;}
.st .dot{width:20px;height:20px;border-radius:50%;margin-top:12px;}
.st .txt{font-size:32px;line-height:1.35;color:#ded7c8;}
.st .sm{display:block;font-size:22px;color:#8d8578;margin-top:6px;font-family:'GeistMono',monospace;}

/* two column compare */
.cols{display:grid;grid-template-columns:1fr 1fr;gap:34px;}
.col{border:1px solid rgba(255,255,255,.12);border-radius:22px;padding:42px 44px;background:rgba(255,255,255,.04);}
.col h3{font-family:'Newsreader',serif;font-size:58px;font-weight:500;margin-bottom:20px;}
.col p{font-size:32px;line-height:1.45;color:#bcb4a4;}

/* quote match visual */
.quote{font-family:'Newsreader',serif;font-size:31px;line-height:1.5;font-style:italic;color:#e8e1d2;}
.matchbox{border-radius:16px;padding:26px 30px;border:2px solid;}
.matchbox.ok{border-color:rgba(146,193,158,.6);background:rgba(146,193,158,.1);}
.matchbox.bad{border-color:rgba(226,145,125,.55);background:rgba(226,145,125,.1);}
.mtag{font-family:'GeistMono',monospace;font-size:21px;letter-spacing:.06em;margin-bottom:12px;}

/* ---------------- motion (seeked frame-by-frame by shoot_slides.mjs) ---------------- */
.w{display:inline-block;}
.struck{position:relative;display:inline-block;opacity:.8;}
.strikeline{position:absolute;left:-4px;right:-4px;top:54%;height:4px;border-radius:2px;
  background:#e2917d;transform-origin:left center;}
.bar-fill{transform-origin:left center;}
.shot img{transform-origin:28% 18%;}
@keyframes rise{from{opacity:0;transform:translateY(30px)}to{opacity:1;transform:none}}
@keyframes pop{from{opacity:0;transform:translateY(18px) scale(.93)}to{opacity:1;transform:none}}
@keyframes slideR{from{opacity:0;transform:translateX(-38px)}to{opacity:1;transform:none}}
@keyframes wordIn{from{opacity:0;transform:translateY(.34em);filter:blur(10px)}to{opacity:1;transform:none;filter:blur(0)}}
@keyframes charIn{from{opacity:0;transform:translateY(.5em) scale(.9);filter:blur(12px)}to{opacity:1;transform:none;filter:blur(0)}}
@keyframes arrowIn{from{opacity:0;transform:translateX(-16px)}to{opacity:1;transform:none}}
@keyframes shotIn{from{opacity:0;transform:translateY(60px) scale(.965)}to{opacity:1;transform:none}}
@keyframes barGrow{from{transform:scaleX(0)}to{transform:scaleX(1)}}
@keyframes push{from{transform:scale(1)}to{transform:scale(1.055)}}
@keyframes strike{from{transform:scaleX(0)}to{transform:scaleX(1)}}
@keyframes ringPulse{0%{box-shadow:0 0 0 0 rgba(146,193,158,.0)}40%{box-shadow:0 0 0 10px rgba(146,193,158,.28)}100%{box-shadow:0 0 0 0 rgba(146,193,158,0)}}
"""


# --------------------------------------------------------------------------- helpers
def shot_img(name, width=None, max_h=None):
    """Real app screenshot, scaled to fill the height left under the heading (optionally capped)."""
    p = SCREENS / f"{name}.png"
    if not p.exists():
        return f'<div class="shot" style="width:900px;display:flex;align-items:center;justify-content:center;color:#6b6456;font-family:GeistMono">screenshot missing: {name}</div>'
    cap = f' style="max-height:{max_h}px"' if max_h else ""
    return f'<div class="shot"{cap}><img src="{p.as_uri()}"></div>'


def shot_head(eyebrow, title):
    return f'<p class="eyebrow">{eyebrow}</p><h2 class="shot-title" style="margin-top:12px">{title}</h2>'


def head(eyebrow, title, sub=None, cls="", title_cls=""):
    h = f'<p class="eyebrow">{eyebrow}</p><h1 class="{title_cls}">{title}</h1>'
    if sub:
        h += f'<p class="sub" style="margin-top:22px">{sub}</p>'
    return h


def bullets(items):
    li = "".join(
        f'<li class="{"dim" if isinstance(i, tuple) else ""}"><span class="bullet"></span><span>{i[0] if isinstance(i, tuple) else i}</span></li>'
        for i in items
    )
    return f'<ul class="big">{li}</ul>'


def stats(items, small=False):
    s = "".join(
        f'<div class="stat"><div class="v {"sm" if small else ""}">{v}</div><div class="l">{l}</div></div>'
        for v, l in items
    )
    return f'<div class="stats">{s}</div>'


def flow(nodes):
    parts = []
    for i, n in enumerate(nodes):
        if i:
            parts.append('<span class="arrow">→</span>')
        cls = n[2] if len(n) > 2 else ""
        parts.append(f'<div class="node {cls}"><div class="t">{n[0]}</div><div class="d">{n[1]}</div></div>')
    return f'<div class="flow">{"".join(parts)}</div>'


def bars(rows, maxv=50):
    out = []
    for lab, val, color, txt in rows:
        pct = max(1.5, val / maxv * 100)
        out.append(
            f'<div class="bar-row"><div class="bar-lab">{lab}</div>'
            f'<div class="bar-track"><div class="bar-fill" style="width:{pct:.1f}%;background:{color}"></div></div>'
            f'<div class="bar-val" style="color:{color}">{txt}</div></div>'
        )
    return f'<div class="bars">{"".join(out)}</div>'


def status_rows(rows):
    out = []
    for color, txt, note in rows:
        n = f'<span class="sm">{note}</span>' if note else ""
        out.append(f'<div class="st"><div class="dot" style="background:{color}"></div><div class="txt">{txt}{n}</div></div>')
    return f'<div class="status">{"".join(out)}</div>'


GREEN, AMBER, SLATE, OX = "#92c19e", "#e1b562", "#a2bad8", "#e2917d"

# --------------------------------------------------------------------------- slides
S = {}

S["hero_problem"] = f"""
{head("The problem", "Thousands of statutes.<br>Thousands of judgments.", "Every legal question still means searching through all of them — and trusting whatever comes back.", title_cls="")}
<div class="spacer"></div>
<div class="chips safe">
  <span class="chip">Central Acts</span><span class="chip">Sections</span><span class="chip">Judgments</span>
  <span class="chip">Amendments</span><span class="chip">Old codes → new codes</span>
</div>"""

S["title_card"] = f"""
<div class="spacer"></div>
<p class="eyebrow">Evidence-grounded legal research</p>
<h1 class="xl" style="margin-top:20px">IndianLaw<span class="accent">GPT</span></h1>
<p class="sub" style="margin-top:28px">A legal research assistant built on retrieval and deterministic citation verification.</p>
<div class="spacer"></div>
<div class="mono-note">A research prototype — not a deployed legal service</div>"""

S["agenda"] = f"""
{head("In this video", "What we built, and what we learned")}
<div class="spacer"></div>
<div class="safe">{bullets(["What we built and why", "How retrieval and citation verification work", "What we tested — and what the results showed", "Where the project stands today"])}</div>"""

S["goal"] = f"""
{head("The goal", "An assistant that answers <span class='accent'>from the documents</span>")}
<div class="spacer"></div>
<div class="diagram">{flow([("Legal question", "user asks"), ("Find relevant law", "retrieval"), ("Answer grounded in it", "generation", "ok")])}</div>
<div class="spacer"></div>"""

S["not_chatbot"] = f"""
<div class="spacer"></div>
<h1 class="sm safe">Not another chatbot that produces<br><span class="accent">convincing-sounding</span> legal answers.</h1>
<div class="spacer"></div>"""

S["research_requires"] = f"""
{head("Legal research actually requires", "Four things a chatbot doesn't do")}
<div class="spacer"></div>
<div class="safe">{bullets(["Finding the right provisions", "Identifying relevant judgments", "Connecting answers to their sources", "Checking whether the evidence supports the claim"])}</div>"""

S["core_principle"] = f"""
<div class="spacer"></div>
<p class="eyebrow">Our focus</p>
<h1 class="sm safe" style="margin-top:18px">An evidence-based research system —<br>with <span class="accent">retrieval</span> and <span class="accent">citation verification</span> at its core.</h1>
<div class="spacer"></div>"""

S["foreshadow_models"] = f"""
{head("And one experiment", "Can a smaller model, running locally, do this job?")}
<div class="spacer"></div>
<div class="diagram">{flow([("Claude", "hosted API"), ("Qwen3-1.7B", "local, base"), ("Fine-tuned Qwen", "local, experimental", "hot")])}</div>
<div class="spacer"></div>"""

S["four_components"] = f"""
{head("System", "Four components")}
<div class="spacer"></div>
<div class="diagram">{flow([("Legal document<br>collection", "the corpus"), ("Retrieval<br>system", "finds passages"), ("Answer<br>generation", "writes the answer"), ("Citation<br>verification", "checks every source", "ok")])}</div>
<div class="spacer"></div>"""

S["shot_home"] = f"""
{shot_head("And a research interface", "Ask, inspect citations, open documents, compare models")}
<div class="shot-wrap" style="margin-top:34px">{shot_img("01_home", 1180)}</div>"""

S["corpus_a"] = f"""
<div class="safe-l"><p class="eyebrow">The foundation — our legal data</p>
<h2 style="margin-top:18px">The corpus</h2>
<div style="margin-top:44px">{stats([("38,432", "documents"), ("64,651", "indexed passages")])}</div>
<p class="mono-note" style="margin-top:34px">Source: project report · live /api/stats</p></div>"""

S["corpus_b"] = f"""
<div class="safe-l"><p class="eyebrow">The corpus in detail</p>
<h2 style="margin-top:18px">What's inside</h2>
<div style="margin-top:40px">{stats([("38,238", "statutory sections"), ("832", "Central Acts"), ("194", "judgments")], small=True)}</div></div>"""

S["corpus_indexed"] = f"""
{head("Why index it", "So the system retrieves real passages —<br>not the model's general knowledge")}
<div class="spacer"></div>
<div class="diagram">{flow([("Model's memory", "unverifiable"), ("Retrieved passage", "checkable", "ok")])}</div>
<div class="spacer"></div>"""

S["coverage"] = f"""
{head("Honest about coverage", "Broad on statutes. Focused on case law.")}
<div class="spacer"></div>
<div class="cols diagram">
  <div class="col"><h3 class="slate">Statutes</h3><p>Broad coverage — 38,238 sections across 832 Central Acts.</p></div>
  <div class="col"><h3 class="amber">Case law</h3><p>Focused — 194 judgments, concentrated on Section 138 of the Negotiable Instruments Act.</p></div>
</div>
<div class="spacer"></div>"""

S["coverage_caveat"] = f"""
<div class="spacer"></div>
<h1 class="sm safe">A large collection of documents does not mean<br><span class="amber">every area of Indian law is covered.</span></h1>
<div class="spacer"></div>"""

S["search_gap"] = f"""
{head("Finding the right information", "Why plain search isn't enough")}
<div class="spacer"></div>
<div class="cols diagram">
  <div class="col"><h3>Keyword search</h3><p>Misses relevant passages when the question uses different wording.</p></div>
  <div class="col"><h3>Semantic search</h3><p>Finds similar meaning — but not exact section numbers or code mappings.</p></div>
</div>
<div class="spacer"></div>"""

S["search_needs"] = f"""
{head("Legal research also needs", "Precision, not just similarity")}
<div class="spacer"></div>
<div class="safe">{bullets(["Exact references", "Section numbers", "Connections between older and newer laws"])}</div>"""

S["hybrid_paths"] = f"""
{head("Hybrid retrieval", "Five ways to search, at the same time")}
<div class="spacer"></div>
<div class="diagram stack" style="gap:20px">
  <div class="row"><div class="node"><div class="t">Semantic search</div><div class="d">meaning-based</div></div>
  <div class="node"><div class="t">Keyword search</div><div class="d">BM25 — exact words</div></div></div>
  <div class="row"><div class="node"><div class="t">Legal-reference matching</div><div class="d">"Section 138 NI Act" → the section</div></div></div>
  <div class="row"><div class="node"><div class="t">Old-law → new-law mapping</div><div class="d">IPC ↔ BNS · CrPC ↔ BNSS</div></div>
  <div class="node"><div class="t">Case-law retrieval</div><div class="d">judgments</div></div></div>
</div>
<div class="spacer"></div>"""

S["rrf_fusion"] = f"""
{head("Reciprocal Rank Fusion", "Many searches → one ranked list")}
<div class="spacer"></div>
<div class="diagram">{flow([("5 search paths", "each ranks results"), ("Fusion", "combine the rankings"), ("One ranked<br>evidence list", "what the model sees", "ok")])}</div>
<p class="sub narrow" style="margin-top:36px">In plain terms: search several different ways, then merge the results into a single ordered list.</p>"""

S["retrieval_why"] = f"""
<div class="spacer"></div>
<h1 class="sm safe">The aim: reliably find the <span class="accent">specific sources</span><br>a legal question actually requires.</h1>
<div class="spacer"></div>"""

S["retrieval_result"] = f"""
<div class="safe-l"><p class="eyebrow">Held-out evaluation</p>
<h2 style="margin-top:16px">Retrieval result</h2>
<div style="margin-top:40px">{stats([("106/112", "required sources retrieved"), ("94.6%", "retrieval rate")])}</div></div>"""

S["retrieval_caveat"] = f"""
<div class="safe-l"><p class="eyebrow">Read this correctly</p>
<h2 style="margin-top:16px">What that number means</h2>
<div class="matchbox ok" style="margin-top:40px;max-width:1080px">
  <div class="mtag green">MEASURES</div>
  <div class="quote" style="font-style:normal">Source retrieval on <b>that evaluation set</b>.</div></div>
<div class="matchbox bad" style="margin-top:24px;max-width:1080px">
  <div class="mtag accent">DOES NOT MEASURE</div>
  <div class="quote" style="font-style:normal">The correctness of every answer.</div></div></div>"""

S["citation_risk"] = f"""
{head("The next problem", "A citation can look right and be wrong")}
<div class="spacer"></div>
<div class="safe">{bullets(["A citation that points to the wrong source", "A quotation that doesn't appear in the retrieved document"])}</div>
<div class="spacer"></div>"""

S["verify_flow"] = f"""
{head("Citation verification", "Built into the pipeline")}
<div class="spacer"></div>
<div class="diagram"><div class="flow">
  <div class="node"><div class="t">Model proposes<br>quotations</div><div class="d">as evidence</div></div>
  <span class="arrow">→</span>
  <div class="node"><div class="t">Python checks<br>the text</div><div class="d">deterministic</div></div>
  <span class="arrow">→</span>
  <div class="stack" style="gap:16px">
    <div class="node ok"><div class="t">✓ Matched</div><div class="d">linked to its real source</div></div>
    <div class="node hot"><div class="t">✕ Not matched</div><div class="d">marked unverified</div></div>
  </div>
</div></div>
<div class="spacer"></div>"""

S["verify_match"] = f"""
<p class="eyebrow">Quotation → retrieved passage</p>
<h2 style="margin-top:14px">Matched, or marked unverified</h2>
<div class="stack" style="margin-top:38px;max-width:1300px">
  <div class="matchbox ok"><div class="mtag green">✓ MATCHED — linked to source metadata</div>
  <div class="quote">"…shall be punished with imprisonment of either description for a term which may extend to two years…"</div></div>
  <div class="matchbox bad"><div class="mtag accent">✕ NOT FOUND IN THE EVIDENCE — citation dropped</div>
  <div class="quote struck">"The standard warranty period shall be twelve years…"<span class="strikeline"></span></div></div>
</div>"""

S["verify_docid"] = f"""
{head("We don't trust the model's own label", "The source is mapped from the retrieved evidence")}
<div class="spacer"></div>
<div class="diagram">{flow([("Model says:<br>doc_id = X", "ignored", "hot"), ("Quote found in<br>passage Y", "authoritative"), ("Source = Y", "from stored metadata", "ok")])}</div>
<div class="spacer"></div>"""

S["verify_inspect"] = f"""
<div class="spacer"></div>
<h1 class="sm safe">So users can <span class="accent">inspect the evidence</span> behind an answer —<br>instead of trusting the model blindly.</h1>
<div class="spacer"></div>"""

S["verify_caveat"] = f"""
<div class="spacer"></div>
<p class="eyebrow">An important limit</p>
<h1 class="sm safe" style="margin-top:18px">Verifying that a quotation <span class="green">exists</span><br>does not prove the legal interpretation is <span class="amber">correct</span>.</h1>
<div class="spacer"></div>"""

S["tech_stack"] = f"""
{head("The research application", "Built on a thin, inspectable stack")}
<div class="spacer"></div>
<div class="diagram">{flow([("React · Vite<br>TypeScript", "frontend"), ("FastAPI", "backend"), ("Same pipeline", "app, API and evaluation", "ok")])}</div>
<div class="spacer"></div>"""

S["shot_progress"] = f"""
{shot_head("Live research progress", "Searching · ranking · drafting · verification")}
<div class="shot-wrap" style="margin-top:30px">{shot_img("03_progress", 1150)}</div>"""

S["shot_answer"] = f"""
<div style="display:flex;justify-content:flex-end"><div style="text-align:right">
<p class="eyebrow">The answer</p><h2 class="shot-title" style="margin-top:12px">Numbered citations and an evidence panel</h2></div></div>
<div class="shot-wrap" style="margin-top:26px;justify-content:flex-end">{shot_img("04b_answer_top", max_h=560)}</div>"""

S["shot_evidence"] = f"""
<div style="display:flex;justify-content:flex-end"><div style="text-align:right">
<p class="eyebrow">Evidence panel</p><h2 class="shot-title" style="margin-top:12px">Every source, and how it was found</h2></div></div>
<div class="shot-wrap" style="margin-top:18px;justify-content:flex-end">{shot_img("07_retrieved_evidence", 415)}</div>"""

S["shot_reader"] = f"""
{shot_head("Document reader", "The cited passage, highlighted in the real source")}
<div class="shot-wrap" style="margin-top:30px">{shot_img("09_document_reader", 1150)}</div>"""

S["shot_lawmap"] = f"""
{shot_head("Old law → new law", "IPC ↔ BNS · CrPC ↔ BNSS · Evidence Act ↔ BSA")}
<div class="shot-wrap" style="margin-top:30px">{shot_img("10_law_map", 1150)}</div>"""

S["shot_history"] = f"""
{shot_head("Statute and case-law search", "Plus browser-local research history")}
<div class="shot-wrap" style="margin-top:30px">{shot_img("11_search", 1150)}</div>"""

S["explore_why"] = f"""
<div class="spacer"></div>
<h1 class="sm safe">We wanted users to do more than read an answer —<br>to <span class="accent">explore the sources</span> and see how it was produced.</h1>
<div class="spacer"></div>"""

S["finetune_question"] = f"""
{head("A second question", "Could a smaller, local model learn this job?")}
<div class="spacer"></div>
<p class="sub safe">Adapt a small model to follow our answering style and structured output — this is where fine-tuning and knowledge distillation entered the project.</p>
<div class="spacer"></div>"""

S["rag_vs_ft"] = f"""
{head("Two different things", "RAG vs fine-tuning")}
<div class="spacer"></div>
<div class="cols diagram">
  <div class="col"><h3 class="slate">RAG</h3><p>Retrieves information from a knowledge base <b>when a question is asked</b>.</p></div>
  <div class="col"><h3 class="accent">Fine-tuning</h3><p>Updates the model's <b>weights</b> using training examples.</p></div>
</div>
<div class="spacer"></div>"""

S["test_not_assume"] = f"""
<div class="spacer"></div>
<h1 class="sm safe">We did not assume fine-tuning would make the model<br>legally correct. <span class="accent">We wanted to test it.</span></h1>
<div class="spacer"></div>"""

S["dataset_pipeline"] = f"""
{head("Before training — reliable examples", "A pipeline, not a scrape")}
<div class="spacer"></div>
<div class="diagram">{flow([("Generate<br>questions", "from seed sources"), ("Check<br>answerability", "against the corpus"), ("Produce teacher<br>answers", "our own pipeline"), ("Review", "graded", "ok")])}</div>
<div class="spacer"></div>"""

S["reviewer_gates"] = f"""
{head("Quality gates", "Checked before anything became training data")}
<div class="spacer"></div>
<div class="safe">{bullets(["Seed sources exist, and quotes appear verbatim in retrieved passages", "An independent Claude reviewer checks answerability, ambiguity and quality", "Teacher answers run through our real answer pipeline", "Deterministic checks plus an independent grading pass"])}</div>"""

S["example_statuses"] = f"""
{head("Every example gets a status", "Nothing enters training unreviewed")}
<div class="spacer"></div>
<div class="chips safe" style="gap:22px">
  <span class="chip" style="border-color:rgba(146,193,158,.5);background:rgba(146,193,158,.12);color:#b6d8bd">VERIFIED</span>
  <span class="chip" style="border-color:rgba(225,181,98,.5);background:rgba(225,181,98,.12);color:#e9cd94">NEEDS REVIEW</span>
  <span class="chip">REJECTED</span>
</div>
<div class="spacer"></div>"""

S["qc_why"] = f"""
<div class="spacer"></div>
<h1 class="sm safe">Training on poorly supported answers<br>would teach the model <span class="amber">those same mistakes.</span></h1>
<div class="spacer"></div>"""

S["lora_setup"] = f"""
{head("The first completed experiment", "Deliberately small")}
<div class="spacer"></div>
<div class="diagram">{flow([("30 verified<br>teacher answers", "training data"), ("Qwen3-1.7B", "4-bit, MLX on Apple Silicon"), ("LoRA adapter", "trained weights", "hot")])}</div>
<div class="spacer"></div>"""

S["three_engine_test"] = f"""
{head("The comparison", "Three engines, one identical test")}
<div class="spacer"></div>
<div class="diagram">{flow([("Base Qwen", "original"), ("LoRA Qwen", "fine-tuned", "hot"), ("Claude", "reference")])}</div>
<p class="sub" style="margin-top:36px">All three answered the same <b>50 held-out questions</b> using <b>identical retrieved evidence</b>.</p>"""

S["identical_evidence"] = f"""
<div class="spacer"></div>
<h1 class="sm safe">Same evidence for every model — so we compare<br><span class="accent">how they answer</span>, not what they were given.</h1>
<div class="spacer"></div>"""

S["metrics_measured"] = f"""
{head("What we measured", "Six dimensions, separately")}
<div class="spacer"></div>
<div class="chips safe" style="gap:18px">
  <span class="chip">Legal correctness</span><span class="chip">Evidence support</span><span class="chip">Citation accuracy</span>
  <span class="chip">Structured output</span><span class="chip">Hallucinated facts</span><span class="chip">Response time</span>
</div>
<div class="spacer"></div>"""

S["results_mixed"] = f"""
<div class="spacer"></div>
<h1 class="safe">The results were <span class="amber">mixed</span>.</h1>
<p class="sub" style="margin-top:26px">And that was the important part.</p>
<div class="spacer"></div>"""

S["chart_citation"] = f"""
<div class="safe-l"><p class="eyebrow">What improved</p>
<h2 style="margin-top:14px">Citation accuracy</h2>
<div style="margin-top:44px">{bars([("Base Qwen", 0, SLATE, "0 / 50"), ("LoRA Qwen", 31, GREEN, "31 / 50"), ("Claude", 50, OX, "50 / 50")])}</div>
<p class="mono-note" style="margin-top:34px">Answers meeting the citation-accuracy criterion, of 50</p></div>"""

S["chart_correctness"] = f"""
<div class="safe-l"><p class="eyebrow">What got worse</p>
<h2 style="margin-top:14px">Legal correctness</h2>
<div style="margin-top:44px">{bars([("Base Qwen", 15, SLATE, "15 / 50"), ("LoRA Qwen", 6, OX, "6 / 50"), ("Claude", 50, GREEN, "50 / 50")])}</div>
<p class="mono-note" style="margin-top:34px">Fully correct answers, of 50 — the fine-tuned model got worse</p></div>"""

S["malformed"] = f"""
{head("And a new problem", "Malformed or truncated responses")}
<div class="spacer"></div>
<div class="safe"><div class="matchbox bad" style="max-width:1150px">
<div class="mtag accent">LORA QWEN — OUTPUT DEFECT</div>
<div class="quote" style="font-style:normal">Roughly half its replies were broken JSON — the answer text had to be recovered from the malformed output.</div></div></div>
<div class="spacer"></div>"""

S["blended_caveat"] = f"""
<div class="spacer"></div>
<p class="eyebrow">The key lesson</p>
<h1 class="sm safe" style="margin-top:18px">The blended score went <span class="green">up</span>.<br>Legal correctness went <span class="accent">down</span>.</h1>
<p class="sub" style="margin-top:30px">We classified the pilot as a <b class="amber">regression requiring investigation</b> — and did not scale it.</p>
<div class="spacer"></div>"""

S["lesson_format"] = f"""
<div class="spacer"></div>
<h1 class="sm safe">Better formatting and citation behaviour<br>do not mean better <span class="accent">legal reasoning</span>.</h1>
<div class="spacer"></div>"""

S["engines_integrated"] = f"""
{head("Into the application", "Three answer engines")}
<div class="spacer"></div>
<div class="diagram">{flow([("Claude", "hosted API"), ("Plain Qwen", "local, via Ollama"), ("LoRA Qwen", "local, experimental", "hot")])}</div>
<div class="spacer"></div>"""

S["evidence_frozen"] = f"""
{head("Retrieve once, freeze, compare", "Every engine answers from the same bundle")}
<div class="spacer"></div>
<div class="diagram">{flow([("Question", ""), ("Retrieval", "runs once"), ("Frozen evidence", "one evidence_id", "ok"), ("Each engine<br>answers", "side by side")])}</div>
<div class="spacer"></div>"""

S["shot_three_engines"] = f"""
{shot_head("Side by side", "Same question, same evidence, three models")}
<div class="shot-wrap" style="margin-top:30px">{shot_img("16_three_columns_top", 1180)}</div>"""

S["why_compare_env"] = f"""
{head("Each answer carries its own record", "Nothing hidden behind a shared view")}
<div class="spacer"></div>
<div class="safe">{bullets(["Its own citation panel and evidence drawer", "Model details — runtime, adapter, timing, retries", "Structured-output status, so malformed or failed replies are visible"])}</div>"""

S["still_experimental"] = f"""
<div class="spacer"></div>
<h1 class="sm safe">The fine-tuned model stays in the app for<br><span class="accent">comparison and investigation</span> — not as proof it is better.</h1>
<div class="spacer"></div>"""

S["demo_panels"] = f"""
{head("Making it inspectable", "What we added for demonstration")}
<div class="spacer"></div>
<div class="safe">{bullets(["A citation-check panel — proposed, matched and rejected quotations", "An evidence panel — document ids, pages, sections, retrieval signals", "Corpus metrics and architecture, visible in the app itself"])}</div>"""

S["curated_questions"] = f"""
{head("Curated demo questions", "Including one the corpus cannot answer")}
<div class="spacer"></div>
<div class="safe"><div class="matchbox ok" style="max-width:1180px;margin-bottom:22px">
<div class="mtag green">ANSWERABLE</div><div class="quote" style="font-style:normal">Questions the current corpus genuinely covers.</div></div>
<div class="matchbox bad" style="max-width:1180px"><div class="mtag amber">DELIBERATELY UNANSWERABLE</div>
<div class="quote" style="font-style:normal">To show insufficient evidence being reported — not hallucinated around.</div></div></div>
<div class="spacer"></div>"""

S["tested_shipped"] = f"""
{head("Tested and shipped", "Evaluation runs, a browser walkthrough, and a clean repository")}
<div class="spacer"></div>
<div class="safe">{bullets(["Evaluation runs and a scripted browser walkthrough", "Pushed to GitHub — with keys, local databases, model artifacts and training data kept out"])}</div>
<div class="spacer"></div>"""

S["status_intro"] = f"""
<div class="spacer"></div>
<p class="eyebrow">Today</p>
<h1 class="safe" style="margin-top:18px">Where IndianLawGPT<br>stands now</h1>
<div class="spacer"></div>"""

S["status_live"] = f"""
<div class="safe-l"><p class="eyebrow">Live and evaluated</p>
<h2 style="margin-top:14px">Working</h2>
<div style="margin-top:36px">{status_rows([
 (GREEN, "RAG pipeline and citation verification", "live and evaluated"),
 (GREEN, "Research interface — Claude, plain Qwen, LoRA Qwen", "three engines, shared evidence"),
 (GREEN, "Retrieval improvements", "tested against several evaluation sets"),
])}</div></div>"""

S["status_paused"] = f"""
<div class="safe-l"><p class="eyebrow">Paused or incomplete</p>
<h2 style="margin-top:14px">Not finished</h2>
<div style="margin-top:36px">{status_rows([
 (AMBER, "Larger training-data generation runs", "stopped before teacher answers were completed"),
 (AMBER, "30-example LoRA pilot", "completed — but no gain in legal correctness, so not scaled"),
 (AMBER, "Three-engine benchmark", "paused before completion"),
])}</div></div>"""

S["status_hosting"] = f"""
<div class="safe-l"><p class="eyebrow">A real limitation</p>
<h2 style="margin-top:14px">Hosting</h2>
<div style="margin-top:36px">{status_rows([
 (OX, "Hosting the frontend does not host the rest", "backend · legal database · Ollama runtime · MLX model service"),
])}</div>
<p class="sub" style="margin-top:34px;max-width:980px">The frontend is only the visible layer. Everything that produces an answer runs behind it.</p></div>"""

S["demo_not_prod"] = f"""
<div class="spacer"></div>
<h1 class="sm safe">A <span class="green">demo-ready legal research prototype</span> —<br>not a fully deployed production legal service.</h1>
<div class="spacer"></div>"""

S["recap"] = f"""
{head("More than connecting a model to documents", "What the work actually involved")}
<div class="spacer"></div>
<div class="safe">{bullets(["Organised legal data", "Improved retrieval", "Verified citations", "Designed an application", "Prepared training examples and evaluated model behaviour"])}</div>"""

S["lesson_tradeoff"] = f"""
<div class="spacer"></div>
<p class="eyebrow">What we learned</p>
<h1 class="sm safe" style="margin-top:18px">A model can improve in one area<br>while getting <span class="accent">worse in another</span>.</h1>
<p class="sub" style="margin-top:30px">Which is why legal correctness has to be evaluated separately from formatting and citation performance.</p>
<div class="spacer"></div>"""

S["next_steps"] = f"""
{head("Next", "Investigate before scaling")}
<div class="spacer"></div>
<div class="safe">{bullets(["Investigate the fine-tuning regression", "Improve the quality of training examples", "Keep testing before scaling the model-adaptation work"])}</div>"""

S["goal_philosophy"] = f"""
<div class="spacer"></div>
<h1 class="sm safe">A system where users can <span class="accent">inspect the evidence</span>,<br>understand the limits, and evaluate the answer —<br>rather than simply accepting it.</h1>
<div class="spacer"></div>"""

S["closing"] = f"""
<div class="spacer"></div>
<h1 class="xl">IndianLaw<span class="accent">GPT</span></h1>
<div class="stack safe" style="margin-top:40px;gap:16px">
  <p class="sub" style="font-size:38px;color:#ded7c8">An evidence-grounded legal research prototype</p>
  <p class="sub" style="font-size:38px;color:#ded7c8">A platform for comparing answer engines</p>
  <p class="sub" style="font-size:38px;color:#ded7c8">A foundation for further legal-AI experimentation</p>
</div>
<div class="spacer"></div>"""

S["thank_you"] = f"""
<div class="spacer"></div>
<h1 class="xl safe">Thank you<br>for watching.</h1>
<div class="spacer"></div>
<div class="mono-note">IndianLawGPT · research prototype · github.com/Furqaan77/Law</div>"""


ANIM_JS = '\n<script>\n(() => {\n  const EASE = "cubic-bezier(.22,1,.36,1)";\n  const COUNTERS = new Map();\n  const set = (el, name, delay, dur, ease = EASE) => { el.style.animation = `${name} ${dur}s ${ease} ${delay}s both`; };\n\n  function split(el, perChar) {\n    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);\n    const nodes = []; while (walker.nextNode()) nodes.push(walker.currentNode);\n    const out = [];\n    for (const n of nodes) {\n      const parts = perChar ? [...n.textContent] : n.textContent.split(/(\\s+)/);\n      const frag = document.createDocumentFragment();\n      for (const part of parts) {\n        if (!part) continue;\n        if (/^\\s+$/.test(part)) { frag.appendChild(document.createTextNode(part)); continue; }\n        const w = document.createElement("span"); w.className = "w"; w.textContent = part;\n        frag.appendChild(w); out.push(w);\n      }\n      n.parentNode.replaceChild(frag, n);\n    }\n    return out;\n  }\n\n  function counter(el, delay, dur) {\n    const text = el.textContent.trim();\n    const m = text.match(/^([^\\d]*)([\\d,]+(?:\\.\\d+)?)(.*)$/);\n    if (!m) return;\n    const [, pre, num, post] = m;\n    const decimals = (num.split(".")[1] || "").length, comma = num.includes(",");\n    const target = parseFloat(num.replace(/,/g, ""));\n    el.style.minWidth = el.getBoundingClientRect().width + "px";   // no layout jitter while counting\n    el.dataset.delay = delay; el.dataset.dur = dur;\n    COUNTERS.set(el, (p) => {\n      const v = target * p;\n      const s = comma ? v.toLocaleString("en-US", { minimumFractionDigits: decimals, maximumFractionDigits: decimals })\n                      : (decimals ? v.toFixed(decimals) : String(Math.round(v)));\n      return pre + s + post;\n    });\n  }\n\n  function prepare(slide) {\n    let t = 0.05;\n    const seg = parseFloat(slide.dataset.seg || "8");\n    const eb = slide.querySelector(".eyebrow");\n    if (eb) { set(eb, "rise", t, 0.8); t += 0.14; }\n    for (const h of slide.querySelectorAll("h1,h2")) {\n      const perChar = h.classList.contains("xl") && h.textContent.trim().length <= 14;\n      const units = split(h, perChar);\n      const step = perChar ? 0.045 : Math.min(0.075, 1.1 / Math.max(units.length, 1));\n      units.forEach((u, i) => set(u, perChar ? "charIn" : "wordIn", t + i * step, perChar ? 0.9 : 0.85));\n      t += units.length * step + 0.18;\n    }\n    for (const s of slide.querySelectorAll(".sub")) { set(s, "rise", t, 0.9); t += 0.2; }\n\n    const items = slide.querySelectorAll(".node,.arrow,ul.big li,.stat,.chip,.col,.matchbox,.st,.bar-row,.shot,.mono-note");\n    for (const el of items) {\n      if (el.matches(".shot")) {\n        set(el, "shotIn", t, 1.2);\n        const img = el.querySelector("img");\n        // slow push-in for the whole scene, so the screenshot never sits still\n        if (img) set(img, "push", t + 0.6, Math.max(2, seg - t - 0.6), "cubic-bezier(.45,.05,.55,.95)");\n        t += 0.3; continue;\n      }\n      if (el.matches(".arrow")) { set(el, "arrowIn", t, 0.6); t += 0.1; continue; }\n      const name = el.matches(".node,.chip,.stat") ? "pop" : el.matches("ul.big li,.st") ? "slideR" : "rise";\n      set(el, name, t, 0.85);\n      if (el.matches(".stat")) { const v = el.querySelector(".v"); if (v) counter(v, t + 0.15, 1.6); }\n      if (el.matches(".bar-row")) {\n        const f = el.querySelector(".bar-fill"); if (f) set(f, "barGrow", t + 0.25, 1.5);\n        const v = el.querySelector(".bar-val"); if (v) counter(v, t + 0.25, 1.5);\n      }\n      if (el.matches(".matchbox.ok")) set(el, "ringPulse", t + 0.9, 1.4);\n      if (el.matches(".matchbox.bad")) {\n        set(el, name, t, 0.85);\n        const line = el.querySelector(".strikeline");\n        if (line) set(line, "strike", t + 0.9, 0.7, "cubic-bezier(.65,0,.35,1)");\n      }\n      t += el.matches(".chip") ? 0.09 : 0.14;\n    }\n  }\n\n  window.__slides = [...document.querySelectorAll(".slide")];\n  for (const s of window.__slides) prepare(s);\n\n  window.seek = (id, t) => {\n    const slide = document.getElementById(id);\n    for (const a of slide.getAnimations({ subtree: true })) { a.pause(); a.currentTime = t * 1000; }\n    for (const [el, fmt] of COUNTERS) {\n      if (!slide.contains(el)) continue;\n      let p = Math.min(1, Math.max(0, (t - +el.dataset.delay) / +el.dataset.dur));\n      p = 1 - Math.pow(1 - p, 3);\n      el.textContent = fmt(p);\n    }\n  };\n  // when the last animation in a slide settles\n  window.introEnd = (id) => {\n    const slide = document.getElementById(id);\n    let end = 0;\n    for (const a of slide.getAnimations({ subtree: true })) {\n      const tm = a.effect.getComputedTiming();\n      end = Math.max(end, (tm.delay + tm.activeDuration) / 1000);\n    }\n    for (const [el] of COUNTERS) if (slide.contains(el)) end = Math.max(end, +el.dataset.delay + +el.dataset.dur);\n    return end;\n  };\n  window.__ready = true;\n})();\n</script>'

# --------------------------------------------------------------------------- emit
def main():
    ids = [s[1] for s in SCENES]
    missing = [i for i in ids if i not in S]
    if missing:
        raise SystemExit(f"Missing slide definitions: {missing}")

    css = CSS.replace("FONTS", FONTS.as_uri())
    # each slide carries its on-screen length (+ the 0.5 s dissolve) so long moves can span the scene
    seg = {}
    for i, (start, sid, _av) in enumerate(SCENES):
        end = SCENES[i + 1][0] if i + 1 < len(SCENES) else END
        seg.setdefault(sid, round(end - start + 0.5, 3))
    body = "".join(
        f'<div class="slide {"light" if sid in LIGHT else ""}" id="{sid}" data-seg="{seg[sid]}">{S[sid]}</div>\n'
        for sid in dict.fromkeys(ids)
    )
    html = (f"<!doctype html><html><head><meta charset='utf-8'><style>{css}</style></head>"
            f"<body>{body}{ANIM_JS}</body></html>")
    (HERE / "slides.html").write_text(html)

    scenes = []
    for i, (start, sid, av) in enumerate(SCENES):
        end = SCENES[i + 1][0] if i + 1 < len(SCENES) else END
        scenes.append({"id": sid, "start": round(start, 3), "end": round(end, 3),
                       "dur": round(end - start, 3), "avatar": av})
    timeline = {"scenes": scenes, "avatar_states": AVATAR_STATES, "end": END,
                "sources": ["First video.mp4", "Second .mp4", "Third.mp4"]}
    (HERE / "timeline.json").write_text(json.dumps(timeline, indent=1))
    print(f"slides.html: {len(set(ids))} unique slides")
    print(f"timeline.json: {len(scenes)} scenes, ends {END}s")
    short = [s for s in scenes if s["dur"] < 3.0]
    if short:
        print("NOTE short scenes:", [(s['id'], s['dur']) for s in short])


LIGHT = {"verify_caveat", "blended_caveat", "coverage_caveat", "retrieval_caveat"}

if __name__ == "__main__":
    main()
