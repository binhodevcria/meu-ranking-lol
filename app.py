import streamlit as st
import pandas as pd
import plotly.express as px
import os
import json
from PIL import Image

# Tenta importar bibliotecas externas com tratamento de erro
try:
    import google.generativeai as genai
    import requests
    BIBLIOTECAS_OK = True
except ImportError:
    BIBLIOTECAS_OK = False

# --- CONFIGURAÇÕES DE DADOS ---
FILE_DB = 'ranking_lol_final.csv'

def init_db():
    if not os.path.exists(FILE_DB):
        df = pd.DataFrame(columns=['Data', 'Jogador', 'Tipo', 'Vitoria', 'Score', 'K', 'D', 'A', 'Part', 'Torres', 'Dano'])
        df.to_csv(FILE_DB, index=False)

# --- FÓRMULA DE SCORE ---
def calcular_score(v, tipo, k, d, a, part, torres, dano):
    score = (35 if tipo == "Flex" else 25) if v else -10
    score += (part * 30) + (torres * 5) + (dano / 2000)
    if d <= 1 and part < 0.30: score -= 20
    return round(score, 2)

# --- INTERFACE ---
st.set_page_config(page_title="LoL AI Rank", layout="wide")
init_db()

st.title("⚔️ Ranking de Agressividade LoL")

# Verificação de Dependências
if not BIBLIOTECAS_OK:
    st.error("🚨 Erro de Dependências: Verifique se o seu 'requirements.txt' no GitHub contém 'google-generativeai' e 'requests'.")
    st.stop()

# Verificação de Chaves
API_KEY_GEMINI = st.secrets.get("GEMINI_KEY", "")
API_KEY_RIOT = st.secrets.get("RIOT_KEY", "")

if not API_KEY_GEMINI:
    st.warning("⚠️ GEMINI_KEY não encontrada nos Secrets.")

# --- SIDEBAR: ENTRADA DE DADOS ---
st.sidebar.header("📥 Cadastrar Partida")
metodo = st.sidebar.selectbox("Método", ["Riot API (Flex)", "IA Vision (Print Custom)"])

if metodo == "Riot API (Flex)":
    with st.sidebar.form("riot_form"):
        r_nome = st.text_input("Nick")
        r_tag = st.text_input("Tag")
        if st.form_submit_button("Buscar Flex"):
            # Lógica da API Riot aqui
            st.info("Buscando dados da Riot...")
            # (Mantendo a lógica de busca que enviamos antes)

else:
    u_file = st.sidebar.file_uploader("Upload do Print", type=['png', 'jpg'])
    nome_ai = st.sidebar.text_input("Seu Nick no Print")
    if u_file and nome_ai and st.sidebar.button("Analisar com IA"):
        # Configura Gemini
        genai.configure(api_key=API_KEY_GEMINI)
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        img = Image.open(u_file)
        prompt = f"Analise o print de LoL para o jogador {nome_ai}. Extraia JSON: vitoria(bool), k(int), d(int), a(int), participacao_kills(float 0-1), torres_destruidas(int), dano_total(int). Responda apenas o JSON."
        
        try:
            response = model.generate_content([prompt, img])
            dados = json.loads(response.text.replace('```json', '').replace('```', '').strip())
            
            sc = calcular_score(dados['vitoria'], "Custom", dados['k'], dados['d'], dados['a'], dados['participacao_kills'], dados['torres_destruidas'], dados['dano_total'])
            
            # Salvar
            new_row = [pd.Timestamp.now(), nome_ai.upper(), "Custom", dados['vitoria'], sc, dados['k'], dados['d'], dados['a'], dados['participacao_kills'], dados['torres_destruidas'], dados['dano_total']]
            pd.DataFrame([new_row], columns=pd.read_csv(FILE_DB).columns).to_csv(FILE_DB, mode='a', header=False, index=False)
            st.success("Dados salvos via IA!")
            st.rerun()
        except Exception as e:
            st.error(f"Erro na IA: {e}")

# --- DASHBOARD ---
df = pd.read_csv(FILE_DB)
if not df.empty:
    st.subheader("🏆 Leaderboard")
    rank = df.groupby('Jogador').agg({'Score': 'sum', 'Dano': 'mean'}).sort_values('Score', ascending=False)
    st.dataframe(rank.style.background_gradient(cmap='Greens'), use_container_width=True)
    
    df['Acumulado'] = df.groupby('Jogador')['Score'].cumsum()
    fig = px.line(df, x=df.index, y='Acumulado', color='Jogador', title="Evolução")
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("Aguardando dados...")
