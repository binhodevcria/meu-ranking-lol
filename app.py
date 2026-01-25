import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import google.generativeai as genai
import requests
import os
import json
import time
import numpy as np
from datetime import datetime
from PIL import Image
from pydantic import BaseModel
from urllib.parse import quote
from typing import Optional

# ==============================================================================
# 0. CONFIGURAÇÕES (LÓGICA V18)
# ==============================================================================
# Tamanho do lote de busca na API (Sincronização Rápida)
BATCH_SIZE = 20 

# JANELA COMPETITIVA: O Ranking considera apenas as últimas X partidas de cada um
# Isso balanceia quem jogou 100 partidas com quem jogou 15.
RANKING_WINDOW = 15 

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
    {"nick": "MEC Viper", "tag": "MEC"},
    {"nick": "Sugiro Correr", "tag": "BR1"}
]

NOME_DISPLAY = {
    "GUIZINHA": "GUIZA",
    "EZFALSE": "GUIZA",
    "GUIZA": "GUIZA"
}

st.set_page_config(page_title="OFENSIVO SCORE", layout="wide", page_icon="⚔️")

# ==============================================================================
# 1. VISUAL (CSS ARRUMADO V30)
# ==============================================================================
st.markdown("""
<style>
    .stApp { background-color: #0e1117; }
    h1, h2, h3 { font-family: 'Roboto', sans-serif; color: #ffffff; }
    
    /* KPI Cards */
    div[data-testid="metric-container"] {
        background-color: #1a1c24; 
        border-left: 4px solid #c8aa6e;
        padding: 15px; 
        border-radius: 6px; 
        box-shadow: 0 4px 10px rgba(0,0,0,0.5);
    }
    
    /* Medalhas - Layout Flexbox para centralizar e não quebrar */
    .medal-box {
        background: linear-gradient(145deg, #1e2328, #1a1c24); 
        border: 1px solid #c8aa6e; 
        padding: 20px; 
        border-radius: 10px; 
        text-align: center; 
        box-shadow: 0 4px 15px rgba(0,0,0,0.6); 
        height: 240px; /* Altura fixa para alinhar */
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;
    }
    .medal-icon { font-size: 3.5em; margin-bottom: 10px; line-height: 1; }
    .medal-title { color: #d4af37; font-weight: bold; font-size: 1.1em; text-transform: uppercase; letter-spacing: 1px; margin: 0; }
    .medal-player { color: #ff4b4b; font-weight: 800; font-size: 1.6em; margin: 10px 0; text-shadow: 0px 2px 4px rgba(0,0,0,0.8); line-height: 1.2; }
    .medal-desc { color: #a0a0a0; font-style: italic; font-size: 0.85em; }

    .title-text { font-size: 3.5em; font-weight: bold; color: #ff4b4b; text-align: center; text-shadow: 2px 2px #000; }
    .subtitle-text { font-size: 1.2em; font-style: italic; color: #a0a0a0; text-align: center; margin-bottom: 30px; }
    .stButton>button { background-color: #1e2328; color: #cdbe91; border: 1px solid #463714; font-weight: bold; width: 100%; }
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# 2. MOTORES
# ==============================================================================
class MatchStats(BaseModel):
    MatchID: str; Data: str; Timestamp: float; Jogador: str; Tipo: str
    Vitoria: bool; Score: float; K: int; D: int; A: int; Part: float
    Dano_Estruturas: int; DPM: float; Pinks: int
    RankRiot: Optional[str] = "Unranked"

class BravuraEngine:
    @staticmethod
    def calculate_score(vitoria, d, part, dano_est, dano_camp, minutos, pinks):
        if minutos < 10: return 0.0
        score = 25.0 if vitoria else 0.0
        score += (part * 40)
        dpm = dano_camp / minutos if minutos > 0 else 0
        score += (dpm / 100)
        score += (dano_est / 500)
        score += (pinks * 1.0)
        if d <= 2 and part < 0.35: score -= 25.0
        return round(score, 2)

def get_rank_bravura(media):
    if pd.isna(media) or media == 0: return "💤 Inativo"
    if media < 20: return "🛡️ Defesa"
    if media < 40: return "🌿 Herbívoro"
    if media < 60: return "🤝 Honra Tentou"
    if media < 80: return "⚔️ Ofensivo"
    return "💉 Viciado em Dopamina"

# ==============================================================================
# 3. BANCO DE DADOS
# ==============================================================================
class DatabaseAdapter:
    FILE_DB = 'leaguestats_bravura.csv'
    
    def __init__(self):
        if not os.path.exists(self.FILE_DB):
            pd.DataFrame(columns=MatchStats.model_fields.keys()).to_csv(self.FILE_DB, index=False)
        else:
            try:
                df = pd.read_csv(self.FILE_DB)
                if 'RankRiot' not in df.columns:
                    df['RankRiot'] = 'Unranked'
                    df.to_csv(self.FILE_DB, index=False)
            except: pass

    def get_all(self):
        try:
            df = pd.read_csv(self.FILE_DB, dtype={'MatchID': str})
            if df.empty: return pd.DataFrame()
            df['Jogador'] = df['Jogador'].apply(lambda x: NOME_DISPLAY.get(str(x).upper(), str(x).upper()))
            num_cols = ['Score', 'K', 'D', 'A', 'Part', 'DPM', 'Dano_Estruturas', 'Pinks', 'Timestamp']
            for c in num_cols: df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
            return df
        except: return pd.DataFrame()

    def save(self, stats: MatchStats):
        try:
            df = pd.read_csv(self.FILE_DB, dtype={'MatchID': str})
            stats_id = str(stats.MatchID)
            stats_player = str(stats.Jogador).upper()
            df['MatchID'] = df['MatchID'].astype(str)
            if not ((df['MatchID'] == stats_id) & (df['Jogador'] == stats_player)).any():
                pd.concat([df, pd.DataFrame([stats.model_dump()])], ignore_index=True).to_csv(self.FILE_DB, index=False)
                return True
            return False
        except: return False
    
    def reset_database(self):
        if os.path.exists(self.FILE_DB): os.remove(self.FILE_DB)
        pd.DataFrame(columns=MatchStats.model_fields.keys()).to_csv(self.FILE_DB, index=False)
        return True

# ==============================================================================
# 4. API RIOT (LÓGICA V18 - BATCH RECENTE)
# ==============================================================================
class RiotAdapter:
    def __init__(self, api_key):
        self.headers = {"X-Riot-Token": api_key}
        self.season_start = 1735689600 # 2026

    def request_blindado(self, url):
        for i in range(3):
            try:
                resp = requests.get(url, headers=self.headers)
                if resp.status_code == 200: return resp.json()
                elif resp.status_code == 429:
                    time.sleep(int(resp.headers.get("Retry-After", 5)) + 1)
                    continue
                elif resp.status_code == 404: return None
            except: return None
        return None

    def fetch_rank(self, puuid):
        try:
            summ = self.request_blindado(f"https://br1.api.riotgames.com/lol/summoner/v4/summoners/by-puuid/{puuid}")
            if not summ: return "Unranked"
            leagues = self.request_blindado(f"https://br1.api.riotgames.com/lol/league/v4/entries/by-summoner/{summ['id']}")
            if leagues:
                flex = next((l for l in leagues if l['queueType'] == "RANKED_FLEX_SR"), None)
                if flex: return f"{flex['tier']} {flex['rank']}"
            return "Unranked"
        except: return "Unranked"

    def fetch_recent_flex(self, nome, tag):
        try:
            n, t = quote(nome.strip()), quote(tag.replace('#','').strip())
            acc = self.request_blindado(f"https://americas.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{n}/{t}")
            if not acc: return None, 0, "Conta não achada"
            puuid = acc['puuid']
            
            rank_atual = self.fetch_rank(puuid)
            
            # Baixa as 20 ultimas Flex recentes (Lógica V18)
            url = f"https://americas.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids?queue=440&startTime={self.season_start}&start=0&count={BATCH_SIZE}"
            m_ids = self.request_blindado(url)
            
            if not m_ids: return [], 0, "Sem Flex Recente"
            
            data = []
            for m_id in m_ids:
                d = self.request_blindado(f"https://americas.api.riotgames.com/lol/match/v5/matches/{m_id}")
                if d:
                    p = next((x for x in d['info']['participants'] if x['puuid'] == puuid), None)
                    if p:
                        mins = d['info']['gameDuration']/60
                        sc = BravuraEngine.calculate_score(p['win'], p['deaths'], p['challenges'].get('killParticipation', 0), p['damageDealtToBuildings'], p['totalDamageDealtToChampions'], mins, p['visionWardsBoughtInGame'])
                        data.append(MatchStats(
                            MatchID=str(m_id), 
                            Data=datetime.fromtimestamp(d['info']['gameCreation']/1000).strftime('%d/%m'), 
                            Timestamp=d['info']['gameCreation'], 
                            Jogador=nome.upper(), 
                            Tipo='Flex', 
                            Vitoria=p['win'], 
                            Score=sc, K=p['kills'], D=p['deaths'], A=p['assists'], 
                            Part=p['challenges'].get('killParticipation', 0), 
                            Dano_Estruturas=p['damageDealtToBuildings'], 
                            DPM=round(p['totalDamageDealtToChampions']/mins, 2), 
                            Pinks=p['visionWardsBoughtInGame'], 
                            RankRiot=rank_atual
                        ))
                time.sleep(0.1)
            return data, len(data), "OK"
        except Exception as e: return None, 0, str(e)

# ==============================================================================
# 5. RENDER UI
# ==============================================================================
def render():
    db = DatabaseAdapter()
    riot = RiotAdapter(st.secrets.get("RIOT_KEY", ""))
    gemini = genai.GenerativeModel('models/gemini-1.5-flash') if st.secrets.get("GEMINI_KEY") else None

    st.markdown("<div class='title-text'>⚔️ OFENSIVO SCORE ⚔️</div>", unsafe_allow_html=True)
    st.markdown("<div class='subtitle-text'>criado para jogadores ofensivos que gostam de rir e vencer</div>", unsafe_allow_html=True)

    with st.sidebar:
        st.header("🎮 Painel deidara HO")
        acao = st.radio("Ação:", ["Sincronizar Squad (API)", "Subir Print (Custom)"])
        
        if acao == "Sincronizar Squad (API)":
            if st.button(f"🔄 Sincronizar (Recentes)"):
                log = st.status("Verificando partidas recentes...", expanded=True)
                total_novos = 0
                for p in SQUAD_LIST:
                    log.write(f"🔎 **{p['nick']}**...")
                    matches, count, msg = riot.fetch_recent_flex(p['nick'], p['tag'])
                    if matches is not None:
                        saved = 0
                        for m in matches:
                            if db.save(m): saved += 1
                        total_novos += saved
                        if saved > 0: log.write(f"✅ +{saved} novas!")
                    else: log.error(f"❌ Erro: {msg}")
                    time.sleep(0.2)
                log.update(label="Fim!", state="complete", expanded=False)
                if total_nov

