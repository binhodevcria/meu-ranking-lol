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
# 0. CONFIGURAÇÕES & SQUAD
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
    {"nick": "MEC Viper", "tag": "MEC"},
    {"nick": "Sugiro Correr", "tag": "BR1"}
]

# Mapa de Agrupamento
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
    div[data-testid="metric-container"] { background-color: #1a1c24; border-left: 4px solid #c8aa6e; padding: 15px; border-radius: 6px; box-shadow: 0 4px 10px rgba(0,0,0,0.5); }
    .medal-box { background: linear-gradient(145deg, #1e2328, #1a1c24); border: 1px solid #c8aa6e; padding: 15px; border-radius: 10px; text-align: center; height: 100%; display: flex; flex-direction: column; justify-content: center; align-items: center; }
    .medal-icon { font-size: 3em; margin-bottom: 5px; }
    .medal-title { color: #d4af37; font-weight: bold; font-size: 1.1em; text-transform: uppercase; margin: 0; }
    .medal-player { color: #ff4b4b; font-weight: bold; font-size: 1.6em; margin: 5px 0; }
    .medal-desc { color: #a0a0a0; font-style: italic; font-size: 0.85em; }
    .title-text { font-size: 3.5em; font-weight: bold; color: #ff4b4b; text-align: center; text-shadow: 2px 2px #000; }
    .subtitle-text { font-size: 1.2em; font-style: italic; color: #a0a0a0; text-align: center; margin-bottom: 30px; }
    .stButton>button { background-color: #1e2328; color: #cdbe91; border: 1px solid #463714; font-weight: bold; width: 100%; }
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# 2. CORE LOGIC
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
            # Normaliza nomes
            df['Jogador'] = df['Jogador'].apply(lambda x: NOME_DISPLAY.get(str(x).upper(), str(x).upper()))
            # Converte números
            num_cols = ['Score', 'K', 'D', 'A', 'Part', 'DPM', 'Dano_Estruturas', 'Pinks', 'Timestamp']
            for c in num_cols: df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
            return df
        except: return pd.DataFrame()

    def get_existing_ids(self):
        # Retorna set de IDs que já temos
        df = pd.read_csv(self.FILE_DB, dtype={'MatchID': str})
        if df.empty: return set()
        return set(df['MatchID'].tolist())

    def save(self, stats: MatchStats):
        try:
            df = pd.read_csv(self.FILE_DB, dtype={'MatchID': str})
            stats_id = str(stats.MatchID)
            stats_player = str(stats.Jogador).upper()
            df['MatchID'] = df['MatchID'].astype(str)
            
            # Verifica se já existe esse match para esse player (evita duplicação)
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
# 4. API RIOT (SYNC TOTAL 2026)
# ==============================================================================
class RiotAdapter:
    def __init__(self, api_key):
        self.headers = {"X-Riot-Token": api_key}
        self.season_start = 1735689600 # 01/01/2026

    def request_blindado(self, url):
        for i in range(3):
            try:
                resp = requests.get(url, headers=self.headers)
                if resp.status_code == 200: return resp.json()
                elif resp.status_code == 404: return None 
                elif resp.status_code == 429:
                    time.sleep(int(resp.headers.get("Retry-After", 5)) + 1)
                    continue
            except: return None
        return None

    def fetch_rank(self, puuid):
        # Tenta pegar o Elo (BR1)
        try:
            summ = self.request_blindado(f"https://br1.api.riotgames.com/lol/summoner/v4/summoners/by-puuid/{puuid}")
            if not summ: return "Unranked"
            
            leagues = self.request_blindado(f"https://br1.api.riotgames.com/lol/league/v4/entries/by-summoner/{summ['id']}")
            if leagues:
                flex = next((l for l in leagues if l['queueType'] == "RANKED_FLEX_SR"), None)
                if flex: return f"{flex['tier']} {flex['rank']}"
            return "Unranked"
        except: return "Unranked"

    def sync_player_full_season(self, nome, tag, existing_ids_set):
        """
        Baixa TODAS as Flex de 2026, compara com o banco e baixa só o delta.
        """
        try:
            # 1. Pega PUUID
            n_enc, t_enc = quote(nome.strip()), quote(tag.replace('#','').strip())
            acc = self.request_blindado(f"https://americas.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{n_enc}/{t_enc}")
            if not acc: return [], 0, "Conta não encontrada"
            puuid = acc['puuid']
            
            # 2. Pega Rank Atual
            rank_atual = self.fetch_rank(puuid)

            # 3. Pega Lista de TODAS as Flex de 2026 (Paginação se necessário, mas 100 deve cobrir Jan)
            # queue=440 (Flex)
            url_ids = f"https://americas.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids?queue=440&startTime={self.season_start}&start=0&count=100"
            server_ids = self.request_blindado(url_ids)
            
            if not server_ids: return [], 0, "Sem Flex em 2026"

            # 4. Calcula o Delta (O que eu não tenho?)
            missing_ids = [mid for mid in server_ids if str(mid) not in existing_ids_set]
            
            if not missing_ids: return [], 0, "Já atualizado"

            # 5. Baixa Detalhes dos Faltantes
            new_data = []
            for mid in missing_ids:
                d = self.request_blindado(f"https://americas.api.riotgames.com/lol/match/v5/matches/{mid}")
                if d:
                    # Verifica de novo se é Flex (segurança)
                    if d['info']['queueId'] == 440:
                        p = next((x for x in d['info']['participants'] if x['puuid'] == puuid), None)
                        if p:
                            mins = d['info']['gameDuration']/60
                            sc = BravuraEngine.calculate_score(p['win'], p['deaths'], p['challenges'].get('killParticipation', 0), p['damageDealtToBuildings'], p['totalDamageDealtToChampions'], mins, p['visionWardsBoughtInGame'])
                            
                            new_data.append(MatchStats(
                                MatchID=str(mid), 
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
            
            return new_data, len(new_data), "OK"

        except Exception as e: return [], 0, str(e)

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
            if st.button("🔄 Sincronizar Tudo (2026)"):
                log = st.status("Verificando histórico completo...", expanded=True)
                total_added = 0
                
                # Carrega o cache de IDs existentes para não baixar repetido
                existing_ids = db.get_existing_ids()

                for p in SQUAD_LIST:
                    log.write(f"🔎 **{p['nick']}**: Analisando...")
                    
                    new_matches, count, msg = riot.sync_player_full_season(p['nick'], p['tag'], existing_ids)
                    
                    if count > 0:
                        saved = 0
                        for m in new_matches:
                            if db.save(m): 
                                saved += 1
                                existing_ids.add(m.MatchID) # Atualiza cache local
                        total_added += saved
                        log.write(f"✅ {p['nick']}: +{saved} jogos novos!")
                    elif msg == "Já atualizado":
                        log.write(f"💤 {p['nick']}: Tudo em dia.")
                    else:
                        log.error(f"❌ {p['nick']}: {msg}")
                    
                    time.sleep(0.2)
                
                log.update(label="Fim!", state="complete", expanded=False)
                if total_added > 0:
                    st.success(f"+{total_added} novas partidas no histórico!")
                    time.sleep(2)
                    st.rerun()
                else: st.info("Nenhuma partida nova encontrada.")

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

    # --- LÓGICA DE BALANCEAMENTO NATURAL (Achatar a Curva) ---
    df_ranking = df_f.copy()
    if not df_f.empty:
        # 1. Conta quantos jogos cada um tem
        counts = df_f['Jogador'].value_counts()
        if not counts.empty:
            median_games = counts.median() # Ex: 30 jogos
            limit_threshold = median_games * 3 # Ex: 90 jogos (Discrepância Absurda)
            
            # Se alguém passar do triplo da mediana, cortamos
            players_to_cap = counts[counts > limit_threshold].index.tolist()
            
            if players_to_cap:
                frames = []
                for p in df_f['Jogador'].unique():
                    p_data = df_f[df_f['Jogador'] == p].sort_values('Timestamp', ascending=False)
                    if p in players_to_cap:
                        # Pega só os ultimos N jogos (limit_threshold)
                        frames.append(p_data.head(int(limit_threshold)))
                    else:
                        # Pega tudo
                        frames.append(p_data)
                df_ranking = pd.concat(frames)

    t1, t2, t3, t4, t5, t6, t7 = st.tabs(["🏆 RANKING", "🎖️ MEDALHAS", "📊 TRANSPARÊNCIA", "⚖️ ELOS", "⚓ AFUNDAMENTO", "🚪 QUEM SAI?", "👹 CUSTOMS"])

    with t1:
        if not df_ranking.empty:
            k1, k2, k3, k4 = st.columns(4)
            mvp_name = df_ranking.groupby('Jogador')['Score'].mean().idxmax()
            mvp_val = df_ranking.groupby('Jogador')['Score'].mean().max()
            
            k1.metric("🔥 MVP (Média)", mvp_name, f"{mvp_val:.1f}")
            k2.metric("💀 Dano (Médio)", f"{df_ranking.groupby('Jogador')['DPM'].mean().max():.0f}")
            k3.metric("🎮 Histórico Total", f"{len(df_f)} Jogos")
            k4.metric("📈 Média Global", f"{df_f['Score'].mean():.1f}")
            
            st.markdown("---")
            c1, c2 = st.columns([1.5, 2])
            with c1:
                stats = []
                for p in todos:
                    d = df_ranking[df_ranking['Jogador'] == p]
                    media = d['Score'].mean() if not d.empty else 0
                    stats.append({'Jogador': p, 'Média': media, 'Jogos': len(d)})
                
                lb = pd.DataFrame(stats).sort_values('Média', ascending=False)
                lb['Rank'] = lb['Média'].apply(get_rank_bravura)
                st.dataframe(lb[['Jogador', 'Rank', 'Média', 'Jogos']].style.background_gradient(cmap='YlOrRd', subset=['Média']), use_container_width=True)
            
            with c2:
                # O Gráfico mostra a evolução TOTAL (Histórico Completo)
                df_hist = df_f.sort_values('Timestamp')
                df_hist['Acumulado'] = df_hist.groupby('Jogador')['Score'].cumsum()
                fig = px.area(df_hist, x='Data', y='Acumulado', color='Jogador', template='plotly_dark', title="Evolução Total")
                st.plotly_chart(fig, use_container_width=True)
        else: st.info("Sem dados. Clique em Sincronizar.")

    with t2:
        if not df_f.empty: # Medalhas consideram histórico total
            m1, m2, m3, m4 = st.columns(4)
            agg = df_f.groupby('Jogador').agg({'DPM': 'mean', 'Score': 'sum', 'D': 'sum', 'Part': 'mean', 'Vitoria': 'sum'})
            if not agg.empty:
                try:
                    with m1: st.markdown(f"<div class='medal-box'><div class='medal-icon'>🐢</div><div class='medal-title'>ARIEL</div><div class='medal-player'>{agg.sort_values(['Part', 'Vitoria']).index[0]}</div><span class='medal-desc'>Mais Safe (Menor KP)</span></div>", unsafe_allow_html=True)
                    with m2: st.markdown(f"<div class='medal-box'><div class='medal-icon'>🧨</div><div class='medal-title'>DANUDO</div><div class='medal-player'>{agg['DPM'].idxmax()}</div><span class='medal-desc'>Maior Dano Médio</span></div>", unsafe_allow_html=True)
                    with m3: st.markdown(f"<div class='medal-box'><div class='medal-icon'>🔪</div><div class='medal-title'>DINIZ</div><div class='medal-player'>{agg['Score'].idxmax()}</div><span class='medal-desc'>Maior Soma de Pontos</span></div>", unsafe_allow_html=True)
                    with m4: st.markdown(f"<div class='medal-box'><div class='medal-icon'>💀</div><div class='medal-title'>INIMIGO KDA</div><div class='medal-player'>{agg['D'].idxmax()}</div><span class='medal-desc'>Quem mais morreu</span></div>", unsafe_allow_html=True)
                except: pass

    with t3:
        if not df_ranking.empty:
            st.subheader(f"📊 Auditoria (Com Balanceamento)")
            df_a = df_ranking.copy()
            df_a['Pts_KP (+40)'] = df_a['Part'] * 40
            df_a['Pts_DPM (/100)'] = df_a['DPM'] / 100
            df_a['Pts_Torre (/500)'] = df_a['Dano_Estruturas'] / 500
            df_a['Pts_Visao (x1)'] = df_a['Pinks']
            df_a['Penal_Medo (-25)'] = np.where((df_a['D'] <= 2) & (df_a['Part'] < 0.35), -25, 0)
            
            audit = df_a.groupby('Jogador').agg({
                'Score': 'mean', 'Pts_KP (+40)': 'mean', 'Pts_DPM (/100)': 'mean', 
                'Pts_Torre (/500)': 'mean', 'Pts_Visao (x1)': 'mean', 'Penal_Medo (-25)': 'mean'
            }).round(2).sort_values('Score', ascending=False)
            st.dataframe(audit, use_container_width=True)

    with t4:
        if not df_f.empty:
            # Pega o rank mais recente não-Unranked
            elo = df_f[df_f['RankRiot'] != 'Unranked'].sort_values('Timestamp').groupby('Jogador').tail(1)[['Jogador', 'RankRiot']].set_index('Jogador')
            elo_all = df_f.sort_values('Timestamp').groupby('Jogador').tail(1)[['Jogador', 'RankRiot']].set_index('Jogador')
            elo_all.update(elo)
            
            media = df_ranking.groupby('Jogador')['Score'].mean() 
            comp = pd.DataFrame({'Riot Flex': elo_all['RankRiot'], 'Score Médio': media})
            comp['Rank Deidara'] = comp['Score Médio'].apply(get_rank_bravura)
            st.dataframe(comp.sort_values('Score Médio', ascending=False), use_container_width=True)

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
