import streamlit as st
import pandas as pd
import plotly.express as px
import os

# --- CONFIGURAÇÕES DE DADOS ---
FILE_DB = 'ranking_lol_dados.csv'

def init_db():
    if not os.path.exists(FILE_DB):
        df = pd.DataFrame(columns=['Data', 'Jogador', 'Score', 'K', 'D', 'A', 'Modo'])
        df.to_csv(FILE_DB, index=False)

# --- INTERFACE ---
st.set_page_config(page_title="LoL Rank Ofensivo", layout="wide")
init_db()

st.title("⚔️ Ranking de Agressividade: LoL Amigos")
st.markdown("---")

# --- SIDEBAR: REGISTRO DE PARTIDA ---
st.sidebar.header("📝 Registrar Partida")
with st.sidebar.form("match_form", clear_on_submit=True):
    nome = st.text_input("Nick do Jogador").upper()
    vitoria = st.checkbox("Vitória?")
    modo = st.selectbox("Modo", ["Flex", "Custom"])
    
    c1, c2, c3 = st.columns(3)
    k = c1.number_input("Kills", 0)
    d = c2.number_input("Deaths", 0)
    a = c3.number_input("Assists", 0)
    
    total_time = st.number_input("Total Kills do seu Time", 1)
    
    if st.form_submit_button("Salvar Partida"):
        if nome:
            # Cálculo de Score (Lógica de Agressividade)
            score_base = (30 if modo == "Flex" else 25) if vitoria else -10
            participacao = (k + a) / total_time
            score_final = score_base + (participacao * 25)
            
            # Barra de Medo: Penaliza KDA player passivo (0 ou 1 morte com <35% P)
            if d <= 1 and participacao < 0.35:
                score_final -= 15
            
            novo_dado = pd.DataFrame([[pd.Timestamp.now(), nome, round(score_final, 2), k, d, a, modo]], 
                                     columns=['Data', 'Jogador', 'Score', 'K', 'D', 'A', 'Modo'])
            novo_dado.to_csv(FILE_DB, mode='a', header=False, index=False)
            st.success(f"Score de {score_final:.1f} para {nome} salvo!")
            st.rerun()
        else:
            st.error("Por favor, insira o nome do jogador.")

# --- DASHBOARD PRINCIPAL ---
df = pd.read_csv(FILE_DB)

if not df.empty:
    df['Data'] = pd.to_datetime(df['Data'])
    
    # 1. MÉTRICAS DE TOPO
    st.subheader("📊 Líderes do Ranking")
    ranking_total = df.groupby('Jogador')['Score'].sum().sort_values(ascending=False).reset_index()
    
    cols = st.columns(min(len(ranking_total), 4))
    for i, row in ranking_total.head(4).iterrows():
        with cols[i]:
            st.metric(f"{i+1}º Lugar", row['Jogador'], f"{row['Score']:.1f} pts")

    # 2. GRÁFICO DE EVOLUÇÃO ACUMULADA
    st.markdown("---")
    st.subheader("📈 Jornada de Desempenho")
    
    df_plot = df.sort_values(['Jogador', 'Data'])
    df_plot['Score Acumulado'] = df_plot.groupby('Jogador')['Score'].cumsum()
    
    fig = px.line(df_plot, x='Data', y='Score Acumulado', color='Jogador',
                  markers=True, template="plotly_dark", 
                  labels={"Score Acumulado": "Pontuação Total", "Data": "Data da Partida"})
    st.plotly_chart(fig, use_container_width=True)

    # 3. TABELA DETALHADA
    st.markdown("---")
    st.subheader("📜 Histórico e Médias")
    
    tab1, tab2 = st.tabs(["Ranking Consolidado", "Últimas Partidas"])
    
    with tab1:
        resumo = df.groupby('Jogador').agg({
            'Score': 'sum',
            'K': 'mean',
            'D': 'mean',
            'A': 'mean',
            'Modo': 'count'
        }).rename(columns={'Modo': 'Jogos'}).sort_values('Score', ascending=False)
        st.dataframe(resumo.style.background_gradient(cmap='Greens', subset=['Score']), use_container_width=True)
        
    with tab2:
        st.dataframe(df.sort_values('Data', ascending=False), use_container_width=True)

else:
    st.info("O ranking está vazio. Registre a primeira partida na barra lateral!")
