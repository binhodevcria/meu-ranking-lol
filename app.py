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
# 1. IDENTIDADE VISUAL
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
        # Lê tudo como string primeiro para evitar erros de tipo no ID
        df = pd.read_csv(self.FILE_DB, dtype={'MatchID': str})
        df['Jogador'] = df['Jogador'].apply(lambda x: NOME_DISPLAY.get(x.upper(), x.upper()))
        return df

    def save(self, stats: MatchStats):
        try:
            df = pd.read_csv(self.FILE_DB, dtype={'MatchID': str})
            
            # LÓGICA ACUMULATIVA:
            # Só salva se NÃO existir uma linha com o mesmo ID DE PARTIDA e o mesmo JOGADOR.
            # Isso permite que a mesma partida seja salva para jogadores diferentes (duo/flex),
            # mas impede que o mesmo jogador tenha a mesma partida duplicada.
            ja_existe = ((df['MatchID'] == str(stats.MatchID)) & (df['Jogador'] == stats.Jogador.upper())).any()
            
            if not ja_existe:
                pd.concat([df, pd.DataFrame([stats.model_dump()])], ignore_index=True).to_csv(self.FILE_DB, index=False)
                return True
            return False
        except:
            return False

    def reset_database(self):
        if os.path.exists(self.FILE_DB):
            os.remove(self.FILE_DB)
        pd.DataFrame(columns=MatchStats.model_fields.keys()).to_csv(self.FILE_DB, index=False)
        return True

class RiotAdapter:
    def __init__(self, api_key):
        self.headers = {"X-Riot-Token": api_key}
        # Data de Início da Season 2026 (aprox)
        self.season_start = 1735689600 
    
    def fetch_matches(self, nome, tag, limit=15):
        try:
            nome_enc, tag_enc = quote(nome.strip()), quote(tag.replace('#','').strip())
            
            # 1. Busca Conta
            acc_resp = requests.get(f"https://americas.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{nome_enc}/{tag_enc}", headers=self.headers)
            if acc_resp.status_code != 200: return None, f"Erro Conta {acc_resp.status_code}"
            puuid = acc_resp.json()['puuid']
            
            # 2. Busca IDs (Season 2026 em diante)
            # start=0, count=15 sempre pega os 15 mais recentes.
            # Como o banco filtra duplicatas, isso funciona como "Atualização Incremental"
            url_matches = f"https://americas.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids?startTime={self.season_start}&start=0&count={limit}"
            m_ids_resp = requests.get(url_matches, headers=self.headers)
            if m_ids_resp.status_code != 200: return None, "Erro Lista Partidas"
            m_ids = m_ids_resp.json()
            
            data = []
            for m_id in m_ids:
                # 3. Busca Detalhes
                d_resp = requests.get(f"https://americas.api.riotgames.com/lol/match/v5/matches/{m_id}", headers=self.headers)
                if d_resp.status_code == 200:
                    d = d_resp.json()
                    p = next((x for x in d['info']['participants'] if x['puuid'] == puuid), None)
                    
                    if p:
                        mins = d['info']['gameDuration']/60
                        sc = BravuraEngine.calculate_score(p['win'], p['deaths'], p['challenges'].get('killParticipation', 0), p['damageDealtToBuildings'], p['totalDamageDealtToChampions'], mins, p['visionWardsBoughtInGame'])
                        
                        qid = d['info']['queueId']
                        tipo = 'Flex' if qid == 440 else ('SoloQ' if qid == 420 else 'Outros')
                        
                        data.append(MatchStats(MatchID=str(m_id), Data=datetime.fromtimestamp(d['info']['gameCreation']/1000).strftime('%d/%m'), Timestamp=d['info']['gameCreation'], Jogador=nome.upper(), Tipo=tipo, Vitoria=p['win'], Score=sc, K=p['kills'], D=p['deaths'], A=p['assists'], Part=p['challenges'].get('killParticipation', 0), Dano_Estruturas=p['damageDealtToBuildings'], DPM=round(p['totalDamageDealtToChampions']/mins, 2), Pinks=p['visionWardsBoughtInGame']))
                
                # Delay vital para evitar Erro 429 com muitos jogadores
                time.sleep(0.8) 
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
                bar = st.progress(0, text="Iniciando busca...")
                total_salvo = 0
                
                for idx, p in enumerate(SQUAD_LIST):
                    bar.progress(idx/len(SQUAD_LIST), text=f"Lendo: {p['nick']}...")
                    matches, err = riot.fetch_matches(p['nick'], p['tag'])
                    
                    if matches:
                        count_p = 0
                        for m in matches: 
                            if db.save(m): count_p += 1
                        total_salvo += count_p
                    
                    time.sleep(1) # Pausa entre jogadores
                
                bar.progress(1.0, text="Finalizado!")
                if total_salvo > 0:
                    st.success(f"Sucesso! +{total_salvo} novas partidas no histórico.")
                    time.sleep(2)
                    st.rerun()
                else:
                    st.info("Nenhuma partida nova encontrada.")

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
                except:
                    st.error("Erro na leitura do print.")

        # --- BOTÃO DE RESET (ADICIONADO) ---
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
            # Destaques com Delta Verde (Visual Original)
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
