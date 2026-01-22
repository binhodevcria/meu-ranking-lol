import streamlit as st
import pandas as pd
import plotly.express as px
import google.generativeai as genai
from PIL import Image
import json
import os

# --- CONFIGURAÇÃO INICIAL ---
FILE_DB = 'ranking_lol_oficial.csv'

def init_db():
    if not os.path.exists(FILE_DB):
        df = pd.DataFrame(columns=[
            'Data', 'Jogador', 'Tipo', 'Vitoria', 'Score', 
            'K', 'D', 'A', 'Part', 'Torres', 'Dano'
        ])
        df.to_csv(FILE_DB, index=False)

st.set_page_config(page_title="LoL Aggressive Rank", layout="wide")
init_db()

# --- CONEXÃO COM GOOGLE AI (GEMINI) ---
gemini_key = st.secrets.get("GEMINI_KEY")

if not gemini_key:
    st.error("❌ Configure 'GEMINI_KEY' nos Secrets do Streamlit.")
    st.stop()

try:
    genai.configure(api_key=gemini_key)
    # Tenta encontrar o modelo disponível para evitar erro 404
    modelos_disponiveis = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
    # Prioriza o flash, se não houver, pega o primeiro que funcione
    modelo_nome = 'models/gemini-1.5-flash' if 'models/gemini-1.5-flash' in modelos_disponiveis else modelos_disponiveis[0]
    model = genai.GenerativeModel(model_name=modelo_nome)
except Exception as e:
    st.error(f"Erro ao conectar com Google AI: {e}")
    st.stop()

# --- FÓRMULA DE AGRESSIVIDADE ---
def calcular_score(v, k, d, a, part, torres, dano):
    # Vitória/Derrota
    score = 25 if v else -10
    # Engajamento (Participação em kills: 0.0 a 1.0)
    score += (part * 30)
    # Objetivos e Impacto
    score += (torres * 5) + (dano / 2000)
    # Barra de Medo (Penalidade por passividade)
    if d <= 1 and part < 0.30:
        score -= 20
    return round(score, 2)

# --- INTERFACE ---
st.title("⚔️ Ranking de Agressividade LoL")

with st.sidebar:
    st.header("📥 Registrar Partida")
    nome_jogador = st.text_input("Seu Nick no Print (Exato)").upper()
    u_file = st.file_uploader("Upload do Print das Estatísticas", type=['png', 'jpg', 'jpeg'])

    if st.button("🚀 Analisar com IA") and u_file and nome_jogador:
        try:
            with st.spinner("IA lendo o print..."):
                img = Image.open(u_file)
                prompt = f"""
                Analise este print de fim de jogo de League of Legends para o jogador {nome_jogador}.
                Retorne APENAS um JSON bruto (sem markdown) com este formato:
                {{"vitoria": bool, "k": int, "d": int, "a": int, "participacao": float, "torres": int, "dano": int}}
                Se o valor for desconhecido, use 0. Participacao deve ser entre 0 e 1.
                """
                response = model.generate_content([prompt, img])
                
                # Limpa a resposta para garantir JSON puro
                texto_limpo = response.text.replace('```json', '').replace('```', '').strip()
                dados = json.loads(texto_limpo)
                
                # Cálculo
                sc = calcular_score(dados['vitoria'], dados['k'], dados['d'], dados['a'], dados['participacao'], dados['torres'], dados['dano'])
                
                # Salvar no CSV
                df = pd.read_csv(FILE_DB)
                nova_linha = {
                    'Data': pd.Timestamp.now(), 'Jogador': nome_jogador, 'Tipo': 'Custom',
                    'Vitoria': dados['vitoria'], 'Score': sc, 'K': dados['k'], 'D': dados['d'], 
                    'A': dados['a'], 'Part': dados['participacao'], 'Torres': dados['torres'], 'Dano': dados['dano']
                }
                df = pd.concat([df, pd.DataFrame([nova_linha])], ignore_index=True)
                df.to_csv(FILE_DB, index=False)
                st.success(f"✅ Partida salva! Score: {sc}")
                st.rerun()
        except Exception as e:
            st.error(f"Erro na análise: {e}")

# --- DASHBOARD ---
df_view = pd.read_csv(FILE_DB)

if not df_view.empty:
    col1, col2 = st.columns([1, 2])
    
    with col1:
        st.subheader("🏆 Leaderboard")
        rank = df_view.groupby('Jogador')['Score'].sum().sort_values(ascending=False).reset_index()
        st.dataframe(rank.style.background_gradient(cmap='Oranges', subset=['Score']), use_container_width=True)

    with col2:
        st.subheader("📈 Evolução Acumulada")
        df_view['Score_Acumulado'] = df_view.groupby('Jogador')['Score'].cumsum()
        fig = px.line(df_view, x=df_view.index, y='Score_Acumulado', color='Jogador', markers=True, template="plotly_dark")
        st.plotly_chart(fig, use_container_width=True)
        
    st.subheader("📜 Histórico Recente")
    st.dataframe(df_view.sort_values('Data', ascending=False), use_container_width=True)
else:
    st.info("Aguardando o primeiro print para gerar o ranking...")
