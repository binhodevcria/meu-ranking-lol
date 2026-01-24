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
# 0. SQUAD LIST & COTAS DE EQUIDADE
# ==============================================================================
# Define quantos jogos puxar no total por "Entidade"
GLOBAL_GAME_TARGET = 15 

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

# Mapeamento para visualização unificada
NOME_DISPLAY = {
    "GUIZINHA": "GUIZA",
    "EZFALSE": "GUIZA",
    "GUIZA": "GUIZA"
}

# Conta quantas contas cada "Entidade" tem para dividir a cota
ACCOUNT_COUNTS = {}
for p in SQUAD_LIST:
    real_name = NOME_DISPLAY.get(p['nick'].upper(), p['nick'].upper())
    ACCOUNT_COUNTS[real_name] = ACCOUNT_COUNTS.get(real_name, 0) + 1

st.set_page_config(page_title="OFENSIVO SCORE", layout="wide", page_icon="⚔️")

# ==============================================================================
# 1. IDENTIDADE VISUAL (PRESERVADA)
# ==============================================================================
st.markdown("""
<style>
    .stApp { background-color: #0e1117; }
    h1, h2, h3 { font-family: 'Roboto', sans-serif; color: #ffffff; }
    
    div[data-testid="metric-container"] {
        background-color: #1a1c24; border-left: 4px solid #c8aa6e;
        padding: 15px; border-radius: 6px; box-shadow: 0 4px 10px rgba(0,0,0,0.5);
    }
    
    .medal-box {
        background: linear-gradient(145deg, #1e2328, #1a1c24); border: 1px solid #c8aa6e;
        padding: 20px; border-radius: 10px; text-align: center;
        box-shadow: 0 4px 15px rgba(0,0,0,0.6); height: 100%;
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
# 2. CORE LOGIC (FÓRMULA & RANKINGS)
# ==============================================================================
class MatchStats(BaseModel):
    MatchID: str; Data: str; Timestamp: float; Jogador: str; Tipo: str
    Vitoria: bool; Score: float; K: int; D: int; A: int; Part: float
    Dano_Estruturas: int; DPM: float; Pinks: int

class BravuraEngine:
    @staticmethod
    def calculate_score(vitoria, d, part, dano_est, dano_camp, minutos, pinks):
        if minutos < 10: return 0.0 # Remake
        
        score = 25.0 if vitoria else 0.0
        score += (part * 40)
        dpm = dano_camp / minutos if minutos > 0 else 0
        score += (dpm / 100)
        score += (dano_est / 500) # Estruturas inclusas
        score += (pinks * 1.0)    # Visão reduzida
        
        if d <= 2 and part < 0.35: score -= 25.0 # Penalidade Safe Player
        return round(score, 2)

def get_rank_bravura(media):
    if pd.isna(media) or media == 0: return "💤 Inativo"
    if media < 20: return "🛡️ Defesa"
    if media < 40: return "🌿 Herbívoro"
    if media < 60: return "🤝 Honra Tentou"
    if media < 80: return "⚔️ Ofensivo"
    return "💉 Viciado em Dopamina"

# ==============================================================================
# 3. INFRASTRUCTURE
# ==============================================================================
class DatabaseAdapter:
    FILE_DB = 'leaguestats_bravura.csv'
    def __init__(self):
        if not os.path.exists(self.FILE_DB):
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
            if not ((df['MatchID'] == str(stats.MatchID)) & (df['Jogador'] == stats.Jogador.upper())).any():
                pd.concat([df, pd.DataFrame([stats.model_dump()])], ignore_index=True).to_csv(self.FILE_DB, index=False)
                return True
            return False
        except: return False
    
    def reset_database(self):
        if os.path.exists(self.FILE_DB): os.remove(self.FILE_DB)
        pd.DataFrame(columns=MatchStats.model_fields.keys()).to_csv(self.FILE_DB, index=False)
        return True

class RiotAdapter:
    def __init__(self, api_key):
        self.headers = {"X-Riot-Token": api_key}
        self.season_start = 1735689600 # 2026

    def request_blindado(self, url):
        """Gerencia 429 automaticamente"""
        for i in range(3):
            resp = requests.get(url, headers=self.headers)
            if resp.status_code == 200: return resp.json()
            elif resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", 10))
                st.toast(f"⏳ Pausa Riot: {wait}s...", icon="🛑")
                time.sleep(wait + 1)
                continue
            elif resp.status_code == 404: return None
            else: return None
        return None

    def fetch_matches_with_quota(self, nome, tag, quota_limit):
        """
        Busca profunda (100 jogos) mas só retorna 'quota_limit' jogos FLEX.
        Garante a equidade exata.
        """
        try:
            n, t = quote(nome.strip()), quote(tag.replace('#','').strip())
            acc = self.request_blindado(f"https://americas.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{n}/{t}")
            if not acc: return None, 0, "Conta não achada"
            puuid = acc['puuid']

            # BUSCA PROFUNDA (100): Pega tudo pra filtrar depois
            m_ids = self.request_blindado(f"https://americas.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids?startTime={self.season_start}&start=0&count=100")
            if not m_ids: return [], 0, "Sem histórico"
            
            data = []
            flex_collected = 0
            
            for m_id in m_ids:
                # SE ATINGIU A COTA (Ex: 5 jogos pro Guiza, 15 pro Sylas), PARA DE PROCESSAR
                if flex_collected >= quota_limit:
                    break 

                d = self.request_blindado(f"https://americas.api.riotgames.com/lol/match/v5/matches/{m_id}")
                if d:
                    # FILTRO RIGOROSO: SOMENTE FLEX (440)
                    if d['info']['queueId'] == 440:
                        p = next((x for x in d['info']['participants'] if x['puuid'] == puuid), None)
                        if p:
                            mins = d['info']['gameDuration']/60
                            sc = BravuraEngine.calculate_score(p['win'], p['deaths'], p['challenges'].get('killParticipation', 0), p['damageDealtToBuildings'], p['totalDamageDealtToChampions'], mins, p['visionWardsBoughtInGame'])
                            
                            data.append(MatchStats(MatchID=str(m_id), Data=datetime.fromtimestamp(d['info']['gameCreation']/1000).strftime('%d/%m'), Timestamp=d['info']['gameCreation'], Jogador=nome.upper(), Tipo='Flex', Vitoria=p['win'], Score=sc, K=p['kills'], D=p['deaths'], A=p['assists'], Part=p['challenges'].get('killParticipation', 0), Dano_Estruturas=p['damageDealtToBuildings'], DPM=round(p['totalDamageDealtToChampions']/mins, 2), Pinks=p['visionWardsBoughtInGame']))
                            
                            flex_collected += 1
                
                time.sleep(0.1)
            
            return data, flex_collected, "OK"
        except Exception as e: return None, 0, str(e)

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
            if st.button("🔄 ATUALIZAR COM COTA DE EQUIDADE"):
                
                status_container = st.status("Processando cotas de partidas...", expanded=True)
                total_global = 0
                
                for idx, p in enumerate(SQUAD_LIST):
                    real_name = NOME_DISPLAY.get(p['nick'].upper(), p['nick'].upper())
                    
                    # CÁLCULO DA COTA INDIVIDUAL
                    # Se Meta=15 e Guiza tem 3 contas -> Cota = 5
                    # Se Meta=15 e Sylas tem 1 conta -> Cota = 15
                    my_quota = int(GLOBAL_GAME_TARGET / ACCOUNT_COUNTS[real_name])
                    
                    status_container.write(f"🔎 {p['nick']} (Meta: {my_quota} Flex Recentes)...")
                    
                    matches, count, msg = riot.fetch_matches_with_quota(p['nick'], p['tag'], quota_limit=my_quota)
                    
                    if matches is not None:
                        saved = 0
                        for m in matches: 
                            if db.save(m): saved += 1
                        
                        total_global += saved
                        if count == my_quota:
                            status_container.write(f"✅ {p['nick']}: Cota Atingida ({count}/{my_quota} Flex)")
                        else:
                            status_container.write(f"⚠️ {p['nick']}: Parcial ({count}/{my_quota} Flex)")
                    else:
                        status_container.error(f"❌ {p['nick']}: {msg}")
                    
                    time.sleep(0.5)
                
                status_container.update(label="Ciclo Finalizado!", state="complete", expanded=False)
                if total_global > 0:
                    st.success(f"Sucesso! +{total_global} partidas sincronizadas.")
                    time.sleep(2)
                    st.rerun()
                else: st.info("Nenhuma partida nova para a cota atual.")

        else:
            file = st.file_uploader("Upload Print", type=['png','jpg'])
            p_name = st.text_input("Nick no Print (Ex: Guiza)").upper()
            if st.button("🤖 Analisar") and file and gemini:
                try:
                    prompt = f"Extraia stats LoL JSON para {p_name}: {{'vitoria':bool,'k':int,'d':int,'a':int,'part':float,'dano_est':int,'dano_camp':int,'min':int,'pinks':int}}"
                    raw = json.loads(gemini.generate_content([prompt, Image.open(file)]).text.replace('```json', '').replace('```', '').strip())
                    sc = BravuraEngine.calculate_score(raw['vitoria'], raw['d'], raw['part'], raw['dano_est'], raw['dano_camp'], raw['min'], raw['pinks'])
                    m = MatchStats(MatchID=f"c_{int(time.time())}", Data=datetime.now().strftime('%d/%m'), Timestamp=time.time()*1000, Jogador=p_name, Tipo='Custom', Vitoria=raw['vitoria'], Score=sc, K=raw['k'], D=raw['d'], A=raw['a'], Part=raw['part'], Dano_Estruturas=raw['dano_est'], DPM=round(raw['dano_camp']/raw['min'], 2), Pinks=raw['pinks'])
                    db.save(m)
                    st.success("Custom salva!")
                    st.rerun()
                except: st.error("Erro na leitura.")

        st.markdown("---")
        if st.button("🗑️ Resetar Database"):
            db.reset_database()
            st.rerun()

    df = db.get_all()
    # Lista de todos para garantir que quem tem 0 jogos apareça
    todos_nomes = sorted(list(ACCOUNT_COUNTS.keys()))

    tab_f, tab_m, tab_c = st.tabs(["🏆 RANKING OFENSIVO", "🎖️ MURAL DE MEDALHAS", "👹 CUSTOMS"])
    
    with tab_f:
        if not df.empty:
            df_f = df[df['Tipo'] != 'Custom']
        else:
            df_f = pd.DataFrame()

        # KPIs
        k1, k2, k3, k4 = st.columns(4)
        if not df_f.empty:
            mvp_name = df_f.groupby('Jogador')['Score'].mean().idxmax()
            mvp_val = df_f.groupby('Jogador')['Score'].mean().max()
            jogos_hoje = len(df_f[df_f['Timestamp'] > (time.time()*1000 - 86400000)])
            
            k1.metric("🔥 MVP (Média)", mvp_name, f"{mvp_val:.1f}")
            k2.metric("💀 Rei do Dano", df_f.groupby('Jogador')['DPM'].mean().idxmax(), f"{df_f['DPM'].max():.0f}")
            k3.metric("🎮 Flex Games", len(df_f), f"+{jogos_hoje} Hoje")
            k4.metric("📈 Média Squad", f"{df_f['Score'].mean():.1f}")
        
        st.markdown("---")
        c1, c2 = st.columns([1.5, 2])
        
        with c1:
            st.subheader("Classificação (0-100)")
            stats_data = []
            for player in todos_nomes:
                p_df = df_f[df_f['Jogador'] == player] if not df_f.empty else pd.DataFrame()
                if not p_df.empty:
                    media = p_df['Score'].mean()
                    stats_data.append({
                        'Jogador': player,
                        'Média Score': media,
                        'Jogos': len(p_df),
                        'Dano Médio': p_df['DPM'].mean()
                    })
                else:
                    stats_data.append({'Jogador': player, 'Média Score': 0.0, 'Jogos': 0, 'Dano Médio': 0.0})
            
            leaderboard = pd.DataFrame(stats_data).sort_values('Média Score', ascending=False)
            leaderboard['Rank deidara'] = leaderboard['Média Score'].apply(get_rank_bravura)
            
            st.dataframe(
                leaderboard[['Jogador', 'Rank deidara', 'Média Score', 'Jogos', 'Dano Médio']].style.background_gradient(cmap='YlOrRd', subset=['Média Score']), 
                use_container_width=True, height=500
            )
        
        with c2:
            st.subheader("Histórico (Acumulado)")
            if not df_f.empty:
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
            else: st.info("Sem dados para gráfico.")

    with tab_m:
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
                diniz = agg['Score'].idxmax() # Diniz ganha quem tem maior SOMA (Bravura Total)
                st.markdown(f"<div class='medal-box'><div class='medal-icon'>🔪</div><div class='medal-title'>DINIZ</div><div class='medal-player'>{diniz}</div><div class='medal-desc'>Mestre Bravura</div></div>", unsafe_allow_html=True)
            with m4:
                inimigo = agg['D'].idxmax()
                st.markdown(f"<div class='medal-box'><div class='medal-icon'>💀</div><div class='medal-title'>INIMIGO KDA</div><div class='medal-player'>{inimigo}</div><div class='medal-desc'>Feeder Oficial</div></div>", unsafe_allow_html=True)

    with tab_c:
        if not df.empty:
            df_c = df[df['Tipo'] == 'Custom']
            if not df_c.empty:
                rank_c = df_c.groupby('Jogador')['Score'].mean().sort_values(ascending=False).reset_index()
                rank_c.columns = ['Jogador', 'Média Score']
                st.dataframe(rank_c.style.background_gradient(cmap='Reds', subset=['Média Score']), use_container_width=True)
                st.table(df_c[['Data', 'Jogador', 'Score', 'Vitoria']].tail(10))

    st.markdown("<hr><div class='footer-group'>É o grupo</div><div class='footer-final'>deidara HO</div>", unsafe_allow_html=True)

if __name__ == "__main__":
    render()
