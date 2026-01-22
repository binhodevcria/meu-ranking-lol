import streamlit as st
import pandas as pd
import plotly.express as px
import google.generativeai as genai
import requests
from PIL import Image
import json
import os

# --- CONFIGURAÇÃO ---
FILE_DB = 'ranking_lol_final.csv'
def init_db():
    if not os.path.exists(FILE_DB):
        df = pd.DataFrame(columns=['Data', 'Jogador', 'Tipo', 'Vitoria', 'Score', 'K', 'D', 'A', 'Part', 'Torres', 'Dano'])
        df.to_csv(FILE_DB, index=False)

st.set_page_config(page_title="LoL Aggressive Rank", layout="wide")
init_db()

# Secrets
gemini_key = st.secrets.get("GEMINI_KEY")
riot_key = st.secrets.get("RIOT_KEY")

if gemini_key:
    genai.configure(api_key=gemini_key)
    model = genai.GenerativeModel('gemini-1.5-flash')

# --- FUNÇÃO RIOT (FLEX) ---
def buscar_riot_flex(nome, tag):
    try:
        # 1. Conta (PUUID)
        url_acc = f"https://americas.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{nome}/{tag}?api_key={riot_key}"
        res_acc = requests.get(url_acc)
        if res_acc.status_code != 200: return None, f"Erro Riot Account: {res_acc.status_code}"
        puuid = res_acc.json()['puuid']
        
        # 2. Última Flex (Queue 440)
        url_m = f"https://americas.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids?queue=440&count=1&api_key={riot_key}"
        res_m = requests.get(url_m)
        match_id = res_m.json()[0]
        
        # 3. Detalhes
        url_d = f"https://americas.api.riotgames.com/lol/match/v5/matches/{match_id}?api_key={riot_key}"
        d = requests.get(url_d).json()
        p = next(i for i in d['info']['participants'] if i['puuid'] == puuid)
        
        return {
            'vitoria': p['win'], 'k': p['kills'], 'd': p['deaths'], 'a': p['assists'],
            'participacao': p['challenges'].get('killParticipation', 0),
            'torres': p['turretKills'], 'dano': p['totalDamageDealtToChampions']
        }, None
    except Exception as e:
        return None, str(e)

# --- FÓRMULA DE SCORE ---
def calcular_score(v, k, d, a, part, torres, dano):
    score = 30 if v else -10
    score += (part * 30) + (torres * 5) + (dano / 2000)
    if d <= 1 and part < 0.30: score -= 20
    return round(score, 2)

# --- INTERFACE ---
st.title("⚔️ Ranking LoL: Scanner de Prints & API")

with st.sidebar:
    metodo = st.radio("Método de Entrada", ["IA Vision (Print)", "Riot API (Flex)"])
    
    if metodo == "IA Vision (Print)":
        u_file = st.file_uploader("Suba o print das estatísticas", type=['png', 'jpg'])
        if u_file:
            img = Image.open(u_file)
            if st.button("🔍 Escanear Print"):
                with st.spinner("IA analisando todos os jogadores..."):
                    prompt = "Analise este print de LoL e extraia os dados de TODOS os jogadores visíveis em um JSON: lista de objetos com {nome, vitoria(bool), k, d, a, participacao(float), torres, dano}. Retorne apenas JSON."
                    response = model.generate_content([prompt, img])
                    try:
                        dados_todos = json.loads(response.text.replace('```json', '').replace('```', '').strip())
                        st.session_state['dados_ocr'] = dados_todos
                    except: st.error("Erro ao processar JSON da IA.")
            
            if 'dados_ocr' in st.session_state:
                lista_nicks = [p['nome'] for p in st.session_state['dados_ocr']]
                nick_selecionado = st.selectbox("Quem é você no print?", lista_nicks)
                
                if st.button("Confirmar e Salvar"):
                    p = next(i for i in st.session_state['dados_ocr'] if i['nome'] == nick_selecionado)
                    sc = calcular_score(p['vitoria'], p['k'], p['d'], p['a'], p['participacao'], p['torres'], p['dano'])
                    
                    df = pd.read_csv(FILE_DB)
                    nova_linha = {'Data': pd.Timestamp.now(), 'Jogador': p['nome'].upper(), 'Tipo': 'Custom', 'Vitoria': p['vitoria'], 'Score': sc, 'K': p['k'], 'D': p['d'], 'A': p['a'], 'Part': p['participacao'], 'Torres': p['torres'], 'Dano': p['dano']}
                    pd.concat([df, pd.DataFrame([nova_linha])], ignore_index=True).to_csv(FILE_DB, index=False)
                    st.success(f"Salvo: {nick_selecionado} com {sc} pts!")
                    st.rerun()

    else:
        r_nome = st.text_input("Nick (Ex: Faker)")
        r_tag = st.text_input("Tag (Ex: BR1)")
        if st.button("Sincronizar Flex"):
            d, erro = buscar_riot_flex(r_nome, r_tag)
            if d:
                sc = calcular_score(d['vitoria'], d['k'], d['d'], d['a'], d['participacao'], d['torres'], d['dano'])
                df = pd.read_csv(FILE_DB)
                nova_linha = {'Data': pd.Timestamp.now(), 'Jogador': r_nome.upper(), 'Tipo': 'Flex', 'Vitoria': d['vitoria'], 'Score': sc, 'K': d['k'], 'D': d['d'], 'A': d['a'], 'Part': d['participacao'], 'Torres': d['torres'], 'Dano': d['dano']}
                pd.concat([df, pd.DataFrame([nova_linha])], ignore_index=True).to_csv(FILE_DB, index=False)
                st.success(f"Flex sincronizada! Score: {sc}")
                st.rerun()
            else: st.error(f"Erro: {erro}")

# --- DASHBOARD ---
df_view = pd.read_csv(FILE_DB)
if not df_view.empty:
    st.dataframe(df_view.sort_values('Score', ascending=False), use_container_width=True)
    fig = px.line(df_view, x=df_view.index, y=df_view.groupby('Jogador')['Score'].cumsum(), color='Jogador', title="Evolução do Grupo")
    st.plotly_chart(fig, use_container_width=True)
