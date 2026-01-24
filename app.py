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

# ==============================================================================
# 0. CONFIGURAÇÕES GLOBAIS & TEMAS
# ==============================================================================
st.set_page_config(page_title="LeagueStats: Bravura Edition", layout="wide", page_icon="🛡️")

# Tema CSS (Dark & Clean)
st.markdown("""
<style>
    /* Fundo e Fontes */
    .stApp { background-color: #0e1117; }
    h1, h2, h3 { font-family: 'Roboto', sans-serif; color: #ffffff; }
    
    /* Cards de Métricas */
    div[data-testid="metric-container"] {
        background-color: #1a1c24;
        border-left: 5px solid #d4af37; /* Dourado */
        padding: 15px;
        border-radius: 8px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.3);
    }
    
    /* Tabelas */
    .dataframe { font-size: 14px; }
    
    /* Botões */
    .stButton>button {
        background-color: #2b313e;
        color: white;
        border: 1px solid #4a4e69;
        border-radius: 5px;
    }
    .stButton>button:hover {
        border-color: #d4af37;
        color: #d4af37;
    }
    
    /* Botão de Perigo */
    div[data-testid="stExpander"] { border: 1px solid #ff4b4b; }
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# 1. DOMAIN LAYER (Regras de Negócio - Sociologia)
# ==============================================================================
class MatchStats(BaseModel):
    """Modelo de dados validado (Pydantic) para garantir consistência."""
    MatchID: str
    Data: str
    Timestamp: float
    Jogador: str
    Tipo: str # 'Flex' ou 'Custom'
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
    """Motor de cálculo do Score. A 'Constituição' do grupo."""
    
    @staticmethod
    def calculate_score(vitoria: bool, d: int, part: float, dano_est: int, dano_camp: int, minutos: int, pinks: int) -> float:
        # 1. Base (Vitória vale 25, Derrota 0 - Acúmulo Positivo)
        score = 25.0 if vitoria else 0.0
        
        # 2. Pressão de Combate (40% de peso na participação)
        score += (part * 40)
        
        # 3. Volume de Jogo (DPM / 100)
        dpm = dano_camp / minutos if minutos > 0 else 0
        score += (dpm / 100)
        
        # 4. Pressão de Mapa (Dano Estruturas / 500)
        score += (dano_est / 500)
        
        # 5. Visão Ofensiva
        score += (pinks * 2)
        
        # 6. PENALIDADE SOCIAL (Filtro Anti-KDA Player)
        # Morreu pouco (<=2) e não ajudou (<35%) = Punição Severa
        if d <= 2 and part < 0.35:
            score -= 25.0
            
        return round(score, 2)

# ==============================================================================
# 2. INFRASTRUCTURE LAYER (Adapters & Services)
# ==============================================================================
class DatabaseAdapter:
    """Gerencia persistência (CSV) simulando um Banco de Dados."""
    FILE_DB = 'leaguestats_bravura.csv'

    def __init__(self):
        if not os.path.exists(self.FILE_DB):
            self._create_db()

    def _create_db(self):
        df = pd.DataFrame(columns=MatchStats.model_fields.keys())
        df.to_csv(self.FILE_DB, index=False)

    def get_all(self) -> pd.DataFrame:
        if not os.path.exists(self.FILE_DB):
            self._create_db()
        return pd.read_csv(self.FILE_DB)

    def save(self, stats: MatchStats):
        df = self.get_all()
        # Idempotência: Não salva se já existir o ID
        if stats.MatchID not in df['MatchID'].values:
            new_row = pd.DataFrame([stats.model_dump()])
            pd.concat([df, new_row], ignore_index=True).to_csv(self.FILE_DB, index=False)
            return True
        return False
    
    def reset_database(self):
        if os.path.exists(self.FILE_DB):
            os.remove(self.FILE_DB)
            self._create_db()
            return True
        return False

class RiotAdapter:
    """Conecta com a Riot API. Inclui tratamento de erro e cache."""
    def __init__(self, api_key):
        self.headers = {"X-Riot-Token": api_key}
        self.season_start = 1735689600 # 01/01/2026

    def fetch_flex_matches(self, nome, tag, limit=10):
        try:
            # 1. Account V1
            acc_url = f"https://americas.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{nome}/{tag}"
            acc_resp = requests.get(acc_url, headers=self.headers)
            if acc_resp.status_code != 200: return None, f"Erro Conta: {acc_resp.status_code}"
            puuid = acc_resp.json()['puuid']

            # 2. Match V5 (Flex Queue 440)
            matches_url = f"https://americas.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids?startTime={self.season_start}&queue=440&start=0&count={limit}"
            matches_resp = requests.get(matches_url, headers=self.headers)
            if matches_resp.status_code != 200: return None, f"Erro Partidas: {matches_resp.status_code}"
            
            match_ids = matches_resp.json()
            processed_data = []

            # Progress Bar para UX
            bar = st.progress(0, text="A descarregar Replays...")
            for i, m_id in enumerate(match_ids):
                bar.progress((i + 1) / len(match_ids), text=f"A analisar partida {i+1}/{len(match_ids)}")
                
                # Fetch Detalhes
                detail_url = f"https://americas.api.riotgames.com/lol/match/v5/matches/{m_id}"
                d_resp = requests.get(detail_url, headers=self.headers)
                
                if d_resp.status_code == 200:
                    d = d_resp.json()
                    p = next(part for part in d['info']['participants'] if part['puuid'] == puuid)
                    
                    minutos = d['info']['gameDuration'] / 60
                    
                    # Usando o Motor de Domínio
                    score_final = BravuraEngine.calculate_score(
                        p['win'], p['deaths'], p['challenges'].get('killParticipation', 0),
                        p['damageDealtToBuildings'], p['totalDamageDealtToChampions'], 
                        minutos, p['visionWardsBoughtInGame']
                    )
                    
                    processed_data.append(MatchStats(
                        MatchID=m_id,
                        Data=datetime.fromtimestamp(d['info']['gameCreation']/1000).strftime('%Y-%m-%d %H:%M'),
                        Timestamp=d['info']['gameCreation'],
                        Jogador=nome.upper(),
                        Tipo='Flex',
                        Vitoria=p['win'],
                        Score=score_final,
                        K=p['kills'], D=p['deaths'], A=p['assists'],
                        Part=p['challenges'].get('killParticipation', 0),
                        Dano_Estruturas=p['damageDealtToBuildings'],
                        DPM=round(p['totalDamageDealtToChampions']/minutos, 2),
                        Pinks=p['visionWardsBoughtInGame']
                    ))
                time.sleep(0.1) # Respeita rate limit da Riot
            
            bar.empty()
            return processed_data, None
            
        except Exception as e:
            return None, str(e)

class GeminiAdapter:
    """Visão Computacional para ler prints."""
    def __init__(self, api_key):
        if api_key:
            genai.configure(api_key=api_key)
            self.model = genai.GenerativeModel('models/gemini-1.5-flash')
        else:
            self.model = None

    def analyze(self, image, player_name):
        if not self.model: return None
        # Prompt otimizado para JSON estrito
        prompt = f"""
        Extraia estatísticas de LoL para o jogador '{player_name}'.
        Retorne APENAS JSON:
        {{"vitoria": bool, "k": int, "d": int, "a": int, "part": float (0-1), 
          "dano_est": int, "dano_camp": int, "min": int, "pinks": int}}
        Use 0 se não encontrar valor.
        """
        try:
            resp = self.model.generate_content([prompt, image])
            return json.loads(resp.text.replace('```json', '').replace('```', '').strip())
        except: return None

# ==============================================================================
# 3. UI LAYER (Interface Gráfica)
# ==============================================================================

# Função auxiliar segura para converter cor hex para RGBA
def safe_hex_to_rgba(hex_color, opacity=0.1):
    try:
        c = hex_color.lstrip('#')
        return f"rgba({int(c[0:2], 16)}, {int(c[2:4], 16)}, {int(c[4:6], 16)}, {opacity})"
    except:
        return hex_color

def render_dashboard():
    db = DatabaseAdapter()
    riot = RiotAdapter(st.secrets.get("RIOT_KEY"))
    gemini = GeminiAdapter(st.secrets.get("GEMINI_KEY"))

    st.title("🛡️ LeagueStats: Bravura Tracker")
    st.caption("Season 2026 • Sociologia do Jogo • Powered by Riot & Gemini")

    # --- SIDEBAR (CONTROLES) ---
    with st.sidebar:
        st.header("🎮 Central de Controlo")
        mode = st.radio("Fonte de Dados:", ["Riot API (Flex)", "Gemini OCR (Custom)"])
        
        st.markdown("---")
        if mode == "Riot API (Flex)":
            nick = st.text_input("Nick")
            tag = st.text_input("Tag")
            limit = st.slider("Buscar últimas:", 5, 50, 20)
            
            if st.button("🔄 Sincronizar") and nick and tag:
                matches, error = riot.fetch_flex_matches(nick, tag, limit)
                if matches:
                    new_count = 0
                    for m in matches:
                        if db.save(m): new_count += 1
                    if new_count > 0: st.success(f"{new_count} novas partidas!")
                    else: st.info("Tudo atualizado.")
                    st.rerun()
                elif error:
                    st.error(f"Erro: {error}")
        
        else:
            uploaded = st.file_uploader("Print da Partida", type=['png', 'jpg'])
            p_name = st.text_input("Nome no Print").upper()
            if st.button("🤖 Analisar") and uploaded and p_name:
                with st.spinner("A processar..."):
                    raw = gemini.analyze(Image.open(uploaded), p_name)
                    if raw:
                        sc = BravuraEngine.calculate_score(
                            raw['vitoria'], raw['d'], raw['part'], raw['dano_est'], 
                            raw['dano_camp'], raw['min'], raw['pinks']
                        )
                        # Cria objeto validado
                        match = MatchStats(
                            MatchID=f"cust_{int(time.time())}",
                            Data=datetime.now().strftime('%Y-%m-%d %H:%M'),
                            Timestamp=time.time()*1000,
                            Jogador=p_name, Tipo='Custom',
                            Vitoria=raw['vitoria'], Score=sc,
                            K=raw['k'], D=raw['d'], A=raw['a'], Part=raw['part'],
                            Dano_Estruturas=raw['dano_est'],
                            DPM=round(raw['dano_camp']/raw['min'], 2),
                            Pinks=raw['pinks']
                        )
                        db.save(match)
                        st.success(f"Custom Salva! Score: {sc}")
                        st.rerun()
                    else: st.error("Falha na leitura.")

        # --- ZONA DE PERIGO (RESET) ---
        st.markdown("---")
        with st.expander("🔥 Zona de Perigo"):
            st.warning("Atenção: Isto apaga TODOS os dados!")
            if st.button("🗑️ APAGAR TUDO", type="primary"):
                if db.reset_database():
                    st.toast("Base de dados reiniciada! 💥")
                    time.sleep(1)
                    st.rerun()

    # --- ÁREA PRINCIPAL ---
    df = db.get_all()
    if df.empty:
        st.info("👋 Bem-vindo! Comece por sincronizar dados na barra lateral.")
        return

    # Tabs separadas
    tab_flex, tab_custom = st.tabs(["🏆 COMPETITIVO (FLEX)", "👹 RESENHA (CUSTOM)"])

    for tab, tipo in [(tab_flex, 'Flex'), (tab_custom, 'Custom')]:
        with tab:
            df_filter = df[df['Tipo'] == tipo].copy()
            if df_filter.empty:
                st.warning(f"Sem dados de {tipo} ainda.")
                continue

            # 1. KPIs de Topo
            kpi1, kpi2, kpi3, kpi4 = st.columns(4)
            top_player = df_filter.groupby('Jogador')['Score'].sum().idxmax()
            top_dmg = df_filter.groupby('Jogador')['DPM'].mean().idxmax()
            
            kpi1.metric("MVP da Season", top_player, "Bravura Máxima")
            kpi2.metric("Rei do Dano", top_dmg, f"{df_filter.groupby('Jogador')['DPM'].mean().max():.0f} DPM")
            kpi3.metric("Total de Jogos", len(df_filter), f"{len(df_filter['MatchID'].unique())} partidas")
            kpi4.metric("Score Médio", f"{df_filter['Score'].mean():.1f}", "Pontos por jogo")

            st.markdown("---")

            # 2. Layout Assimétrico
            col_table, col_graph = st.columns([1, 3])
            
            with col_table:
                st.subheader("Leaderboard")
                rank = df_filter.groupby('Jogador')['Score'].sum().sort_values(ascending=False).reset_index()
                rank.index += 1
                st.dataframe(
                    rank.style.background_gradient(cmap='YlOrRd', subset=['Score']),
                    use_container_width=True,
                    height=350
                )
                
                with st.expander("Ver Estatísticas Técnicas"):
                    details = df_filter.groupby('Jogador').agg({
                        'DPM': 'mean', 'Dano_Estruturas': 'mean', 'Part': 'mean', 'Pinks': 'mean'
                    })
                    st.dataframe(details.style.format("{:.1f}"))

            with col_graph:
                st.subheader("Evolução Temporal")
                df_filter = df_filter.sort_values('Timestamp')
                df_filter['Acumulado'] = df_filter.groupby('Jogador')['Score'].cumsum()
                
                fig = go.Figure()
                colors = px.colors.qualitative.Pastel
                
                for i, player in enumerate(df_filter['Jogador'].unique()):
                    d_p = df_filter[df_filter['Jogador'] == player]
                    color = colors[i % len(colors)]
                    
                    fill_color_rgba = safe_hex_to_rgba(color, 0.1)

                    fig.add_trace(go.Scatter(
                        x=d_p['Data'], y=d_p['Acumulado'],
                        name=player,
                        mode='lines+markers',
                        line=dict(shape='spline', width=3, color=color),
                        fill='tozeroy',
                        fillcolor=fill_color_rgba
                    ))
                
                fig.update_layout(
                    template="plotly_dark",
                    paper_bgcolor='rgba(0,0,0,0)',
                    plot_bgcolor='rgba(0,0,0,0)',
                    hovermode="x unified",
                    legend=dict(orientation="h", y=1.1, x=0.5, xanchor='center')
                )
                st.plotly_chart(fig, use_container_width=True)

if __name__ == "__main__":
    render_dashboard()
