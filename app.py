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
import base64
from datetime import datetime
from PIL import Image
from pydantic import BaseModel
from urllib.parse import quote
from typing import Optional
from itertools import combinations

# ==============================================================================
# 0. CONFIGURAÇÕES
# ==============================================================================
BATCH_SIZE = 20 
RANKING_WINDOW = 15 
SQUAD_FILE = 'squad.json'

# GitHub Config (para commit automático)
GITHUB_REPO = "binhodevcria/meu-ranking-lol"
GITHUB_BRANCH = "main"

def load_squad():
    """Carrega a lista de jogadores do arquivo JSON externo"""
    try:
        if os.path.exists(SQUAD_FILE):
            with open(SQUAD_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except: pass
    # Fallback se o arquivo não existir
    return [
        {"nick": "Gabinho", "tag": "INTEN"},
        {"nick": "Naguinha", "tag": "INTEN"},
        {"nick": "Guiza", "tag": "INTEN"}
    ]

def github_commit_squad(squad_data, github_token, repo=GITHUB_REPO, branch=GITHUB_BRANCH):
    """
    Faz commit do squad.json diretamente no GitHub via API
    Retorna (sucesso: bool, mensagem: str)
    """
    try:
        headers = {
            "Authorization": f"Bearer {github_token}",
            "Accept": "application/vnd.github.v3+json"
        }
        
        # 1. Pegar SHA atual do arquivo (necessário para update)
        url_get = f"https://api.github.com/repos/{repo}/contents/{SQUAD_FILE}?ref={branch}"
        resp_get = requests.get(url_get, headers=headers)
        
        if resp_get.status_code == 404:
            # Arquivo não existe, será criado
            current_sha = None
        elif resp_get.status_code == 200:
            current_sha = resp_get.json().get('sha')
        else:
            return False, f"Erro ao acessar repo: {resp_get.status_code}"
        
        # 2. Preparar conteúdo em base64
        content_json = json.dumps(squad_data, indent=4, ensure_ascii=False)
        content_b64 = base64.b64encode(content_json.encode('utf-8')).decode('utf-8')
        
        # 3. Fazer commit
        url_put = f"https://api.github.com/repos/{repo}/contents/{SQUAD_FILE}"
        payload = {
            "message": f"🎮 Squad atualizado via OFENSIVO SCORE",
            "content": content_b64,
            "branch": branch
        }
        if current_sha:
            payload["sha"] = current_sha
        
        resp_put = requests.put(url_put, headers=headers, json=payload)
        
        if resp_put.status_code in [200, 201]:
            return True, "✅ Commit realizado com sucesso!"
        else:
            error_msg = resp_put.json().get('message', 'Erro desconhecido')
            return False, f"Erro no commit: {error_msg}"
            
    except Exception as e:
        return False, f"Erro: {str(e)}"

SQUAD_LIST = load_squad()

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
    Champion: Optional[str] = "Unknown"
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
                # Migração: Adiciona colunas faltantes com valores padrão
                changed = False
                for col in expected_cols:
                    if col not in df.columns:
                        if col in ['MatchID', 'Data', 'Jogador', 'Tipo', 'RankRiot', 'Champion']:
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
        self.season_start = 1767225600000 # 01/01/2026 00:00:00 UTC

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
                            Champion=p.get('championName', 'Unknown'),
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
        with st.expander("🛠️ Admin - Gerenciar Squad"):
            st.markdown("### 👥 Squad Atual")
            
            # Inicializa session_state para edição do squad
            if 'temp_squad' not in st.session_state:
                st.session_state.temp_squad = SQUAD_LIST.copy()
            
            # Mostrar jogadores atuais com botão de remover
            for i, player in enumerate(st.session_state.temp_squad):
                col1, col2, col3 = st.columns([3, 2, 1])
                with col1:
                    st.text(player['nick'])
                with col2:
                    st.text(f"#{player['tag']}")
                with col3:
                    if st.button("❌", key=f"remove_{i}"):
                        st.session_state.temp_squad.pop(i)
                        st.rerun()
            
            st.markdown("---")
            st.markdown("### ➕ Adicionar Jogador")
            
            col_nick, col_tag = st.columns([3, 2])
            with col_nick:
                new_nick = st.text_input("Nick do jogador:", key="new_nick", placeholder="Ex: NovoJogador")
            with col_tag:
                new_tag = st.text_input("Tag:", key="new_tag", placeholder="Ex: BR1")
            
            if st.button("➕ Adicionar ao Squad"):
                if new_nick and new_tag:
                    st.session_state.temp_squad.append({"nick": new_nick.strip(), "tag": new_tag.strip()})
                    st.success(f"✅ {new_nick}#{new_tag} adicionado!")
                    st.rerun()
                else:
                    st.warning("Preencha nick e tag!")
            
            # Verificar se houve alterações
            if st.session_state.temp_squad != SQUAD_LIST:
                st.markdown("---")
                st.success("✅ **Alterações detectadas!**")
                
                # Gerar JSON formatado
                json_output = json.dumps(st.session_state.temp_squad, indent=4, ensure_ascii=False)
                
                with st.expander("📋 Ver JSON gerado"):
                    st.code(json_output, language="json")
                
                st.markdown("---")
                st.markdown("### 🚀 Salvar no GitHub")
                
                # Input para GitHub Token
                github_token = st.text_input(
                    "GitHub Personal Access Token:", 
                    type="password",
                    help="Crie um token em GitHub → Settings → Developer settings → Personal access tokens",
                    key="github_token"
                )
                
                # Input para o repositório (pré-preenchido mas editável)
                github_repo = st.text_input(
                    "Repositório (usuario/repo):",
                    value=GITHUB_REPO,
                    help="Ex: gabri/LoL_Rank",
                    key="github_repo"
                )
                
                col_commit, col_undo = st.columns(2)
                
                with col_commit:
                    if st.button("📤 Fazer Commit no GitHub", type="primary"):
                        if github_token and github_repo:
                            with st.spinner("Fazendo commit..."):
                                success, msg = github_commit_squad(
                                    st.session_state.temp_squad, 
                                    github_token, 
                                    repo=github_repo
                                )
                            if success:
                                st.success(msg)
                                st.balloons()
                                st.info("🔄 O app será atualizado automaticamente em alguns segundos!")
                            else:
                                st.error(msg)
                        else:
                            st.warning("Preencha o token e o repositório!")
                
                with col_undo:
                    if st.button("🔄 Desfazer alterações"):
                        st.session_state.temp_squad = SQUAD_LIST.copy()
                        st.rerun()
            
            st.markdown("---")
            st.markdown("### 🗑️ Resetar Dados")
            if st.button("⚠️ Resetar Tudo (Limpar Partidas)"):
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

    t1, t2, t3, t4, t5, t6, t7, t8, t9, t10 = st.tabs([
        "🏆 RANKING", "🎖️ MEDALHAS", "📊 TRANSPARÊNCIA", "⚖️ ELOS", 
        "⚓ AFUNDAMENTO", "🚪 QUEM SAI?", "👹 CUSTOMS",
        "📈 RECORDES", "🎮 CAMPEÕES", "👥 DUOS"
    ])

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

    # ==================== NOVA ABA: RECORDES ====================
    with t8:
        st.subheader("📈 Recordes Pessoais")
        if not df_f.empty:
            st.markdown("*Os maiores feitos de cada jogador na temporada*")
            
            # Recordes por categoria
            records_data = []
            for jogador in df_f['Jogador'].unique():
                jdf = df_f[df_f['Jogador'] == jogador]
                if jdf.empty: continue
                
                # Pega a partida com maior score, maior DPM, etc.
                max_score_row = jdf.loc[jdf['Score'].idxmax()]
                max_dpm_row = jdf.loc[jdf['DPM'].idxmax()]
                max_kills_row = jdf.loc[jdf['K'].idxmax()]
                max_x1_row = jdf.loc[jdf['SoloKills'].idxmax()]
                
                records_data.append({
                    'Jogador': jogador,
                    '🏆 Maior Score': f"{max_score_row['Score']:.1f}",
                    '💥 Maior DPM': f"{max_dpm_row['DPM']:.0f}",
                    '⚔️ Mais Kills': int(max_kills_row['K']),
                    '🎪 Mais X1': int(max_x1_row['SoloKills']),
                    'Jogos': len(jdf)
                })
            
            if records_data:
                df_records = pd.DataFrame(records_data)
                st.dataframe(df_records.set_index('Jogador'), use_container_width=True)
                
                # Top 3 recordes visuais
                st.markdown("---")
                st.markdown("### 🥇 Hall da Fama")
                
                col1, col2, col3 = st.columns(3)
                
                # Maior Score de todos
                best_score = df_f.loc[df_f['Score'].idxmax()]
                with col1:
                    st.markdown(f"""
                    <div class='medal-box'>
                        <div class='medal-icon'>🔥</div>
                        <div class='medal-title'>MAIOR SCORE</div>
                        <div class='medal-player'>{best_score['Jogador']}</div>
                        <span class='medal-desc'>{best_score['Score']:.1f} pts em {best_score['Data']}</span>
                    </div>
                    """, unsafe_allow_html=True)
                
                # Maior DPM de todos
                best_dpm = df_f.loc[df_f['DPM'].idxmax()]
                with col2:
                    st.markdown(f"""
                    <div class='medal-box'>
                        <div class='medal-icon'>💥</div>
                        <div class='medal-title'>MAIOR DANO</div>
                        <div class='medal-player'>{best_dpm['Jogador']}</div>
                        <span class='medal-desc'>{best_dpm['DPM']:.0f} DPM em {best_dpm['Data']}</span>
                    </div>
                    """, unsafe_allow_html=True)
                
                # Mais kills em uma partida
                best_kills = df_f.loc[df_f['K'].idxmax()]
                with col3:
                    st.markdown(f"""
                    <div class='medal-box'>
                        <div class='medal-icon'>⚔️</div>
                        <div class='medal-title'>MAIS ABATES</div>
                        <div class='medal-player'>{best_kills['Jogador']}</div>
                        <span class='medal-desc'>{int(best_kills['K'])} kills em {best_kills['Data']}</span>
                    </div>
                    """, unsafe_allow_html=True)
        else:
            st.info("Sem dados para recordes.")

    # ==================== NOVA ABA: CAMPEÕES ====================
    with t9:
        st.subheader("🎮 Estatísticas por Campeão")
        if not df_f.empty and 'Champion' in df_f.columns:
            # Filtro de jogador
            selected_player = st.selectbox("Selecione o jogador:", ["Todos"] + sorted(df_f['Jogador'].unique().tolist()))
            
            if selected_player != "Todos":
                df_champ = df_f[df_f['Jogador'] == selected_player]
            else:
                df_champ = df_f
            
            # Agregar por campeão
            champ_stats = df_champ.groupby('Champion').agg({
                'Vitoria': ['sum', 'count'],
                'K': 'mean',
                'D': 'mean', 
                'A': 'mean',
                'DPM': 'mean',
                'Score': 'mean'
            }).round(2)
            
            champ_stats.columns = ['Vitórias', 'Jogos', 'K (avg)', 'D (avg)', 'A (avg)', 'DPM (avg)', 'Score (avg)']
            champ_stats['Winrate'] = ((champ_stats['Vitórias'] / champ_stats['Jogos']) * 100).round(1).astype(str) + '%'
            champ_stats = champ_stats.sort_values('Jogos', ascending=False)
            
            # Filtrar campeões "Unknown" se houver muitos dados reais
            if 'Unknown' in champ_stats.index and len(champ_stats) > 1:
                unknown_count = champ_stats.loc['Unknown', 'Jogos'] if 'Unknown' in champ_stats.index else 0
                total_count = champ_stats['Jogos'].sum()
                if unknown_count < total_count * 0.5:  # Se menos de 50% é Unknown
                    st.warning("⚠️ Alguns dados antigos não têm campeão registrado (mostrados como 'Unknown'). Sincronize novamente para atualizar!")
            
            st.dataframe(champ_stats[['Jogos', 'Winrate', 'K (avg)', 'D (avg)', 'A (avg)', 'DPM (avg)', 'Score (avg)']], use_container_width=True)
            
            # Gráfico de pizza dos campeões mais jogados
            if len(champ_stats) > 1:
                top_champs = champ_stats.head(8).reset_index()
                fig = px.pie(top_champs, values='Jogos', names='Champion', 
                            title='Top 8 Campeões Mais Jogados',
                            template='plotly_dark',
                            color_discrete_sequence=px.colors.qualitative.Set3)
                st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Sem dados de campeões. Sincronize para coletar!")

    # ==================== NOVA ABA: DUOS ====================
    with t10:
        st.subheader("👥 Sinergia entre Jogadores")
        if not df_f.empty:
            st.markdown("*Análise de performance quando jogadores jogam juntos*")
            
            # Identificar partidas com múltiplos jogadores do squad
            match_players = df_f.groupby('MatchID')['Jogador'].apply(list).reset_index()
            match_results = df_f.groupby('MatchID')['Vitoria'].first().reset_index()
            
            # Calcular duos
            duo_stats = {}
            for _, row in match_players.iterrows():
                players = row['Jogador']
                if len(players) >= 2:
                    match_id = row['MatchID']
                    won = match_results[match_results['MatchID'] == match_id]['Vitoria'].values[0]
                    
                    # Para cada par de jogadores na partida
                    for duo in combinations(sorted(players), 2):
                        duo_key = f"{duo[0]} & {duo[1]}"
                        if duo_key not in duo_stats:
                            duo_stats[duo_key] = {'wins': 0, 'games': 0}
                        duo_stats[duo_key]['games'] += 1
                        if won:
                            duo_stats[duo_key]['wins'] += 1
            
            if duo_stats:
                # Converter para DataFrame
                duo_data = []
                for duo, stats in duo_stats.items():
                    if stats['games'] >= 3:  # Mínimo 3 jogos juntos
                        winrate = (stats['wins'] / stats['games']) * 100
                        duo_data.append({
                            'Dupla': duo,
                            'Jogos Juntos': stats['games'],
                            'Vitórias': stats['wins'],
                            'Winrate': f"{winrate:.1f}%",
                            'Winrate_num': winrate
                        })
                
                if duo_data:
                    df_duos = pd.DataFrame(duo_data).sort_values('Jogos Juntos', ascending=False)
                    
                    # Métricas principais
                    col1, col2, col3 = st.columns(3)
                    
                    best_duo = df_duos.loc[df_duos['Winrate_num'].idxmax()]
                    worst_duo = df_duos.loc[df_duos['Winrate_num'].idxmin()]
                    most_games_duo = df_duos.iloc[0]
                    
                    with col1:
                        st.metric("🏆 Melhor Duo", best_duo['Dupla'], f"{best_duo['Winrate']} WR")
                    with col2:
                        st.metric("🤝 Duo Mais Frequente", most_games_duo['Dupla'], f"{most_games_duo['Jogos Juntos']} jogos")
                    with col3:
                        st.metric("💀 Pior Duo", worst_duo['Dupla'], f"{worst_duo['Winrate']} WR")
                    
                    st.markdown("---")
                    
                    # Tabela completa
                    st.dataframe(df_duos[['Dupla', 'Jogos Juntos', 'Vitórias', 'Winrate']], use_container_width=True)
                    
                    # Gráfico de barras horizontal
                    fig = px.bar(df_duos.head(10), x='Winrate_num', y='Dupla', orientation='h',
                                color='Winrate_num', color_continuous_scale='RdYlGn',
                                title='Top 10 Duplas por Winrate',
                                template='plotly_dark',
                                labels={'Winrate_num': 'Winrate (%)'})
                    fig.update_layout(yaxis={'categoryorder': 'total ascending'})
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info("Precisa de mais jogos em dupla (mínimo 3 juntos).")
            else:
                st.info("Sem dados de partidas em grupo ainda.")
        else:
            st.info("Sem dados para análise de duos.")

    st.markdown("<hr><div class='footer-group'>É o grupo</div><div class='footer-final'>deidara HO</div>", unsafe_allow_html=True)

if __name__ == "__main__":
    render()
