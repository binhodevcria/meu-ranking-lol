import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import google.generativeai as genai
import requests
import os
import json
import time
from datetime import datetime, timedelta
from PIL import Image
from pydantic import BaseModel
from typing import Optional, List
from urllib.parse import quote

# ==============================================================================
# 0. CONFIGURAÇÕES VISUAIS
# ==============================================================================
st.set_page_config(page_title="LeagueStats: Bravura", layout="wide", page_icon="🛡️")

st.markdown("""
<style>
    .stApp { background-color: #0e1117; }
    h1, h2, h3, h4 { font-family: 'Roboto', sans-serif; color: #ffffff; }
    div[data-testid="metric-container"] {
        background-color: #1a1c24; border-left: 4px solid #c8aa6e; padding: 15px; border-radius: 6px;
    }
    div[data-testid="stExpander"] { border: 1px solid #c8aa6e; }
    .log-success { color: #4ade80; font-family: monospace; font-size: 12px; }
    .log-warn { color: #facc15; font-family: monospace; font-size: 12px; }
    .log-error { color: #f87171; font-family: monospace; font-size: 12px; }
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# 1. LOGIC LAYER
# ==============================================================================
class MatchStats(BaseModel):
    MatchID: str
    Data: str
    Timestamp: float
    Jogador: str
    Tipo: str
    Vitoria: bool
    Score: float
    K: int
    D: int
    A: int
    Part: float
    Dano_Estruturas: int
    DPM: float
    Pinks: int

class BravuraEngine:
    @staticmethod
    def calculate_score(vitoria, d, part, dano_est, dano_camp, minutos, pinks):
        score = 25.0 if vitoria else 0.0
        score += (part * 40)
        dpm = dano_camp / minutos if minutos > 0 else 0
        score += (dpm / 100)
        score += (dano_est / 500)
        score += (pinks * 2)
        if d <= 2 and part < 0.35: score -= 25.0
        return round(score, 2)

# ==============================================================================
# 2. DATA LAYER (CORREÇÃO DE DUPLICIDADE AQUI)
# ==============================================================================
class DatabaseAdapter:
    FILE_DB = 'leaguestats_bravura.csv'
    def __init__(self):
        if not os.path.exists(self.FILE_DB): self._create_db()
    
    def _create_db(self):
        pd.DataFrame(columns=MatchStats.model_fields.keys()).to_csv(self.FILE_DB, index=False)
    
    def get_all(self):
        if not os.path.exists(self.FILE_DB): self._create_db()
        # Força leitura de MatchID como string para evitar erros de tipo
        return pd.read_csv(self.FILE_DB, dtype={'MatchID': str})
    
    def save(self, stats: MatchStats):
        df = self.get_all()
        
        # --- FIX CRÍTICO: CHAVE COMPOSTA (MATCH_ID + JOGADOR) ---
        # Verifica se já existe uma linha onde o ID E o JOGADOR são iguais ao atual
        # Isso permite que a mesma partida seja salva várias vezes, desde que para jogadores diferentes
        already_exists = ((df['MatchID'] == str(stats.MatchID)) & 
                          (df['Jogador'] == stats.Jogador)).any()

        if not already_exists:
            pd.concat([df, pd.DataFrame([stats.model_dump()])], ignore_index=True).to_csv(self.FILE_DB, index=False)
            return True
        return False

    def reset_database(self):
        if os.path.exists(self.FILE_DB):
            os.remove(self.FILE_DB)
            self._create_db()
            return True
        return False

class RiotAdapter:
    def __init__(self, api_key):
        self.headers = {"X-Riot-Token": api_key}
        self.season_start = 1735689600 # 01/01/2026

    def fetch_matches(self, nome, tag, limit=20, force_any_queue=False):
        logs = []
        try:
            # 1. Tratamento de URL
            tag_clean = tag.replace('#', '').strip()
            nome_enc = quote(nome.strip())
            tag_enc = quote(tag_clean)

            # 2. Account V1
            acc_url = f"https://americas.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{nome_enc}/{tag_enc}"
            logs.append(f"🔍 Buscando conta: {nome} #{tag_clean}...")
            
            acc_resp = requests.get(acc_url, headers=self.headers)
            
            if acc_resp.status_code != 200:
                return None, f"Erro Conta ({acc_resp.status_code})", logs
            
            puuid = acc_resp.json()['puuid']

            # 3. Match IDs
            queue_param = "" if force_any_queue else "&queue=440"
            # Removendo filtro de data para garantir que acha jogos (mesmo que de dez/2025 para teste)
            matches_url = f"https://americas.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids?start=0&count={limit}{queue_param}"
            
            matches_resp = requests.get(matches_url, headers=self.headers)
            match_ids = matches_resp.json()
            
            if not match_ids:
                return None, "⚠️ Nenhuma partida encontrada.", logs
            
            logs.append(f"✅ Encontradas {len(match_ids)} partidas. Processando cruzamento de dados...")
            
            processed_data = []
            bar = st.progress(0, text="Baixando...")
            
            for i, m_id in enumerate(match_ids):
                bar.progress((i + 1) / len(match_ids), text=f"Lendo {i+1}/{len(match_ids)}")
                d_resp = requests.get(f"https://americas.api.riotgames.com/lol/match/v5/matches/{m_id}", headers=self.headers)
                
                if d_resp.status_code == 200:
                    d = d_resp.json()
                    p = next((part for part in d['info']['participants'] if part['puuid'] == puuid), None)
                    
                    if p:
                        mins = d['info']['gameDuration'] / 60
                        sc = BravuraEngine.calculate_score(
                            p['win'], p['deaths'], p['challenges'].get('killParticipation', 0),
                            p['damageDealtToBuildings'], p['totalDamageDealtToChampions'], mins, p['visionWardsBoughtInGame']
                        )
                        
                        queue_id = d['info']['queueId']
                        tipo_str = 'Flex' if queue_id == 440 else ('SoloQ' if queue_id == 420 else 'Outros')
                        
                        processed_data.append(MatchStats(
                            MatchID=str(m_id),
                            Data=datetime.fromtimestamp(d['info']['gameCreation']/1000).strftime('%Y-%m-%d %H:%M'),
                            Timestamp=d['info']['gameCreation'],
                            Jogador=nome.upper(),
                            Tipo=tipo_str,
                            Vitoria=p['win'], Score=sc, K=p['kills'], D=p['deaths'], A=p['assists'],
                            Part=p['challenges'].get('killParticipation', 0),
                            Dano_Estruturas=p['damageDealtToBuildings'],
                            DPM=round(p['totalDamageDealtToChampions']/mins, 2),
                            Pinks=p['visionWardsBoughtInGame']
                        ))
                time.sleep(0.05)
            
            bar.empty()
            return processed_data, None, logs

        except Exception as e:
            return None, f"Erro: {str(e)}", logs

class GeminiAdapter:
    def __init__(self, api_key):
        if api_key:
            genai.configure(api_key=api_key)
            self.model = genai.GenerativeModel('models/gemini-1.5-flash')
        else: self.model = None
    def analyze(self, image, player_name):
        if not self.model: return None
        try:
            resp = self.model.generate_content([f"Extraia stats LoL JSON para {player_name}: {{'vitoria':bool,'k':int,'d':int,'a':int,'part':float,'dano_est':int,'dano_camp':int,'min':int,'pinks':int}}", image])
            return json.loads(resp.text.replace('```json', '').replace('```', '').strip())
        except: return None

# ==============================================================================
# 3. UI LAYER
# ==============================================================================
def safe_hex_to_rgba(hex_color, opacity=0.1):
    try:
        c = hex_color.lstrip('#')
        return f"rgba({int(c[0:2], 16)}, {int(c[2:4], 16)}, {int(c[4:6], 16)}, {opacity})"
    except: return hex_color

def render_dashboard():
    db = DatabaseAdapter()
    riot = RiotAdapter(st.secrets.get("RIOT_KEY", ""))
    gemini = GeminiAdapter(st.secrets.get("GEMINI_KEY", ""))

    st.title("🛡️ LeagueStats: Bravura Tracker")
    st.caption("Season 2026 • Sociologia do Jogo • V5.3 (Multi-Player Fix)")

    with st.sidebar:
        st.header("🎮 Painel de Controle")
        mode = st.radio("Fonte:", ["Riot API", "Gemini OCR"])
        st.markdown("---")
        
        if mode == "Riot API":
            nick = st.text_input("Nick (Ex: Gabinho)")
            tag = st.text_input("Tag (Ex: INTEN)")
            limit = st.slider("Qtd. Jogos:", 5, 50, 20)
            
            # Opções Avançadas
            with st.expander("🛠️ Opções Avançadas", expanded=True):
                force_all = st.checkbox("Buscar QUALQUER Fila", value=True, help="Ignora filtro de Flex.")
            
            if st.button("🔄 Sincronizar") and nick and tag:
                matches, error, logs = riot.fetch_matches(nick, tag, limit, force_any_queue=force_all)
                
                with st.status("Processando...", expanded=False):
                    for l in logs: st.write(l)
