import streamlit as st
import pandas as pd
import plotly.express as px
import requests
import os
import time

# --- CONFIGURAÇÕES E SEGURANÇA ---
# No Streamlit Cloud, coloque sua chave em Settings > Secrets
API_KEY = st.secrets.get("RIOT_KEY", "SUA_CHAVE_TEMPORARIA_AQUI")
FILE_DB = 'ranking_agressivo_lol.csv'

def init_db():
    if not os.path.exists(FILE_DB):
        df = pd.DataFrame(columns=[
            'Data', 'Jogador', 'Tipo', 'Vitoria', 'Score', 
            'K', 'D', 'A', 'Pinks', 'Torres', 'Dano_Campeoes'
        ])
        df.to_csv(FILE_DB, index=False)

# --- A FÓRMULA MESTRA DE AGRESSIVIDADE ---
def calcular_score_completo(v, tipo, k, d, a, part_k, pinks, torres, dano):
    # Base: Flex vale mais pelo nível competitivo
    score = (35 if tipo == "Flex" else 25) if v else -10
    
    # Ofensividade (Participação em kills é o peso mais forte: 0.0 a 1.0)
    score += (part_k * 30)
    
    # Objetivos e Visão Proativa
    score += (torres * 4)  # Bônus por levar torre (agressividade no mapa)
    score += (pinks * 1.5) # Visão ofensiva
    
    # Performance de Dano (Normalizado: cada 10k de dano = 5 pontos)
    score += (dano / 2000)
    
    # Penalidade de Passividade (A "Barra de Medo")
    if d <= 1 and part_k < 0.30:
        score -= 20
        
    return round(score, 2)

# --- INTEGRAÇÃO RIOT API ---
def sync_riot_flex(nome, tag):
    try:
        # 1. PUUID
        url_id = f"https://americas.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{nome}/{tag}?api_key={API_KEY}"
        acc = requests.get(url_id).json()
        puuid = acc['puuid']
        
        # 2. Última Partida Flex (440)
        url_m = f"https://americas.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids?queue=440&count=1&api_key={API_KEY}"
        m_id = requests.get(url_m).json()[0]
        
        # 3. Detalhes
        url_d = f"https://americas.api.riotgames.com/lol/match/v5/matches/{m_id}?api_key={API_KEY}"
        detalhes = requests.get(url_d).json()
        
        p = next(i for i in detalhes['info']['participants'] if i['puuid'] == puuid)
        
        # Traduzindo dados da Riot para nossa fórmula
        res = {
            'Vitoria': p['win'],
            'K': p['kills'], 'D': p['deaths'], 'A': p['assists'],
            'P%': p['challenges'].get('killParticipation', 0),
            'Pinks': p['visionWardsBoughtInGame'],
            'Torres': p['turretKills'],
            'Dano': p['totalDamageDealtToChampions']
        }
        return res, m_id
    except Exception as e:
        return None, str(e)

# --- INTERFACE ---
st.set_page_config(page_title="LoL Aggressive Stats", layout="wide")
init_db()

st.title("⚔️ Ranking de Agressividade Automático")

col_input, col_view = st.columns([1, 2])

with col_input:
    st.header("📥 Entrada de Dados")
    aba1, aba2 = st.tabs(["Riot API (Flex)", "Print/Manual (Custom)"])
    
    with aba1:
        riot_nome = st.text_input("Nome (Ex: Faker)")
        riot_tag = st.text_input("Tag (Ex: BR1)")
        if st.button("Sincronizar Última Flex"):
            dados, m_id = sync_riot_flex(riot_nome, riot_tag)
            if dados:
                sc = calcular_score_completo(dados['Vitoria'], "Flex", dados['K'], dados['D'], dados['A'], dados['P%'], dados['Pinks'], dados['Torres'], dados['Dano'])
                
                # Salvar no CSV
                df_new = pd.DataFrame([[pd.Timestamp.now(), riot_nome.upper(), "Flex", dados['Vitoria'], sc, dados['K'], dados['D'], dados['A'], dados['Pinks'], dados['Torres'], dados['Dano']]], columns=pd.read_csv(FILE_DB).columns)
                df_new.to_csv(FILE_DB, mode='a', header=False, index=False)
                st.success(f"Partida Flex lida! Score: {sc}")
            else:
                st.error("Erro ao buscar dados. Verifique o Nick/Tag ou a API KEY.")

    with aba2:
        st.info("Para Customs, preencha os dados da agressividade:")
        with st.form("manual"):
            m_nome = st.text_input("Nome do Amigo").upper()
            m_v = st.checkbox("Vitória?")
            c1, c2, c3 = st.columns(3)
            mk = c1.number_input("K", 0)
            md = c2.number_input("D", 0)
            ma = c3.number_input("A", 0)
            m_p = st.slider("Participação em Kills %", 0, 100, 50) / 100
            m_pinks = st.number_input("Pinks", 0)
            m_torres = st.number_input("Torres destruídas", 0)
            m_dano = st.number_input("Dano Total", 0)
            
            if st.form_submit_button("Salvar Custom"):
                sc_m = calcular_score_completo(m_v, "Custom", mk, md, ma, m_p, m_pinks, m_torres, m_dano)
                df_m = pd.DataFrame([[pd.Timestamp.now(), m_nome, "Custom", m_v, sc_m, mk, md, ma, m_pinks, m_torres, m_dano]], columns=pd.read_csv(FILE_DB).columns)
                df_m.to_csv(FILE_DB, mode='a', header=False, index=False)
                st.rerun()

# --- DASHBOARD ---
df = pd.read_csv(FILE_DB)
if not df.empty:
    with col_view:
        st.header("🏆 Ranking Ofensivo")
        rank = df.groupby('Jogador').agg({'Score': 'sum', 'K': 'mean', 'Dano_Campeoes': 'mean', 'Torres': 'sum'}).sort_values('Score', ascending=False)
        st.dataframe(rank.style.background_gradient(cmap='Oranges'), use_container_width=True)
        
        # Gráfico
        df['Score_Acumulado'] = df.groupby('Jogador')['Score'].cumsum()
        fig = px.line(df, x=df.index, y='Score_Acumulado', color='Jogador', title="Evolução da Agressividade", template="plotly_dark")
        st.plotly_chart(fig, use_container_width=True)
