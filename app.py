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
# 0. SQUAD LIST COMPLETA (12 JOGADORES)
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

# Unificação visual (Guiza)
NOME_DISPLAY = {
    "GUIZINHA": "GUIZA",
    "EZFALSE": "GUIZA",
    "GUIZA": "GUIZA"
}

# Sistema de Elos de Bravura
def get_elo_bravura(pontos):
    if pontos < 150: return "🌑 Ferro de Barro"
    if pontos < 400: return "🥉 Bronze Ofensivo"
    if pontos < 800: return "🥈 Prata de Respeito"
    if pontos < 1300: return "🥇 Ouro de deidara"
    if pontos < 2000: return "💎 Platina Elite"
    if pontos < 3000: return "🔥 Diamante de Sangue"
    return "🐉 DESAFIANTE HO"

# ==============================================================================
# 1. IDENTIDADE VISUAL
# ==============================================================================
st.set_page_config(page_title="OFENSIVO SCORE", layout="wide", page_icon="⚔️")

st.markdown("""
<style>
    .stApp { background-color: #0e1117; }
    h1, h2, h3 { font-family: 'Roboto', sans-serif; color: #ffffff; }
    
    div[data-testid="metric-container"] {
        background-color: #1a1c24;
        border-left: 4px solid #c8aa6e;
        padding: 15px;
        border-radius: 6px;
        box-shadow: 0 4px 10px rgba(0,0,0,0.5);
    }
    
    .medal-box {
        background: linear-gradient(145deg, #1e2328, #1a1c24);
        border: 1px solid #c8aa6e;
        padding: 20px;
        border-radius: 10px;
        text-align: center;
        box-shadow: 0 4px 15px rgba(0,0,0,0.6);
        height: 100%;
    }
    .medal-icon { font-size: 3em; margin-bottom: 10px; }
    .medal-title { color: #d4af37; font-weight: bold; font-size: 1.2em; text-transform: uppercase; }
    .medal-player { color: #ff4b4b; font-weight: bold; font-size: 1.8em; margin: 10px 0; }
    .medal-desc { color: #a0a0a0; font-style: italic; font-size: 0.9em; }

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
    MatchID: str; Data: str; Timestamp: float; Jogador: str; Tipo: str; Vitoria: bool; Score: float
    K: int; D: int; A: int; Part: float; Dano_Estruturas: int; DPM: float; Pinks: int
    RankRiot: Optional[str] = "Unranked"

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
        if os.path.exists(self.FILE_DB):
            try:
                df = pd.read_csv(self.FILE_DB)
                if 'RankRiot' not in df.columns:
                    df['RankRiot'] = 'Unranked'
                    df.to_csv(self.FILE_DB, index=False)
            except: pass
        else:
            pd.DataFrame(columns=MatchStats.model_fields.keys()).to_csv(self.FILE_DB, index=False)
    
    def get_all(self):
        try:
            df = pd.read_csv(self.FILE_DB, dtype={'MatchID': str})
            df['Jogador'] = df['Jogador'].apply(lambda x: NOME_DISPLAY.get(x.upper(), x.upper()))
            return df
        except: return pd.DataFrame()

    def save(self, stats: MatchStats):
        try:
            df = pd.read_csv(self.FILE_DB, dtype={'MatchID': str})
            # Salva se não existir (MatchID + Jogador)
            if not ((df['MatchID'] == str(stats.MatchID)) & (df['Jogador'] == stats.Jogador.upper())).any():
                pd.concat([df, pd.DataFrame([stats.model_dump()])], ignore_index=True).to_csv(self.FILE_DB, index=False)
                return True
            return False
        except: return False
    
    def reset_db(self):
        if os.path.exists(self.FILE_DB): os.remove(self.FILE_DB)

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
            acc_req = requests.get(f"https://americas.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{n}/{t}", headers=self.headers)
            
            # Se der erro 404 ou 403, retorna silenciosamente para não parar o loop
            if acc_req.status_code != 200: return None, f"Erro {acc_req.status_code}"
            
            acc = acc_req.json()
            puuid = acc['puuid']
            rank_flex = self.fetch_flex_rank(puuid)
            
            m_ids = requests.get(f"https://americas.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids?startTime=1735689600&start=0&count={limit}", headers=self.headers).json()
            
            data = []
            for m_id in m_ids:
                d_req = requests.get(f"https://americas.api.riotgames.com/lol/match/v5/matches/{m_id}", headers=self.headers)
                if d_req.status_code == 200:
                    d = d_req.json()
                    p = next((x for x in d['info']['participants'] if x['puuid'] == puuid), None)
                    if p:
                        mins = d['info']['gameDuration']/60
                        sc = BravuraEngine.calculate_score(p['win'], p['deaths'], p['challenges'].get('killParticipation', 0), p['damageDealtToBuildings'], p['totalDamageDealtToChampions'], mins, p['visionWardsBoughtInGame'])
                        qid = d['info']['queueId']
                        tipo = 'Flex' if qid == 440 else ('SoloQ' if qid == 420 else 'Outros')
                        data.append(MatchStats(MatchID=str(m_id), Data=datetime.fromtimestamp(d['info']['gameCreation']/1000).strftime('%d/%m'), Timestamp=d['info']['gameCreation'], Jogador=nome.upper(), Tipo=tipo, Vitoria=p['win'], Score=sc, K=p['kills'], D=p['deaths'], A=p['assists'], Part=p['challenges'].get('killParticipation', 0), Dano_Estruturas=p['damageDealtToBuildings'], DPM=round(p['totalDamageDealtToChampions']/mins, 1), Pinks=p['visionWardsBoughtInGame'], RankRiot=rank_flex))
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
        st.header("🎮 deidara HO")
        modo = st.radio("Ação:", ["Sincronizar Squad (API)", "Subir Print (Custom)"])
        
        st.markdown("---")
        if modo == "Sincronizar Squad (API)":
            if st.button("🔄 ATUALIZAR SQUAD"):
                bar = st.progress(0, text="Iniciando a busca...")
                status_box = st.empty()
                
                for idx, p in enumerate(SQUAD_LIST):
                    nome_completo = f"{p['nick']} #{p['tag']}"
                    bar.progress((idx)/len(SQUAD_LIST), text=f"Lendo: {nome_completo}")
                    
                    try:
                        matches, err = riot.fetch_matches(p['nick'], p['tag'])
                        if matches:
                            count = 0
                            for m in matches: 
                                if db.save(m): count += 1
                            status_box.info(f"✅ {p['nick']}: {count} novas partidas.")
                        elif err:
                            status_box.warning(f"⚠️ {p['nick']}: {err}")
                    except:
                        status_box.error(f"❌ Erro ao ler {p['nick']}")
                    
                    time.sleep(1) # Delay generoso para não travar
                
                bar.progress(1.0, text="Finalizado!")
                st.success("Atualização completa! Recarregue a página se necessário.")
                time.sleep(2)
                st.rerun()

        else:
            u_file = st.file_uploader("Upload Custom", type=['png','jpg'])
            p_name = st.text_input("Nick no Print").upper()
            if st.button("🤖 Analisar") and u_file and gemini:
                try:
                    prompt = f"Extraia stats LoL JSON para {p_name}: {{'vitoria':bool,'k':int,'d':int,'a':int,'part':float,'dano_est':int,'dano_camp':int,'min':int,'pinks':int}}"
                    raw = json.loads(gemini.generate_content([prompt, Image.open(u_file)]).text.replace('```json', '').replace('```', '').strip())
                    sc = BravuraEngine.calculate_score(raw['vitoria'], raw['d'], raw['part'], raw['dano_est'], raw['dano_camp'], raw['min'], raw['pinks'])
                    m = MatchStats(MatchID=f"c_{int(time.time())}", Data=datetime.now().strftime('%d/%m'), Timestamp=time.time()*1000, Jogador=p_name, Tipo='Custom', Vitoria=raw['vitoria'], Score=sc, K=raw['k'], D=raw['d'], A=raw['a'], Part=raw['part'], Dano_Estruturas=raw['dano_est'], DPM=round(raw['dano_camp']/raw['min'], 1), Pinks=raw['pinks'], RankRiot="Custom")
                    db.save(m)
                    st.success("Custom Salva!")
                    st.rerun()
                except: st.error("Erro ao ler imagem.")

        st.markdown("---")
        if st.button("🗑️ Resetar Tudo"):
            db.reset_db()
            st.rerun()

    df = db.get_all()
    if df.empty:
        st.info("Sincronize o Squad para começar!")
        return

    tab_rank, tab_medalhas, tab_custom = st.tabs(["🏆 RANKING GERAL", "🎖️ MURAL DE MEDALHAS", "👹 CUSTOMS"])

    with tab_rank:
        df_f = df[df['Tipo'] != 'Custom']
        if not df_f.empty:
            k1, k2, k3, k4 = st.columns(4)
            top_player = df_f.groupby('Jogador')['Score'].sum().idxmax()
            top_dmg = df_f.groupby('Jogador')['DPM'].mean().idxmax()
            k1.metric("🔥 MVP Ofensivo", top_player, "Líder Supremo")
            k2.metric("💀 Rei do Dano", top_dmg, f"Média: {df_f['DPM'].max():.0f}")
            k3.metric("🎮 Partidas", len(df_f), "Analisadas")
            k4.metric("📊 Score Médio", f"{df_f['Score'].mean():.1f}", "Global")

            st.markdown("---")
            
            c1, c2 = st.columns([1.2, 2])
            with c1:
                st.subheader("Leaderboard")
                leader = df_f.groupby('Jogador').agg({'Score': 'sum', 'RankRiot': 'last'}).sort_values('Score', ascending=False).reset_index()
                leader['Elo HO'] = leader['Score'].apply(get_elo_bravura)
                st.dataframe(leader[['Jogador', 'Elo HO', 'Score', 'RankRiot']].style.background_gradient(cmap='YlOrRd', subset=['Score']), use_container_width=True, height=450)

            with c2:
                st.subheader("Evolução")
                df_f = df_f.sort_values('Timestamp')
                df_f['Acumulado'] = df_f.groupby('Jogador')['Score'].cumsum()
                fig = go.Figure()
                colors = px.colors.qualitative.Pastel
                for idx, player in enumerate(df_f['Jogador'].unique()):
                    d_p = df_f[df_f['Jogador'] == player]
                    color = colors[idx % len(colors)]
                    fig.add_trace(go.Scatter(x=d_p['Data'], y=d_p['Acumulado'], name=player, mode='lines+markers', line=dict(shape='spline', width=3, color=color), fill='tozeroy', fillcolor=safe_hex_to_rgba(color, 0.1)))
                fig.update_layout(template="plotly_dark", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', hovermode="x unified", legend=dict(orientation="h", y=1.1))
                st.plotly_chart(fig, use_container_width=True)

    with tab_medalhas:
        df_f = df[df['Tipo'] != 'Custom']
        if not df_f.empty:
            st.subheader("Destaques da Temporada")
            m1, m2, m3, m4 = st.columns(4)
            agg = df_f.groupby('Jogador').agg({'DPM': 'mean', 'Score': 'sum', 'D': 'sum', 'Part': 'mean', 'Vitoria': 'sum'})
            
            with m1:
                ariel = agg.sort_values(['Part', 'Vitoria'], ascending=[True, True]).index[0]
                st.markdown(f"<div class='medal-box'><div class='medal-icon'>🐢</div><div class='medal-title'>ARIEL</div><div class='medal-player'>{ariel}</div><div class='medal-desc'>Safe Player</div></div>", unsafe_allow_html=True)
            with m2:
                danudo = agg['DPM'].idxmax()
                st.markdown(f"<div class='medal-box'><div class='medal-icon'>🧨</div><div class='medal-title'>DANUDO</div><div class='medal-player'>{danudo}</div><div class='medal-desc'>Maior Dano</div></div>", unsafe_allow_html=True)
            with m3:
                diniz = agg['Score'].idxmax()
                st.markdown(f"<div class='medal-box'><div class='medal-icon'>🔪</div><div class='medal-title'>DINIZ</div><div class='medal-player'>{diniz}</div><div class='medal-desc'>Mestre Bravura</div></div>", unsafe_allow_html=True)
            with m4:
                inimigo = agg['D'].idxmax()
                st.markdown(f"<div class='medal-box'><div class='medal-icon'>💀</div><div class='medal-title'>INIMIGO KDA</div><div class='medal-player'>{inimigo}</div><div class='medal-desc'>Feeder Oficial</div></div>", unsafe_allow_html=True)

    with tab_custom:
        df_c = df[df['Tipo'] == 'Custom']
        if not df_c.empty:
            st.dataframe(df_c.groupby('Jogador')['Score'].sum().sort_values(ascending=False).reset_index().style.background_gradient(cmap='Reds'), use_container_width=True)
            st.table(df_c[['Data', 'Jogador', 'Score', 'Vitoria']].tail(10))
        else: st.info("Nenhuma Custom registrada.")

    st.markdown("<hr><div class='footer-group'>É o grupo</div><div class='footer-final'>deidara HO</div>", unsafe_allow_html=True)

if __name__ == "__main__":
    render()
