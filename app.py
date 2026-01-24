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
# 2. DATA LAYER (AUTO-REPARO)
# ==============================================================================
class DatabaseAdapter:
    FILE_DB = 'leaguestats_bravura.csv'
    
    def __init__(self):
        # Garante que o arquivo existe
        if not os.path.exists(self.FILE_DB): 
            self._create_db()
    
    def _create_db(self):
        try:
            pd.DataFrame(columns=MatchStats.model_fields.keys()).to_csv(self.FILE_DB, index=False)
        except:
            pass
    
    def get_all(self):
        # Tenta ler. Se der erro (arquivo corrompido), recria.
        try:
            return pd.read_csv(self.FILE_DB, dtype={'MatchID': str})
        except Exception as e:
            st.warning("Banco de dados corrompido detectado. Resetando arquivo...")
            self._create_db()
            return pd.read_csv(self.FILE_DB, dtype={'MatchID': str})
    
    def save(self, stats: MatchStats):
        try:
            df = self.get_all()
            # LÓGICA DE UNICIDADE COMPOSTA: ID + JOGADOR
            already_exists = ((df['MatchID'] == str(stats.MatchID)) & 
                              (df['Jogador'] == stats.Jogador)).any()

            if not already_exists: # <--- O ERRO ESTAVA AQUI (FALTAVAM OS DOIS PONTOS)
                pd.concat([df, pd.DataFrame([stats.model_dump()])], ignore_index=True).to_csv(self.FILE_DB, index=False)
                return True
            return False
        except Exception as e:
            st.error(f"Erro ao salvar: {e}")
            return False

    def reset_database(self):
        if os.path.exists(self.FILE_DB):
            os.remove(self.FILE_DB)
        self._create_db()
        return True

class RiotAdapter:
    def __init__(self, api_key):
        self.headers = {"X-Riot-Token": api_key}
        self.season_start = 1735689600 # 01/01/2026

    def fetch_matches(self, nome, tag, limit=20, force_any_queue=False):
        logs = []
        try:
            tag_clean = tag.replace('#', '').strip()
            nome_enc = quote(nome.strip())
            tag_enc = quote(tag_clean)

            # 1. Account
            acc_url = f"https://americas.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{nome_enc}/{tag_enc}"
            logs.append(f"🔍 Buscando conta: {nome} #{tag_clean}...")
            acc_resp = requests.get(acc_url, headers=self.headers)
            
            if acc_resp.status_code != 200:
                return None, f"Erro Conta ({acc_resp.status_code})", logs
            
            puuid = acc_resp.json()['puuid']

            # 2. IDs
            queue_param = "" if force_any_queue else "&queue=440"
            matches_url = f"https://americas.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids?start=0&count={limit}{queue_param}"
            
            matches_resp = requests.get(matches_url, headers=self.headers)
            match_ids = matches_resp.json()
            
            if not match_ids:
                return None, "⚠️ Nenhuma partida encontrada.", logs
            
            logs.append(f"✅ Encontradas {len(match_ids)} partidas. Processando...")
            
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
    st.caption("Season 2026 • Sociologia do Jogo • V5.4 (Fixed)")

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
                    if error: st.error(error)
                
                if matches:
                    saved_count = 0
                    for m in matches:
                        if db.save(m): saved_count += 1
                    
                    if saved_count > 0:
                        st.success(f"✅ Sucesso! {saved_count} partidas salvas para {nick.upper()}.")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.warning(f"⚠️ Jogos encontrados, mas TODOS já existiam para este jogador.")

        else:
            u_file = st.file_uploader("Print", type=['png','jpg'])
            p_name = st.text_input("Nick no Print").upper()
            if st.button("Analisar") and u_file:
                raw = gemini.analyze(Image.open(u_file), p_name)
                if raw:
                    sc = BravuraEngine.calculate_score(raw['vitoria'], raw['d'], raw['part'], raw['dano_est'], raw['dano_camp'], raw['min'], raw['pinks'])
                    m = MatchStats(MatchID=f"c_{int(time.time())}", Data=datetime.now().strftime('%Y-%m-%d %H:%M'), Timestamp=time.time()*1000, Jogador=p_name, Tipo='Custom', Vitoria=raw['vitoria'], Score=sc, K=raw['k'], D=raw['d'], A=raw['a'], Part=raw['part'], Dano_Estruturas=raw['dano_est'], DPM=round(raw['dano_camp']/raw['min'], 2), Pinks=raw['pinks'])
                    db.save(m)
                    st.rerun()

        st.markdown("---")
        if st.button("🗑️ Resetar Database"):
            db.reset_database()
            st.rerun()

    # --- DASHBOARD ---
    df = db.get_all()
    
    if df.empty:
        st.info("Banco de dados reiniciado e limpo. Comece a sincronizar!")
        return

    # Filtro Temporal (Feature Requisitada)
    col_f, _ = st.columns([1, 3])
    with col_f:
        periodo = st.selectbox("📅 Filtro de Período:", ["Todo o Histórico", "Últimos 30 Dias", "Últimos 7 Dias"])
    
    now = datetime.now().timestamp() * 1000
    if periodo == "Últimos 30 Dias":
        df = df[df['Timestamp'] > (now - 2592000000)]
    elif periodo == "Últimos 7 Dias":
        df = df[df['Timestamp'] > (now - 604800000)]

    if df.empty:
        st.warning(f"Existem dados, mas nenhum neste período ({periodo}).")
        return

    # Renderiza Tabs Dinamicamente
    tipos = sorted(df['Tipo'].unique())
    tabs = st.tabs([f"🏆 {t}" for t in tipos])
    
    for i, tipo in enumerate(tipos):
        with tabs[i]:
            df_t = df[df['Tipo'] == tipo].copy()
            
            k1, k2, k3, k4 = st.columns(4)
            top = df_t.groupby('Jogador')['Score'].sum().idxmax()
            k1.metric("MVP", top)
            k2.metric("Rei do Dano", df_t.groupby('Jogador')['DPM'].mean().idxmax(), f"{df_t.groupby('Jogador')['DPM'].mean().max():.0f}")
            k3.metric("Jogos Analisados", len(df_t))
            k4.metric("Média Score", f"{df_t['Score'].mean():.1f}")
            
            st.markdown("---")
            c1, c2 = st.columns([1, 2])
            with c1:
                st.subheader("Leaderboard")
                rank = df_t.groupby('Jogador')['Score'].sum().sort_values(ascending=False).reset_index()
                rank.index += 1
                st.dataframe(rank.style.background_gradient(cmap='YlOrRd', subset=['Score']), use_container_width=True)
            with c2:
                st.subheader("Evolução")
                df_t = df_t.sort_values('Timestamp')
                df_t['Acumulado'] = df_t.groupby('Jogador')['Score'].cumsum()
                fig = go.Figure()
                colors = px.colors.qualitative.Pastel
                for idx, player in enumerate(df_t['Jogador'].unique()):
                    d_p = df_t[df_t['Jogador'] == player]
                    color = colors[idx % len(colors)]
                    fig.add_trace(go.Scatter(x=d_p['Data'], y=d_p['Acumulado'], name=player, mode='lines+markers', line=dict(shape='spline', width=3, color=color), fill='tozeroy', fillcolor=safe_hex_to_rgba(color, 0.1)))
                fig.update_layout(template="plotly_dark", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', hovermode="x unified", legend=dict(orientation="h", y=1.1, x=0.5, xanchor='center'))
                st.plotly_chart(fig, use_container_width=True)

if __name__ == "__main__":
    render_dashboard()
