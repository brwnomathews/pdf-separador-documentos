import streamlit as st
import pymupdf
from io import BytesIO
import zipfile
from PIL import Image
import time
from datetime import date
from openai import OpenAI
import base64
import re

st.set_page_config(page_title="Separador por TAG - IA Simples", layout="wide")

st.title("📄 Separador de PDFs por TAG")
st.markdown("**Modo Simples com IA** — Nemotron Nano 12B 2 VL (free)")

# ====================== CONFIGURAÇÃO ======================
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=st.secrets.get("OPENROUTER_API_KEY", "")
)

ia_cache = {}

def image_to_base64(img: Image.Image) -> str:
    buffered = BytesIO()
    img.save(buffered, format="PNG")
    return base64.b64encode(buffered.getvalue()).decode()

def extrair_tag_com_ia(img: Image.Image, page_num: int) -> str:
    """Extrai TAG usando apenas a IA"""
    if not st.secrets.get("OPENROUTER_API_KEY"):
        st.error("❌ Configure a chave OPENROUTER_API_KEY nos Secrets.")
        st.stop()

    cache_key = f"page_{page_num}"
    if cache_key in ia_cache:
        return ia_cache[cache_key]

    try:
        base64_image = image_to_base64(img)

        prompt = f"""
Analise a imagem da página {page_num}.

Extraia a TAG que está entre vários X's.
Formato típico: XXXXX Nome completo - NR01 - 20122025 XXXXX

Regras:
- Retorne apenas a TAG limpa no formato: "Nome Completo - NR01 - 20122025"
- Corrija erros óbvios de OCR (O vira 0, I ou l vira 1)
- Se não encontrar TAG clara, retorne exatamente: SEM_TAG
- Não coloque nenhum texto extra, explicação ou aspas.
"""

        response = client.chat.completions.create(
            model="nvidia/nemotron-nano-12b-v2-vl:free",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64_image}"}}
                ]
            }],
            temperature=0.0,
            max_tokens=100
        )

        content = response.choices[0].message.content
        tag = content.strip() if content else "SEM_TAG"
        
        ia_cache[cache_key] = tag
        return tag

    except Exception as e:
        st.warning(f"Erro na IA (página {page_num}): {str(e)[:100]}")
        return f"SEM_TAG_PAG_{page_num}"

def normalizar_tag(texto: str) -> str:
    if not texto or "SEM_TAG" in texto.upper():
        return texto
    texto = texto.upper().strip()
    texto = re.sub(r'\s+', ' ', texto)          # mantém um espaço entre palavras
    texto = re.sub(r'NR0?[I1LO]+', 'NR01', texto)
    texto = re.sub(r'O', '0', texto)
    texto = re.sub(r'[I|L]', '1', texto)
    return texto.strip()

# ====================== PROCESSAMENTO ======================
uploaded_files = st.file_uploader("Arraste ou selecione os PDFs", type="pdf", accept_multiple_files=True)

if uploaded_files and st.button("🚀 Iniciar Processamento Simples com IA", type="primary"):
    
    if not st.secrets.get("OPENROUTER_API_KEY"):
        st.error("Configure sua chave OPENROUTER_API_KEY nos Secrets.")
        st.stop()

    progress_bar = st.progress(0)
    status_text = st.empty()
    log_container = st.container()
    log_container.markdown("### 📜 Log em Tempo Real")
    log_area = log_container.empty()

    full_log = ""
    zip_buffer = BytesIO()

    with zipfile.ZipFile(zip_buffer, "w") as zip_file:
        total_arquivos = len(uploaded_files)
        
        for idx, uploaded_file in enumerate(uploaded_files):
            status_text.info(f"Processando: **{uploaded_file.name}**")
            pdf_bytes = uploaded_file.read()
            doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
            
            grupos = {}   # tag_normalizada -> lista de páginas
            
            for page_num in range(len(doc)):
                perc = int(((idx + (page_num + 1) / len(doc)) / total_arquivos) * 100)
                progress_bar.progress(perc)
                
                page = doc[page_num]
                pix = page.get_pixmap(dpi=200)
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                
                tag_da_pagina = extrair_tag_com_ia(img, page_num + 1)
                tag_normalizada = normalizar_tag(tag_da_pagina)
                
                log_msg = f"**Página {page_num+1}** → `{tag_da_pagina}`"
                full_log += log_msg + "\n\n"
                log_area.markdown(full_log)
                
                # Agrupamento simples: mesma TAG = mesmo grupo
                if tag_normalizada in grupos:
                    grupos[tag_normalizada].append(page_num)
                    full_log += f"✅ Adicionada ao grupo existente\n---\n"
                else:
                    grupos[tag_normalizada] = [page_num]
                    full_log += f"🆕 Novo grupo criado\n---\n"
                
                log_area.markdown(full_log)
            
            # Salvar cada grupo como PDF separado
            full_log += f"**📦 Criando {len(grupos)} arquivos para {uploaded_file.name}**\n\n"
            log_area.markdown(full_log)
            
            for tag_norm, paginas in grupos.items():
                novo_doc = pymupdf.open()
                for p in sorted(paginas):
                    novo_doc.insert_pdf(doc, from_page=p, to_page=p)
                
                pdf_bytes_out = novo_doc.tobytes()
                
                # Nome do arquivo: usa a TAG original ou genérico
                nome_arquivo = f"{tag_norm}.pdf" if "SEM_TAG" not in tag_norm.upper() else f"SEM_TAG_PAG_{paginas[0]+1}.pdf"
                zip_file.writestr(nome_arquivo, pdf_bytes_out)
                novo_doc.close()
                
                full_log += f"✅ Salvo: `{nome_arquivo}` • {len(paginas)} páginas\n"
                log_area.markdown(full_log)
            
            doc.close()
            time.sleep(0.3)

    zip_buffer.seek(0)
    progress_bar.progress(100)
    status_text.success("✅ Processamento concluído!")

    data_atual = date.today().isoformat()
    st.download_button(
        label="📥 Baixar ZIP com os PDFs",
        data=zip_buffer,
        file_name=f"Lote_IA_Simples_{data_atual}.zip",
        mime="application/zip",
        type="primary"
    )

st.caption("Versão simples • Apenas IA (Nemotron Nano VL free)")
