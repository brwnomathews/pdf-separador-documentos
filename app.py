import streamlit as st
import fitz  # PyMuPDF
import google.generativeai as genai
import json
import io
import zipfile
from PIL import Image
from datetime import datetime

# Configuração da Página Streamlit (limpa e expandida)
st.set_page_config(page_title="REFRAMINAS DocAI", page_icon="📄", layout="wide")

# Acessando a chave da API de forma 100% invisível para o usuário final
try:
    api_key = st.secrets["GEMINI_API_KEY"]
except KeyError:
    st.error("❌ Erro interno do servidor: Chave API não configurada.")
    st.stop()

genai.configure(api_key=api_key)

# Cabeçalho Principal Simplificado
st.title("📄 REFRAMINAS DocAI")
st.markdown("Faça o upload do PDF mestre. O sistema irá ler as TAGs de identificação, corrigir a orientação das páginas e gerar um arquivo ZIP com os documentos organizados.")

# ==========================================
# O SUPER PROMPT DE TAGS
# ==========================================
PROMPT_SISTEMA = """Você é um sistema de extração de dados de alta precisão da REFRAMINAS.
Todas as páginas deste documento contêm uma TAG de identificação impressa, delimitada por "XXXXX" no início e no fim.
Sua única tarefa é localizar essa TAG e a orientação da página.

REGRAS:
1. ARQUIVO: Encontre o texto que está entre os "XXXXX" (por exemplo: XXXXX Bruno Cesar Mateus De Oliveira - NR01 - 12122026 XXXXX). 
   Extraia apenas o conteúdo interno, removendo os "X" e os espaços em branco nas pontas.
2. ROTACAO: O documento escaneado está torto? Retorne 0, 90, 180 ou 270 (graus no sentido horário necessários para o texto ficar em pé e legível).

Retorne APENAS um objeto JSON válido, sem explicações ou formatação markdown.

JSON ESPERADO: {"arquivo": "TEXTO EXTRAIDO DA TAG", "rotacao": 0}"""

# Área de Upload Centralizada
uploaded_file = st.file_uploader("Selecione o arquivo PDF digitalizado", type=["pdf"])

# ==========================================
# LAYOUT DE BOTÕES LADO A LADO
# ==========================================
# Criamos duas colunas na interface
col1, col2 = st.columns(2)

# Colocamos o botão de Iniciar na coluna da esquerda
with col1:
    btn_iniciar = st.button("🚀 Iniciar Processamento", use_container_width=True)

# Criamos um "espaço fantasma" na coluna da direita para o botão de download que virá depois
download_placeholder = col2.empty()

if btn_iniciar and uploaded_file:
    
    model = genai.GenerativeModel('gemini-3.1-flash-lite-preview')
    
    st.markdown("### 💻 Terminal de Processamento")
    terminal_placeholder = st.empty()
    log_msgs = []

    def add_log(msg):
        """Atualiza o terminal visual em tempo real."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_msgs.append(f"[{timestamp}] > {msg}")
        
        # Inverte a lista para mensagem mais nova no topo
        logs_formatados = "<br>".join(reversed(log_msgs))
        
        html_content = f"""
        <div style="background-color: #0c0c0c; color: #00ff00; font-family: 'Consolas', 'Courier New', monospace; 
                    padding: 15px; border-radius: 5px; height: 350px; overflow-y: auto; font-size: 14px; 
                    border: 1px solid #333; box-shadow: inset 0 0 10px #000;">
            {logs_formatados}
        </div>
        """
        terminal_placeholder.markdown(html_content, unsafe_allow_html=True)
    
    with st.spinner("Analisando documentos..."):
        pdf_bytes = uploaded_file.read()
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        total_paginas = len(doc)
        
        add_log(f"Sistema iniciado. Lote recebido com {total_paginas} página(s).")
        
        grupos_documentos = {}
        barra_progresso = st.progress(0)
        
        for i in range(total_paginas):
            add_log(f"Lendo página {i+1}/{total_paginas}...")
            
            page = doc.load_page(i)
            pix = page.get_pixmap(dpi=150)
            img_bytes = pix.tobytes("jpeg")
            img = Image.open(io.BytesIO(img_bytes))
            
            try:
                response = model.generate_content([PROMPT_SISTEMA, img])
                texto_limpo = response.text.strip().replace("```json", "").replace("```", "")
                info = json.loads(texto_limpo)
                
                nome_arquivo = info.get("arquivo", f"PAGINA_{i+1}_SEM_TAG_ENCONTRADA")
                rotacao = info.get("rotacao", 0)
                
                if nome_arquivo not in grupos_documentos:
                    grupos_documentos[nome_arquivo] = []
                
                grupos_documentos[nome_arquivo].append({
                    "index": i,
                    "rotacao": rotacao
                })
                
                status_rotacao = f" (Girando {rotacao}º)" if rotacao != 0 else ""
                add_log(f"[OK] Identificado: '{nome_arquivo}'{status_rotacao}")
                
            except Exception as e:
                add_log(f"[ERRO] Falha ao processar página {i+1}. Detalhe: {e}")
            
            barra_progresso.progress((i + 1) / total_paginas)
            
        add_log("Leitura concluída. Montando arquivo ZIP...")
        
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            
            for nome_arquivo, paginas in grupos_documentos.items():
                novo_pdf = fitz.open()
                
                for pg_info in paginas:
                    novo_pdf.insert_pdf(doc, from_page=pg_info["index"], to_page=pg_info["index"])
                    pg_copiada = novo_pdf[-1]
                    if pg_info["rotacao"] != 0:
                        pg_copiada.set_rotation(pg_info["rotacao"])
                
                pdf_bytes_final = novo_pdf.write()
                nome_final = f"{nome_arquivo}.pdf"
                zip_file.writestr(nome_final, pdf_bytes_final)
                add_log(f"Arquivo gerado: {nome_final}")
                novo_pdf.close()
                
        doc.close()
        add_log("Processo finalizado com sucesso. ZIP pronto!")
        st.success("✅ Documentos processados com sucesso!")
        
        # ==========================================
        # INJETANDO O BOTÃO NA COLUNA DA DIREITA
        # ==========================================
        # Agora injetamos o botão de download naquele espaço fantasma que deixamos ao lado do Iniciar
        with download_placeholder:
            st.download_button(
                label="📥 Baixar Documentos (ZIP)",
                data=zip_buffer.getvalue(),
                file_name="REFRAMINAS_Documentos.zip",
                mime="application/zip",
                use_container_width=True
            )
