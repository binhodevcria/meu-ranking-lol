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
# 0. CONFIGURAÇÕES
# ==============================================================================
BATCH_SIZE = 20 
RANKING_WINDOW = 15 

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
    
    div[data-testid="metric-container"] div[data-testid="stMetricValue"] {
        color: #00ff00 !important;
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
    SoloKills: int; Plates: int; Multikills: int
    RankRiot: Optional[str] = "Unranked"

class BravuraEngine:
    @staticmethod
    def calculate_performance_score(vitoria, part, dano_est, dano_camp, minutos, pinks, solo_kills, plates, multi_score):
        """Calcula APENAS a performance positiva (sem penalidades) para o histórico"""
        if minutos < 10: return 0.0
        
        # 1. Base
        score = 25.0 if vitoria else 0.0
        
        # 2. Performance
        dpm = dano_camp / minutos if minutos > 0 else 0
        score += (part * 40)       # KP
        score += (dpm / 100)       # Dano
        score += (dano_est / 500)  # Objetivos
        score += (pinks * 2.0)     # Visão (X2)
        
        # 3. Agressividade Extra (Novas Features)
        score += (solo_kills * 2.0) # X1
        score += (plates * 1.0)     # Placas
        score += multi_score        # Multikills

        return round(score, 2)

def get_rank_bravura(media):
    if pd.isna(media) or media == 0: return "💤 Inativo"
    if media < 25: return "🛡️ Defesa"
    if media < 45: return "🌿 Herbívoro"
    if media < 65: return "🤝 Honra Tentou"
    if media < 85: return "⚔️ Ofensivo"
    return "💉 Viciado em Dopamina"

# ==============================================================================
# 3. BANCO DE DADOS (FIXED MIGRATION)
# ==============================================================================
class DatabaseAdapter:
    FILE_DB = 'leaguestats_bravura.csv'
    
    def __init__(self):
        # Garante que o arquivo existe com TODAS as colunas
        expected_cols = list(MatchStats.model_fields.keys())
        
        if not os.path.exists(self.FILE_DB):
            pd.DataFrame(columns=expected_cols).to_csv(self.FILE_DB, index=False)
        else:
            try:
                df = pd.read_csv(self.FILE_DB)
                # Migração: Adiciona colunas faltantes com 0
                changed = False
                for col in expected_cols:
                    if col not in df.columns:
                        if col in ['MatchID', 'Data', 'Jogador', 'Tipo', 'RankRiot']:
                            df[col] = "Unknown"
                        else:
                            df[col] = 0
                        changed = True
                
                if changed: df.to_csv(self.FILE_DB, index=False)
            except: pass

    def get_all(self):
        try:
            df = pd.read_csv(self.FILE_DB, dtype={'MatchID': str})
            if df.empty: return pd.DataFrame()
            df['Jogador'] = df['Jogador'].apply(lambda x: NOME_DISPLAY.get(str(x).upper(), str(x).upper()))
            
            # Converte tudo que é numérico
            num_cols = ['Score', 'K', 'D', 'A', 'Part', 'DPM', 'Dano_Estruturas', 'Pinks', 'Timestamp', 'SoloKills', 'Plates', 'Multikills']
            for c in num_cols: 
                if c in df.columns: df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
            return df
        except: return pd.DataFrame()

    def save(self, stats: MatchStats):
        try:
            df = pd.read_csv(self.FILE_DB, dtype={'MatchID': str})
            stats_id = str(stats.MatchID)
            stats_player = str(stats.Jogador).upper()
            df['MatchID'] = df['MatchID'].astype(str)
            
            # Checa duplicidade
            if not ((df['MatchID'] == stats_id) & (df['Jogador'] == stats_player)).any():
                # Transforma o objeto stats em DataFrame garantindo as colunas
                new_row = pd.DataFrame([stats.model_dump()])
                pd.concat([df, new_row], ignore_index=True).to_csv(self.FILE_DB, index=False)
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
        self.season_start = 1735689600000 

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
            
            url = f"https://americas.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids?queue=440&startTime={1735689600}&start=0&count={BATCH_SIZE}"
            m_ids = self.request_blindado(url)
            
            if not m_ids: return [], 0, "Sem Flex Recente"
            
            data = []
            for m_id in m_ids:
                d = self.request_blindado(f"https://americas.api.riotgames.com/lol/match/v5/matches/{m_id}")
                if d:
                    if d['info']['gameCreation'] < self.season_start: continue

                    p = next((x for x in d['info']['participants'] if x['puuid'] == puuid), None)
                    if p:
                        mins = d['info']['gameDuration']/60
                        
                        # Extração Segura das Novas Métricas
                        challenges = p.get('challenges', {})
                        solo_kills = challenges.get('soloKills', 0)
                        plates = challenges.get('turretPlatesTaken', 0)
                        
                        multi_score = (p.get('doubleKills', 0)*1) + (p.get('tripleKills', 0)*3) + (p.get('quadraKills', 0)*5) + (p.get('pentaKills', 0)*10)

                        sc = BravuraEngine.calculate_performance_score(
                            p['win'], p.get('challenges', {}).get('killParticipation', 0), 
                            p['damageDealtToBuildings'], p['totalDamageDealtToChampions'], mins, 
                            p['visionWardsBoughtInGame'], solo_kills, plates, multi_score
                        )
                        
                        data.append(MatchStats(
                            MatchID=str(m_id), 
                            Data=datetime.fromtimestamp(d['info']['gameCreation']/1000).strftime('%d/%m'), 
                            Timestamp=d['info']['gameCreation'], 
                            Jogador=nome.upper(), 
                            Tipo='Flex', 
                            Vitoria=p['win'], 
                            Score=sc, K=p['kills'], D=p['deaths'], A=p['assists'], 
                            Part=p.get('challenges', {}).get('killParticipation', 0), 
                            Dano_Estruturas=p['damageDealtToBuildings'], 
                            DPM=round(p['totalDamageDealtToChampions']/mins, 2), 
                            Pinks=p['visionWardsBoughtInGame'], 
                            SoloKills=solo_kills, Plates=plates, Multikills=multi_score,
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
            if st.button(f"🔄 Sincronizar (Últimas {BATCH_SIZE})"):
                log = st.status("Verificando partidas recentes...", expanded=True)
                total_added = 0
                for p in SQUAD_LIST:
                    log.write(f"🔎 **{p['nick']}**...")
                    matches, count, msg = riot.fetch_recent_flex(p['nick'], p['tag'])
                    if matches is not None:
                        saved = 0
                        for m in matches:
                            if db.save(m): saved += 1
                        total_added += saved
                        if saved > 0: log.write(f"✅ +{saved} novas!")
                    else: log.error(f"❌ Erro: {msg}")
                    time.sleep(0.2)
                log.update(label="Fim!", state="complete", expanded=False)
                if total_added > 0:
                    st.success(f"{total_added} partidas adicionadas!")
                    time.sleep(2)
                    st.rerun()
                else: st.info("Tudo em dia.")
        
        st.markdown("---")
        with st.expander("🛠️ Admin"):
            if st.button("Resetar Tudo (Limpar Banco)"):
                db.reset_database()
                st.rerun()

    df = db.get_all()
    todos = sorted(list(set(NOME_DISPLAY.get(p['nick'].upper(), p['nick'].upper()) for p in SQUAD_LIST)))
    df_f = df[df['Tipo'] != 'Custom'] if not df.empty else pd.DataFrame()

    df_ranking = pd.DataFrame()
    if not df_f.empty:
        # Janela de X partidas
        df_ranking = df_f.sort_values('Timestamp', ascending=False).groupby('Jogador').head(RANKING_WINDOW)

    # --- LÓGICA DE SCORE AGREGADO (MÉDIA DE COMPORTAMENTO) ---
    ranking_data = []
    if not df_ranking.empty:
        for p in todos:
            d = df_ranking[df_ranking['Jogador'] == p]
            if d.empty: continue
            
            # --- CÁLCULO DETALHADO DO SCORE (MÉDIA DA JANELA) ---
            # 1. Base
            avg_win = d['Vitoria'].mean() * 25.0
            
            # 2. Performance
            avg_kp = d['Part'].mean() * 40.0
            avg_dpm = d['DPM'].mean() / 100.0
            avg_obj = d['Dano_Estruturas'].mean() / 500.0
            avg_vis = d['Pinks'].mean() * 2.0
            
            # 3. Agressividade
            avg_x1 = d['SoloKills'].mean() * 2.0
            avg_plates = d['Plates'].mean() * 1.0
            avg_multi = d['Multikills'].mean() 
            
            # Soma Bruta
            final_score = avg_win + avg_kp + avg_dpm + avg_obj + avg_vis + avg_x1 + avg_plates + avg_multi
            
            # 4. Penalidades Holísticas
            penalidade = 0.0
            
            # KDA Player: Se a MÉDIA de mortes for <= 2 e a MÉDIA de KP for < 35%
            if d['D'].mean() <= 2.0 and d['Part'].mean() < 0.35:
                penalidade -= 25.0
            
            # Pacifista: Se a MÉDIA de Dano por Minuto for < 300
            if d['DPM'].mean() < 300:
                penalidade -= 10.0
            
            final_score += penalidade
            
            ranking_data.append({
                'Jogador': p,
                'Score Final': final_score,
                'Jogos': len(d),
                'DPM': d['DPM'].mean(),
                'Max_DPM': d['DPM'].max(),
                'Total_X1': d['SoloKills'].sum(),
                # Dados para Auditoria
                'Pts_Win': avg_win, 'Pts_KP': avg_kp, 'Pts_Dano': avg_dpm, 
                'Pts_Torre': avg_obj, 'Pts_Visao': avg_vis, 
                'Pts_X1': avg_x1, 'Pts_Plates': avg_plates, 'Pts_Multi': avg_multi,
                'Penalidade': penalidade
            })
            
    df_final = pd.DataFrame(ranking_data).sort_values('Score Final', ascending=False)

    t1, t2, t3, t4, t5, t6, t7 = st.tabs(["🏆 RANKING", "🎖️ MEDALHAS", "📊 TRANSPARÊNCIA", "⚖️ ELOS", "⚓ AFUNDAMENTO", "🚪 QUEM SAI?", "👹 CUSTOMS"])

    with t1:
        if not df_final.empty:
            k1, k2, k3, k4 = st.columns(4)
            
            mvp_row = df_final.iloc[0]
            k1.metric("🔥 MVP (Score)", mvp_row['Jogador'], f"{mvp_row['Score Final']:.1f}")
            
            dmg_king = df_final.loc[df_final['Max_DPM'].idxmax()]
            k2.metric("💀 Maior Dano (Pico)", dmg_king['Jogador'], f"{dmg_king['Max_DPM']:.0f}")
            
            x1_king = df_final.loc[df_final['Total_X1'].idxmax()]
            k3.metric("🎪 Circo (Rei X1)", x1_king['Jogador'], f"{int(x1_king['Total_X1'])} Kills")
            
            k4.metric("⚖️ Janela Ranking", f"Últimas {RANKING_WINDOW}")
            
            st.markdown("---")
            c1, c2 = st.columns([1.5, 2])
            with c1:
                df_final['Rank'] = df_final['Score Final'].apply(get_rank_bravura)
                st.dataframe(df_final[['Jogador', 'Rank', 'Score Final', 'Jogos']].style.background_gradient(cmap='YlOrRd', subset=['Score Final']), use_container_width=True)
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
            except: st.warning("Dados insuficientes.")

    with t3:
        if not df_final.empty:
            st.subheader(f"📊 Auditoria Detalhada (Pontos Agregados na Janela)")
            audit_cols = ['Jogador', 'Score Final', 'Pts_Win', 'Pts_KP', 'Pts_Dano', 'Pts_Torre', 'Pts_Visao', 'Pts_X1', 'Pts_Plates', 'Pts_Multi', 'Penalidade']
            st.dataframe(df_final[audit_cols].sort_values('Score Final', ascending=False).round(2), use_container_width=True)

    with t4:
        if not df_f.empty:
            elo = df_f.sort_values('Timestamp').groupby('Jogador').tail(1)[['Jogador', 'RankRiot']].set_index('Jogador')
            comp = df_final[['Jogador', 'Score Final']].set_index('Jogador')
            comp['Riot'] = elo['RankRiot']
            comp['Rank Deidara'] = comp['Score Final'].apply(get_rank_bravura)
            st.dataframe(comp.sort_values('Score Final', ascending=False), use_container_width=True)

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
            else: st.info("Sem jogos de grupo.")

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
