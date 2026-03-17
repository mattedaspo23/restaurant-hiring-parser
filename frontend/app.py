import json
import os

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st

BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:8000")

st.set_page_config(
    page_title="Restaurant Hiring Parser",
    page_icon="🍕",
    layout="wide",
)

PAGES = [
    "Configurazione Filtri",
    "Candidati Shortlist",
    "Heatmap Filtri Mancanti",
    "Analytics",
]

st.sidebar.title("🍕 Hiring Parser")
page = st.sidebar.radio("Navigazione", PAGES)


def api_get(path: str, params: dict = None):
    try:
        resp = requests.get(f"{BACKEND_URL}{path}", params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        st.error(f"Errore API: {e}")
        return None


def api_post(path: str, data: dict = None, files=None):
    try:
        if files:
            resp = requests.post(f"{BACKEND_URL}{path}", files=files, timeout=60)
        else:
            resp = requests.post(
                f"{BACKEND_URL}{path}",
                json=data,
                timeout=60,
            )
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        st.error(f"Errore API: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Page 1: Configurazione Filtri
# ─────────────────────────────────────────────────────────────────────────────
if page == "Configurazione Filtri":
    st.header("⚙️ Configurazione Filtri")

    configs_resp = api_get("/api/filters")
    existing_configs = configs_resp.get("configs", []) if configs_resp else []

    config_names = ["-- Nuova configurazione --"] + [
        f"{c['name']} ({c['id'][:8]}...)" for c in existing_configs
    ]
    selected_idx = st.selectbox(
        "Carica configurazione esistente", range(len(config_names)),
        format_func=lambda i: config_names[i],
    )

    loaded_config = None
    if selected_idx > 0:
        loaded_config = existing_configs[selected_idx - 1]

    with st.form("filter_config_form"):
        config_name = st.text_input(
            "Nome configurazione",
            value=loaded_config["name"] if loaded_config else "",
        )

        role_options = ["cuoco", "cameriere", "barista", "pizzaiolo", "lavapiatti", "altro"]
        default_role_idx = 0
        if loaded_config and loaded_config.get("role"):
            try:
                default_role_idx = role_options.index(loaded_config["role"].lower())
            except ValueError:
                default_role_idx = 0
        role = st.selectbox("Ruolo", role_options, index=default_role_idx)

        min_exp = st.slider(
            "Esperienza minima (anni)",
            0, 20,
            value=int(loaded_config["min_years_exp"]) if loaded_config else 0,
        )

        cert_options = ["HACCP", "SAB", "Alimentarista", "BLSD"]
        default_certs = loaded_config.get("required_certs", []) if loaded_config else []
        required_certs = st.multiselect(
            "Certificazioni richieste", cert_options, default=default_certs
        )

        avail_options = ["Tempo Pieno", "Part-Time", "Weekend", "Serale", "Flessibile"]
        default_avail_idx = 0
        if loaded_config and loaded_config.get("availability"):
            avail_map = {
                "full-time": "Tempo Pieno",
                "part-time": "Part-Time",
                "weekends": "Weekend",
                "evenings": "Serale",
            }
            mapped = avail_map.get(loaded_config["availability"], "Flessibile")
            try:
                default_avail_idx = avail_options.index(mapped)
            except ValueError:
                default_avail_idx = 0
        availability = st.selectbox(
            "Disponibilità", avail_options, index=default_avail_idx
        )

        lang_options = [
            "Italiano", "Inglese", "Francese", "Spagnolo",
            "Tedesco", "Cinese", "Arabo",
        ]
        default_langs = loaded_config.get("languages", []) if loaded_config else []
        languages = st.multiselect("Lingue", lang_options, default=default_langs)

        bonus_skills_str = st.text_input(
            "Competenze bonus (virgola-separati)",
            value=", ".join(
                loaded_config.get("bonus_filters", {}).get("skills", [])
            ) if loaded_config and loaded_config.get("bonus_filters") else "",
        )

        bonus_weights_str = st.text_input(
            "Pesi bonus (virgola-separati, float)",
            value=", ".join(
                str(w) for w in loaded_config.get("bonus_filters", {}).get("weights", [])
            ) if loaded_config and loaded_config.get("bonus_filters") else "",
        )

        col1, col2 = st.columns(2)
        save_btn = col1.form_submit_button("💾 Salva Configurazione")
        apply_btn = col2.form_submit_button("🔍 Applica e Filtra")

    avail_map_reverse = {
        "Tempo Pieno": "full-time",
        "Part-Time": "part-time",
        "Weekend": "weekends",
        "Serale": "evenings",
        "Flessibile": "full-time",
    }

    bonus_skills = [s.strip() for s in bonus_skills_str.split(",") if s.strip()] if bonus_skills_str else []
    bonus_weights = []
    if bonus_weights_str:
        for w in bonus_weights_str.split(","):
            try:
                bonus_weights.append(float(w.strip()))
            except ValueError:
                pass

    config_data = {
        "name": config_name or "Untitled",
        "role": role,
        "min_years_exp": float(min_exp),
        "required_certs": required_certs,
        "availability": avail_map_reverse.get(availability, "full-time"),
        "languages": languages,
        "bonus_filters": {
            "skills": bonus_skills,
            "weights": bonus_weights,
        } if bonus_skills else None,
    }

    if loaded_config:
        config_data["id"] = loaded_config["id"]

    if save_btn:
        result = api_post("/api/filters", config_data)
        if result:
            st.success(f"Configurazione salvata! ID: {result.get('config_id', 'N/A')}")

    if apply_btn:
        save_result = api_post("/api/filters", config_data)
        if save_result:
            config_id = save_result.get("config_id")
            if config_id:
                score_result = api_post("/api/score", {"config_id": config_id})
                if score_result:
                    st.success(
                        f"Filtro applicato! {len(score_result.get('results', []))} candidati trovati"
                    )
                    if score_result.get("results"):
                        df = pd.DataFrame(score_result["results"])
                        st.dataframe(df, use_container_width=True)

    st.divider()
    st.subheader("📤 Carica CV")
    uploaded_file = st.file_uploader(
        "Carica un CV (PDF o DOCX)", type=["pdf", "docx"]
    )
    if uploaded_file:
        result = api_post(
            "/api/upload/cv",
            files={"file": (uploaded_file.name, uploaded_file.getvalue())},
        )
        if result:
            st.success(f"CV elaborato! Candidato: {result.get('profile', {}).get('name', 'N/A')}")
            st.json(result.get("profile", {}))

    st.divider()
    st.subheader("🔄 Importa da fonti esterne")
    col_indeed, col_easyjob = st.columns(2)
    with col_indeed:
        indeed_role = st.text_input("Ruolo Indeed", value="cuoco")
        indeed_location = st.text_input("Località Indeed", value="Italia")
        if st.button("Importa da Indeed"):
            with st.spinner("Importazione Indeed in corso..."):
                result = api_post(
                    "/api/ingest/indeed",
                    {"role": indeed_role, "location": indeed_location},
                )
                if result:
                    st.success(result.get("message", "Completato"))

    with col_easyjob:
        easyjob_role = st.text_input("Ruolo EasyJob", value="ristorazione")
        if st.button("Importa da EasyJob"):
            with st.spinner("Importazione EasyJob in corso..."):
                result = api_post(
                    "/api/ingest/easyjob",
                    {"role": easyjob_role},
                )
                if result:
                    st.success(result.get("message", "Completato"))


# ─────────────────────────────────────────────────────────────────────────────
# Page 2: Candidati Shortlist
# ─────────────────────────────────────────────────────────────────────────────
elif page == "Candidati Shortlist":
    st.header("📋 Candidati Shortlist")

    configs_resp = api_get("/api/filters")
    existing_configs = configs_resp.get("configs", []) if configs_resp else []

    if not existing_configs:
        st.info("Nessuna configurazione filtri trovata. Crea una nella pagina Configurazione Filtri.")
    else:
        config_names = [f"{c['name']} ({c['id'][:8]}...)" for c in existing_configs]
        selected_idx = st.selectbox(
            "Seleziona configurazione filtri", range(len(config_names)),
            format_func=lambda i: config_names[i],
        )

        selected_config = existing_configs[selected_idx]
        config_id = selected_config["id"]

        history_resp = api_get("/api/scoring-history", {"config_id": config_id})
        history = history_resp.get("history", []) if history_resp else []

        if not history:
            st.warning("Nessun risultato per questa configurazione. Applica i filtri prima.")
            if st.button("🔍 Applica filtri ora"):
                result = api_post("/api/score", {"config_id": config_id})
                if result:
                    st.success(f"Trovati {len(result.get('results', []))} candidati")
                    st.rerun()
        else:
            candidates_resp = api_get(f"/api/candidates")
            all_candidates = candidates_resp.get("candidates", []) if candidates_resp else []
            candidate_map = {c["id"]: c for c in all_candidates if c.get("id")}

            rows = []
            for record in history:
                cand = candidate_map.get(record["candidate_id"], {})
                rows.append({
                    "Nome": cand.get("name", "N/A"),
                    "Ruolo": cand.get("role", "N/A"),
                    "Punteggio": record["score"],
                    "Fonte": cand.get("source", "N/A"),
                    "Punti di Forza": ", ".join(record.get("strengths", [])),
                    "Lacune": ", ".join(record.get("gaps", [])),
                    "Email": cand.get("email", ""),
                    "Telefono": cand.get("phone", ""),
                })

            if rows:
                df = pd.DataFrame(rows)
                df = df.sort_values("Punteggio", ascending=False).reset_index(drop=True)

                def color_score(val):
                    if val >= 70:
                        return "background-color: #c6efce; color: #006100"
                    elif val >= 40:
                        return "background-color: #ffeb9c; color: #9c5700"
                    else:
                        return "background-color: #ffc7ce; color: #9c0006"

                styled = df.style.applymap(color_score, subset=["Punteggio"])
                st.dataframe(styled, use_container_width=True)

                st.subheader("Dettagli candidati")
                for i, row in df.iterrows():
                    with st.expander(f"{row['Nome']} — Punteggio: {row['Punteggio']}"):
                        st.write(f"**Ruolo:** {row['Ruolo']}")
                        st.write(f"**Fonte:** {row['Fonte']}")

                        if row["Punti di Forza"]:
                            st.markdown(f"**Punti di forza:** {row['Punti di Forza']}")
                        if row["Lacune"]:
                            gaps_html = ", ".join(
                                f'<span style="color: red; font-weight: bold">{g.strip()}</span>'
                                for g in row["Lacune"].split(",")
                            )
                            st.markdown(f"**Lacune:** {gaps_html}", unsafe_allow_html=True)

                        if row["Email"]:
                            st.markdown(
                                f"📧 [Contatta via email](mailto:{row['Email']})"
                            )
                        if row["Telefono"]:
                            st.write(f"📞 {row['Telefono']}")


# ─────────────────────────────────────────────────────────────────────────────
# Page 3: Heatmap Filtri Mancanti
# ─────────────────────────────────────────────────────────────────────────────
elif page == "Heatmap Filtri Mancanti":
    st.header("🔥 Heatmap — Filtri più spesso mancanti")

    configs_resp = api_get("/api/filters")
    existing_configs = configs_resp.get("configs", []) if configs_resp else []

    if not existing_configs:
        st.info("Nessuna configurazione filtri trovata.")
    else:
        config_names = [f"{c['name']} ({c['id'][:8]}...)" for c in existing_configs]
        selected_idx = st.selectbox(
            "Seleziona configurazione filtri", range(len(config_names)),
            format_func=lambda i: config_names[i],
        )

        selected_config = existing_configs[selected_idx]
        config_id = selected_config["id"]

        history_resp = api_get("/api/scoring-history", {"config_id": config_id})
        history = history_resp.get("history", []) if history_resp else []

        if not history:
            st.warning("Nessun dato di scoring disponibile per questa configurazione.")
        else:
            gap_counts = {}
            total_candidates = len(history)

            for record in history:
                for gap in record.get("gaps", []):
                    gap_counts[gap] = gap_counts.get(gap, 0) + 1

            if gap_counts:
                gap_labels = list(gap_counts.keys())
                gap_values = [gap_counts[g] for g in gap_labels]
                gap_percentages = [
                    round(v / total_candidates * 100, 1) for v in gap_values
                ]

                sorted_data = sorted(
                    zip(gap_labels, gap_values, gap_percentages),
                    key=lambda x: x[2],
                    reverse=True,
                )
                gap_labels = [d[0] for d in sorted_data]
                gap_values = [d[1] for d in sorted_data]
                gap_percentages = [d[2] for d in sorted_data]

                fig = go.Figure(
                    data=go.Heatmap(
                        z=[gap_percentages],
                        x=gap_labels,
                        y=["Candidati"],
                        colorscale="RdYlGn_r",
                        text=[[f"{p}%" for p in gap_percentages]],
                        texttemplate="%{text}",
                        textfont={"size": 14},
                        hovertemplate=(
                            "Filtro: %{x}<br>"
                            "Mancante: %{text}<br>"
                            "<extra></extra>"
                        ),
                    )
                )
                fig.update_layout(
                    title="Percentuale candidati con filtri mancanti",
                    xaxis_title="Filtro",
                    height=300,
                    margin=dict(l=50, r=50, t=60, b=100),
                    xaxis=dict(tickangle=-45),
                )
                st.plotly_chart(fig, use_container_width=True)

                st.subheader("Dettaglio lacune")
                gap_df = pd.DataFrame({
                    "Filtro": gap_labels,
                    "Candidati mancanti": gap_values,
                    "Percentuale": [f"{p}%" for p in gap_percentages],
                })
                st.dataframe(gap_df, use_container_width=True)

                # Additional per-candidate matrix heatmap
                if total_candidates <= 50:
                    candidates_resp = api_get("/api/candidates")
                    all_candidates = candidates_resp.get("candidates", []) if candidates_resp else []
                    candidate_map = {c["id"]: c.get("name", "N/A") for c in all_candidates if c.get("id")}

                    unique_gaps = list(gap_counts.keys())
                    matrix = []
                    cand_names = []
                    for record in history:
                        name = candidate_map.get(record["candidate_id"], record["candidate_id"][:8])
                        cand_names.append(name)
                        row = [1 if g in record.get("gaps", []) else 0 for g in unique_gaps]
                        matrix.append(row)

                    if matrix:
                        fig2 = go.Figure(
                            data=go.Heatmap(
                                z=matrix,
                                x=unique_gaps,
                                y=cand_names,
                                colorscale=[[0, "#c6efce"], [1, "#ffc7ce"]],
                                showscale=False,
                                text=[
                                    ["❌" if v else "✅" for v in row]
                                    for row in matrix
                                ],
                                texttemplate="%{text}",
                            )
                        )
                        fig2.update_layout(
                            title="Matrice candidati × filtri mancanti",
                            height=max(400, len(cand_names) * 30),
                            xaxis=dict(tickangle=-45),
                            margin=dict(l=150, r=50, t=60, b=100),
                        )
                        st.plotly_chart(fig2, use_container_width=True)
            else:
                st.success("Nessuna lacuna trovata! Tutti i candidati soddisfano i filtri.")


# ─────────────────────────────────────────────────────────────────────────────
# Page 4: Analytics
# ─────────────────────────────────────────────────────────────────────────────
elif page == "Analytics":
    st.header("📊 Analytics")

    sources_resp = api_get("/api/analytics/sources")
    trends_resp = api_get("/api/analytics/trends")
    candidates_resp = api_get("/api/candidates")
    all_candidates = candidates_resp.get("candidates", []) if candidates_resp else []

    # KPI cards
    total_candidates = sources_resp.get("total", 0) if sources_resp else 0
    source_data = sources_resp.get("sources", {}) if sources_resp else {}

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Totale Candidati", total_candidates)
    col2.metric("Da Indeed", source_data.get("indeed", 0))
    col3.metric("Da EasyJob", source_data.get("easyjob", 0))
    col4.metric("Da CV Upload", source_data.get("cv_upload", 0))

    # Compute average score across all scoring history
    all_history_resp = api_get("/api/scoring-history")
    all_history = all_history_resp.get("history", []) if all_history_resp else []
    if all_history:
        avg_score = sum(h["score"] for h in all_history) / len(all_history)
        st.metric("Punteggio medio", f"{avg_score:.1f}")

        # Top gaps
        gap_counts = {}
        for h in all_history:
            for gap in h.get("gaps", []):
                gap_counts[gap] = gap_counts.get(gap, 0) + 1
        if gap_counts:
            top_gaps = sorted(gap_counts.items(), key=lambda x: x[1], reverse=True)[:5]
            st.subheader("Top 5 lacune più frequenti")
            for gap_name, count in top_gaps:
                st.write(f"- **{gap_name}**: {count} candidati")

    st.divider()

    # Source breakdown pie chart
    st.subheader("Distribuzione per fonte")
    if source_data:
        fig_pie = px.pie(
            names=list(source_data.keys()),
            values=list(source_data.values()),
            title="Candidati per fonte",
            color_discrete_sequence=px.colors.qualitative.Set2,
        )
        fig_pie.update_traces(textposition="inside", textinfo="percent+label+value")
        st.plotly_chart(fig_pie, use_container_width=True)
    else:
        st.info("Nessun dato disponibile per le fonti.")

    st.divider()

    # Trend over time
    st.subheader("Candidati nel tempo")
    trends = trends_resp.get("trends", []) if trends_resp else []
    if trends:
        trend_df = pd.DataFrame(trends)
        fig_trend = px.line(
            trend_df,
            x="date",
            y="count",
            title="Candidati ingestiti per giorno",
            markers=True,
        )
        fig_trend.update_layout(
            xaxis_title="Data",
            yaxis_title="Numero candidati",
        )
        st.plotly_chart(fig_trend, use_container_width=True)
    else:
        st.info("Nessun dato di trend disponibile.")

    st.divider()

    # Average score per role over time
    st.subheader("Punteggio medio per ruolo")
    if all_history and all_candidates:
        candidate_map = {c["id"]: c for c in all_candidates if c.get("id")}
        role_scores = {}
        for h in all_history:
            cand = candidate_map.get(h["candidate_id"], {})
            role = cand.get("role", "N/A")
            scored_at = h.get("scored_at", "unknown")
            if scored_at and scored_at != "unknown":
                day = scored_at[:10]
            else:
                day = "unknown"
            key = (role, day)
            if key not in role_scores:
                role_scores[key] = []
            role_scores[key].append(h["score"])

        role_avg_rows = []
        for (role, day), scores in role_scores.items():
            role_avg_rows.append({
                "Ruolo": role,
                "Data": day,
                "Punteggio Medio": round(sum(scores) / len(scores), 1),
            })

        if role_avg_rows:
            role_df = pd.DataFrame(role_avg_rows)
            fig_role = px.line(
                role_df,
                x="Data",
                y="Punteggio Medio",
                color="Ruolo",
                title="Punteggio medio per ruolo nel tempo",
                markers=True,
            )
            st.plotly_chart(fig_role, use_container_width=True)
    else:
        st.info("Nessun dato di scoring disponibile per l'analisi per ruolo.")
