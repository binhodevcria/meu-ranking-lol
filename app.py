import streamlit as st
import pandas as pd
import plotly.express as px
import requests
import os
import cv2
import numpy as np
import easyocr
from PIL import Image

# --- CONFIGURAÇÕES DE AMBIENTE ---
# No Streamlit Cloud, adiciona RIOT_KEY em Settings > Secrets
API_KEY = st.secrets.get("RIOT_KEY", "SUA_API_KEY_AQUI")
FILE_DB = 'ranking_lol_ofensivo.csv'

# Inicializar OCR (Cache para não carregar o modelo em cada clique)
@st.cache_resource
def load_ocr():
    return easyocr.Reader(['en'])

def init_db():
    if not os.path.exists(FILE_DB):
        df = pd.DataFrame(columns=[
            'Data', 'Jogador', 'Tipo', 'Vitoria', 'Score', 
            'K', 'D', 'A', 'P_Kills', 'Pinks', 'Torres', 'Dano'
        ])
        df.to_csv(FILE_DB, index=False)

# --- FÓRMULA DE AGRESSIVIDADE (Sociologia do Jogo) ---
def calcular_score_agressivo(v, tipo, k, d, a, part_k, pinks, torres, dano):
    # Base competitiva
    score = (35 if tipo == "Flex" else 25) if v else -10
    # Peso da participação (Engajamento nas lutas)
    score += (part_k * 30)
    # Peso de objetivos (Agressividade no mapa)
    score += (torres * 5) + (pinks * 1.5)
    # Peso de volume (Dano normalizado)
    score += (dano / 2000)
    # Barra de Medo: Penaliza passividade (0 ou 1 morte com <30% participação)
    if d <= 1 and part_k < 0.30:
        score -= 20
    return round(score, 2)

# --- INTEGRAÇÃO RIOT API ---
def get_riot_data(nome, tag):
    try:
        url_id = f"https://americas.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{nome}/{tag}?api_key={API_KEY}"
        acc = requests.get(url_id).json()
        puuid = acc['puuid']
        
        url_m = f"https://americas.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids?queue=440&count=1&api_key={API_KEY}"
        match_id = requests.get(url_m).json()[0]
        
        url_d = f"https://americas.api.riotgames.com/lol/match/v5/matches/{match_id}?api_key={API_KEY}"
        data = requests.get(url_d).json()
        
        p = next(i for i in data['info']['participants'] if i['puuid'] == puuid)
        
        return {
            'V': p['win'], 'K': p['kills'], 'D': p['deaths'], 'A': p['assists'],
            'Part': p['challenges'].get('killParticipation', 0),
            'Pinks': p['visionWardsBoughtInGame'],
            'Torres': p['turretKills'],
            'Dano': p['totalDamageDealtToChampions']
        }
    except: return None

# --- INTERFACE ---
st.set_page_config(page_title="LoL Aggressive Rank", layout="wide")
init_db()
reader = load_ocr()

st.title("⚔️ LoL Aggressive Ranking: API + OCR")

col_input, col_view = st.columns([1, 2])

with col_input:
    st.header("📥 Entrada de Dados")
    tab1, tab2 = st.tabs(["Riot API (Flex)", "OCR Print (Custom)"])
    
    with tab1:
        r_nome = st.text_input("Nick (Ex: Faker)")
        r_tag = st.text_input("Tag (Ex: BR1)")
        if st.button("Sincronizar Última Flex"):
            d = get_riot_data(r_nome, r_tag)
            if d:
                sc = calcular_score_agressivo(d['V'], "Flex", d['K'], d['D'], d['A'], d['Part'], d['Pinks'], d['Torres'], d['Dano'])
                new_data = pd.DataFrame([[pd.Timestamp.now(), r_nome.upper(), "Flex", d['V'], sc, d['K'], d['D'], d['A'], d['Part'], d['Pinks'], d['Torres'], d['Dano']]], columns=pd.read_csv(FILE_DB).columns)
                new_data.to_csv(FILE_DB, mode='a', header=False, index=False)
                st.success(f"Score: {sc} Registado!")
            else: st.error("Falha na API. Verifica a Key.")

    with tab2:
        st.write("Sobe o print das estatísticas da Custom:")
        u_file = st.file_uploader("Upload Print", type=['png', 'jpg'])
        if u_file:
            img = Image.open(u_file)
            img_cv = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2GRAY)
            results = reader.readtext(img_cv)
            # Tenta encontrar números na imagem (Lógica simplificada para teste)
            textos = [res[1] for res in results]
            st.write("Texto detetado:", ", ".join(textos[:10]))
        
        with st.form("custom_form"):
            c_nome = st.text_input("Nome do Amigo").upper()
            c_v = st.checkbox("Vitória?")
            ck, cd, ca = st.columns(3)
            k = ck.number_input("K", 0)
            d = cd.number_input("D", 0)
            a = ca.number_input("A", 0)
            part = st.slider("Participação %", 0, 100, 50) / 100
            t = st.number_input("Torres", 0)
            dano = st.number_input("Dano Total", 0)
            if st.form_submit_button("Salvar Custom"):
                sc_c = calcular_score_agressivo(c_v, "Custom", k, d, a, part, 0, t, dano)
                df_c = pd.DataFrame([[pd.Timestamp.now(), c_nome, "Custom", c_v, sc_c, k, d, a, part, 0, t, dano]], columns=pd.read_csv(FILE_DB).columns)
                df_c.to_csv(FILE_DB, mode='a', header=False, index=False)
                st.rerun()

# --- RANKING E GRÁFICO ---
df = pd.read_csv(FILE_DB)
if not df.empty:
    with col_view:
        st.subheader("🏆 Leaderboard")
        ranking = df.groupby('Jogador').agg({'Score': 'sum', 'K': 'mean', 'Dano': 'mean'}).sort_values('Score', ascending=False)
        st.dataframe(ranking.style.background_gradient(cmap='Oranges'), use_container_width=True)
        
        st.subheader("📈 Evolução")
        df['Acumulado'] = df.groupby('Jogador')['Score'].cumsum()
        fig = px.line(df, x=df.index, y='Acumulado', color='Jogador', template="plotly_dark")
        st.plotly_chart(fig, use_container_width=True)
