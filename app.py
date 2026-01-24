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
# 0. SQUAD LIST (A ELITE)
# ==============================================================================
SQUAD_LIST = [
    {"nick": "Gabinho", "tag": "INTEN"},
    {"nick": "Naguinha", "tag": "INTEN"},
    {"nick": "Guiza", "tag": "INTEN"},
    {"nick": "Rebeca Diana", "tag": "eGIRL"},
    {"nick": "Sylas 1v9", "tag": "BR1"},
    {"nick": "O Magro de OZ", "tag": "BR1"},
    {"nick": "PabIo Escobar", "tag": "INTEN"}, # Copiado exato (com I maiúsculo se for o caso)
    {"nick": "Murakami UHULL", "tag": "BR1"},
    {"nick": "FEFE TA DE SWAIN", "tag": "DEMON"},
    {"nick": "MEC Viper", "tag": "MEC"}
]

# ==============================================================================
# 1. CONFIGURAÇÕES VISUAIS
# ==============================================================================
st.set_page_config(page_title="OFENSIVO SCORE", layout="wide", page_icon="⚔️")

st.markdown("""
<style>
    /* Fundo e Fontes Globais */
    .stApp { background-color: #0e1117; }
    h1, h2, h3, h4 { font-family: 'Roboto', sans-serif; color: #ffffff; }
    
    /* Cards de Métricas (KPIs) */
    div[data-testid="metric-container"] {
        background-color: #1a1c24;
        border-left: 4px solid #ff4b4b; /* Vermelho Agressivo */
        padding: 15px;
        border-radius: 6px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.3);
    }
    
    /* Título Personalizado */
    .title-text { font-size: 3em; font-weight: bold; color: #ff4b4b; text-align: center; }
    .subtitle-text { font-size: 1.2em; font-style: italic; color: #a0a0a0; text-align: center; margin-bottom: 30px; }
    
    /* Footer */
    .footer-group { font-size: 1.5em; color: #ffffff; text-align: left; margin-top: 50px; }
    .footer-final { font-size: 4em; font-weight: bold; color: #d4af37; text-align: center; margin-top: 20px; font-family: 'Impact', sans-serif; letter-spacing: 5px; }

    /* Botões */
    .stButton>button {
        background-color: #2b313e;
        color: white;
        border: 1px solid #ff4b4b;
        border-radius: 5px;
        width: 100%;
    }
    .stButton>button:hover {
        border-color: #ff8888;
        color: #ff8888;
    }
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# 2. LOGIC LAYER
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
# 3. DATA LAYER
# ==============================================================================
class DatabaseAdapter:
    FILE_DB = 'leaguestats_bravura.csv'
    
    def __init__(self):
        if not os.path.exists(self.FILE_DB): self._create_db()
    
    def _create_db(self):
        try: pd.DataFrame(columns=MatchStats.model_fields.keys()).to_csv(self.FILE_DB, index=False)
        except: pass
    
    def get_all(self):
        try: return pd.read_csv(self.FILE_DB, dtype={'MatchID': str})
        except: 
            self._create_db()
            return pd.read_csv(self.FILE_DB, dtype={'MatchID': str})
    
    def save(self, stats: MatchStats):
        try:
            df = self.get_all()
            already_exists = ((df['MatchID'] == str(stats.MatchID)) & (df['Jogador'] == stats.Jogador)).any()
            if not already_exists:
                pd.concat([df, pd.DataFrame([stats.model_dump()])], ignore_index=True).to_csv(self.FILE_DB, index=False)
                return True
            return False
        except: return False

    def reset_database(self):
        if os.path.exists(self.FILE_DB): os.remove(self.FILE_DB)
        self._create_db()
        return True

class RiotAdapter:
    def __init__(self, api_key):
        self.headers = {"X-Riot-Token": api_key}
        self.season_start = 1735689600 # 01/01/2026

    def fetch_matches(self, nome, tag, limit=15): # Padrão atualizado para 15
        try:
            # 1. Limpeza de URL
            tag_clean = tag.replace('#', '').strip()
            nome_enc = quote(nome.strip())
            tag_enc = quote(tag_clean)

            # 2. Account
            acc_url = f"https://americas.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{nome_enc}/{tag_enc}"
            acc_resp = requests.get(acc_url, headers=self.headers)
            if acc_resp.status_code != 200: return None, f"Erro Conta ({acc_resp.status_code})"
            puuid = acc_resp.json()['puuid']

            # 3. Match IDs (Ignorando filtro de fila para pegar tudo, limit 15)
            # &queue=440 (Flex) removido para pegar geral se quiserem, ou mantemos? 
            # O pedido foi "Season 6". Vou deixar aberto para pegar tudo da season.
            matches_url = f"https://americas.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids?startTime={self.season_start}&start=0&count={limit}"
            
            matches_resp = requests.get(matches_url, headers=self.headers)
            match_ids = matches_resp.json()
            
            if not match_ids: return [], None
            
            processed_data = []
            
            for m_id in match_ids:
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
                        
                        qid = d['info']['queueId']
                        # Mapeando filas comuns
                        tipo_str = 'Flex' if qid == 440 else ('SoloQ' if qid == 420 else ('ARAM' if qid == 450 else 'Normal'))
                        
                        processed_data.append(MatchStats(
                            MatchID=str(m_id),
                            Data=datetime.fromtimestamp(d['info']['gameCreation']/1000).strftime('%Y-%m-%d %H:%M'),
                            Timestamp=d['info']['gameCreation'],
                            Jogador=nome.upper(), Tipo=tipo_str,
                            Vitoria=p['win'], Score=sc, K=p['kills'], D=p['deaths'], A=p['assists'],
                            Part=p['challenges'].get('killParticipation', 0),
                            Dano_Estruturas=p['damageDealtToBuildings'],
                            DPM=round(p['totalDamageDealtToChampions']/mins, 2),
                            Pinks=p['visionWardsBoughtInGame']
                        ))
                time.sleep(0.05)
            return processed_data, None
        except Exception as e: return None, str(e)

# ==============================================================================
# 4. UI LAYER
# ==============================================================================
def safe_hex_to_rgba(hex_color, opacity=0.1):
    try:
        c = hex_color.lstrip('#')
        return f"rgba({int(c[0:2], 16)}, {int(c[2:4], 16)}, {int(c[4:6], 16)}, {opacity})"
    except: return hex_color

def render_dashboard():
    db = DatabaseAdapter()
    riot = RiotAdapter(st.secrets.get("RIOT_KEY", ""))

    # --- HEADER ---
    st.markdown("<div class='title-text'>⚔️ OFENSIVO SCORE ⚔️</div>", unsafe_allow_html=True)
    st.markdown("<div class='subtitle-text'>criado para jogadores ofensivos que gostam de rir e vencer</div>", unsafe_allow_html=True)

    # --- SIDEBAR ---
    with st.sidebar:
        st.header("🎮 Painel deidara HO")
        
        # BOTÃO MÁGICO DO SQUAD
        if st.button("🔄 ATUALIZAR LISTA COMPLETA", type="primary"):
            progress_text = "Iniciando atualização do Squad..."
            my_bar = st.progress(0, text=progress_text)
            
            total_saved = 0
            
            for idx, player in enumerate(SQUAD_LIST):
                nick = player['nick']
                tag = player['tag']
                
                my_bar.progress((idx / len(SQUAD_LIST)), text=f"Buscando: {nick} #{tag}...")
                
                # Busca 15 partidas
                matches, err = riot.fetch_matches(nick, tag, limit=15)
                
                if matches:
                    for m in matches:
                        if db.save(m): total_saved += 1
                
                time.sleep(0.5) # Respiro para API
                
            my_bar.progress(1.0, text="Atualização Concluída!")
            
            if total_saved > 0:
                st.success(f"✅ {total_saved} novas partidas encontradas para o grupo!")
                time.sleep(2)
                st.rerun()
            else:
                st.info("Nenhuma partida nova encontrada.")

        st.markdown("---")
        with st.expander("Opções Manuais"):
             if st.button("🗑️ Resetar Database"):
                db.reset_database()
                st.rerun()

    # --- DASHBOARD ---
    df = db.get_all()
    
    if df.empty:
        st.info("A base de dados está vazia. Clique no botão 'ATUALIZAR LISTA COMPLETA' na barra lateral!")
        return

    # Filtro Temporal Simples
    col_f, _ = st.columns([1, 4])
    with col_f:
        periodo = st.selectbox("📅 Período:", ["Season 2026", "Últimos 30 Dias"])
    
    now = datetime.now().timestamp() * 1000
    if periodo == "Últimos 30 Dias":
        df = df[df['Timestamp'] > (now - 2592000000)]
    
    if df.empty:
        st.warning("Sem dados neste período.")
        return

    # Tabs por Fila
    tipos = sorted(df['Tipo'].unique())
    tabs = st.tabs([f"🏆 {t}" for t in tipos])
    
    for i, tipo in enumerate(tipos):
        with tabs[i]:
            df_t = df[df['Tipo'] == tipo].copy()
            
            # KPIs
            k1, k2, k3, k4 = st.columns(4)
            top = df_t.groupby('Jogador')['Score'].sum().idxmax()
            k1.metric("🔥 MVP Ofensivo", top)
            k2.metric("💀 Rei do Dano", df_t.groupby('Jogador')['DPM'].mean().idxmax(), f"{df_t.groupby('Jogador')['DPM'].mean().max():.0f}")
            k3.metric("🎮 Partidas", len(df_t))
            k4.metric("📈 Média Score", f"{df_t['Score'].mean():.1f}")
            
            st.markdown("---")
            c1, c2 = st.columns([1, 2])
            
            with c1:
                st.subheader("Ranking Geral")
                rank = df_t.groupby('Jogador')['Score'].sum().sort_values(ascending=False).reset_index()
                rank.index += 1
                st.dataframe(rank.style.background_gradient(cmap='Reds', subset=['Score']), use_container_width=True)
                
            with c2:
                st.subheader("Evolução da Agressividade")
                df_t = df_t.sort_values('Timestamp')
                df_t['Acumulado'] = df_t.groupby('Jogador')['Score'].cumsum()
                
                fig = go.Figure()
                colors = px.colors.qualitative.Bold # Cores mais fortes
                
                for idx, player in enumerate(df_t['Jogador'].unique()):
                    d_p = df_t[df_t['Jogador'] == player]
                    color = colors[idx % len(colors)]
                    fill_rgba = safe_hex_to_rgba(color, 0.1)
                    
                    fig.add_trace(go.Scatter(
                        x=d_p['Data'], y=d_p['Acumulado'],
                        name=player,
                        mode='lines+markers',
                        line=dict(shape='spline', width=3, color=color),
                        fill='tozeroy',
                        fillcolor=fill_rgba
                    ))
                
                fig.update_layout(
                    template="plotly_dark",
                    paper_bgcolor='rgba(0,0,0,0)',
                    plot_bgcolor='rgba(0,0,0,0)',
                    hovermode="x unified",
                    legend=dict(orientation="h", y=1.1, x=0.5, xanchor='center')
                )
                st.plotly_chart(fig, use_container_width=True)

    # --- FOOTER ---
    st.markdown("<hr>", unsafe_allow_html=True)
    st.markdown("<div class='footer-group'>É o grupo</div>", unsafe_allow_html=True)
    st.markdown("<div class='footer-final'>deidara HO</div>", unsafe_allow_html=True)

if __name__ == "__main__":
    render_dashboard()
