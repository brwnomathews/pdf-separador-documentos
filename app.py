import streamlit as st
from pdf2image import convert_from_bytes
import pytesseract
import pymupdf
from rapidfuzz import fuzz
import re
from io import BytesIO
import zipfile
from PIL import Image
import time
from datetime import date   # ← Correção aqui

st.set_page_config(page_title="Separador por TAG - Tempo Real", layout="wide")

st.title("📄 Separador de PDFs por TAG com Log em Tempo Real")
st.markdown("**Agrupamento global** — páginas com a mesma TAG são reunidas mesmo que estejam distantes no PDF.")

TAXA_SIMILARIDADE = st.slider("Taxa mínima de similaridade (%)", min_value=80, max_value=98, value=88, step=1)

def normalizar_tag(texto: str) -> str:
    texto = texto.upper().strip()
    texto = re.sub(r'\s+', '', texto)
    texto = re.sub(r'NR0?[I1LO]+', 'NR01', texto)
    texto = re.sub(r'O', '0', texto)
    texto = re.sub(r'[I|L]', '1', texto)
    return texto

def extrair_tag(texto: str) -> str:
    match = re.search(r'X{4,}\s*(.+?)\s*-?\s*NR0?1?\s*-?\s*(\d{6,8})\s*X{4,}', texto, re.I | re.DOTALL)
    if match:
        nome = re.sub(r'[\\/:*?"<>|]', '', match.group(1).strip())
        numero = match.group(2).strip()
        return f"{nome} - NR01 - {numero}".strip()
    
    match_fallback = re.search(r'X{4,}\s*(.+?)\s*X{4,}', texto, re.I | re.DOTALL)
    if match_fallback:
        nome = re.sub(r'[\\/:*?"<>|]', '', match_fallback.group(1).strip())[:100]
        return nome if len(nome) > 3 else "SEM_TAG"
    return "SEM_TAG"

# ====================== UPLOAD ======================
uploaded_files = st.file_uploader("Arraste ou selecione os PDFs", type="pdf", accept_multiple_files=True)

if uploaded_files and st.button("🚀 Iniciar Processamento com Log em Tempo Real", type="primary"):
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    # Container para o log em tempo real
    log_container = st.container()
    log_container.markdown("### 📜 Log em Tempo Real")
    log_area = log_container.empty()
    
    full_log = ""

    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as zip_file:
        total_arquivos = len(uploaded_files)
        
        for idx, uploaded_file in enumerate(uploaded_files):
            status_text.info(f"📂 Processando arquivo {idx+1}/{total_arquivos}: **{uploaded_file.name}**")
            
            pdf_bytes = uploaded_file.read()
            doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
            
            grupos = {}  # tag_norm -> {"rep_nome": str, "paginas": list}
            
            for page_num in range(len(doc)):
                # Progresso
                perc = int(((idx + (page_num + 1) / len(doc)) / total_arquivos) * 100)
                progress_bar.progress(perc)
                
                # Extrair imagem da página
                page = doc[page_num]
                pix = page.get_pixmap(dpi=180)
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                
                # Rotação automática + OCR
                text = ""
                for angle in [0, 90, 180, 270]:
                    rotated = img.rotate(angle, expand=True)
                    text = pytesseract.image_to_string(rotated, lang='por')
                    if len(text.strip()) > 30:
                        img = rotated
                        break
                
                tag_da_pagina = extrair_tag(text)
                tag_norm = normalizar_tag(tag_da_pagina)
                
                # Log da página
                log_msg = f"**Página {page_num+1}** → TAG encontrada: `{tag_da_pagina}`"
                full_log += log_msg + "\n\n"
                log_area.markdown(full_log)
                
                # Busca melhor grupo existente
                melhor_sim = 0
                melhor_tag_rep = ""
                melhor_grupo = None
                
                for tnorm, grupo in grupos.items():
                    sim = fuzz.ratio(tnorm, tag_norm)
                    if sim > melhor_sim:
                        melhor_sim = sim
                        melhor_tag_rep = grupo["rep_nome"]
                        melhor_grupo = grupo
                
                if melhor_grupo and melhor_sim >= TAXA_SIMILARIDADE:
                    melhor_grupo["paginas"].append(page_num)
                    full_log += f"🔗 Similaridade com grupo **{melhor_tag_rep}** = **{melhor_sim}%**  \n"
                    full_log += f"✅ **Agrupando página {page_num+1} ao grupo existente**\n---\n"
                else:
                    grupos[tag_norm] = {"rep_nome": tag_da_pagina, "paginas": [page_num]}
                    full_log += f"🆕 **Nova TAG detectada** → Iniciando novo grupo\n---\n"
                
                log_area.markdown(full_log)
            
            # Salvar os grupos deste arquivo
            full_log += f"**📦 Montando {len(grupos)} arquivos finais para {uploaded_file.name}...**\n\n"
            log_area.markdown(full_log)
            
            for tag_norm, grupo in grupos.items():
                novo_doc = pymupdf.open()
                paginas_ordenadas = sorted(grupo["paginas"])
                for p in paginas_ordenadas:
                    novo_doc.insert_pdf(doc, from_page=p, to_page=p)
                
                pdf_bytes_out = novo_doc.tobytes()
                nome_final = f"{grupo['rep_nome']}.pdf"
                zip_file.writestr(nome_final, pdf_bytes_out)
                novo_doc.close()
                
                full_log += f"✅ **Grupo montado**: `{grupo['rep_nome']}` • **{len(paginas_ordenadas)} páginas**\n"
                log_area.markdown(full_log)
            
            doc.close()
            time.sleep(0.2)

    # Finalização
    zip_buffer.seek(0)
    progress_bar.progress(100)
    status_text.success("✅ Processamento concluído com sucesso!")
    
    # Correção: usando datetime.date.today()
    data_atual = date.today().isoformat()
    
    st.download_button(
        label="📥 Baixar ZIP com todos os PDFs separados",
        data=zip_buffer,
        file_name=f"Lote_Processado_{data_atual}.zip",
        mime="application/zip",
        type="primary"
    )

st.caption("• Agrupamento global de páginas • Log em tempo real • Rotação + OCR automático • Streamlit Cloud")
