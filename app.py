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
from typing import Optional, List
from urllib.parse import quote

# ==============================================================================
# 0. CONFIGURAÇÕES
# ==============================================================================
st.set_page_config(page_title="LeagueStats: Bravura Edition", layout="wide", page_icon="🛡️")

# CSS para mensagens de log
st.markdown("""
<style>
    .stApp { background-color: #0e1117; }
    h1, h2, h3 { color: white; font-family: sans-serif; }
    .log-success { color: #4ade80; font-family: monospace; font-size: 12px; }
    .log-warn { color: #facc15; font-family: monospace; font-size: 12px; }
    .log-error { color: #f87171; font-family: monospace; font-size: 12px; }
    div[data-testid="metric-container"] { background-color: #1a1c24; border-left: 5px solid #d4af37; }
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
# 2. DATA LAYER
# ==============================================================================
class DatabaseAdapter:
    FILE_DB = 'leaguestats_bravura.csv'
    def __init__(self):
        if not os.path.exists(self.FILE_DB): self._create_db()
    def _create_db(self):
        pd.DataFrame(columns=MatchStats.model_fields.keys()).to_csv(self.FILE_DB, index=False)
    def get_all(self):
        if not os.path.exists(self.FILE_DB): self._create_db()
        return pd.read_csv(self.FILE_DB)
    def save(self, stats: MatchStats):
        df = self.get_all()
        if stats.MatchID not in df['MatchID'].values:
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

    def fetch_matches(self, nome, tag, limit=10, force_any_queue=False):
        status_log = [] # Lista para guardar logs de debug
        
        try:
            # 1. CONTA (Account V1)
            tag_clean = tag.replace('#', '').strip()
            nome_enc = quote(nome.strip())
            tag_enc = quote(tag_clean)

            acc_url = f"https://americas.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{nome_enc}/{tag_enc}"
            status_log.append(f"🔍 Buscando conta: {nome} #{tag_clean}...")
            
            acc_resp = requests.get(acc_url, headers=self.headers)
            
            if acc_resp.status_code == 404:
                return None, f"❌ Jogador não encontrado. Verifique se o Nick e a Tag #{tag_clean} estão exatos.", status_log
            elif acc_resp.status_code == 403:
                return None, "❌ Chave da Riot Expirada (403). Gere uma nova.", status_log
            elif acc_resp.status_code != 200:
                return None, f"❌ Erro na Riot API: {acc_resp.status_code}", status_log
            
            puuid = acc_resp.json()['puuid']
            status_log.append(f"✅ Conta encontrada! PUUID: {puuid[:10]}...")

            # 2. MATCH IDs
            # Queue 440 = Flex // Se force_any_queue=True, removemos o filtro de fila
            queue_param = "" if force_any_queue else "&queue=440"
            queue_name = "QUALQUER FILA" if force_any_queue else "FLEX (440)"
            
            matches_url = f"https://americas.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids?startTime={self.season_start}{queue_param}&start=0&count={limit}"
            
            status_log.append(f"🔍 Buscando histórico em {queue_name}...")
            matches_resp = requests.get(matches_url, headers=self.headers)
            
            if matches_resp.status_code != 200:
                return None, f"Erro ao buscar lista de partidas: {matches_resp.status_code}", status_log
            
            match_ids = matches_resp.json()
            
            if not match_ids:
                return None, f"⚠️ Nenhuma partida encontrada na Season 2026 em {queue_name}.", status_log
            
            status_log.append(f"✅ Encontradas {len(match_ids)} partidas. Baixando detalhes...")
            
            processed_data = []
            bar = st.progress(0, text="Baixando replays...")
            
            for i, m_id in enumerate(match_ids):
                bar.progress((i + 1) / len(match_ids), text=f"Analisando {i+1}/{len(match_ids)}")
                d_resp = requests.get(f"https://americas.api.riotgames.com/lol/match/v5/matches/{m_id}", headers=self.headers)
                
                if d_resp.status_code == 200:
                    d = d_resp.json()
                    p = next(part for part in d['info']['participants'] if part['puuid'] == puuid)
                    mins = d['info']['gameDuration'] / 60
                    
                    sc = BravuraEngine.calculate_score(
                        p['win'], p['deaths'], p['challenges'].get('killParticipation', 0),
                        p['damageDealtToBuildings'], p['totalDamageDealtToChampions'], mins, p['visionWardsBoughtInGame']
                    )
                    
                    processed_data.append(MatchStats(
                        MatchID=m_id,
                        Data=datetime.fromtimestamp(d['info']['gameCreation']/1000).strftime('%Y-%m-%d %H:%M'),
                        Timestamp=d['info']['gameCreation'],
                        Jogador=nome.upper(),
                        Tipo='Flex' if not force_any_queue else 'Outros', # Marca como Outros se for teste
                        Vitoria=p['win'], Score=sc, K=p['kills'], D=p['deaths'], A=p['assists'],
                        Part=p['challenges'].get('killParticipation', 0),
                        Dano_Estruturas=p['damageDealtToBuildings'],
                        DPM=round(p['totalDamageDealtToChampions']/mins, 2),
                        Pinks=p['visionWardsBoughtInGame']
                    ))
                time.sleep(0.05)
            
            bar.empty()
            return processed_data, None, status_log

        except Exception as e:
            return None, f"Erro Crítico: {str(e)}", status_log

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
def render_dashboard():
    db = DatabaseAdapter()
    riot = RiotAdapter(st.secrets.get("RIOT_KEY", ""))
    gemini = GeminiAdapter(st.secrets.get("GEMINI_KEY", ""))

    st.title("🛡️ LeagueStats: Bravura Tracker")
    st.caption("Season 2026 • Sociologia do Jogo")

    with st.sidebar:
        st.header("🎮 Central de Controle")
        mode = st.radio("Fonte:", ["Riot API", "Gemini OCR"])
        st.markdown("---")
        
        if mode == "Riot API":
            nick = st.text_input("Nick (Ex: O Magro de OZ)")
            tag = st.text_input("Tag (Ex: BR1)")
            any_queue = st.checkbox("Ignorar filtro Flex (Modo Debug)", value=False, help="Marque isso se o jogador não joga Flex, só para testar se o Nick está certo.")
            
            if st.button("🔄 Sincronizar") and nick and tag:
                matches, error, logs = riot.fetch_matches(nick, tag, limit=20, force_any_queue=any_queue)
                
                # Exibe logs de diagnóstico
                with st.expander("📜 Logs de Diagnóstico", expanded=True):
                    for log in logs:
                        st.markdown(f"<span class='log-success'>{log}</span>", unsafe_allow_html=True)
                    if error:
                        st.markdown(f"<span class='log-error'>{error}</span>", unsafe_allow_html=True)

                if matches:
                    count = sum([1 for m in matches if db.save(m)])
                    if count > 0:
                        st.success(f"Sucesso! {count} novas partidas salvas.")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.info("Histórico já estava atualizado.")
        
        else:
            u_file = st.file_uploader("Print", type=['png','jpg'])
            p_name = st.text_input("Nick no Print").upper()
            if st.button("Analisar") and u_file:
                raw = gemini.analyze(Image.open(u_file), p_name)
                if raw:
                    sc = BravuraEngine.calculate_score(raw['vitoria'], raw['d'], raw['part'], raw['dano_est'], raw['dano_camp'], raw['min'], raw['pinks'])
                    match = MatchStats(MatchID=f"c_{int(time.time())}", Data=datetime.now().strftime('%Y-%m-%d %H:%M'), Timestamp=time.time()*1000, Jogador=p_name, Tipo='Custom', Vitoria=raw['vitoria'], Score=sc, K=raw['k'], D=raw['d'], A=raw['a'], Part=raw['part'], Dano_Estruturas=raw['dano_est'], DPM=round(raw['dano_camp']/raw['min'], 2), Pinks=raw['pinks'])
                    db.save(match)
                    st.rerun()

        st.markdown("---")
        with st.expander("🔥 Zona de Perigo"):
            if st.button("🗑️ Resetar Tudo", type="primary"): 
                db.reset_database()
                st.rerun()

    # DASHBOARD
    df = db.get_all()
    if df.empty:
        st.info("👋 Nenhuma partida registrada. Use a barra lateral para adicionar.")
        return

    # TABS (Agora filtramos por Tipo dinamicamente)
    tipos_disponiveis = df['Tipo'].unique()
    tabs = st.tabs([f"🏆 {t}" for t in tipos_disponiveis])
    
    for i, tipo in enumerate(tipos_disponiveis):
        with tabs[i]:
            df_t = df[df['Tipo'] == tipo].copy()
            
            k1, k2, k3, k4 = st.columns(4)
            top = df_t.groupby('Jogador')['Score'].sum().idxmax()
            k1.metric("MVP", top)
            k2.metric("Maior DPM", f"{df_t['DPM'].max():.0f}")
            k3.metric("Jogos", len(df_t))
            k4.metric("Média Score", f"{df_t['Score'].mean():.1f}")
            
            st.markdown("---")
            c1, c2 = st.columns([1, 2])
            with c1:
                st.dataframe(df_t.groupby('Jogador')['Score'].sum().sort_values(ascending=False).reset_index(), use_container_width=True)
            with c2:
                df_t = df_t.sort_values('Timestamp')
                df_t['Acumulado'] = df_t.groupby('Jogador')['Score'].cumsum()
                fig = px.line(df_t, x='Data', y='Acumulado', color='Jogador', markers=True, template='plotly_dark')
                # Configura spline suave
                fig.update_traces(line_shape='spline', mode='lines+markers')
                st.plotly_chart(fig, use_container_width=True)

if __name__ == "__main__":
    render_dashboard()
