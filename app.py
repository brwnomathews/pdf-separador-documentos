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

# --- FUNÇÃO PRINCIPAL DE PROCESSAMENTO ---
def processar_pdfs(arquivos_upados, placeholder_texto, placeholder_progresso):
    zip_buffer = io.BytesIO()
    logs = []
    arquivos_gerados = 0
    erros_ocorridos = False
    
    data_hora_inicio = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logs.append(f"RELATÓRIO DE PROCESSAMENTO - {data_hora_inicio}\n")
    logs.append("="*60)
    
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for arquivo in arquivos_upados:
            placeholder_texto.markdown(f"⏳ Processando arquivo: **{arquivo.name}**")
            logs.append(f"\n📄 Lendo documento de origem: {arquivo.name}")
            
            try:
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
                    
                    try:
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
                        texto_completo_linha = texto_completo.replace('\n', ' ') 
                        
                        # NOVO REGEX DA TAG: XXXXX ... XXXXX
                        regex_prioridade = r'XXXXX\s*(.{1,100}?)\s*XXXXX'
                        match = re.search(regex_prioridade, texto_completo_linha)
                        
                        if match:
                            nome_extraido = match.group(1)
                            if nome_extraido:
                                nome_sugerido = re.sub(r'\s+', ' ', nome_extraido).strip()
                                nome_sugerido = re.sub(r'[\\/:*?"<>|]', '', nome_sugerido)
                                nome_sugerido = nome_sugerido[:100] 
                                nome_final = f"{nome_sugerido}.pdf"
                                
                                # --- INÍCIO DA VALIDAÇÃO DE PÁGINAS ---
                                qtd_paginas_reais = len(paginas_buffer)
                                status_suspeito = False
                                
                                # Busca "Página 3" ou "Pagina 3" (ignora maiúsculas/minúsculas e acentos)
                                regex_pagina = r'(?i)P[áa]gina\s*(\d+)'
                                match_pag = re.search(regex_pagina, texto_completo)
                                
                                if match_pag:
                                    num_pagina_lido = int(match_pag.group(1))
                                    if num_pagina_lido == qtd_paginas_reais:
                                        msg_validacao = f"Validação OK ({qtd_paginas_reais} págs)."
                                    else:
                                        msg_validacao = f"ALERTA: Tag lida na 'Página {num_pagina_lido}', mas o bloco tem {qtd_paginas_reais} folhas fisicas!"
                                        status_suspeito = True
                                else:
                                    msg_validacao = f"Aviso: Não achou rodapé para validar. Salvo com {qtd_paginas_reais} págs."
                                # --- FIM DA VALIDAÇÃO ---
                                
                                pdf_writer = pypdf.PdfWriter()
                                for p_num in paginas_buffer:
                                    pdf_writer.add_page(pdf_original.pages[p_num])
                                
                                pdf_out_buffer = io.BytesIO()
                                pdf_writer.write(pdf_out_buffer)
                                
                                zip_file.writestr(nome_final, pdf_out_buffer.getvalue())
                                
                                # Regista no Log com base na validação
                                if status_suspeito:
                                    logs.append(f"   -> ⚠️ [SUSPEITO] {nome_final} | {msg_validacao}")
                                    erros_ocorridos = True # Isso fará a tela ficar laranja no final
                                else:
                                    logs.append(f"   -> ✅ [SUCESSO] {nome_final} | {msg_validacao}")
                                    
                                arquivos_gerados += 1
                                tags_encontradas_no_arquivo += 1
                                paginas_buffer = []
                                
                    except Exception as e_pagina:
                        erros_ocorridos = True
                        logs.append(f"   -> ❌ [ERRO] Falha ao ler a pág {i+1}: {str(e_pagina)}")
                
                doc_imagens.close()
                
                if tags_encontradas_no_arquivo == 0:
                    erros_ocorridos = True
                    logs.append(f"   -> ⚠️ [AVISO] Nenhuma tag (XXXXX) encontrada. O documento não foi separado.")
                    
            except Exception as e_arquivo:
                erros_ocorridos = True
                logs.append(f"   -> ❌ [ERRO CRÍTICO] O arquivo {arquivo.name} falhou completamente: {str(e_arquivo)}")
        
        logs.append("\n" + "="*60)
        logs.append(f"Total de arquivos gerados com sucesso: {arquivos_gerados}")
        if erros_ocorridos:
            logs.append("STATUS FINAL: Concluído com SUSPEITAS/ALERTAS. Revise os itens marcados com ⚠️ acima.")
        else:
            logs.append("STATUS FINAL: 100% Concluído com Sucesso e Validado!")
            
        zip_file.writestr("log.txt", "\n".join(logs))
        
    return zip_buffer.getvalue(), erros_ocorridos, arquivos_gerados

# --- INTERFACE DO USUÁRIO (FRONT-END) ---
st.title("📄 PDF Smart Splitter")
st.markdown("**BM Automações** | Separador OCR Inteligente c/ Auditoria de Páginas")
st.info("Renomeador e Separador de Documentos: `XXXXX Nome - Tipo - Data XXXXX`")

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
            espaco_texto.info("Lendo documentos e validando integridade das páginas...")
            
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

# --- FEEDBACK VISUAL ---
if st.session_state.zip_pronto is not None:
    st.markdown("### 📦 Seu arquivo está pronto")
    
    if st.session_state.qtd_arquivos == 0:
        st.error("❌ Nenhuma tag XXXXX lida. Baixe o ZIP para ler o log.txt.")
    elif st.session_state.teve_erro:
        st.warning("⚠️ Atenção: Há documentos SUSPEITOS ou faltantes. Baixe e leia o 'log.txt'!")
    else:
        st.success("✅ Processamento 100% íntegro. Todas as numerações bateram!")
        
    data_atual = datetime.datetime.now().strftime("%Y-%m-%d")
    nome_zip = f"Lote_Auditoria_{data_atual}.zip"
    
    st.download_button(
        label="⬇️ BAIXAR ARQUIVOS E LOG",
        data=st.session_state.zip_pronto,
        file_name=nome_zip,
        mime="application/zip"
    )
    
    st.markdown("---")
    if st.button("🧹 Limpar e Começar de Novo"):
        st.session_state.zip_pronto = None
        st.rerun()
