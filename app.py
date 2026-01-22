import streamlit as st
import pandas as pd
import plotly.express as px
import google.generativeai as genai
import requests
import os
from PIL import Image
import json

# --- CONFIGURAÇÕES ---
API_KEY_RIOT = st.secrets.get("RIOT_KEY", "")
API_KEY_GEMINI = st.secrets.get("GEMINI_KEY", "")
FILE_DB = 'ranking_lol_ai.csv'

genai.configure(api_key=API_KEY_GEMINI)
model = genai.GenerativeModel('gemini-1.5-flash')

def init_db():
    if not os.path.exists(FILE_DB):
        df = pd.DataFrame(columns=['Data', 'Jogador', 'Tipo', 'Vitoria', 'Score', 'K', 'D', 'A', 'Part', 'Torres', 'Dano'])
        df.to_csv(FILE_DB, index=False)

# --- FÓRMULA DE AGRESSIVIDADE ---
def calcular_score(v, tipo, k, d, a, part, torres, dano):
    score = (35 if tipo == "Flex" else 25) if v else -10
    score += (part * 30) + (torres * 5) + (dano / 2000)
    if d <= 1 and part < 0.30: score -= 20
    return round(score, 2)

# --- INTELIGÊNCIA ARTIFICIAL (Leitura de Print) ---
def ler_print_com_ia(img_pil, nome_alvo):
    prompt = f"""
    Analise esta imagem de estatísticas de League of Legends. 
    Encontre as estatísticas para o jogador "{nome_alvo}".
    Extraia os seguintes dados em formato JSON:
    {{
        "vitoria": boolean,
        "k": int,
        "d": int,
        "a": int,
        "participacao_kills": float (entre 0 e 1),
        "torres_destruidas": int,
        "dano_total": int
    }}
    Se não encontrar o jogador, retorne erro. Responda APENAS o JSON bruto.
    """
    response = model.generate_content([prompt, img_pil])
    try:
        # Limpa a resposta para garantir que seja um JSON puro
        clean_json = response.text.replace('```json', '').replace('```', '').strip()
        return json.loads(clean_json)
    except:
        return None

# --- INTERFACE ---
st.set_page_config(page_title="LoL AI Rank", layout="wide")
init_db()

st.title("⚔️ Ranking Inteligente: API + IA Vision")

col_input, col_view = st.columns([1, 2])

with col_input:
    st.header("📥 Entrada de Dados")
    tab1, tab2 = st.tabs(["Riot API (Flex)", "IA Vision (Custom)"])
    
    with tab2:
        nome_busca = st.text_input("Seu Nick no Print").upper()
        u_file = st.file_uploader("Upload do Print da Partida", type=['png', 'jpg'])
        
        if u_file and nome_busca:
            img = Image.open(u_file)
            st.image(img, caption="Processando com Gemini AI...", width=300)
            
            if st.button("Analisar com IA"):
                dados = ler_print_com_ia(img, nome_busca)
                if dados:
                    st.success("IA leu os dados com sucesso!")
                    st.json(dados) # Mostrar para conferência
                    
                    sc = calcular_score(dados['vitoria'], "Custom", dados['k'], dados['d'], dados['a'], dados['participacao_kills'], dados['torres_destruidas'], dados['dano_total'])
                    
                    if st.button("Confirmar e Salvar no Ranking"):
                        df_new = pd.DataFrame([[pd.Timestamp.now(), nome_busca, "Custom", dados['vitoria'], sc, dados['k'], dados['d'], dados['a'], dados['participacao_kills'], dados['torres_destruidas'], dados['dano_total']]], columns=pd.read_csv(FILE_DB).columns)
                        df_new.to_csv(FILE_DB, mode='a', header=False, index=False)
                        st.rerun()
                else:
                    st.error("A IA não conseguiu ler os dados. Tente um print mais nítido.")

# --- DASHBOARD ---
df = pd.read_csv(FILE_DB)
if not df.empty:
    with col_view:
        st.subheader("🏆 Leaderboard")
        rank = df.groupby('Jogador').agg({'Score': 'sum', 'Dano': 'mean'}).sort_values('Score', ascending=False)
        st.dataframe(rank.style.background_gradient(cmap='Greens'), use_container_width=True)
        
        df['Acumulado'] = df.groupby('Jogador')['Score'].cumsum()
        fig = px.line(df, x=df.index, y='Acumulado', color='Jogador', title="Evolução da Ofensividade")
        st.plotly_chart(fig, use_container_width=True)
