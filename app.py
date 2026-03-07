import streamlit as st
import fitz  # PyMuPDF
import cv2
import numpy as np
import pypdf
import io
import re
import pytesseract
import zipfile
import datetime

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="PDF Smart Splitter", page_icon="📄", layout="centered")

# --- FUNÇÕES DE VISÃO COMPUTACIONAL ---
def descobrir_angulo(img_np):
    try:
        gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
        osd = pytesseract.image_to_osd(gray)
        angulo_rotacao = int(re.search(r'(?<=Rotate: )\d+', osd).group(0))
        return angulo_rotacao
    except Exception:
        return 0

def endireitar_imagem(image_np):
    gray = cv2.cvtColor(image_np, cv2.COLOR_RGB2GRAY)
    gray = cv2.bitwise_not(gray)
    coords = np.column_stack(np.where(gray > 0))
    if len(coords) == 0:
        return image_np
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

# --- FUNÇÃO PRINCIPAL DE PROCESSAMENTO (COM LOG E TRATAMENTO DE ERROS) ---
def processar_pdfs(arquivos_upados, placeholder_texto, placeholder_progresso):
    zip_buffer = io.BytesIO()
    logs = []  # Nosso "caderno" de anotações
    arquivos_gerados = 0
    erros_ocorridos = False
    
    data_hora_inicio = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logs.append(f"RELATÓRIO DE PROCESSAMENTO - {data_hora_inicio}\n")
    logs.append("="*60)
    
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for arquivo in arquivos_upados:
            placeholder_texto.markdown(f"⏳ Processando arquivo: **{arquivo.name}**")
            logs.append(f"\n📄 Lendo documento de origem: {arquivo.name}")
            
            try: # TRATAMENTO DE ERRO NÍVEL ARQUIVO
                arquivo_bytes = arquivo.read()
                doc_imagens = fitz.open(stream=arquivo_bytes, filetype="pdf")
                pdf_original = pypdf.PdfReader(io.BytesIO(arquivo_bytes))
                
                paginas_buffer = []
                barra = placeholder_progresso.progress(0)
                total_paginas = len(pdf_original.pages)
                tags_encontradas_no_arquivo = 0
                
                for i in range(total_paginas):
                    barra.progress((i + 1) / total_paginas)
                    paginas_buffer.append(i)
                    
                    try: # TRATAMENTO DE ERRO NÍVEL PÁGINA
                        pagina = doc_imagens.load_page(i)
                        pix = pagina.get_pixmap(dpi=300) 
                        img_np = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)
                        
                        if pix.n == 4:
                            img_np = cv2.cvtColor(img_np, cv2.COLOR_RGBA2RGB)
                        elif pix.n == 1:
                            img_np = cv2.cvtColor(img_np, cv2.COLOR_GRAY2RGB)
                        
                        angulo = descobrir_angulo(img_np)
                        if angulo != 0:
                            pdf_original.pages[i].rotate(angulo)
                        
                        if angulo == 90:
                            img_np = cv2.rotate(img_np, cv2.ROTATE_90_CLOCKWISE)
                        elif angulo == 180:
                            img_np = cv2.rotate(img_np, cv2.ROTATE_180)
                        elif angulo == 270:
                            img_np = cv2.rotate(img_np, cv2.ROTATE_90_COUNTERCLOCKWISE)
                            
                        img_endireitada = endireitar_imagem(img_np)
                        texto_completo = pytesseract.image_to_string(img_endireitada, lang='por')
                        texto_completo = texto_completo.replace('\n', ' ') 
                        
                        regex_prioridade = r'NOMEARQ\s*(.{1,100}?)\s*TERMARQ'
                        match = re.search(regex_prioridade, texto_completo)
                        
                        if match:
                            nome_extraido = match.group(1)
                            if nome_extraido:
                                nome_sugerido = re.sub(r'\s+', ' ', nome_extraido).strip()
                                nome_sugerido = re.sub(r'NR0I|NR0l|NROI|NROl', 'NR01', nome_sugerido)
                                nome_sugerido = re.sub(r'[\\/:*?"<>|]', '', nome_sugerido)
                                nome_sugerido = nome_sugerido[:100] 
                                nome_final = f"{nome_sugerido}.pdf"
                                
                                pdf_writer = pypdf.PdfWriter()
                                for p_num in paginas_buffer:
                                    pdf_writer.add_page(pdf_original.pages[p_num])
                                
                                pdf_out_buffer = io.BytesIO()
                                pdf_writer.write(pdf_out_buffer)
                                
                                # Salva o PDF cortado dentro do ZIP
                                zip_file.writestr(nome_final, pdf_out_buffer.getvalue())
                                
                                logs.append(f"   -> [SUCESSO] Tag lida na pág {i+1}. Criado: {nome_final}")
                                arquivos_gerados += 1
                                tags_encontradas_no_arquivo += 1
                                paginas_buffer = []
                                
                    except Exception as e_pagina:
                        erros_ocorridos = True
                        logs.append(f"   -> [ERRO] Falha ao ler a pág {i+1}: {str(e_pagina)}")
                
                doc_imagens.close()
                
                if tags_encontradas_no_arquivo == 0:
                    erros_ocorridos = True
                    logs.append(f"   -> [AVISO] Nenhuma tag encontrada neste documento. Ele foi ignorado.")
                    
            except Exception as e_arquivo:
                erros_ocorridos = True
                logs.append(f"   -> [ERRO CRÍTICO] O arquivo {arquivo.name} falhou completamente: {str(e_arquivo)}")
        
        # Fecha o log e o grava no ZIP
        logs.append("\n" + "="*60)
        logs.append(f"Total de arquivos gerados com sucesso: {arquivos_gerados}")
        if erros_ocorridos:
            logs.append("STATUS FINAL: Concluído com Alertas/Erros. Verifique o detalhamento acima.")
        else:
            logs.append("STATUS FINAL: 100% Concluído com Sucesso!")
            
        zip_file.writestr("log.txt", "\n".join(logs))
        
    return zip_buffer.getvalue(), erros_ocorridos, arquivos_gerados

# --- INTERFACE DO USUÁRIO (FRONT-END) ---
st.title("📄 PDF Smart Splitter")
st.markdown("**BM Automações** | Separador com Auto-Endireitamento e OCR Tesseract")
st.info("Renomeador e Separador de Documentos: `NOMEARQ Nome - Tipo - Data TERMARQ`")

if "zip_pronto" not in st.session_state:
    st.session_state.zip_pronto = None
    st.session_state.teve_erro = False
    st.session_state.qtd_arquivos = 0

arquivos = st.file_uploader("Arraste seus PDFs aqui", type=["pdf"], accept_multiple_files=True)

if arquivos:
    if st.button("PROCESSAR ARQUIVOS", type="primary"):
        espaco_texto = st.empty()
        espaco_progresso = st.empty()
        
        try:
            espaco_texto.info("Lendo documentos com OCR e corrigindo orientação das páginas...")
            
            # Chama a função e salva os 3 retornos na memória
            zip_bytes, teve_erro, qtd_arquivos = processar_pdfs(arquivos, espaco_texto, espaco_progresso)
            
            st.session_state.zip_pronto = zip_bytes
            st.session_state.teve_erro = teve_erro
            st.session_state.qtd_arquivos = qtd_arquivos
            
            espaco_texto.empty()
            espaco_progresso.empty()
            
        except Exception as e:
            espaco_texto.empty()
            espaco_progresso.empty()
            st.error(f"Erro fatal não tratado: {str(e)}")

# --- ÁREA DE DOWNLOAD (Feedback de Cores Inteligente) ---
if st.session_state.zip_pronto is not None:
    st.markdown("### 📦 Seu arquivo está pronto")
    
    # Lógica de cores baseada nos alertas do log
    if st.session_state.qtd_arquivos == 0:
        st.error("❌ Nenhum arquivo novo foi gerado (nenhuma tag lida). Baixe o ZIP para ler o log.txt.")
    elif st.session_state.teve_erro:
        st.warning("⚠️ Processamento concluído com erros ou avisos! Baixe o ZIP e abra o 'log.txt'.")
    else:
        st.success("✅ Processamento 100% concluído com sucesso!")
        
    data_atual = datetime.datetime.now().strftime("%Y-%m-%d")
    nome_zip = f"Lote_Processado_{data_atual}.zip"
    
    st.download_button(
        label="⬇️ BAIXAR ARQUIVO ZIP",
        data=st.session_state.zip_pronto,
        file_name=nome_zip,
        mime="application/zip"
    )
    
    st.markdown("---")
    if st.button("🧹 Limpar e Começar de Novo"):
        st.session_state.zip_pronto = None
        st.rerun()
