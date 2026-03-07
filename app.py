import streamlit as st
import fitz  # PyMuPDF
import easyocr
import cv2
import numpy as np
import pypdf
import io
import zipfile
import re
import datetime

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="PDF Smart Splitter", page_icon="📄", layout="centered")

# --- CARREGAMENTO DO MODELO OCR ---
@st.cache_resource
def carregar_leitor_ocr():
    return easyocr.Reader(['pt'], gpu=False)

reader = carregar_leitor_ocr()

# --- FUNÇÃO PARA ENDIREITAR A IMAGEM ---
def endireitar_imagem(image_np):
    gray = cv2.cvtColor(image_np, cv2.COLOR_RGB2GRAY)
    gray = cv2.bitwise_not(gray)
    coords = np.column_stack(np.where(gray > 0))
    angle = cv2.minAreaRect(coords)[-1]
    
    if angle < -45:
        angle = -(90 + angle)
    else:
        angle = -angle
        
    (h, w) = image_np.shape[:2]
    center = (w // 2, h // 2)
    M = cv2.getRotationMatrix2D(center, angle, 1.0)
    rotated = cv2.warpAffine(image_np, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    return rotated

# --- FUNÇÃO PRINCIPAL DE PROCESSAMENTO ---
# Recebemos os placeholders como parâmetros para atualizar a tela de forma segura
def processar_pdfs(arquivos_upados, placeholder_texto, placeholder_progresso):
    zip_buffer = io.BytesIO()
    
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for arquivo in arquivos_upados:
            # Atualiza o texto fixo na tela
            placeholder_texto.markdown(f"⏳ Processando arquivo: **{arquivo.name}**")
            
            arquivo_bytes = arquivo.read()
            doc_imagens = fitz.open(stream=arquivo_bytes, filetype="pdf")
            pdf_original = pypdf.PdfReader(io.BytesIO(arquivo_bytes))
            
            paginas_buffer = []
            
            # Cria a barra de progresso UMA VEZ por arquivo dentro do espaço fixo
            barra = placeholder_progresso.progress(0)
            
            total_paginas = len(pdf_original.pages)
            
            for i in range(total_paginas):
                # Atualiza a barra de progresso de forma segura
                barra.progress((i + 1) / total_paginas)
                
                paginas_buffer.append(i)
                
                pagina = doc_imagens.load_page(i)
                pix = pagina.get_pixmap(dpi=150)
                img_np = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)
                
                if pix.n == 4:
                    img_np = cv2.cvtColor(img_np, cv2.COLOR_RGBA2RGB)
                elif pix.n == 1:
                    img_np = cv2.cvtColor(img_np, cv2.COLOR_GRAY2RGB)
                
                img_endireitada = endireitar_imagem(img_np)
                resultados_ocr = reader.readtext(img_endireitada, detail=0)
                texto_completo = " ".join(resultados_ocr)
                
                regex_prioridade = r'@@(.*?)\$\$|@@(.*?)\$|@@(.*?(\d{8}))'
                match = re.search(regex_prioridade, texto_completo)
                
                if match:
                    nome_extraido = match.group(1) or match.group(2) or match.group(3)
                    
                    if nome_extraido:
                        nome_sugerido = re.sub(r'\s+', ' ', nome_extraido).strip()
                        nome_sugerido = re.sub(r'NR0I|NR0l|NROI|NROl', 'NR01', nome_sugerido)
                        nome_sugerido = re.sub(r'[\\/:*?"<>|]', '', nome_sugerido)
                        
                        pdf_writer = pypdf.PdfWriter()
                        for p_num in paginas_buffer:
                            pdf_writer.add_page(pdf_original.pages[p_num])
                        
                        pdf_out_buffer = io.BytesIO()
                        pdf_writer.write(pdf_out_buffer)
                        zip_file.writestr(f"{nome_sugerido}.pdf", pdf_out_buffer.getvalue())
                        
                        paginas_buffer = []
                        
            doc_imagens.close()
            
    zip_buffer.seek(0)
    return zip_buffer

# --- INTERFACE DO USUÁRIO (FRONT-END) ---
st.title("📄 PDF Smart Splitter")
st.markdown("**BM Automações** | Separador com Auto-Endireitamento e OCR")

st.info("Renomeador e Separador de Documentos: `@@Nome - Tipo - Data$$`")

arquivos = st.file_uploader("Arraste seus PDFs aqui", type=["pdf"], accept_multiple_files=True)

if arquivos:
    if st.button("PROCESSAR E GERAR ZIP", type="primary"):
        
        # 1. Criamos espaços vazios e fixos na tela ANTES de começar o trabalho pesado
        espaco_texto = st.empty()
        espaco_progresso = st.empty()
        
        try:
            espaco_texto.info("Iniciando motor de OCR... Isso pode levar alguns minutos.")
            
            # 2. Passamos os espaços vazios para a função usar
            arquivo_zip = processar_pdfs(arquivos, espaco_texto, espaco_progresso)
            
            # 3. Limpamos a tela e mostramos o sucesso
            espaco_texto.empty()
            espaco_progresso.empty()
            
            data_atual = datetime.datetime.now().strftime("%Y-%m-%d")
            nome_zip = f"Lote_Processado_{data_atual}.zip"
            
            st.success("✅ Concluído com sucesso!")
            st.download_button(
                label="⬇️ BAIXAR ARQUIVOS PROCESSADOS",
                data=arquivo_zip,
                file_name=nome_zip,
                mime="application/zip"
            )
        except Exception as e:
            st.error(f"Ocorreu um erro durante o processamento: {str(e)}")
