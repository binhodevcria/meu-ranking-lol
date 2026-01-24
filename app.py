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

# ==============================================================================
# 0. CONFIGURAÇÃO SQUAD & MAPEAMENTO
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

# Unificação das contas do Guiza
NOME_DISPLAY = {
    "GUIZINHA": "GUIZA",
    "EZFALSE": "GUIZA",
    "GUIZA": "GUIZA"
}

st.set_page_config(page_title="OFENSIVO SCORE", layout="wide", page_icon="⚔️")

# ==============================================================================
# 1. IDENTIDADE VISUAL (Deltas Verdes e Cards Dourados)
# ==============================================================================
st.markdown("""
<style>
    .stApp { background-color: #0e1117; }
    h1, h2, h3 { font-family: 'Roboto', sans-serif; color: #ffffff; }
    
    /* Cards Dourados com Sombra */
    div[data-testid="metric-container"] {
        background-color: #1a1c24;
        border-left: 4px solid #c8aa6e;
        padding: 15px;
        border-radius: 6px;
        box-shadow: 0 4px 10px rgba(0,0,0,0.5);
    }
    
    /* Títulos deidara HO */
    .title-text { font-size: 3.5em; font-weight: bold; color: #ff4b4b; text-align: center; text-shadow: 2px 2px #000; }
    .subtitle-text { font-size: 1.2em; font-style: italic; color: #a0a0a0; text-align: center; margin-bottom: 30px; }
    .footer-group { font-size: 1.5em; color: #ffffff; text-align: left; margin-top: 50px; }
    .footer-final { font-size: 4em; font-weight: bold; color: #d4af37; text-align: center; margin-top: 10px; font-family: 'Impact'; letter-spacing: 5px; }
    
    .stButton>button { background-color: #1e2328; color: #cdbe91; border: 1px solid #463714; font-weight: bold; width: 100%; }
    .stButton>button:hover { border-color: #c8aa6e; color: #f0e6d2; }
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# 2. CORE LOGIC
# ==============================================================================
class MatchStats(BaseModel):
    MatchID: str; Data: str; Timestamp: float; Jogador: str; Tipo: str
    Vitoria: bool; Score: float; K: int; D: int; A: int; Part: float
    Dano_Estruturas: int; DPM: float; Pinks: int

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
# 3. INFRASTRUCTURE
# ==============================================================================
class DatabaseAdapter:
    FILE_DB = 'leaguestats_bravura.csv'
    def __init__(self):
        if not os.path.exists(self.FILE_DB):
            pd.DataFrame(columns=MatchStats.model_fields.keys()).to_csv(self.FILE_DB, index=False)
    
    def get_all(self):
        df = pd.read_csv(self.FILE_DB, dtype={'MatchID': str})
        df['Jogador'] = df['Jogador'].apply(lambda x: NOME_DISPLAY.get(x.upper(), x.upper()))
        return df

    def save(self, stats: MatchStats):
        df = pd.read_csv(self.FILE_DB, dtype={'MatchID': str})
        if not ((df['MatchID'] == str(stats.MatchID)) & (df['Jogador'] == stats.Jogador.upper())).any():
            pd.concat([df, pd.DataFrame([stats.model_dump()])], ignore_index=True).to_csv(self.FILE_DB, index=False)
            return True
        return False

class RiotAdapter:
    def __init__(self, api_key):
        self.headers = {"X-Riot-Token": api_key}
    
    def fetch_matches(self, nome, tag, limit=15):
        try:
            nome_enc, tag_enc = quote(nome.strip()), quote(tag.replace('#','').strip())
            acc = requests.get(f"https://americas.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{nome_enc}/{tag_enc}", headers=self.headers).json()
            puuid = acc['puuid']
            m_ids = requests.get(f"https://americas.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids?startTime=1735689600&start=0&count={limit}", headers=self.headers).json()
            
            data = []
            for m_id in m_ids:
                d = requests.get(f"https://americas.api.riotgames.com/lol/match/v5/matches/{m_id}", headers=self.headers).json()
                p = next(x for x in d['info']['participants'] if x['puuid'] == puuid)
                mins = d['info']['gameDuration']/60
                sc = BravuraEngine.calculate_score(p['win'], p['deaths'], p['challenges'].get('killParticipation', 0), p['damageDealtToBuildings'], p['totalDamageDealtToChampions'], mins, p['visionWardsBoughtInGame'])
                qid = d['info']['queueId']
                tipo = 'Flex' if qid == 440 else ('SoloQ' if qid == 420 else 'Outros')
                data.append(MatchStats(MatchID=str(m_id), Data=datetime.fromtimestamp(d['info']['gameCreation']/1000).strftime('%Y-%m-%d %H:%M'), Timestamp=d['info']['gameCreation'], Jogador=nome.upper(), Tipo=tipo, Vitoria=p['win'], Score=sc, K=p['kills'], D=p['deaths'], A=p['assists'], Part=p['challenges'].get('killParticipation', 0), Dano_Estruturas=p['damageDealtToBuildings'], DPM=round(p['totalDamageDealtToChampions']/mins, 2), Pinks=p['visionWardsBoughtInGame']))
            return data, None
        except Exception as e: return None, str(e)

# ==============================================================================
# 4. DASHBOARD UI
# ==============================================================================
def safe_hex_to_rgba(hex_color, opacity=0.1):
    try:
        c = hex_color.lstrip('#')
        return f"rgba({int(c[0:2], 16)}, {int(c[2:4], 16)}, {int(c[4:6], 16)}, {opacity})"
    except: return hex_color

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
            if st.button("🔄 ATUALIZAR LISTA COMPLETA"):
                bar = st.progress(0, text="Buscando...")
                saved = 0
                for idx, p in enumerate(SQUAD_LIST):
                    bar.progress(idx/len(SQUAD_LIST), text=f"Buscando {p['nick']}...")
                    matches, _ = riot.fetch_matches(p['nick'], p['tag'])
                    if matches:
                        for m in matches: 
                            if db.save(m): saved += 1
                    time.sleep(0.5)
                st.success(f"Finalizado! +{saved} partidas.")
                st.rerun()
        else:
            file = st.file_uploader("Upload Print", type=['png','jpg'])
            p_name = st.text_input("Nick no Print (Ex: Guiza)").upper()
            if st.button("🤖 Analisar") and file and gemini:
                prompt = f"Extraia stats LoL JSON para {p_name}: {{'vitoria':bool,'k':int,'d':int,'a':int,'part':float,'dano_est':int,'dano_camp':int,'min':int,'pinks':int}}"
                raw = json.loads(gemini.generate_content([prompt, Image.open(file)]).text.replace('```json', '').replace('```', '').strip())
                sc = BravuraEngine.calculate_score(raw['vitoria'], raw['d'], raw['part'], raw['dano_est'], raw['dano_camp'], raw['min'], raw['pinks'])
                db.save(MatchStats(MatchID=f"c_{int(time.time())}", Data=datetime.now().strftime('%Y-%m-%d %H:%M'), Timestamp=time.time()*1000, Jogador=p_name, Tipo='Custom', Vitoria=raw['vitoria'], Score=sc, K=raw['k'], D=raw['d'], A=raw['a'], Part=raw['part'], Dano_Estruturas=raw['dano_est'], DPM=round(raw['dano_camp']/raw['min'], 2), Pinks=raw['pinks']))
                st.rerun()

    df = db.get_all()
    if df.empty: return

    tab_f, tab_c = st.tabs(["🏆 OFICIAIS (API)", "👹 CUSTOMS (PRINTS)"])
    
    with tab_f:
        df_f = df[df['Tipo'] != 'Custom']
        if not df_f.empty:
            k1, k2, k3, k4 = st.columns(4)
            # Destaques com o "Delta Verde" (Número pequeno em verde)
            k1.metric("🔥 MVP Ofensivo", df_f.groupby('Jogador')['Score'].sum().idxmax(), "Status: ATIVO")
            k2.metric("💀 Rei do Dano", df_f.groupby('Jogador')['DPM'].mean().idxmax(), f"{df_f['DPM'].max():.0f} MAX")
            k3.metric("🎮 Jogos", len(df_f), f"+{len(df_f[df_f['Timestamp'] > (time.time()*1000 - 86400000)])} HOJE")
            k4.metric("📈 Média Score", f"{df_f['Score'].mean():.1f}", "BRAVURA")
            
            st.markdown("---")
            c1, c2 = st.columns([1, 2.2])
            with c1:
                st.subheader("Leaderboard")
                rank = df_f.groupby('Jogador')['Score'].sum().sort_values(ascending=False).reset_index()
                rank.index += 1
                # Tabela Colorida Restaurada
                st.dataframe(rank.style.background_gradient(cmap='YlOrRd', subset=['Score']), use_container_width=True)
            with c2:
                st.subheader("Evolução (Spline)")
                df_f = df_f.sort_values('Timestamp')
                df_f['Acumulado'] = df_f.groupby('Jogador')['Score'].cumsum()
                fig = go.Figure()
                colors = px.colors.qualitative.Pastel
                for idx, player in enumerate(df_f['Jogador'].unique()):
                    d_p = df_f[df_f['Jogador'] == player]; color = colors[idx % len(colors)]
                    fig.add_trace(go.Scatter(x=d_p['Data'], y=d_p['Acumulado'], name=player, mode='lines+markers', line=dict(shape='spline', width=3, color=color), fill='tozeroy', fillcolor=safe_hex_to_rgba(color, 0.1)))
                fig.update_layout(template="plotly_dark", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', hovermode="x unified", legend=dict(orientation="h", y=1.1, x=0.5, xanchor='center'))
                st.plotly_chart(fig, use_container_width=True)

    with tab_c:
        df_c = df[df['Tipo'] == 'Custom']
        if not df_c.empty:
            st.subheader("Leaderboard Customs")
            rank_c = df_c.groupby('Jogador')['Score'].sum().sort_values(ascending=False).reset_index()
            st.dataframe(rank_c.style.background_gradient(cmap='Reds', subset=['Score']), use_container_width=True)
            st.subheader("Histórico de Resenha")
            st.table(df_c[['Data', 'Jogador', 'Score', 'Vitoria']].tail(10))

    st.markdown("<hr><div class='footer-group'>É o grupo</div><div class='footer-final'>deidara HO</div>", unsafe_allow_html=True)

if __name__ == "__main__":
    render()
