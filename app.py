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
# 0. SQUAD LIST (12 JOGADORES)
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

# Unificação de Contas (Visual)
NOME_DISPLAY = {
    "GUIZINHA": "GUIZA",
    "EZFALSE": "GUIZA",
    "GUIZA": "GUIZA"
}

st.set_page_config(page_title="OFENSIVO SCORE", layout="wide", page_icon="⚔️")

# ==============================================================================
# 1. IDENTIDADE VISUAL (Sua preferida)
# ==============================================================================
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
        if minutos < 5: return 0.0
        score = 25.0 if vitoria else 0.0
        score += (part * 40)
        dpm = dano_camp / minutos if minutos > 0 else 0
        score += (dpm / 100)
        score += (dano_est / 500)
        score += (pinks * 2)
        if d <= 2 and part < 0.35: score -= 25.0
        return round(score, 2)

# ==============================================================================
# 3. INFRASTRUCTURE & BANCO
# ==============================================================================
class DatabaseAdapter:
    FILE_DB = 'leaguestats_bravura.csv'
    def __init__(self):
        if not os.path.exists(self.FILE_DB):
            pd.DataFrame(columns=MatchStats.model_fields.keys()).to_csv(self.FILE_DB, index=False)
    
    def get_all(self):
        try:
            df = pd.read_csv(self.FILE_DB, dtype={'MatchID': str})
            # Aplica unificação apenas na leitura visual
            df['Jogador'] = df['Jogador'].apply(lambda x: NOME_DISPLAY.get(x.upper(), x.upper()))
            return df
        except: return pd.DataFrame()

    def save(self, stats: MatchStats):
        try:
            df = pd.read_csv(self.FILE_DB, dtype={'MatchID': str})
            # Evita duplicidade exata
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

    # --- O SEGREDO DO SUCESSO: REQUEST BLINDADO ---
    def request_blindado(self, url):
        """Tenta fazer a requisição. Se der 429, espera o tempo necessário."""
        while True:
            resp = requests.get(url, headers=self.headers)
            
            if resp.status_code == 200:
                return resp.json()
            
            elif resp.status_code == 429:
                # Pega o tempo que a Riot mandou esperar (Retry-After)
                wait_time = int(resp.headers.get("Retry-After", 60))
                # Aviso visual para o usuário não achar que travou
                st.toast(f"🛑 Limite da Riot atingido! Aguardando {wait_time} segundos...", icon="⏳")
                time.sleep(wait_time + 1) # Espera +1s de segurança
                continue # Tenta de novo
            
            else:
                # Erro real (404, 403, etc)
                return None

    def fetch_matches(self, nome, tag, limit=15):
        try:
            nome_enc, tag_enc = quote(nome.strip()), quote(tag.replace('#','').strip())
            
            # 1. Conta
            acc = self.request_blindado(f"https://americas.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{nome_enc}/{tag_enc}")
            if not acc: return None, "Erro ao buscar Conta/Nick"
            
            puuid = acc['puuid']

            # 2. Lista de IDs
            m_ids = self.request_blindado(f"https://americas.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids?startTime={self.season_start}&start=0&count={limit}")
            if not m_ids: return [], None
            
            data = []
            for m_id in m_ids:
                # 3. Detalhes (Blindado)
                d = self.request_blindado(f"https://americas.api.riotgames.com/lol/match/v5/matches/{m_id}")
                
                if d:
                    p = next((x for x in d['info']['participants'] if x['puuid'] == puuid), None)
                    if p:
                        mins = d['info']['gameDuration']/60
                        sc = BravuraEngine.calculate_score(p['win'], p['deaths'], p['challenges'].get('killParticipation', 0), p['damageDealtToBuildings'], p['totalDamageDealtToChampions'], mins, p['visionWardsBoughtInGame'])
                        qid = d['info']['queueId']
                        tipo = 'Flex' if qid == 440 else ('SoloQ' if qid == 420 else 'Outros')
                        data.append(MatchStats(MatchID=str(m_id), Data=datetime.fromtimestamp(d['info']['gameCreation']/1000).strftime('%Y-%m-%d %H:%M'), Timestamp=d['info']['gameCreation'], Jogador=nome.upper(), Tipo=tipo, Vitoria=p['win'], Score=sc, K=p['kills'], D=p['deaths'], A=p['assists'], Part=p['challenges'].get('killParticipation', 0), Dano_Estruturas=p['damageDealtToBuildings'], DPM=round(p['totalDamageDealtToChampions']/mins, 2), Pinks=p['visionWardsBoughtInGame']))
                
                # Pequena pausa ética para não forçar o 429 toda hora
                time.sleep(0.5)
            
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
        
        st.markdown("---")
        
        if acao == "Sincronizar Squad (API)":
            if st.button("🔄 ATUALIZAR LISTA COMPLETA"):
                # Barra de Progresso Real
                bar = st.progress(0, text="Iniciando motor de busca blindado...")
                log_box = st.empty()
                total_salvo_geral = 0
                
                total_jogadores = len(SQUAD_LIST)
                
                for idx, p in enumerate(SQUAD_LIST):
                    display_name = f"{p['nick']} ({idx+1}/{total_jogadores})"
                    bar.progress(idx / total_jogadores, text=f"Lendo: {display_name}...")
                    
                    matches, err = riot.fetch_matches(p['nick'], p['tag'])
                    
                    if matches:
                        novos = 0
                        for m in matches:
                            if db.save(m): novos += 1
                        total_salvo_geral += novos
                        if novos > 0:
                            st.toast(f"✅ {p['nick']}: +{novos} jogos salvos!", icon="💾")
                    elif err:
                        st.toast(f"⚠️ {p['nick']}: {err}", icon="⚠️")
                    
                    # Atualiza o log visual na sidebar
                    log_box.text(f"Último processado: {p['nick']}")
                
                bar.progress(1.0, text="Processo Finalizado!")
                
                if total_salvo_geral > 0:
                    st.success(f"Sucesso Total! +{total_salvo_geral} novas partidas no histórico.")
                    time.sleep(3)
                    st.rerun()
                else:
                    st.info("Nenhuma partida nova encontrada (os dados já estavam atualizados).")

        else:
            file = st.file_uploader("Upload Print", type=['png','jpg'])
            p_name = st.text_input("Nick no Print (Ex: Guiza)").upper()
            if st.button("🤖 Analisar") and file and gemini:
                try:
                    prompt = f"Extraia stats LoL JSON para {p_name}: {{'vitoria':bool,'k':int,'d':int,'a':int,'part':float,'dano_est':int,'dano_camp':int,'min':int,'pinks':int}}"
                    raw = json.loads(gemini.generate_content([prompt, Image.open(file)]).text.replace('```json', '').replace('```', '').strip())
                    sc = BravuraEngine.calculate_score(raw['vitoria'], raw['d'], raw['part'], raw['dano_est'], raw['dano_camp'], raw['min'], raw['pinks'])
                    m = MatchStats(MatchID=f"c_{int(time.time())}", Data=datetime.now().strftime('%Y-%m-%d %H:%M'), Timestamp=time.time()*1000, Jogador=p_name, Tipo='Custom', Vitoria=raw['vitoria'], Score=sc, K=raw['k'], D=raw['d'], A=raw['a'], Part=raw['part'], Dano_Estruturas=raw['dano_est'], DPM=round(raw['dano_camp']/raw['min'], 2), Pinks=raw['pinks'])
                    db.save(m)
                    st.success("Custom salva!")
                    st.rerun()
                except: st.error("Erro na leitura.")

        st.markdown("---")
        if st.button("🗑️ Resetar Database"):
            db.reset_database()
            st.rerun()

    df = db.get_all()
    if df.empty:
        st.info("Banco de dados vazio. Clique em Atualizar Lista Completa.")
        return

    tab_f, tab_c = st.tabs(["🏆 OFICIAIS (API)", "👹 CUSTOMS (PRINTS)"])
    
    with tab_f:
        df_f = df[df['Tipo'] != 'Custom']
        if not df_f.empty:
            k1, k2, k3, k4 = st.columns(4)
            jogos_recentes = len(df_f[df_f['Timestamp'] > (time.time()*1000 - 86400000)])
            
            k1.metric("🔥 MVP Ofensivo", df_f.groupby('Jogador')['Score'].sum().idxmax(), "Líder")
            k2.metric("💀 Rei do Dano", df_f.groupby('Jogador')['DPM'].mean().idxmax(), f"{df_f['DPM'].max():.0f} Max")
            k3.metric("🎮 Jogos", len(df_f), f"+{jogos_recentes} Hoje")
            k4.metric("📈 Média Score", f"{df_f['Score'].mean():.1f}", "Global")
            
            st.markdown("---")
            c1, c2 = st.columns([1, 2.2])
            with c1:
                st.subheader("Leaderboard")
                rank = df_f.groupby('Jogador')['Score'].sum().sort_values(ascending=False).reset_index()
                rank.index += 1
                st.dataframe(rank.style.background_gradient(cmap='YlOrRd', subset=['Score']), use_container_width=True)
            with c2:
                st.subheader("Evolução (Spline)")
                df_f = df_f.sort_values('Timestamp')
                df_f['Acumulado'] = df_f.groupby('Jogador')['Score'].cumsum()
                fig = go.Figure()
                colors = px.colors.qualitative.Pastel
                for idx, player in enumerate(df_f['Jogador'].unique()):
                    d_p = df_f[df_f['Jogador'] == player]
                    color = colors[idx % len(colors)]
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
