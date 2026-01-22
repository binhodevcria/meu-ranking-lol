import streamlit as st
import pandas as pd
import plotly.express as px
import google.generativeai as genai
import requests
import os
import json
from PIL import Image
from datetime import datetime

# --- CONFIGURAÇÃO DE AMBIENTE ---
FILE_DB = 'ranking_bravura_season_2026.csv'
SEASON_START_TIMESTAMP = 1735689600  # 01/01/2026 00:00:00 UTC

def init_db():
    if not os.path.exists(FILE_DB):
        df = pd.DataFrame(columns=[
            'MatchID', 'Data', 'Jogador', 'Tipo', 'Vitoria', 'Score', 
            'K', 'D', 'A', 'Part', 'Dano_Estruturas', 'DPM', 'Pinks'
        ])
        df.to_csv(FILE_DB, index=False)

st.set_page_config(page_title="Bravura Season 2026", layout="wide")
init_db()

# Secrets
gemini_key = st.secrets.get("GEMINI_KEY")
riot_key = st.secrets.get("RIOT_KEY")

if gemini_key:
    genai.configure(api_key=gemini_key)
    model = genai.GenerativeModel('models/gemini-1.5-flash')

# --- LÓGICA DE CÁLCULO ---
def calcular_score_bravura(v, d, part, dano_est, dano_camp, minutos, pinks):
    score = 25 if v else 0
    score += (part * 40)
    dpm = dano_camp / minutos if minutos > 0 else 0
    score += (dpm / 100)
    score += (dano_est / 500)
    score += (pinks * 2)
    
    # Filtro de Passividade
    if d <= 2 and part < 0.35:
        score -= 25
    return round(score, 2)

# --- INTEGRAÇÃO RIOT API (SEASON 2026) ---
def sync_season_riot(nome, tag):
    try:
        headers = {"X-Riot-Token": riot_key}
        # 1. PUUID
        acc = requests.get(f"https://americas.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{nome}/{tag}", headers=headers).json()
        puuid = acc['puuid']
        
        # 2. Buscar IDs de partidas desde o início da Season (Queue 440 = Flex)
        url_matches = f"https://americas.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids?startTime={SEASON_START_TIMESTAMP}&queue=440&start=0&count=20"
        match_ids = requests.get(url_matches, headers=headers).json()
        
        if not match_ids:
            return [], "Nenhuma Flex encontrada na Season 2026."

        novas_partidas = []
        df_existente = pd.read_csv(FILE_DB)
        
        for m_id in match_ids:
            # Pula se a partida já estiver no banco
            if m_id in df_existente['MatchID'].values:
                continue
                
            d = requests.get(f"https://americas.api.riotgames.com/lol/match/v5/matches/{m_id}", headers=headers).json()
            p = next(i for i in d['info']['participants'] if i['puuid'] == puuid)
            
            minutos = d['info']['gameDuration'] / 60
            sc = calcular_score_bravura(
                p['win'], p['deaths'], p['challenges'].get('killParticipation', 0),
                p['damageDealtToBuildings'], p['totalDamageDealtToChampions'], minutos, p['visionWardsBoughtInGame']
            )
            
            novas_partidas.append({
                'MatchID': m_id,
                'Data': datetime.fromtimestamp(d['info']['gameCreation']/1000).strftime('%Y-%m-%d %H:%M'),
                'Jogador': nome.upper(),
                'Tipo': 'Flex',
                'Vitoria': p['win'],
                'Score': sc,
                'K': p['kills'], 'D': p['deaths'], 'A': p['assists'],
                'Part': p['challenges'].get('killParticipation', 0),
                'Dano_Estruturas': p['damageDealtToBuildings'],
                'DPM': p['totalDamageDealtToChampions'] / minutos,
                'Pinks': p['visionWardsBoughtInGame']
            })
            
        return novas_partidas, None
    except Exception as e:
        return None, str(e)

# --- INTERFACE ---
st.title("🛡️ Ranking de Bravura: Season 2026")

with st.sidebar:
    st.header("📥 Sincronização")
    metodo = st.radio("Método:", ["Riot API (Season 2026)", "IA Vision (Print Custom)"])
    
    if metodo == "Riot API (Season 2026)":
        r_nome = st.text_input("Nick")
        r_tag = st.text_input("Tag")
        if st.button("Puxar Dados da Season"):
            with st.spinner("Buscando histórico da temporada..."):
                partidas, erro = sync_season_riot(r_nome, r_tag)
                if partidas:
                    df = pd.read_csv(FILE_DB)
                    df_novos = pd.DataFrame(partidas)
                    pd.concat([df, df_novos], ignore_index=True).to_csv(FILE_DB, index=False)
                    st.success(f"Foram adicionadas {len(partidas)} novas partidas!")
                    st.rerun()
                elif erro: st.error(erro)
                else: st.info("Tudo atualizado! Nenhuma partida nova encontrada.")

    else:
        # Módulo IA Vision (Simplificado para o código final)
        u_file = st.file_uploader("Upload Print", type=['png', 'jpg'])
        nick_ai = st.text_input("Nick no Print").upper()
        if u_file and nick_ai and st.button("Analisar com IA"):
            img = Image.open(u_file)
            prompt = f"Analise o print de LoL para {nick_ai}. Extraia JSON: vitoria(bool), d(int), participacao(float), dano_estruturas(int), dano_campeoes(int), duracao_minutos(int), pinks(int)."
            resp = model.generate_content([prompt, img])
            dados = json.loads(resp.text.replace('```json', '').replace('```', '').strip())
            sc = calcular_score_bravura(dados['vitoria'], dados['d'], dados['participacao'], dados['dano_estruturas'], dados['dano_campeoes'], dados['duracao_minutos'], dados['pinks'])
            
            df = pd.read_csv(FILE_DB)
            nova = {'MatchID': f"custom_{os.urandom(4).hex()}", 'Data': datetime.now().strftime('%Y-%m-%d %H:%M'), 'Jogador': nick_ai, 'Tipo': 'Custom', 'Vitoria': dados['vitoria'], 'Score': sc, 'K': 0, 'D': dados['d'], 'A': 0, 'Part': dados['participacao'], 'Dano_Estruturas': dados['dano_estruturas'], 'DPM': dados['dano_campeoes']/dados['duracao_minutos'], 'Pinks': dados['pinks']}
            pd.concat([df, pd.DataFrame([nova])], ignore_index=True).to_csv(FILE_DB, index=False)
            st.rerun()

# --- DASHBOARD ---
df_view = pd.read_csv(FILE_DB)
if not df_view.empty:
    st.subheader("🏆 Leaderboard da Temporada")
    # Agregação por jogador
    rank = df_view.groupby('Jogador').agg({
        'Score': 'sum',
        'DPM': 'mean',
        'Dano_Estruturas': 'mean',
        'MatchID': 'count'
    }).rename(columns={'MatchID': 'Jogos'}).sort_values('Score', ascending=False)
    
    st.dataframe(rank.style.background_gradient(cmap='YlOrRd'), use_container_width=True)

    st.subheader("📈 Curva de Bravura Acumulada")
    df_view = df_view.sort_values('Data')
    df_view['Acumulado'] = df_view.groupby('Jogador')['Score'].cumsum()
    fig = px.line(df_view, x='Data', y='Acumulado', color='Jogador', markers=True, template="plotly_dark")
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("Aguardando o primeiro sincronismo da Season 2026...")
