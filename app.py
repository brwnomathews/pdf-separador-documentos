import streamlit as st
import fitz  # PyMuPDF
import google.generativeai as genai
import json
import io
import zipfile
from PIL import Image

# Configuração da Página Streamlit
st.set_page_config(page_title="REFRAMINAS DocAI v3", page_icon="🤖", layout="wide")

# 1. Acessando a chave da API através do st.secrets de forma segura
try:
    api_key = st.secrets["GEMINI_API_KEY"]
except KeyError:
    st.error("❌ Chave API não encontrada. Por favor, configure 'GEMINI_API_KEY' nos Secrets do Streamlit Cloud.")
    st.stop() # Para a execução do app até que a chave seja configurada

# Inicializando o Gemini com a chave secreta
genai.configure(api_key=api_key)

st.sidebar.title("⚙️ Configurações")
st.sidebar.success("✅ Chave API carregada dos Secrets de forma segura!")

st.title("📄 REFRAMINAS DocAI - Motor Streamlit")
st.markdown("Faça o upload de um PDF desordenado. A IA irá **separar, classificar, rotacionar e agrupar** tudo em um arquivo ZIP final.")

# O Super Prompt Consolidado
PROMPT_SISTEMA = """Você é um perito em documentos da REFRAMINAS. Analise esta página e retorne APENAS um JSON.
  
DETERMINE:
1. TIPO: 
   - FICHA DE EPI (com datas) ou FICHA DE EPI SEM DATA.
   - CERTIFICADOS (NR01, 06, 12, 18, 33, 34, 35).
   - LISTA DE PRESENCA NRXX.
   - ORDEM DE SERVICO (Layout A ou B).
   - RH: FICHA DE REGISTRO, CONTRATO DE TRABALHO, OPCAO VALE TRANSPORTE.
   - Outros: PPR, IT, TERMO DE RESPONSABILIDADE, ENSAIO DE VEDACAO, PPAE CSN.
2. NOME: Extraia o nome do colaborador seguindo os padrões do layout.
3. DATA: Formato DDMMAAAA (priorize datas de admissão/vigência para RH, e data de término para listas).
4. ROTACAO: Identifique se o texto está rotacionado na imagem. Retorne: 0, 90, 180 ou 270 (graus no sentido horário para ficar legível).

JSON ESPERADO: {"nome": "NOME COMPLETO", "tipo": "TIPO DOC", "data": "DDMMAAAA", "rotacao": 0}"""

uploaded_file = st.file_uploader("Envie o PDF mestre contendo várias páginas", type=["pdf"])

# O botão não precisa mais verificar se a api_key foi digitada, pois o st.stop() já tratou isso no início
if st.button("🚀 Iniciar Processamento Inteligente") and uploaded_file:
    
    # Configurando o modelo especificado
    model = genai.GenerativeModel('gemini-3.1-flash-lite-preview')
    
    with st.spinner("Lendo o arquivo PDF..."):
        pdf_bytes = uploaded_file.read()
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        total_paginas = len(doc)
        
        grupos_documentos = {}
        
        barra_progresso = st.progress(0)
        status_texto = st.empty()
        
        # Processamento página por página
        for i in range(total_paginas):
            status_texto.text(f"🧠 Analisando página {i+1} de {total_paginas}...")
            
            # Converter página em Imagem para a IA "ver"
            page = doc.load_page(i)
            pix = page.get_pixmap(dpi=150)
            img_bytes = pix.tobytes("jpeg")
            img = Image.open(io.BytesIO(img_bytes))
            
            # Enviar para o Gemini
            try:
                response = model.generate_content([PROMPT_SISTEMA, img])
                texto_limpo = response.text.strip().replace("```json", "").replace("```", "")
                info = json.loads(texto_limpo)
                
                # Chave de agrupamento
                chave = f"{info.get('nome', 'DESCONHECIDO')} - {info.get('tipo', 'INDEFINIDO')} - {info.get('data', 'SEM_DATA')}"
                
                if chave not in grupos_documentos:
                    grupos_documentos[chave] = []
                
                grupos_documentos[chave].append({
                    "index": i,
                    "rotacao": info.get("rotacao", 0)
                })
                
                st.toast(f"Página {i+1} classificada: {chave}")
                
            except Exception as e:
                st.error(f"Erro na página {i+1}: {e}")
            
            # Atualizar progresso
            barra_progresso.progress((i + 1) / total_paginas)
            
        status_texto.text("📦 Montando arquivos e gerando ZIP...")
        
        # Montagem do ZIP final
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            
            for chave, paginas in grupos_documentos.items():
                novo_pdf = fitz.open()
                
                for pg_info in paginas:
                    # Copia a página original
                    novo_pdf.insert_pdf(doc, from_page=pg_info["index"], to_page=pg_info["index"])
                    pg_copiada = novo_pdf[-1]
                    
                    # Corrige a rotação se a IA detectou que estava torto
                    rotacao_ia = pg_info["rotacao"]
                    if rotacao_ia != 0:
                        pg_copiada.set_rotation(rotacao_ia)
                
                # Salva o PDF individual em memória e adiciona ao ZIP
                pdf_bytes_final = novo_pdf.write()
                zip_file.writestr(f"{chave}.pdf", pdf_bytes_final)
                novo_pdf.close()
                
        doc.close()
        
        st.success("✅ Processamento concluído com sucesso!")
        
        # Botão de Download do ZIP
        st.download_button(
            label="📥 Baixar Pasta Compactada (.ZIP)",
            data=zip_buffer.getvalue(),
            file_name="REFRAMINAS_Documentos_Processados.zip",
            mime="application/zip",
            use_container_width=True
        )
