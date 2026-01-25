import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import google.generativeai as genai
import requests
import os
import json
import time
import numpy as np
from datetime import datetime
from PIL import Image
from pydantic import BaseModel
from urllib.parse import quote
from typing import Optional

# ==============================================================================
# 0. CONFIGURAÇÕES (LÓGICA V18 + AGREGADO)
# ==============================================================================
BATCH_SIZE = 20 
RANKING_WINDOW = 15 # Janela de análise para o Agregado

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
    {"nick": "Sugiro Correr", "tag": "BR1"}
]

NOME_DISPLAY = {
    "GUIZINHA": "GUIZA",
    "EZFALSE": "GUIZA",
    "GUIZA": "GUIZA"
}

st.set_page_config(page_title="OFENSIVO SCORE", layout="wide", page_icon="⚔️")

# ==============================================================================
# 1. VISUAL
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
    
    .medal-box {
        background: linear-gradient(145deg, #1e2328, #1a1c24); 
        border: 1px solid #c8aa6e; 
        padding: 20px; 
        border-radius: 10px; 
        text-align: center; 
        box-shadow: 0 4px 15px rgba(0,0,0,0.6); 
        height: 240px; 
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;
    }
    .medal-icon { font-size: 3.5em; margin-bottom: 10px; line-height: 1; }
    .medal-title { color: #d4af37; font-weight: bold; font-size: 1.1em; text-transform: uppercase; letter-spacing: 1px; margin: 0; }
    .medal-player { color: #ff4b4b; font-weight: 800; font-size: 1.6em; margin: 10px 0; text-shadow: 0px 2px 4px rgba(0,0,0,0.8); line-height: 1.2; }
    .medal-desc { color: #a0a0a0; font-style: italic; font-size: 0.85em; }

    .title-text { font-size: 3.5em; font-weight: bold; color: #ff4b4b; text-align: center; text-shadow: 2px 2px #000; }
    .subtitle-text { font-size: 1.2em; font-style: italic; color: #a0a0a0; text-align: center; margin-bottom: 30px; }
    
    .footer-group { font-size: 1.8em; color: #ffffff; text-align: left; margin-top: 60px; margin-left: 20px; }
    .footer-final { font-size: 5em; font-weight: bold; color: #d4af37; text-align: center; margin-top: 10px; font-family: 'Impact', sans-serif; letter-spacing: 6px; text-shadow: 3px 3px 0px #000; }
    
    .stButton>button { background-color: #1e2328; color: #cdbe91; border: 1px solid #463714; font-weight: bold; width: 100%; }
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# 2. MOTORES
# ==============================================================================
class MatchStats(BaseModel):
    MatchID: str; Data: str; Timestamp: float; Jogador: str; Tipo: str
    Vitoria: bool; Score: float; K: int; D: int; A: int; Part: float
    Dano_Estruturas: int; DPM: float; Pinks: int
    RankRiot: Optional[str] = "Unranked"

class BravuraEngine:
    @staticmethod
    def calculate_score(vitoria, d, part, dano_est, dano_camp, minutos, pinks):
        # Esta função calcula o score INDIVIDUAL da partida (para histórico e gráficos)
        if minutos < 10: return 0.0
        score = 25.0 if vitoria else 0.0
        score += (part * 40)
        dpm = dano_camp / minutos if minutos > 0 else 0
        score += (dpm / 100)
        score += (dano_est / 500)
        score += (pinks * 2.0)
        # Penalidade Individual (Ainda existe no histórico, mas não no ranking agregado)
        if d <= 2 and part < 0.35: score -= 25.0
        return round(score, 2)

def get_rank_bravura(media):
    if pd.isna(media) or media == 0: return "💤 Inativo"
    if media < 20: return "🛡️ Defesa"
    if media < 40: return "🌿 Herbívoro"
    if media < 60: return "🤝 Honra Tentou"
    if media < 80: return "⚔️ Ofensivo"
    return "💉 Viciado em Dopamina"

# ==============================================================================
# 3. BANCO DE DADOS
# ==============================================================================
class DatabaseAdapter:
    FILE_DB = 'leaguestats_bravura.csv'
    
    def __init__(self):
        if not os.path.exists(self.FILE_DB):
            pd.DataFrame(columns=MatchStats.model_fields.keys()).to_csv(self.FILE_DB, index=False)
        else:
            try:
                df = pd.read_csv(self.FILE_DB)
                if 'RankRiot' not in df.columns:
                    df['RankRiot'] = 'Unranked'
                    df.to_csv(self.FILE_DB, index=False)
            except: pass

    def get_all(self):
        try:
            df = pd.read_csv(self.FILE_DB, dtype={'MatchID': str})
            if df.empty: return pd.DataFrame()
            df['Jogador'] = df['Jogador'].apply(lambda x: NOME_DISPLAY.get(str(x).upper(), str(x).upper()))
            num_cols = ['Score', 'K', 'D', 'A', 'Part', 'DPM', 'Dano_Estruturas', 'Pinks', 'Timestamp']
            for c in num_cols: df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
            return df
        except: return pd.DataFrame()

    def save(self, stats: MatchStats):
        try:
            df = pd.read_csv(self.FILE_DB, dtype={'MatchID': str})
            stats_id = str(stats.MatchID)
            stats_player = str(stats.Jogador).upper()
            df['MatchID'] = df['MatchID'].astype(str)
            if not ((df['MatchID'] == stats_id) & (df['Jogador'] == stats_player)).any():
                pd.concat([df, pd.DataFrame([stats.model_dump()])], ignore_index=True).to_csv(self.FILE_DB, index=False)
                return True
            return False
        except: return False
    
    def reset_database(self):
        if os.path.exists(self.FILE_DB): os.remove(self.FILE_DB)
        pd.DataFrame(columns=MatchStats.model_fields.keys()).to_csv(self.FILE_DB, index=False)
        return True

# ==============================================================================
# 4. API RIOT
# ==============================================================================
class RiotAdapter:
    def __init__(self, api_key):
        self.headers = {"X-Riot-Token": api_key}
        self.season_start = 1735689600 

    def request_blindado(self, url):
        for i in range(3):
            try:
                resp = requests.get(url, headers=self.headers)
                if resp.status_code == 200: return resp.json()
                elif resp.status_code == 429:
                    time.sleep(int(resp.headers.get("Retry-After", 5)) + 1)
                    continue
                elif resp.status_code == 404: return None
            except: return None
        return None

    def fetch_rank(self, puuid):
        try:
            summ = self.request_blindado(f"https://br1.api.riotgames.com/lol/summoner/v4/summoners/by-puuid/{puuid}")
            if not summ: return "Unranked"
            leagues = self.request_blindado(f"https://br1.api.riotgames.com/lol/league/v4/entries/by-summoner/{summ['id']}")
            if leagues:
                flex = next((l for l in leagues if l['queueType'] == "RANKED_FLEX_SR"), None)
                if flex: return f"{flex['tier']} {flex['rank']}"
            return "Unranked"
        except: return "Unranked"

    def fetch_recent_flex(self, nome, tag):
        try:
            n, t = quote(nome.strip()), quote(tag.replace('#','').strip())
            acc = self.request_blindado(f"https://americas.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{n}/{t}")
            if not acc: return None, 0, "Conta não achada"
            puuid = acc['puuid']
            
            rank_atual = self.fetch_rank(puuid)
            
            url = f"https://americas.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids?queue=440&startTime={self.season_start}&start=0&count={BATCH_SIZE}"
            m_ids = self.request_blindado(url)
            
            if not m_ids: return [], 0, "Sem Flex Recente"
            
            data = []
            for m_id in m_ids:
                d = self.request_blindado(f"https://americas.api.riotgames.com/lol/match/v5/matches/{m_id}")
                if d:
                    p = next((x for x in d['info']['participants'] if x['puuid'] == puuid), None)
                    if p:
                        mins = d['info']['gameDuration']/60
                        sc = BravuraEngine.calculate_score(p['win'], p['deaths'], p['challenges'].get('killParticipation', 0), p['damageDealtToBuildings'], p['totalDamageDealtToChampions'], mins, p['visionWardsBoughtInGame'])
                        data.append(MatchStats(
                            MatchID=str(m_id), 
                            Data=datetime.fromtimestamp(d['info']['gameCreation']/1000).strftime('%d/%m'), 
                            Timestamp=d['info']['gameCreation'], 
                            Jogador=nome.upper(), 
                            Tipo='Flex', 
                            Vitoria=p['win'], 
                            Score=sc, K=p['kills'], D=p['deaths'], A=p['assists'], 
                            Part=p['challenges'].get('killParticipation', 0), 
                            Dano_Estruturas=p['damageDealtToBuildings'], 
                            DPM=round(p['totalDamageDealtToChampions']/mins, 2), 
                            Pinks=p['visionWardsBoughtInGame'], 
                            RankRiot=rank_atual
                        ))
                time.sleep(0.1)
            return data, len(data), "OK"
        except Exception as e: return None, 0, str(e)

# ==============================================================================
# 5. RENDER UI
# ==============================================================================
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
            if st.button(f"🔄 Sincronizar (Recentes)"):
                log = st.status("Verificando partidas recentes...", expanded=True)
                total_novos = 0
                for p in SQUAD_LIST:
                    log.write(f"🔎 **{p['nick']}**...")
                    matches, count, msg = riot.fetch_recent_flex(p['nick'], p['tag'])
                    if matches is not None:
                        saved = 0
                        for m in matches:
                            if db.save(m): saved += 1
                        total_novos += saved
                        if saved > 0: log.write(f"✅ +{saved} novas!")
                    else: log.error(f"❌ Erro: {msg}")
                    time.sleep(0.2)
                log.update(label="Fim!", state="complete", expanded=False)
                if total_novos > 0:
                    st.success(f"{total_novos} adicionadas!")
                    time.sleep(2)
                    st.rerun()
                else: st.info("Tudo em dia.")
        
        else:
            file = st.file_uploader("Upload Print", type=['png','jpg'])
            p_name = st.text_input("Nick").upper()
            if st.button("🤖 Analisar") and file and gemini:
                try:
                    prompt = f"Extraia stats LoL JSON para {p_name}: {{'vitoria':bool,'k':int,'d':int,'a':int,'part':float,'dano_est':int,'dano_camp':int,'min':int,'pinks':int}}"
                    raw = json.loads(gemini.generate_content([prompt, Image.open(file)]).text.replace('```json', '').replace('```', '').strip())
                    sc = BravuraEngine.calculate_score(raw['vitoria'], raw['d'], raw['part'], raw['dano_est'], raw['dano_camp'], raw['min'], raw['pinks'])
                    m = MatchStats(MatchID=f"c_{int(time.time())}", Data=datetime.now().strftime('%d/%m'), Timestamp=time.time()*1000, Jogador=p_name, Tipo='Custom', Vitoria=raw['vitoria'], Score=sc, K=raw['k'], D=raw['d'], A=raw['a'], Part=raw['part'], Dano_Estruturas=raw['dano_est'], DPM=round(raw['dano_camp']/raw['min'], 2), Pinks=raw['pinks'], RankRiot="Custom")
                    db.save(m)
                    st.success("Salvo!")
                    st.rerun()
                except: st.error("Erro no print.")
        
        st.markdown("---")
        with st.expander("🛠️ Admin"):
            if st.button("Resetar Tudo"):
                db.reset_database()
                st.rerun()

    df = db.get_all()
    todos = sorted(list(set(NOME_DISPLAY.get(p['nick'].upper(), p['nick'].upper()) for p in SQUAD_LIST)))
    df_f = df[df['Tipo'] != 'Custom'] if not df.empty else pd.DataFrame()

    # --- PROCESSAMENTO AGREGADO (HOLÍSTICO) ---
    ranking_data = []
    
    # Separa as últimas 15 partidas por jogador
    df_window = pd.DataFrame()
    if not df_f.empty:
        df_window = df_f.sort_values('Timestamp', ascending=False).groupby('Jogador').head(RANKING_WINDOW)
    
    # Calcula os scores AGREGADOS (Média do comportamento e não média dos scores)
    for p in todos:
        d = df_window[df_window['Jogador'] == p]
        if d.empty: continue
        
        # 1. Vitórias (25 pts se 100% winrate)
        win_rate = d['Vitoria'].mean()
        pts_win = 25.0 * win_rate
        
        # 2. Participação (Média * 40)
        avg_kp = d['Part'].mean()
        pts_kp = avg_kp * 40.0
        
        # 3. Dano (Média / 100)
        avg_dpm = d['DPM'].mean()
        pts_dpm = avg_dpm / 100.0
        
        # 4. Torre (Média / 500)
        avg_tower = d['Dano_Estruturas'].mean()
        pts_tower = avg_tower / 500.0
        
        # 5. Visão (Média * 2.0)
        avg_vision = d['Pinks'].mean()
        pts_vision = avg_vision * 2.0
        
        # 6. PENALIDADE AGREGADA
        # Só pune se a MÉDIA de mortes for baixa E a MÉDIA de participação for baixa
        avg_deaths = d['D'].mean()
        penalidade = 0.0
        if avg_deaths <= 2.0 and avg_kp < 0.35:
            penalidade = -25.0
            
        final_score = pts_win + pts_kp + pts_dpm + pts_tower + pts_vision + penalidade
        
        ranking_data.append({
            'Jogador': p,
            'Score Agregado': final_score,
            'Jogos': len(d),
            'DPM': avg_dpm, # Média para tabela
            'Max_DPM': d['DPM'].max(), # Máximo para destaque
            'Pts_KP': pts_kp,
            'Pts_Dano': pts_dpm,
            'Pts_Torre': pts_tower,
            'Pts_Visao': pts_vision,
            'Penalidade': penalidade
        })
        
    df_ranking_final = pd.DataFrame(ranking_data)

    t1, t2, t3, t4, t5, t6, t7 = st.tabs(["🏆 RANKING", "🎖️ MEDALHAS", "📊 TRANSPARÊNCIA", "⚖️ ELOS", "⚓ AFUNDAMENTO", "🚪 QUEM SAI?", "👹 CUSTOMS"])

    with t1:
        if not df_ranking_final.empty:
            k1, k2, k3, k4 = st.columns(4)
            
            # CARD 1: MVP (Maior Score Agregado)
            mvp_row = df_ranking_final.loc[df_ranking_final['Score Agregado'].idxmax()]
            k1.metric("🔥 MVP (Score)", mvp_row['Jogador'], f"{mvp_row['Score Agregado']:.1f}")
            
            # CARD 2: MAIOR DANO (Pico Único na Janela)
            # Encontra quem teve o maior pico de dano em uma partida
            dmg_king_row = df_ranking_final.loc[df_ranking_final['Max_DPM'].idxmax()]
            k2.metric("💀 Maior Dano (Pico)", dmg_king_row['Jogador'], f"{dmg_king_row['Max_DPM']:.0f}")
            
            # CARD 3: VICIADO
            viciado_row = df_ranking_final.loc[df_ranking_final['Jogos'].idxmax()]
            k3.metric("🎮 Viciado", viciado_row['Jogador'], f"{viciado_row['Jogos']} Jogos (Janela)")
            
            k4.metric("⚖️ Janela Ranking", f"Últimas {RANKING_WINDOW}")
            
            st.markdown("---")
            c1, c2 = st.columns([1.5, 2])
            with c1:
                # Tabela ordenada por Score Agregado
                lb = df_ranking_final.sort_values('Score Agregado', ascending=False)
                lb['Rank'] = lb['Score Agregado'].apply(get_rank_bravura)
                st.dataframe(lb[['Jogador', 'Rank', 'Score Agregado', 'Jogos']].style.background_gradient(cmap='YlOrRd', subset=['Score Agregado']), use_container_width=True)
            with c2:
                df_hist = df_f.sort_values('Timestamp')
                df_hist['Acumulado'] = df_hist.groupby('Jogador')['Score'].cumsum()
                fig = px.area(df_hist, x='Data', y='Acumulado', color='Jogador', template='plotly_dark')
                st.plotly_chart(fig, use_container_width=True)
        else: st.info("Sem dados. Clique em Sincronizar.")

    with t2:
        if not df_f.empty: 
            m1, m2, m3, m4 = st.columns(4)
            agg = df_f.groupby('Jogador').agg({'DPM': 'mean', 'Score': 'sum', 'D': 'sum', 'Part': 'mean', 'Vitoria': 'sum'})
            try:
                p_safe = agg.sort_values(['Part', 'Vitoria']).index[0]
                p_dmg = agg['DPM'].idxmax()
                p_mvp = agg['Score'].idxmax()
                p_kda = agg['D'].idxmax()
                
                with m1: st.markdown(f"<div class='medal-box'><div class='medal-icon'>🐢</div><div class='medal-title'>ARIEL</div><div class='medal-player'>{p_safe}</div><span class='medal-desc'>Mais Safe (Menor KP)</span></div>", unsafe_allow_html=True)
                with m2: st.markdown(f"<div class='medal-box'><div class='medal-icon'>🧨</div><div class='medal-title'>DANUDO</div><div class='medal-player'>{p_dmg}</div><span class='medal-desc'>Maior Dano Médio</span></div>", unsafe_allow_html=True)
                with m3: st.markdown(f"<div class='medal-box'><div class='medal-icon'>🔪</div><div class='medal-title'>DINIZ</div><div class='medal-player'>{p_mvp}</div><span class='medal-desc'>Maior Soma de Pontos</span></div>", unsafe_allow_html=True)
                with m4: st.markdown(f"<div class='medal-box'><div class='medal-icon'>💀</div><div class='medal-title'>INIMIGO KDA</div><div class='medal-player'>{p_kda}</div><span class='medal-desc'>Quem mais morreu</span></div>", unsafe_allow_html=True)
            except: st.warning("Dados insuficientes para medalhas.")

    with t3:
        if not df_ranking_final.empty:
            st.subheader(f"📊 Auditoria (Cálculo Agregado)")
            # Exibe os dados calculados no loop principal (Agregados)
            audit_cols = ['Jogador', 'Score Agregado', 'Pts_KP', 'Pts_Dano', 'Pts_Torre', 'Pts_Visao', 'Penalidade']
            st.dataframe(df_ranking_final[audit_cols].sort_values('Score Agregado', ascending=False).round(2), use_container_width=True)

    with t4:
        if not df_f.empty:
            elo = df_f.sort_values('Timestamp').groupby('Jogador').tail(1)[['Jogador', 'RankRiot']].set_index('Jogador')
            # Usa o Score Agregado para comparar
            comp = df_ranking_final[['Jogador', 'Score Agregado']].set_index('Jogador')
            comp['Riot Flex'] = elo['RankRiot']
            comp['Rank Deidara'] = comp['Score Agregado'].apply(get_rank_bravura)
            st.dataframe(comp.sort_values('Score Agregado', ascending=False), use_container_width=True)

    with t5:
        if not df_f.empty:
            mc = df_f.groupby('MatchID')['Jogador'].count()
            sq = mc[mc >= 3].index.tolist()
            df_sq = df_f[df_f['MatchID'].isin(sq)]
            if not df_sq.empty:
                cnt = df_sq['Jogador'].value_counts()
                val = cnt[cnt >= 5].index.tolist()
                df_b = df_sq[df_sq['Jogador'].isin(val)]
                if not df_b.empty:
                    lr = ((1 - df_b.groupby('Jogador')['Vitoria'].mean()) * 100).reset_index(name='Derrota %').sort_values('Derrota %', ascending=False)
                    st.plotly_chart(px.bar(lr, x='Jogador', y='Derrota %', color='Derrota %', template='plotly_dark', color_continuous_scale='Reds'), use_container_width=True)
                else: st.info("Necessário 5+ jogos em grupo.")
            else: st.info("Sem jogos de grupo (3+).")

    with t6:
        if not df_f.empty:
            last_ts = df_f['Timestamp'].max()
            last = df_f[df_f['Timestamp'] == last_ts].sort_values('Score')
            if not last.empty:
                st.error(f"QUEM SAI: {last.iloc[0]['Jogador']}")
                st.dataframe(last[['Jogador', 'Score', 'K', 'D', 'A']].style.highlight_min(subset=['Score'], color='red'), use_container_width=True)

    with t7:
        if not df.empty:
            df_c = df[df['Tipo'] == 'Custom']
            if not df_c.empty:
                st.dataframe(df_c.groupby('Jogador')['Score'].mean().sort_values(ascending=False), use_container_width=True)

    st.markdown("<hr><div class='footer-group'>É o grupo</div><div class='footer-final'>deidara HO</div>", unsafe_allow_html=True)

if __name__ == "__main__":
    render()
