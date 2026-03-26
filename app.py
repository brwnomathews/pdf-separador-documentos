import streamlit as st
import fitz  # PyMuPDF
import google.generativeai as genai
import json
import io
import zipfile
from PIL import Image

# Configuração da Página Streamlit
st.set_page_config(page_title="REFRAMINAS DocAI v4", page_icon="🤖", layout="wide")

# Acessando a chave da API de forma segura
try:
    api_key = st.secrets["GEMINI_API_KEY"]
except KeyError:
    st.error("❌ Chave API não encontrada nos Secrets.")
    st.stop()

genai.configure(api_key=api_key)

st.sidebar.title("⚙️ Configurações")
st.sidebar.success("✅ Sistema Híbrido: TAGs + IA Ativado")

st.title("📄 REFRAMINAS DocAI - Leitura por TAGs")
st.markdown("A IA irá procurar a TAG padrão `XXXXX [Dados] XXXXX` em cada página, corrigir a rotação, e agrupar o PDF final com precisão absoluta.")

# ==========================================
# O NOVO SUPER PROMPT - SIMPLES E LETAL
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

uploaded_file = st.file_uploader("Envie o PDF mestre contendo as páginas com as TAGs XXXXX", type=["pdf"])

if st.button("🚀 Processar Documentos por TAG") and uploaded_file:
    
    model = genai.GenerativeModel('gemini-3.1-flash-lite-preview')
    
    with st.spinner("Lendo o arquivo PDF mestre..."):
        pdf_bytes = uploaded_file.read()
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        total_paginas = len(doc)
        
        grupos_documentos = {}
        barra_progresso = st.progress(0)
        status_texto = st.empty()
        
        for i in range(total_paginas):
            status_texto.text(f"🔍 Procurando TAG na página {i+1} de {total_paginas}...")
            
            # Converter página em imagem
            page = doc.load_page(i)
            pix = page.get_pixmap(dpi=150)
            img_bytes = pix.tobytes("jpeg")
            img = Image.open(io.BytesIO(img_bytes))
            
            try:
                # Chama a IA
                response = model.generate_content([PROMPT_SISTEMA, img])
                texto_limpo = response.text.strip().replace("```json", "").replace("```", "")
                info = json.loads(texto_limpo)
                
                # A chave agora é diretamente o nome extraído da TAG!
                nome_arquivo = info.get("arquivo", f"PAGINA_{i+1}_SEM_TAG_ENCONTRADA")
                
                if nome_arquivo not in grupos_documentos:
                    grupos_documentos[nome_arquivo] = []
                
                grupos_documentos[nome_arquivo].append({
                    "index": i,
                    "rotacao": info.get("rotacao", 0)
                })
                
                st.toast(f"Página {i+1} identificada: {nome_arquivo}")
                
            except Exception as e:
                st.error(f"Erro ao processar página {i+1}: {e}")
            
            barra_progresso.progress((i + 1) / total_paginas)
            
        status_texto.text("📦 Empacotando documentos agrupados pelas TAGs...")
        
        # Montagem do ZIP final
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            
            for nome_arquivo, paginas in grupos_documentos.items():
                novo_pdf = fitz.open()
                
                for pg_info in paginas:
                    # Copia a página e corrige rotação
                    novo_pdf.insert_pdf(doc, from_page=pg_info["index"], to_page=pg_info["index"])
                    pg_copiada = novo_pdf[-1]
                    if pg_info["rotacao"] != 0:
                        pg_copiada.set_rotation(pg_info["rotacao"])
                
                # Salva no ZIP com o nome exato da TAG + ".pdf"
                pdf_bytes_final = novo_pdf.write()
                zip_file.writestr(f"{nome_arquivo}.pdf", pdf_bytes_final)
                novo_pdf.close()
                
        doc.close()
        st.success("✅ Processamento concluído! Todos os documentos foram separados e nomeados conforme as TAGs.")
        
        st.download_button(
            label="📥 Baixar ZIP com Documentos Organizados",
            data=zip_buffer.getvalue(),
            file_name="REFRAMINAS_Docs_Por_TAG.zip",
            mime="application/zip",
            use_container_width=True
        )
