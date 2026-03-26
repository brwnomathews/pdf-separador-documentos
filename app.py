import streamlit as st
import pymupdf
from io import BytesIO
import zipfile
import time
from datetime import date
from openai import OpenAI
import re

st.set_page_config(page_title="Separador por TAG - IA Simples", layout="wide")

st.title("📄 Separador de PDFs por TAG")
st.markdown("**Modo Simples com IA** — DeepSeek Chat (free) usando o texto já existente no PDF")

# ====================== CONFIGURAÇÃO ======================
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=st.secrets.get("OPENROUTER_API_KEY", "")
)

ia_cache = {}

def extrair_tag_com_ia(texto_pagina: str, page_num: int) -> str:
    """Extrai TAG usando apenas texto + DeepSeek"""
    if not st.secrets.get("OPENROUTER_API_KEY"):
        st.error("❌ Configure OPENROUTER_API_KEY nos Secrets.")
        st.stop()

    cache_key = f"page_{page_num}"
    if cache_key in ia_cache:
        return ia_cache[cache_key]

    try:
        prompt = f"""
Analise o texto abaixo e extraia a TAG que está entre os X's.

Texto da página {page_num}:
{texto_pagina}

Formato típico esperado: XXXXX Nome completo - NR01 - 20122025 XXXXX

Regras:
- Retorne APENAS a TAG limpa no formato: "Nome Completo - NR01 - 20122025"
- Corrija erros comuns de OCR (O → 0, I/l → 1)
- Se não encontrar TAG clara, retorne exatamente: SEM_TAG
- Nenhuma explicação, nenhum texto extra.
"""

        response = client.chat.completions.create(
            model="deepseek/deepseek-chat:free",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=100
        )

        tag = response.choices[0].message.content.strip() if response.choices[0].message.content else "SEM_TAG"
        ia_cache[cache_key] = tag
        return tag

    except Exception as e:
        st.warning(f"Erro na IA (página {page_num}): {str(e)[:100]}")
        return f"SEM_TAG_PAG_{page_num}"

def normalizar_tag(texto: str) -> str:
    if not texto or "SEM_TAG" in texto.upper():
        return texto
    texto = texto.upper().strip()
    texto = re.sub(r'\s+', ' ', texto)
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
                texto_pagina = page.get_text("text")   # ← Usa o OCR já existente
                
                tag_da_pagina = extrair_tag_com_ia(texto_pagina, page_num + 1)
                tag_normalizada = normalizar_tag(tag_da_pagina)
                
                log_msg = f"**Página {page_num+1}** → `{tag_da_pagina}`"
                full_log += log_msg + "\n\n"
                log_area.markdown(full_log)
                
                # Agrupamento simples
                if tag_normalizada in grupos:
                    grupos[tag_normalizada].append(page_num)
                    full_log += f"✅ Adicionada ao grupo existente\n---\n"
                else:
                    grupos[tag_normalizada] = [page_num]
                    full_log += f"🆕 Novo grupo criado\n---\n"
                
                log_area.markdown(full_log)
            
            # Salvar grupos
            full_log += f"**📦 Criando {len(grupos)} arquivos para {uploaded_file.name}**\n\n"
            log_area.markdown(full_log)
            
            for tag_norm, paginas in grupos.items():
                novo_doc = pymupdf.open()
                for p in sorted(paginas):
                    novo_doc.insert_pdf(doc, from_page=p, to_page=p)
                
                pdf_bytes_out = novo_doc.tobytes()
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
        label="📥 Baixar ZIP",
        data=zip_buffer,
        file_name=f"Lote_IA_Simples_{data_atual}.zip",
        mime="application/zip",
        type="primary"
    )

st.caption("Versão simples • DeepSeek Chat (free) usando texto já existente no PDF")
