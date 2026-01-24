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

# Configuração simples
st.set_page_config(page_title="Teste LoL", layout="wide")

st.title("🛡️ Teste de Recuperação")
st.write("Se você está lendo isso, o problema era o Pydantic ou o CSS!")

# Verifica bibliotecas
try:
    import pydantic
    st.success("✅ Biblioteca Pydantic encontrada!")
except ImportError:
    st.error("❌ Biblioteca Pydantic NÃO encontrada. Atualize o requirements.txt!")

# Secrets check
if st.secrets.get("RIOT_KEY"):
    st.success("✅ Chaves de API encontradas.")
else:
    st.warning("⚠️ Chaves não configuradas.")
