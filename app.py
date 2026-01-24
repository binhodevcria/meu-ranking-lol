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
# 0. SQUAD LIST & CONFIGURAÇÕES
# ==============================================================================
# Quantas partidas buscar no TOTAL por pessoa (Equidade)
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
    {"nick": "MEC Viper", "tag": "MEC"},
    {"nick": "Sugiro Correr", "tag": "BR1"}  # <--- NOVO MEMBRO ADICIONADO
]

# Unificação de Contas (Para o Guiza não roubar no gráfico)
NOME_DISPLAY = {
    "GUIZINHA": "GUIZA",
    "EZFALSE": "GUIZA",
    "GUIZA": "GUIZA"
}

# Conta quantas contas cada "Entidade" tem para dividir a cota de busca
ACCOUNT_COUNTS = {}
for p in SQUAD_LIST:
    # Se o nome não estiver no mapa, usa o próprio nick
    real_name = NOME_DISPLAY.get(p['nick'].upper(), p['nick'].upper())
    ACCOUNT_COUNTS[real_name] = ACCOUNT_COUNTS.get(real_name, 0) + 1

st.set_page_config(page_title="OFENSIVO SCORE", layout="wide", page_icon="⚔️")

# ==============================================================================
# 1. IDENTIDADE VISUAL
# ==============================================================================
st.markdown("""
<style>
    .stApp { background-color: #0e1117; }
    h1, h2, h3 { font-family: 'Roboto', sans-serif; color: #ffffff; }
    
    /* Cards */
    div[data-testid="metric-container"] {
        background-color: #1a1c24; border-left: 4px solid #c8aa6e;
        padding: 15px; border-radius: 6px; box-shadow: 0 4px 10px rgba(0,0,0,0.5);
    }
    
    /* Medalhas */
    .medal-box {
        background: linear-gradient(145deg, #1e2328, #1a1c24); border: 1px solid #c8aa6e;
        padding: 20px; border-radius: 10px; text-align: center;
        box-shadow: 0 4px 15px rgba(0,0,0,0.6); height: 100%;
    }
    .medal-icon { font-size: 3em; margin-bottom: 10px; }
    .medal-title { color: #d4af37; font-weight: bold; font-size: 1.2em; text-transform: uppercase; }
    .medal-player { color: #ff4b4b; font-weight: bold; font-size: 1.8em; margin: 10px 0; }
    
    /* Textos */
    .title-text { font-size: 3.5em; font-weight: bold; color: #ff4b4b; text-align: center; text-shadow: 2px 2px #000; }
    .subtitle-text { font-size: 1.2em; font-style: italic; color: #a0a0a0; text-align: center; margin-bottom: 30px; }
    .footer-group { font-size: 1.5em; color: #ffffff; text-align: left; margin-top: 50px; }
    .footer-final { font-size: 4em; font-weight: bold; color: #d4af37; text-align: center; margin-top: 10px; font-family: 'Impact'; letter-spacing: 5px; }
    
    .stButton>button { background-color: #1e2328; color: #cdbe91; border: 1px solid #463714; font-weight: bold; width: 100%; }
    .stButton>button:hover { border-color: #c8aa6e; color: #f0e6d2; }
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# 2. LÓGICA DO SCORE
# ==============================================================================
class MatchStats(BaseModel):
    MatchID: str; Data: str; Timestamp: float; Jogador: str; Tipo: str
    Vitoria: bool; Score: float; K: int; D: int; A: int; Part: float
    Dano_Estruturas: int; DPM: float; Pinks: int
    RankRiot: Optional[str] = "Unranked"

class BravuraEngine:
    @staticmethod
    def calculate_score(vitoria, d, part, dano_est, dano_camp, minutos, pinks):
        if minutos < 10: return 0.0 # Ignora Remake
        
        score = 25.0 if vitoria else 0.0
        score += (part * 40)
        dpm = dano_camp / minutos if minutos > 0 else 0
        score += (dpm / 100)
        score += (dano_est / 500)
        score += (pinks * 1.0)
        
        if d <= 2 and part < 0.35: score -= 25.0 # Penalidade KDA Player
        return round(score, 2)

def get_rank_bravura(media):
    if pd.isna(media) or media == 0: return "💤 Inativo"
    if media < 20: return "🛡️ Defesa"
    if media < 40: return "🌿 Herbívoro"
    if media < 60: return "🤝 Honra Tentou"
    if media < 80: return "⚔️ Ofensivo"
    return "💉 Viciado em Dopamina"

# ==============================================================================
# 3. INFRAESTRUTURA
# ==============================================================================
class DatabaseAdapter:
    FILE_DB = 'leaguestats_bravura.csv'
    def __init__(self):
        # Auto-Criação ou Auto-Reparo de Colunas
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
            # Normaliza os nomes ao ler (Guizinha -> Guiza)
            df['Jogador'] = df['Jogador'].apply(lambda x: NOME_DISPLAY.get(x.upper(), x.upper()))
            return df
        except: return pd.DataFrame()

    def save(self, stats: MatchStats):
        try:
            df = pd.read_csv(self.FILE_DB, dtype={'MatchID': str})
            # Salva apenas se MatchID + Jogador não existirem
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
        self.season_start = 1735689600 # 01/01/2026

    def request_blindado(self, url):
        """Sistema anti-429 (Rate Limit)"""
        for i in range(3):
            resp = requests.get(url, headers=self.headers)
            if resp.status_code == 200: return resp.json()
            elif resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", 10))
                # Pequeno delay ético
                time.sleep(wait + 1)
                continue
            else: return None
        return None

    def fetch_flex_rank(self, puuid):
        try:
            sid = self.request_blindado(f"https://br1.api.riotgames.com/lol/summoner/v4/summoners/by-puuid/{puuid}")['id']
            leagues = self.request_blindado(f"https://br1.api.riotgames.com/lol/league/v4/entries/by-summoner/{sid}")
            flex = next((l for l in leagues if l['queueType'] == "RANKED_FLEX_SR"), None)
            return f"{flex['tier']} {flex['rank']}" if flex else "Unranked"
        except: return "Unranked"

    def fetch_matches_with_quota(self, nome, tag, quota_limit):
        """
        1. Busca até 100 partidas no histórico (Garimpo Profundo).
        2. Filtra APENAS Flex.
        3. Para de salvar quando atingir a 'quota_limit' (Equidade).
        """
        try:
            n, t = quote(nome.strip()), quote(tag.replace('#','').strip())
            acc = self.request_blindado(f"https://americas.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{n}/{t}")
            if not acc: return None, 0, "Conta não achada"
            puuid = acc['puuid']
            
            rank_atual = self.fetch_flex_rank(puuid)

            # Busca profunda
            m_ids = self.request_blindado(f"https://americas.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids?startTime={self.season_start}&start=0&count=100")
            if not m_ids: return [], 0, "Sem histórico 2026"
            
            data = []
            flex_collected = 0
            
            for m_id in m_ids:
                # SE JÁ PEGOU A COTA (Ex: 5 jogos da Guizinha), PARA.
                if flex_collected >= quota_limit: break 

                d = self.request_blindado(f"https://americas.api.riotgames.com/lol/match/v5/matches/{m_id}")
                if d:
                    # FILTRO: SOMENTE FLEX (440)
                    if d['info']['queueId'] == 440:
                        p = next((x for x in d['info']['participants'] if x['puuid'] == puuid), None)
                        if p:
                            mins = d['info']['gameDuration']/60
                            sc = BravuraEngine.calculate_score(p['win'], p['deaths'], p['challenges'].get('killParticipation', 0), p['damageDealtToBuildings'], p['totalDamageDealtToChampions'], mins, p['visionWardsBoughtInGame'])
                            data.append(MatchStats(MatchID=str(m_id), Data=datetime.fromtimestamp(d['info']['gameCreation']/1000).strftime('%d/%m'), Timestamp=d['info']['gameCreation'], Jogador=nome.upper(), Tipo='Flex', Vitoria=p['win'], Score=sc, K=p['kills'], D=p['deaths'], A=p['assists'], Part=p['challenges'].get('killParticipation', 0), Dano_Estruturas=p['damageDealtToBuildings'], DPM=round(p['totalDamageDealtToChampions']/mins, 2), Pinks=p['visionWardsBoughtInGame'], RankRiot=rank_atual))
                            flex_collected += 1
                
                time.sleep(0.1) # Não sobrecarregar API
            
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
            if st.button("🔄 ATUALIZAR (TUDO)"):
                status = st.status("Iniciando varredura...", expanded=True)
                total_salvo = 0
                
                for idx, p in enumerate(SQUAD_LIST):
                    # Calcula Cota
                    real = NOME_DISPLAY.get(p['nick'].upper(), p['nick'].upper())
                    quota = int(GLOBAL_GAME_TARGET / ACCOUNT_COUNTS[real])
                    
                    status.write(f"🔎 {p['nick']} (Meta: {quota} Flex)...")
                    matches, c, msg = riot.fetch_matches_with_quota(p['nick'], p['tag'], quota)
                    
                    if matches is not None:
                        saved = 0
                        for m in matches: 
                            if db.save(m): saved += 1
                        total_salvo += saved
                        if saved > 0:
                            status.write(f"✅ {p['nick']}: +{saved} jogos novos salvos!")
                    else:
                        status.error(f"❌ {p['nick']}: {msg}")
                    
                    time.sleep(0.5)
                
                status.update(label="Finalizado!", state="complete", expanded=False)
                if total_salvo > 0:
                    st.success(f"+{total_salvo} novas partidas Flex.")
                    time.sleep(2)
                    st.rerun()
                else:
                    st.info("Nenhuma partida nova encontrada para as cotas atuais.")

        else:
            file = st.file_uploader("Upload Print", type=['png','jpg'])
            p_name = st.text_input("Nick no Print").upper()
            if st.button("🤖 Analisar") and file and gemini:
                try:
                    prompt = f"Extraia stats LoL JSON para {p_name}: {{'vitoria':bool,'k':int,'d':int,'a':int,'part':float,'dano_est':int,'dano_camp':int,'min':int,'pinks':int}}"
                    raw = json.loads(gemini.generate_content([prompt, Image.open(file)]).text.replace('```json', '').replace('```', '').strip())
                    sc = BravuraEngine.calculate_score(raw['vitoria'], raw['d'], raw['part'], raw['dano_est'], raw['dano_camp'], raw['min'], raw['pinks'])
                    m = MatchStats(MatchID=f"c_{int(time.time())}", Data=datetime.now().strftime('%d/%m'), Timestamp=time.time()*1000, Jogador=p_name, Tipo='Custom', Vitoria=raw['vitoria'], Score=sc, K=raw['k'], D=raw['d'], A=raw['a'], Part=raw['part'], Dano_Estruturas=raw['dano_est'], DPM=round(raw['dano_camp']/raw['min'], 2), Pinks=raw['pinks'], RankRiot="Custom")
                    db.save(m)
                    st.success("Salvo!")
                    st.rerun()
                except: st.error("Erro na leitura.")

        st.markdown("---")
        if st.button("🗑️ Resetar Database"):
            db.reset_database()
            st.rerun()

    df = db.get_all()
    # Lista de todos os jogadores reais (para garantir que quem tem 0 jogos apareça na tabela)
    todos_jogadores = sorted(list(ACCOUNT_COUNTS.keys()))
    
    # Prepara Dados Flex
    if not df.empty:
        df_f = df[df['Tipo'] != 'Custom']
    else:
        df_f = pd.DataFrame()

    # ABAS
    tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs(["🏆 RANKING", "🎖️ MEDALHAS", "📊 TRANSPARÊNCIA", "⚖️ ELOS", "⚓ AFUNDAMENTO", "🚪 QUEM SAI?", "👹 CUSTOMS"])

    # --- 1. RANKING (MÉDIA 0-100) ---
    with tab1:
        if not df_f.empty:
            k1, k2, k3, k4 = st.columns(4)
            mvp_name = df_f.groupby('Jogador')['Score'].mean().idxmax()
            mvp_val = df_f.groupby('Jogador')['Score'].mean().max()
            
            k1.metric("🔥 MVP (Média)", mvp_name, f"{mvp_val:.1f}")
            k2.metric("💀 Rei do Dano", df_f.groupby('Jogador')['DPM'].mean().idxmax(), f"{df_f['DPM'].max():.0f}")
            k3.metric("🎮 Flex Games", len(df_f))
            k4.metric("📈 Média Squad", f"{df_f['Score'].mean():.1f}")
            
            st.markdown("---")
            c1, c2 = st.columns([1.5, 2])
            with c1:
                stats = []
                for p in todos_jogadores:
                    if not df_f.empty:
                        d_p = df_f[df_f['Jogador'] == p]
                    else: d_p = pd.DataFrame()
                    
                    stats.append({
                        'Jogador': p, 
                        'Média': d_p['Score'].mean() if not d_p.empty else 0, 
                        'Jogos': len(d_p)
                    })
                
                lb = pd.DataFrame(stats).sort_values('Média', ascending=False)
                lb['Rank'] = lb['Média'].apply(get_rank_bravura)
                
                st.dataframe(lb[['Jogador', 'Rank', 'Média', 'Jogos']].style.background_gradient(cmap='YlOrRd', subset=['Média']), use_container_width=True, height=500)
            
            with c2:
                # Gráfico acumulativo
                df_f = df_f.sort_values('Timestamp')
                df_f['Acumulado'] = df_f.groupby('Jogador')['Score'].cumsum()
                fig = px.area(df_f, x='Data', y='Acumulado', color='Jogador', template='plotly_dark')
                st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Nenhum dado Flex encontrado. Clique em Atualizar.")

    # --- 2. MEDALHAS ---
    with tab2:
        if not df_f.empty:
            m1, m2, m3, m4 = st.columns(4)
            agg = df_f.groupby('Jogador').agg({'DPM': 'mean', 'Score': 'sum', 'D': 'sum', 'Part': 'mean', 'Vitoria': 'sum'})
            # Ariel: Menor part, Menos vitorias
            with m1: st.markdown(f"<div class='medal-box'><div class='medal-icon'>🐢</div><div>ARIEL</div><h2>{agg.sort_values(['Part', 'Vitoria']).index[0]}</h2></div>", unsafe_allow_html=True)
            with m2: st.markdown(f"<div class='medal-box'><div class='medal-icon'>🧨</div><div>DANUDO</div><h2>{agg['DPM'].idxmax()}</h2></div>", unsafe_allow_html=True)
            with m3: st.markdown(f"<div class='medal-box'><div class='medal-icon'>🔪</div><div>DINIZ</div><h2>{agg['Score'].idxmax()}</h2></div>", unsafe_allow_html=True)
            with m4: st.markdown(f"<div class='medal-box'><div class='medal-icon'>💀</div><div>INIMIGO KDA</div><h2>{agg['D'].idxmax()}</h2></div>", unsafe_allow_html=True)

    # --- 3. TRANSPARÊNCIA ---
    with tab3:
        if not df_f.empty:
            audit = df_f.groupby('Jogador').agg({'Score':'mean', 'K':'mean', 'D':'mean', 'A':'mean', 'DPM':'mean', 'Pinks':'mean', 'Part':'mean'}).round(2)
            st.dataframe(audit, use_container_width=True)

    # --- 4. COMPARAÇÃO ELOS ---
    with tab4:
        if not df_f.empty:
            # Pega último Rank Riot registrado
            elo = df_f.sort_values('Timestamp').groupby('Jogador').tail(1)[['Jogador', 'RankRiot']].set_index('Jogador')
            media = df_f.groupby('Jogador')['Score'].mean()
            comp = pd.DataFrame({'Riot (Flex)': elo['RankRiot'], 'Score Médio': media})
            comp['Rank Deidara'] = comp['Score Médio'].apply(get_rank_bravura)
            st.dataframe(comp.sort_values('Score Médio', ascending=False), use_container_width=True)

    # --- 5. ÍNDICE DE AFUNDAMENTO ---
    with tab5:
        if not df_f.empty:
            # Agrupa jogos onde >= 3 membros estavam juntos
            match_counts = df_f.groupby('MatchID')['Jogador'].count()
            squad_matches = match_counts[match_counts >= 3].index.tolist()
            df_sq = df_f[df_f['MatchID'].isin(squad_matches)]
            
            if not df_sq.empty:
                wr = df_sq.groupby('Jogador')['Vitoria'].mean()
                lr = ((1 - wr) * 100).reset_index(name='Taxa Derrota (%)').sort_values('Taxa Derrota (%)', ascending=False)
                fig_l = px.bar(lr, x='Jogador', y='Taxa Derrota (%)', color='Taxa Derrota (%)', color_continuous_scale='Reds', template='plotly_dark')
                st.plotly_chart(fig_l, use_container_width=True)
                st.caption(f"Baseado em {len(squad_matches)} partidas com 3+ membros.")
            else: st.info("Sem partidas em grupo (3+) registradas.")

    # --- 6. QUEM SAI? ---
    with tab6:
        if not df_f.empty:
            last_ts = df_f['Timestamp'].max()
            last_game = df_f[df_f['Timestamp'] == last_ts].sort_values('Score')
            if not last_game.empty:
                sai = last_game.iloc[0]
                st.error(f"QUEM SAI: {sai['Jogador']} (Score: {sai['Score']:.1f})")
                st.dataframe(last_game[['Jogador', 'Score', 'K', 'D', 'A', 'DPM']].style.highlight_min(subset=['Score'], color='red'), use_container_width=True)

    # --- 7. CUSTOMS ---
    with tab7:
        if not df.empty:
            df_c = df[df['Tipo'] == 'Custom']
            if not df_c.empty:
                st.dataframe(df_c.groupby('Jogador')['Score'].mean().sort_values(ascending=False), use_container_width=True)
                st.table(df_c[['Data', 'Jogador', 'Score', 'Vitoria']].tail(5))

    st.markdown("<hr><div class='footer-group'>É o grupo</div><div class='footer-final'>deidara HO</div>", unsafe_allow_html=True)

if __name__ == "__main__":
    render()
