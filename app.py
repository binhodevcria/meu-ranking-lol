import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import google.generativeai as genai
import requests
import os
import json
import time
from datetime import datetime, timedelta
from PIL import Image
from pydantic import BaseModel
from typing import Optional, List
from urllib.parse import quote

# ==============================================================================
# 0. CONFIGURAÇÕES VISUAIS
# ==============================================================================
st.set_page_config(page_title="LeagueStats: Bravura", layout="wide", page_icon="🛡️")

st.markdown("""
<style>
    .stApp { background-color: #0e1117; }
    h1, h2, h3, h4 { font-family: 'Roboto', sans-serif; color: #ffffff; }
    div[data-testid="metric-container"] {
        background-color: #1a1c24; border-left: 4px solid #c8aa6e; padding: 15px; border-radius: 6px;
    }
    div[data-testid="stExpander"] { border: 1px solid #c8aa6e; }
    .log-success { color: #4ade80; font-family: monospace; font-size: 12px; }
    .log-warn { color: #facc15; font-family: monospace; font-size: 12px; }
    .log-error { color: #f87171; font-family: monospace; font-size: 12px; }
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# 1. LOGIC LAYER
# ==============================================================================
class MatchStats(BaseModel):
    MatchID: str
    Data: str
    Timestamp: float
    Jogador: str
    Tipo: str
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
    @staticmethod
    def calculate_score(vitoria, d, part, dano_est, dano_camp, minutos, pinks):
        score = 25.0 if vitoria else 0.0
        score += (part * 40)
        dpm = dano_camp / minutos if minutos > 0 else 0
        score += (dpm / 100)
        score += (dano_est / 500)
        score += (pinks * 2)
        if d <= 2 and part < 0.35: score -= 25.0
        return round(score, 2)

# ==============================================================================
# 2. DATA LAYER (AUTO-REPARO)
# ==============================================================================
class DatabaseAdapter:
    FILE_DB = 'leaguestats_bravura.csv'
    
    def __init__(self):
        # Garante que o arquivo existe
        if not os.path.exists(self.FILE_DB): 
            self._create_db()
    
    def _create_db(self):
        try:
            pd.DataFrame(columns=MatchStats.model_fields.keys()).to_csv(self.FILE_DB, index=False)
        except:
            pass
    
    def get_all(self):
        # Tenta ler. Se der erro (arquivo corrompido), rec
