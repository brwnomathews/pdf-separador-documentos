import streamlit as st
import fitz  # PyMuPDF para converter PDF em imagem
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

# --- CARREGAMENTO DO MODELO OCR (CACHE) ---
# Usamos cache para que o modelo não seja recarregado a cada clique, deixando o app mais rápido.
@st.cache_resource
def carregar_leitor_ocr():
    return easyocr.Reader(['pt'], gpu=False)

reader = carregar_leitor_ocr()

# --- FUNÇÃO PARA ENDIREITAR A IMAGEM (DESKEW) ---
def endireitar_imagem(image_np):
    # Converte para tons de cinza
    gray = cv2.cvtColor(image_np, cv2.COLOR_RGB2GRAY)
    # Inverte as cores (texto branco, fundo preto) para a detecção
    gray = cv2.bitwise_not(gray)
    
    # Encontra as coordenadas de todos os pixels maiores que 0 (o texto)
    coords = np.column_stack(np.where(gray > 0))
    
    # Calcula o retângulo que engloba o texto e pega o ângulo
    angle = cv2.minAreaRect(coords)[-1]
    
    # Ajusta o ângulo para OpenCV
    if angle < -45:
        angle = -(90 + angle)
    else:
        angle = -angle
        
    # Rotaciona a imagem
    (h, w) = image_np.shape[:2]
    center = (w // 2, h // 2)
    M = cv2.getRotationMatrix2D(center, angle, 1.0)
    rotated = cv2.warpAffine(image_np, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    
    return rotated

# --- FUNÇÃO PRINCIPAL DE PROCESSAMENTO ---
def processar_pdfs(arquivos_upados):
    zip_buffer = io.BytesIO()
    
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for arquivo in arquivos_upados:
            st.write(f"⏳ Processando: **{arquivo.name}**")
            
            # Lendo o PDF para extração e o PDF original para corte
            arquivo_bytes = arquivo.read()
            doc_imagens = fitz.open(stream=arquivo_bytes, filetype="pdf")
            pdf_original = pypdf.PdfReader(io.BytesIO(arquivo_bytes))
            
            paginas_buffer = []
            barra_progresso = st.progress(0)
            
            for i in range(len(pdf_original.pages)):
                # Atualiza a barra de progresso
                barra_progresso.progress((i + 1) / len(pdf_original.pages))
                
                paginas_buffer.append(i)
                
                # 1. Converter página em imagem
                pagina = doc_imagens.load_page(i)
                pix = pagina.get_pixmap(dpi=150) # DPI 150 para balancear qualidade/velocidade
                img_np = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)
                
                if pix.n == 4:
                    img_np = cv2.cvtColor(img_np, cv2.COLOR_RGBA2RGB)
                elif pix.n == 1:
                    img_np = cv2.cvtColor(img_np, cv2.COLOR_GRAY2RGB)
                
                # 2. Endireitar a imagem
                img_endireitada = endireitar_imagem(img_np)
                
                # 3. Aplicar OCR
                resultados_ocr = reader.readtext(img_endireitada, detail=0)
                texto_completo = " ".join(resultados_ocr)
                
                # 4. Buscar a TAG de separação com Regex
                regex_prioridade = r'@@(.*?)\$\$|@@(.*?)\$|@@(.*?(\d{8}))'
                match = re.search(regex_prioridade, texto_completo)
                
                if match:
                    # Pega o grupo que encontrou a correspondência
                    nome_extraido = match.group(1) or match.group(2) or match.group(3)
                    
                    if nome_extraido:
                        # Limpeza do nome do arquivo
                        nome_sugerido = re.sub(r'\s+', ' ', nome_extraido).strip()
                        nome_sugerido = re.sub(r'NR0I|NR0l|NROI|NROl', 'NR01', nome_sugerido)
                        nome_sugerido = re.sub(r'[\\/:*?"<>|]', '', nome_sugerido)
                        
                        # Cria um novo PDF apenas com as páginas do buffer
                        pdf_writer = pypdf.PdfWriter()
                        for p_num in paginas_buffer:
                            pdf_writer.add_page(pdf_original.pages[p_num])
                        
                        # Salva o novo PDF em memória e adiciona ao ZIP
                        pdf_out_buffer = io.BytesIO()
                        pdf_writer.write(pdf_out_buffer)
                        zip_file.writestr(f"{nome_sugerido}.pdf", pdf_out_buffer.getvalue())
                        
                        # Reseta o buffer para o próximo documento
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
        with st.spinner("Iniciando motor de OCR e processamento... Isso pode levar alguns minutos dependendo do tamanho do PDF."):
            try:
                arquivo_zip = processar_pdfs(arquivos)
                
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