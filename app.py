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
# 0. SQUAD LIST & CONFIGS
# ==============================================================================
SQUAD_LIST = [
    {"nick": "Gabinho", "tag": "INTEN"},
    {"nick": "Naguinha", "tag": "INTEN"},
    {"nick": "Guiza", "tag": "INTEN"},
    {"nick": "Rebeca Diana", "tag": "eGIRL"},
    {"nick": "Sylas 1v9", "tag": "BR1"},
    {"nick": "O Magro de OZ", "tag": "BR1"},
    {"nick": "PabIo Escobar", "tag": "INTEN"},
    {"nick": "Murakami UHULL", "tag": "BR1"},
    {"nick": "FEFE TA DE SWAIN", "tag": "DEMON"},
    {"nick": "MEC Viper", "tag": "MEC"}
]

st.set_page_config(page_title="OFENSIVO SCORE", layout="wide", page_icon="⚔️")

# ==============================================================================
# 1. ESTILIZAÇÃO DEIDARA HO
# ==============================================================================
st.markdown("""
<style>
    .stApp { background-color: #0e1117; }
    h1, h2, h3 { font-family: 'Roboto', sans-serif; color: #ffffff; }
    div[data-testid="metric-container"] {
        background-color: #1a1c24; border-left: 4px solid #ff4b4b; padding: 15px; border-radius: 6px;
    }
    .title-text { font-size: 3.5em; font-weight: bold; color: #ff4b4b; text-align: center; text-shadow: 2px 2px #000; }
    .subtitle-text { font-size: 1.2em; font-style: italic; color: #a0a0a0; text-align: center; margin-bottom: 30px; }
    .footer-group { font-size: 1.5em; color: #ffffff; text-align: left; margin-top: 50px; }
    .footer-final { font-size: 4em; font-weight: bold; color: #d4af37; text-align: center; margin-top: 10px; font-family: 'Impact'; letter-spacing: 5px; }
    .stButton>button { background-color: #2b313e; color: white; border: 1px solid #ff4b4b; border-radius: 5px; width: 100%; }
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# 2. CORE LOGIC (Bravura Engine)
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
# 3. INFRASTRUCTURE (Data & API)
# ==============================================================================
class DatabaseAdapter:
    FILE_DB = 'leaguestats_bravura.csv'
    def __init__(self):
        if not os.path.exists(self.FILE_DB):
            pd.DataFrame(columns=MatchStats.model_fields.keys()).to_csv(self.FILE_DB, index=False)
    def get_all(self):
        return pd.read_csv(self.FILE_DB, dtype={'MatchID': str})
    def save(self, stats: MatchStats):
        df = self.get_all()
        if not ((df['MatchID'] == str(stats.MatchID)) & (df['Jogador'] == stats.Jogador)).any():
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

class GeminiAdapter:
    def __init__(self, api_key):
        if api_key:
            genai.configure(api_key=api_key)
            self.model = genai.GenerativeModel('models/gemini-1.5-flash')
    def analyze(self, image, player_name):
        prompt = f"Extraia stats LoL JSON para {player_name}: {{'vitoria':bool,'k':int,'d':int,'a':int,'part':float,'dano_est':int,'dano_camp':int,'min':int,'pinks':int}}"
        resp = self.model.generate_content([prompt, image])
        return json.loads(resp.text.replace('```json', '').replace('```', '').strip())

# ==============================================================================
# 4. DASHBOARD UI
# ==============================================================================
def render():
    db = DatabaseAdapter()
    riot = RiotAdapter(st.secrets.get("RIOT_KEY", ""))
    gemini = GeminiAdapter(st.secrets.get("GEMINI_KEY", ""))

    st.markdown("<div class='title-text'>⚔️ OFENSIVO SCORE ⚔️</div>", unsafe_allow_html=True)
    st.markdown("<div class='subtitle-text'>criado para jogadores ofensivos que gostam de rir e vencer</div>", unsafe_allow_html=True)

    with st.sidebar:
        st.header("🎮 Painel deidara HO")
        acao = st.radio("Ação:", ["Sincronizar Squad (API)", "Subir Print (Custom)"])
        
        if acao == "Sincronizar Squad (API)":
            if st.button("🔄 ATUALIZAR LISTA COMPLETA"):
                bar = st.progress(0, text="Iniciando...")
                saved = 0
                for idx, p in enumerate(SQUAD_LIST):
                    bar.progress(idx/len(SQUAD_LIST), text=f"Buscando {p['nick']}...")
                    matches, _ = riot.fetch_matches(p['nick'], p['tag'])
                    if matches:
                        for m in matches: 
                            if db.save(m): saved += 1
                    time.sleep(0.5)
                st.success(f"Feito! +{saved} partidas.")
                st.rerun()
        else:
            file = st.file_uploader("Print da Custom", type=['png','jpg'])
            p_name = st.text_input("Nick no Print").upper()
            if st.button("🤖 Analisar Print") and file:
                raw = gemini.analyze(Image.open(file), p_name)
                sc = BravuraEngine.calculate_score(raw['vitoria'], raw['d'], raw['part'], raw['dano_est'], raw['dano_camp'], raw['min'], raw['pinks'])
                db.save(MatchStats(MatchID=f"c_{int(time.time())}", Data=datetime.now().strftime('%Y-%m-%d %H:%M'), Timestamp=time.time()*1000, Jogador=p_name, Tipo='Custom', Vitoria=raw['vitoria'], Score=sc, K=raw['k'], D=raw['d'], A=raw['a'], Part=raw['part'], Dano_Estruturas=raw['dano_est'], DPM=round(raw['dano_camp']/raw['min'], 2), Pinks=raw['pinks']))
                st.success("Custom salva!")
                st.rerun()

    df = db.get_all()
    if df.empty:
        st.info("Sem dados. Use a lateral!")
        return

    # Tabs (Flex/SoloQ e Custom)
    tab_f, tab_c = st.tabs(["🏆 OFICIAIS (API)", "👹 CUSTOMS (PRINTS)"])
    
    with tab_f:
        df_f = df[df['Tipo'] != 'Custom']
        if not df_f.empty:
            k1, k2 = st.columns(2)
            k1.metric("🔥 MVP Ofensivo", df_f.groupby('Jogador')['Score'].sum().idxmax())
            k2.metric("💀 Rei do Dano", df_f.groupby('Jogador')['DPM'].mean().idxmax())
            st.dataframe(df_f.groupby('Jogador')['Score'].sum().sort_values(ascending=False).reset_index(), use_container_width=True)
            # Gráfico Spline
            df_f = df_f.sort_values('Timestamp')
            df_f['Acumulado'] = df_f.groupby('Jogador')['Score'].cumsum()
            fig = px.line(df_f, x='Data', y='Acumulado', color='Jogador', markers=True, template='plotly_dark')
            fig.update_traces(line_shape='spline')
            st.plotly_chart(fig, use_container_width=True)

    with tab_c:
        df_c = df[df['Tipo'] == 'Custom']
        if not df_c.empty:
            st.subheader("Leaderboard das Customs")
            st.dataframe(df_c.groupby('Jogador')['Score'].sum().sort_values(ascending=False).reset_index(), use_container_width=True)
            st.subheader("Histórico de Bravura")
            st.dataframe(df_c[['Data', 'Jogador', 'Score', 'Vitoria']], use_container_width=True)
        else: st.warning("Nenhuma Custom subida via print ainda.")

    st.markdown("<hr><div class='footer-group'>É o grupo</div><div class='footer-final'>deidara HO</div>", unsafe_allow_html=True)

if __name__ == "__main__":
    render()
