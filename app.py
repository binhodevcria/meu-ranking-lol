import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import google.generativeai as genai
import requests
import os
import json
import time
from datetime import datetime
from PIL import Image
from pydantic import BaseModel
from urllib.parse import quote
from typing import Optional

# ==============================================================================
# 0. SQUAD & MAPEAMENTO
# ==============================================================================
SQUAD_LIST = [
    {"nick": "Gabinho", "tag": "INTEN"},
    {"nick": "Naguinha", "tag": "INTEN"},
    {"nick": "Guiza", "tag": "INTEN"},
    {"nick": "Guizinha", "tag": "BR1"},
    {"nick": "Ezfalse", "tag": "BR1"},
    {"nick": "Rebeca Diana", "tag": "eGIRL"},
    {"nick": "Sylas 1v9", "tag": "BR1"},
    {"nick": "O Magro de OZ", "tag": "BR1"},
    {"nick": "PabIo Escobar", "tag": "INTEN"},
    {"nick": "Murakami UHULL", "tag": "BR1"},
    {"nick": "FEFE TA DE SWAIN", "tag": "DEMON"},
    {"nick": "MEC Viper", "tag": "MEC"}
]

NOME_DISPLAY = {"GUIZINHA": "GUIZA", "EZFALSE": "GUIZA", "GUIZA": "GUIZA"}

def get_elo_bravura(pontos):
    if pontos < 100: return "🌑 Ferro de Barro"
    if pontos < 400: return "🥉 Bronze Ofensivo"
    if pontos < 800: return "🥈 Prata de Respeito"
    if pontos < 1300: return "🥇 Ouro de deidara"
    if pontos < 2000: return "💎 Platina Elite"
    return "🐉 DESAFIANTE HO"

# ==============================================================================
# 1. VISUAL
# ==============================================================================
st.set_page_config(page_title="OFENSIVO SCORE", layout="wide")

st.markdown("""
<style>
    .stApp { background-color: #0e1117; }
    .title-text { font-size: 3.5em; font-weight: bold; color: #ff4b4b; text-align: center; }
    .subtitle-text { font-size: 1.2em; font-style: italic; color: #a0a0a0; text-align: center; margin-bottom: 20px; }
    div[data-testid="metric-container"] { background-color: #1a1c24; border-left: 4px solid #c8aa6e; padding: 15px; }
    .medal-box { background: #1e2328; border: 1px solid #c8aa6e; padding: 10px; border-radius: 8px; text-align: center; }
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# 2. LOGIC & API
# ==============================================================================
class MatchStats(BaseModel):
    MatchID: str; Data: str; Timestamp: float; Jogador: str; Tipo: str; Vitoria: bool; Score: float
    K: int; D: int; A: int; Part: float; Dano_Estruturas: int; DPM: float; Pinks: int
    RankRiot: Optional[str] = "Unranked"

class RiotAdapter:
    def __init__(self, api_key):
        self.headers = {"X-Riot-Token": api_key}
    
    def fetch_flex_rank(self, puuid):
        try:
            sid = requests.get(f"https://br1.api.riotgames.com/lol/summoner/v4/summoners/by-puuid/{puuid}", headers=self.headers).json()['id']
            leagues = requests.get(f"https://br1.api.riotgames.com/lol/league/v4/entries/by-summoner/{sid}", headers=self.headers).json()
            flex = next((l for l in leagues if l['queueType'] == "RANKED_FLEX_SR"), None)
            return f"{flex['tier']} {flex['rank']}" if flex else "Unranked"
        except: return "Unranked"

    def fetch_matches(self, nome, tag, limit=15):
        try:
            n, t = quote(nome.strip()), quote(tag.replace('#','').strip())
            acc = requests.get(f"https://americas.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{n}/{t}", headers=self.headers).json()
            puuid = acc['puuid']
            rank_flex = self.fetch_flex_rank(puuid)
            
            m_ids = requests.get(f"https://americas.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids?startTime=1735689600&start=0&count={limit}", headers=self.headers).json()
            data = []
            for m_id in m_ids:
                d = requests.get(f"https://americas.api.riotgames.com/lol/match/v5/matches/{m_id}", headers=self.headers).json()
                p = next(x for x in d['info']['participants'] if x['puuid'] == puuid)
                sc = (25.0 if p['win'] else 0.0) + (p['challenges'].get('killParticipation', 0) * 40) + ((p['totalDamageDealtToChampions']/(d['info']['gameDuration']/60))/100)
                data.append(MatchStats(MatchID=str(m_id), Data=datetime.fromtimestamp(d['info']['gameCreation']/1000).strftime('%d/%m'), Timestamp=d['info']['gameCreation'], Jogador=nome.upper(), Tipo='Flex' if d['info']['queueId']==440 else 'Outros', Vitoria=p['win'], Score=round(sc,2), K=p['kills'], D=p['deaths'], A=p['assists'], Part=p['challenges'].get('killParticipation', 0), Dano_Estruturas=p['damageDealtToBuildings'], DPM=round(p['totalDamageDealtToChampions']/(d['info']['gameDuration']/60), 1), Pinks=p['visionWardsBoughtInGame'], RankRiot=rank_flex))
            return data, None
        except Exception as e: return None, str(e)

# ==============================================================================
# 3. RENDER
# ==============================================================================
def render():
    db_file = 'leaguestats_bravura.csv'
    if not os.path.exists(db_file): pd.DataFrame(columns=MatchStats.model_fields.keys()).to_csv(db_file, index=False)
    
    st.markdown("<div class='title-text'>⚔️ OFENSIVO SCORE ⚔️</div>", unsafe_allow_html=True)
    st.markdown("<div class='subtitle-text'>criado para jogadores ofensivos que gostam de rir e vencer</div>", unsafe_allow_html=True)

    riot = RiotAdapter(st.secrets.get("RIOT_KEY", ""))
    
    with st.sidebar:
        st.header("🎮 deidara HO")
        if st.button("🔄 ATUALIZAR SQUAD (FLEX)"):
            bar = st.progress(0)
            df_old = pd.read_csv(db_file, dtype={'MatchID': str})
            for idx, p in enumerate(SQUAD_LIST):
                bar.progress(idx/len(SQUAD_LIST), text=f"Lendo {p['nick']}...")
                matches, _ = riot.fetch_matches(p['nick'], p['tag'])
                if matches:
                    for m in matches:
                        if not ((df_old['MatchID'] == m.MatchID) & (df_old['Jogador'] == m.Jogador.upper())).any():
                            df_old = pd.concat([df_old, pd.DataFrame([m.model_dump()])], ignore_index=True)
            df_old.to_csv(db_file, index=False)
            st.rerun()

    df = pd.read_csv(db_file, dtype={'MatchID': str})
    df['Jogador'] = df['Jogador'].apply(lambda x: NOME_DISPLAY.get(x.upper(), x.upper()))
    
    if df.empty: return

    # --- ABA DE RANKING ---
    tab_r, tab_m = st.tabs(["🏆 LEADERBOARD & ELOS", "🏅 MURAL DE MEDALHAS"])

    with tab_r:
        df_f = df[df['Tipo'] != 'Custom']
        leader = df_f.groupby('Jogador').agg({'Score': 'sum', 'RankRiot': 'last'}).sort_values('Score', ascending=False).reset_index()
        leader['Elo Bravura'] = leader['Score'].apply(get_elo_bravura)
        
        st.dataframe(leader[['Jogador', 'Elo Bravura', 'Score', 'RankRiot']].style.background_gradient(cmap='YlOrRd', subset=['Score']), use_container_width=True)
        
        # Gráfico Area
        df_f = df_f.sort_values('Timestamp')
        df_f['Acumulado'] = df_f.groupby('Jogador')['Score'].cumsum()
        fig = px.line(df_f, x='Data', y='Acumulado', color='Jogador', template='plotly_dark', title="Evolução da Bravura")
        fig.update_traces(line_shape='spline', fill='tozeroy')
        st.plotly_chart(fig, use_container_width=True)

    with tab_m:
        st.subheader("Os Melhores (e Piores) da Semana")
        m1, m2, m3, m4 = st.columns(4)
        
        # Lógica das Medalhas
        stats = df_f.groupby('Jogador').agg({'DPM': 'mean', 'Score': 'sum', 'D': 'sum', 'Part': 'mean', 'Vitoria': 'sum'})
        
        with m1:
            ariel = stats.sort_values(['Part', 'Vitoria'], ascending=[True, True]).index[0]
            st.markdown(f"<div class='medal-box'>🐢<br><b>ARIEL</b><br><small>Safe Player</small><br><h3 style='color:#ff4b4b'>{ariel}</h3></div>", unsafe_allow_html=True)
        with m2:
            danudo = stats['DPM'].idxmax()
            st.markdown(f"<div class='medal-box'>🧨<br><b>DANUDO</b><br><small>Maior Dano</small><br><h3 style='color:#c8aa6e'>{danudo}</h3></div>", unsafe_allow_html=True)
        with m3:
            diniz = stats['Score'].idxmax()
            st.markdown(f"<div class='medal-box'>🔪<br><b>DINIZ</b><br><small>Mestre Bravura</small><br><h3 style='color:#c8aa6e'>{diniz}</h3></div>", unsafe_allow_html=True)
        with m4:
            inimigo = stats['D'].idxmax()
            st.markdown(f"<div class='medal-box'>💀<br><b>INIMIGO KDA</b><br><small>Mais Mortes</small><br><h3 style='color:#ff4b4b'>{inimigo}</h3></div>", unsafe_allow_html=True)

    st.markdown("<hr><div style='text-align:center'><div style='font-size:1.5em'>É o grupo</div><div style='font-size:4em; font-weight:bold; color:#d4af37; font-family:Impact'>deidara HO</div></div>", unsafe_allow_html=True)

if __name__ == "__main__":
    render()
