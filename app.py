import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import google.generativeai as genai
import requests
import os
import json
import time
from datetime import datetime
from PIL import Image
from pydantic import BaseModel
from typing import Optional, List

# ==============================================================================
# 0. CONFIGURAÇÕES GLOBAIS & TEMAS
# ==============================================================================
st.set_page_config(page_title="LeagueStats: Bravura Edition", layout="wide", page_icon="🛡️")

# Tema CSS (Dark & Clean)
st.markdown("""
<style>
    /* Fundo e Fontes */
    .stApp { background-color: #0e1117; }
    h1, h2, h3 { font-family: 'Roboto', sans-serif; color: #ffffff; }
    
    /* Cards de Métricas */
    div[data-testid="metric-container"] {
        background-color: #1a1c24;
        border-left: 5px solid #d4af37; /* Dourado */
        padding: 15px;
        border-radius: 8px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.3);
    }
    
    /* Tabelas */
    .dataframe { font-size: 14px; }
    
    /* Botões */
    .stButton>button {
        background-color: #2b313e;
        color: white;
        border: 1px solid #4a4e69;
        border-radius: 5px;
    }
    .stButton>button:hover {
        border-color: #d4af37;
        color: #d4af37;
    }
    
    /* Botão de Perigo */
    div[data-testid="stExpander"] { border: 1px solid #ff4b4b; }
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# 1. DOMAIN LAYER (Regras de Negócio - Sociologia)
# ==============================================================================
class MatchStats(BaseModel):
    """Modelo de dados validado (Pydantic) para garantir consistência."""
    MatchID: str
    Data: str
    Timestamp: float
    Jogador: str
    Tipo: str # 'Flex' ou 'Custom'
    Vitoria: bool
    Score: float
    K: int
    D: int
    A: int
    Part: float
    Dano_Estruturas: int
    DPM: float
    Pinks: int

class BravuraEngine:
    """Motor de cálculo do Score. A 'Constituição' do grupo."""
    
    @staticmethod
    def calculate_score(vitoria: bool, d: int, part: float, dano_est: int, dano_camp: int, minutos: int, pinks: int) -> float:
        # 1. Base (Vitória vale 25, Derrota 0 - Acúmulo Positivo)
        score = 25.0 if vitoria else 0.0
        
        # 2. Pressão de Combate (40% de peso na participação)
        score += (part * 40)
        
        # 3. Volume de Jogo (DPM / 100)
        dpm = dano_camp / minutos if minutos > 0 else 0
        score += (dpm / 100)
        
        # 4. Pressão de Mapa (Dano Estruturas / 500)
        score += (dano_est / 500)
        
        # 5. Visão Ofensiva
        score += (pinks * 2)
        
        # 6. PENALIDADE SOCIAL (Filtro Anti-KDA Player)
        # Morreu pouco (<=2) e não ajudou (<35%) = Punição Severa
        if d <= 2 and part < 0.35:
            score -= 25.0
            
        return round(score, 2)

# ==============================================================================
# 2. INFRASTRUCTURE LAYER (Adapters & Services)
# ==============================================================================
class DatabaseAdapter:
    """Gerencia persistência (CSV) simulando um Banco de Dados."""
    FILE_DB = 'leaguestats_bravura.csv'

    def __init__(self):
        if not os.path.exists(self.FILE_DB):
            self._create_db()

    def _create_db(self):
        df = pd.DataFrame(columns=MatchStats.model_fields.keys())
        df.to_csv(self.FILE_DB, index=False)

    def get_all(self) -> pd.DataFrame:
        if not os.path.exists(self.FILE_DB):
            self._create_db()
        return pd.read_csv(self.FILE_DB)
