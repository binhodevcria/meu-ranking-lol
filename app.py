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
# 0. SQUAD LIST & CONFIGURAÇÕES
# ==============================================================================
# Define o tamanho do lote de atualização (Rápido e constante)
BATCH_SIZE = 20 

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
    
    /* Cards de KPI */
    div[data-testid="metric-container"] {
        background-color: #1a1c24; border-left: 4px solid #c8aa6e;
        padding: 15px; border-radius: 6px; box-shadow: 0 4px 10px rgba(0,0,0,0.5);
    }
    
    /* Medalhas */
    .medal-box {
        background: linear-gradient(145deg, #1e2328, #1a1c24); border: 1px solid #c8aa6e;
        padding: 15px; border-radius: 10px; text-align: center;
        box-shadow: 0 4px 15px rgba(0,0,0,0.6); height: 100%; display: flex; flex-direction: column; justify-content: center; align-items: center;
    }
    .medal-icon { font-size: 3.5em; margin-bottom: 5px; }
    .medal-title { color: #d4af37; font-weight: bold; font-size: 1.2em; text-transform: uppercase; margin: 0; }
    .medal-player { color: #ff4b4b; font-weight: bold; font-size: 1.5em; margin: 5px 0; }
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
# 2. LÓGICA DE NEGÓCIO
# ==============================================================================
class MatchStats(BaseModel):
    MatchID: str; Data: str; Timestamp: float; Jogador: str; Tipo: str
    Vitoria: bool; Score: float; K: int; D: int; A: int; Part: float
    Dano_Estruturas: int; DPM: float; Pinks: int
    RankRiot: Optional[str] = "Unranked"

class BravuraEngine:
    @staticmethod
    def calculate_score(vitoria, d, part, dano_est, dano_camp, minutos, pinks):
        if minutos < 10: return 0.0
        score = 25.0 if vitoria else 0.0
        score += (part * 40)
        dpm = dano_camp / minutos if minutos > 0 else 0
        score += (dpm / 100)
        score += (dano_est / 500)
        score += (pinks * 1.0)
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
# 3. INFRAESTRUTURA
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
            # LÓGICA DE ACÚMULO:
            # Verifica se essa partida (ID) para esse jogador JÁ EXISTE.
            # Se não existir, salva. Se existir, ignora.
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
        for i in range(3):
            resp = requests.get(url, headers=self.headers)
            if resp.status_code == 200: return resp.json()
            elif resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", 5))
                time.sleep(wait + 1)
                continue
            elif resp.status_code == 404: return None
            else: return None
        return None

    def fetch_rank(self, puuid):
        # Tenta buscar o Elo Flex na API BR1
        try:
            summ = self.request_blindado(f"https://br1.api.riotgames.com/lol/summoner/v4/summoners/by-puuid/{puuid}")
            if not summ: return "Unranked"
            leagues = self.request_blindado(f"https://br1.api.riotgames.com/lol/league/v4/entries/by-summoner/{summ['id']}")
            if leagues:
                flex = next((l for l in leagues if l['queueType'] == "RANKED_FLEX_SR"), None)
                if flex: return f"{flex['tier']} {flex['rank']}"
            return "Unranked"
        except: return "Unranked"

    def fetch_latest_flex_batch(self, nome, tag):
        try:
            n, t = quote(nome.strip()), quote(tag.replace('#','').strip())
            acc = self.request_blindado(f"https://americas.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{n}/{t}")
            if not acc: return None, 0, "Conta não encontrada"
            puuid = acc['puuid']
            
            # 1. Pega Elo Atualizado
            rank_atual = self.fetch_rank(puuid)

            # 2. Busca as ÚLTIMAS 20 partidas FLEX (queue=440)
            # Isso é rápido e eficiente. Se tiver partidas novas, elas estarão aqui.
            url_ids = f"https://americas.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids?queue=440&startTime={self.season_start}&start=0&count={BATCH_SIZE}"
            
            m_ids = self.request_blindado(url_ids)
            if not m_ids: return [], 0, "Sem Flex Recente"
            
            data = []
            
            for m_id in m_ids:
                d = self.request_blindado(f"https://americas.api.riotgames.com/lol/match/v5/matches/{m_id}")
                if d:
                    p = next((x for x in d['info']['participants'] if x['puuid'] == puuid), None)
                    if p:
                        mins = d['info']['gameDuration']/60
                        sc = BravuraEngine.calculate_score(p['win'], p['deaths'], p['challenges'].get('killParticipation', 0), p['damageDealtToBuildings'], p['totalDamageDealtToChampions'], mins, p['visionWardsBoughtInGame'])
                        data.append(MatchStats(MatchID=str(m_id), Data=datetime.fromtimestamp(d['info']['gameCreation']/1000).strftime('%d/%m'), Timestamp=d['info']['gameCreation'], Jogador=nome.upper(), Tipo='Flex', Vitoria=p['win'], Score=sc, K=p['kills'], D=p['deaths'], A=p['assists'], Part=p['challenges'].get('killParticipation', 0), Dano_Estruturas=p['damageDealtToBuildings'], DPM=round(p['totalDamageDealtToChampions']/mins, 2), Pinks=p['visionWardsBoughtInGame'], RankRiot=rank_atual))
                
                time.sleep(0.1) 
            
            return data, len(data), "OK"
            
        except Exception as e: return None, 0, str(e)

# ==============================================================================
# 4. RENDER
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
                status_log = st.status(f"Buscando as {BATCH_SIZE} últimas Flex de cada um...", expanded=True)
                total_novos = 0
                
                for idx, p in enumerate(SQUAD_LIST):
                    status_log.write(f"🔎 **{p['nick']}**: Verificando...")
                    
                    matches, total_fetched, msg = riot.fetch_latest_flex_batch(p['nick'], p['tag'])
                    
                    if matches is not None:
                        saved_count = 0
                        for m in matches: 
                            if db.save(m): saved_count += 1 # Só incrementa se for NOVO no banco
                        
                        total_novos += saved_count
                        
                        if saved_count > 0:
                            status_log.write(f"✅ {p['nick']}: +{saved_count} novas partidas salvas!")
                        else:
                            status_log.write(f"💤 {p['nick']}: Nenhuma novidade.")
                    else:
                        status_log.error(f"❌ {p['nick']}: {msg}")
                    
                    time.sleep(0.3)
                
                status_log.update(label="Sincronização Finalizada!", state="complete", expanded=False)
                
                if total_novos > 0:
                    st.success(f"Sucesso! {total_novos} novas partidas adicionadas ao histórico.")
                    time.sleep(2)
                    st.rerun()
                else:
                    st.info("O banco de dados já está atualizado com as últimas partidas.")

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
    todos = sorted(list(set(NOME_DISPLAY.get(p['nick'].upper(), p['nick'].upper()) for p in SQUAD_LIST)))
    df_f = df[df['Tipo'] != 'Custom'] if not df.empty else pd.DataFrame()

    # ABAS
    t1, t2, t3, t4, t5, t6, t7 = st.tabs(["🏆 RANKING", "🎖️ MEDALHAS", "📊 TRANSPARÊNCIA", "⚖️ ELOS", "⚓ AFUNDAMENTO", "🚪 QUEM SAI?", "👹 CUSTOMS"])

    with t1:
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
                for p in todos:
                    d = df_f[df_f['Jogador'] == p]
                    stats.append({'Jogador': p, 'Média': d['Score'].mean() if not d.empty else 0, 'Jogos': len(d)})
                lb = pd.DataFrame(stats).sort_values('Média', ascending=False)
                lb['Rank'] = lb['Média'].apply(get_rank_bravura)
                st.dataframe(lb[['Jogador', 'Rank', 'Média', 'Jogos']].style.background_gradient(cmap='YlOrRd', subset=['Média']), use_container_width=True)
            with c2:
                df_f = df_f.sort_values('Timestamp')
                df_f['Acumulado'] = df_f.groupby('Jogador')['Score'].cumsum()
                fig = px.area(df_f, x='Data', y='Acumulado', color='Jogador', template='plotly_dark')
                st.plotly_chart(fig, use_container_width=True)

    with t2:
        if not df_f.empty:
            m1, m2, m3, m4 = st.columns(4)
            agg = df_f.groupby('Jogador').agg({'DPM': 'mean', 'Score': 'sum', 'D': 'sum', 'Part': 'mean', 'Vitoria': 'sum'})
            with m1: st.markdown(f"<div class='medal-box'><div class='medal-icon'>🐢</div><div class='medal-title'>ARIEL</div><div class='medal-player'>{agg.sort_values(['Part', 'Vitoria']).index[0]}</div><span class='medal-desc'>Mais Safe (Menor KP)</span></div>", unsafe_allow_html=True)
            with m2: st.markdown(f"<div class='medal-box'><div class='medal-icon'>🧨</div><div class='medal-title'>DANUDO</div><div class='medal-player'>{agg['DPM'].idxmax()}</div><span class='medal-desc'>Maior Dano Médio</span></div>", unsafe_allow_html=True)
            with m3: st.markdown(f"<div class='medal-box'><div class='medal-icon'>🔪</div><div class='medal-title'>DINIZ</div><div class='medal-player'>{agg['Score'].idxmax()}</div><span class='medal-desc'>Maior Soma de Pontos</span></div>", unsafe_allow_html=True)
            with m4: st.markdown(f"<div class='medal-box'><div class='medal-icon'>💀</div><div class='medal-title'>INIMIGO KDA</div><div class='medal-player'>{agg['D'].idxmax()}</div><span class='medal-desc'>Quem mais morreu</span></div>", unsafe_allow_html=True)

    with t3:
        if not df_f.empty:
            st.subheader("📊 Raio-X da Pontuação (Médias por Partida)")
            df_audit = df_f.copy()
            # Mostra o valor calculado pelos pesos
            df_audit['Pts_KP (+40)'] = df_audit['Part'] * 40
            df_audit['Pts_DPM (/100)'] = df_audit['DPM'] / 100
            df_audit['Pts_Torre (/500)'] = df_audit['Dano_Estruturas'] / 500
            df_audit['Pts_Visao (x1)'] = df_audit['Pinks']
            df_audit['Penal_Medo (-25)'] = np.where((df_audit['D'] <= 2) & (df_audit['Part'] < 0.35), -25, 0)
            
            audit = df_audit.groupby('Jogador').agg({
                'Score': 'mean', 'Pts_KP (+40)': 'mean', 'Pts_DPM (/100)': 'mean', 
                'Pts_Torre (/500)': 'mean', 'Pts_Visao (x1)': 'mean', 'Penal_Medo (-25)': 'mean'
            }).round(2).sort_values('Score', ascending=False)
            st.dataframe(audit, use_container_width=True)

    with t4:
        if not df_f.empty:
            elo = df_f[df_f['RankRiot'] != 'Unranked'].sort_values('Timestamp').groupby('Jogador').tail(1)[['Jogador', 'RankRiot']].set_index('Jogador')
            elo_all = df_f.sort_values('Timestamp').groupby('Jogador').tail(1)[['Jogador', 'RankRiot']].set_index('Jogador')
            elo_all.update(elo)
            
            media = df_f.groupby('Jogador')['Score'].mean()
            comp = pd.DataFrame({'Riot Flex (Real)': elo_all['RankRiot'], 'Score Médio': media})
            comp['Rank Deidara (Nosso)'] = comp['Score Médio'].apply(get_rank_bravura)
            st.dataframe(comp.sort_values('Score Médio', ascending=False), use_container_width=True)

    with t5:
        if not df_f.empty:
            match_counts = df_f.groupby('MatchID')['Jogador'].count()
            squad_matches = match_counts[match_counts >= 3].index.tolist()
            df_sq = df_f[df_f['MatchID'].isin(squad_matches)]
            
            if not df_sq.empty:
                # Filtro de equilíbrio: Mínimo 5 jogos para não distorcer a %
                counts = df_sq['Jogador'].value_counts()
                validos = counts[counts >= 5].index.tolist()
                df_bal = df_sq[df_sq['Jogador'].isin(validos)]
                
                if not df_bal.empty:
                    wr = df_bal.groupby('Jogador')['Vitoria'].mean()
                    # Taxa de Derrota = 1 - Winrate
                    lr = ((1 - wr) * 100).reset_index(name='Taxa de Derrota (%)').sort_values('Taxa de Derrota (%)', ascending=False)
                    st.plotly_chart(px.bar(lr, x='Jogador', y='Taxa de Derrota (%)', color='Taxa de Derrota (%)', template='plotly_dark', color_continuous_scale='Reds'), use_container_width=True)
                    st.caption("Gráfico mostra a % de jogos perdidos quando em grupo (mín. 5 partidas).")
                else: st.info("Calibrando... Nenhum jogador atingiu 5 partidas em grupo ainda.")
            else: st.info("Nenhuma partida com 3+ membros do grupo foi registrada.")

    with t6:
        if not df_f.empty:
            last_ts = df_f['Timestamp'].max()
            last = df_f[df_f['Timestamp'] == last_ts].sort_values('Score')
            if not last.empty:
                sai = last.iloc[0]
                st.error(f"QUEM SAI: {sai['Jogador']} (Score: {sai['Score']:.1f})")
                st.dataframe(last[['Jogador', 'Score', 'K', 'D', 'A', 'DPM']].style.highlight_min(subset=['Score'], color='red'), use_container_width=True)

    with t7:
        if not df.empty:
            df_c = df[df['Tipo'] == 'Custom']
            if not df_c.empty:
                st.dataframe(df_c.groupby('Jogador')['Score'].mean().sort_values(ascending=False), use_container_width=True)

    st.markdown("<hr><div class='footer-group'>É o grupo</div><div class='footer-final'>deidara HO</div>", unsafe_allow_html=True)

if __name__ == "__main__":
    render()
