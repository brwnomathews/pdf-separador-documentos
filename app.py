import streamlit as st
from pdf2image import convert_from_bytes
import pymupdf
from rapidfuzz import fuzz
from io import BytesIO
import zipfile
from PIL import Image
import time
from datetime import date
from openai import OpenAI
import base64

st.set_page_config(page_title="Separador por TAG - Somente IA", layout="wide")

st.title("📄 Separador de PDFs por TAG - **Modo Exclusivo com IA**")
st.markdown("**Usando apenas Nemotron Nano 12B 2 VL (free)** — Sem regex, sem pytesseract como principal.")

# ====================== CONFIGURAÇÕES ======================
TAXA_SIMILARIDADE = st.slider("Taxa mínima de similaridade para agrupamento (%)", 
                              min_value=75, max_value=98, value=87, step=1)

# OpenRouter Client
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=st.secrets.get("OPENROUTER_API_KEY", "")
)

ia_cache = {}  # Cache simples por conteúdo da página

def image_to_base64(img: Image.Image) -> str:
    buffered = BytesIO()
    img.save(buffered, format="PNG")
    return base64.b64encode(buffered.getvalue()).decode()

def extrair_tag_com_ia(img: Image.Image, page_num: int) -> str:
    """Chama exclusivamente o Nemotron Nano VL com a imagem"""
    if not st.secrets.get("OPENROUTER_API_KEY"):
        st.error("❌ Chave OPENROUTER_API_KEY não configurada nos Secrets.")
        st.stop()

    # Cache simples
    cache_key = f"page_{page_num}_{hash(str(img.size))}"
    if cache_key in ia_cache:
        return ia_cache[cache_key]

    try:
        base64_image = image_to_base64(img)

        prompt = f"""
Você é um especialista em extração precisa de informações de documentos escaneados em português brasileiro.

Analise cuidadosamente a imagem da página {page_num} e extraia a TAG que está delimitada por várias letras "X".

Formato esperado da TAG:
XXXXX Nome completo da pessoa - NR01 - 20122025 XXXXX

Instruções importantes:
- Extraia apenas o conteúdo principal entre os X's.
- Corrija erros comuns de OCR (ex: O → 0, I/l → 1, espaços extras).
- Retorne a TAG limpa no formato exato: "Nome Completo - NR01 - 20122025"
- Se não conseguir identificar claramente a TAG, retorne exatamente: "SEM_TAG"

Responda **apenas** com a TAG ou "SEM_TAG". Sem explicações, sem texto adicional.
"""

        response = client.chat.completions.create(
            model="nvidia/nemotron-nano-12b-v2-vl:free",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{base64_image}"}
                        }
                    ]
                }
            ],
            temperature=0.0,
            max_tokens=100
        )

        tag_extraida = response.choices[0].message.content.strip()
        ia_cache[cache_key] = tag_extraida
        return tag_extraida

    except Exception as e:
        st.warning(f"Erro na IA na página {page_num}: {str(e)[:80]}...")
        return "SEM_TAG"

def normalizar_tag(texto: str) -> str:
    if not texto or texto == "SEM_TAG":
        return "SEM_TAG"
    texto = texto.upper().strip()
    texto = re.sub(r'\s+', '', texto)  # precisa importar re abaixo
    texto = re.sub(r'NR0?[I1LO]+', 'NR01', texto)
    texto = re.sub(r'O', '0', texto)
    texto = re.sub(r'[I|L]', '1', texto)
    return texto

# ====================== PROCESSAMENTO ======================
uploaded_files = st.file_uploader("Arraste ou selecione os PDFs", type="pdf", accept_multiple_files=True)

if uploaded_files and st.button("🚀 Iniciar Processamento EXCLUSIVO com Nemotron Nano VL", type="primary"):
    
    if not st.secrets.get("OPENROUTER_API_KEY"):
        st.error("⚠️ Configure sua chave OPENROUTER_API_KEY nos Secrets do Streamlit Cloud primeiro.")
        st.stop()

    progress_bar = st.progress(0)
    status_text = st.empty()
    log_container = st.container()
    log_container.markdown("### 📜 Log em Tempo Real - Modo IA Exclusivo")
    log_area = log_container.empty()

    full_log = ""
    zip_buffer = BytesIO()

    import re  # import aqui para evitar erro

    with zipfile.ZipFile(zip_buffer, "w") as zip_file:
        total_arquivos = len(uploaded_files)
        
        for idx, uploaded_file in enumerate(uploaded_files):
            status_text.info(f"📂 Processando com IA: **{uploaded_file.name}**")
            pdf_bytes = uploaded_file.read()
            doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
            
            grupos = {}   # tag_norm -> {"rep_nome": str, "paginas": list}
            
            for page_num in range(len(doc)):
                perc = int(((idx + (page_num + 1) / len(doc)) / total_arquivos) * 100)
                progress_bar.progress(perc)
                
                # Renderiza página em alta qualidade
                page = doc[page_num]
                pix = page.get_pixmap(dpi=220)   # alta resolução para melhor visão da IA
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                
                # Chama a IA (única fonte de extração)
                tag_da_pagina = extrair_tag_com_ia(img, page_num + 1)
                
                log_msg = f"**Página {page_num+1}** → IA extraiu: `{tag_da_pagina}`"
                full_log += log_msg + "\n\n"
                log_area.markdown(full_log)
                
                tag_norm = normalizar_tag(tag_da_pagina)
                
                # Agrupamento global por similaridade
                melhor_sim = 0
                melhor_tag_rep = ""
                melhor_grupo = None
                
                for tnorm, grupo in grupos.items():
                    sim = fuzz.ratio(tnorm, tag_norm)
                    if sim > melhor_sim:
                        melhor_sim = sim
                        melhor_tag_rep = grupo["rep_nome"]
                        melhor_grupo = grupo
                
                if melhor_grupo and melhor_sim >= TAXA_SIMILARIDADE and tag_da_pagina != "SEM_TAG":
                    melhor_grupo["paginas"].append(page_num)
                    full_log += f"🔗 Similaridade **{melhor_sim}%** → Agrupando página {page_num+1} ao grupo\n---\n"
                else:
                    if tag_da_pagina == "SEM_TAG":
                        tag_da_pagina = f"SEM_TAG_PAG_{page_num+1}"
                    grupos[tag_norm] = {"rep_nome": tag_da_pagina, "paginas": [page_num]}
                    full_log += f"🆕 **Novo grupo criado** pela IA\n---\n"
                
                log_area.markdown(full_log)
            
            # Salvar os grupos deste arquivo
            full_log += f"**📦 Montando {len(grupos)} documentos finais para {uploaded_file.name}**\n\n"
            log_area.markdown(full_log)
            
            for grupo in grupos.values():
                novo_doc = pymupdf.open()
                for p in sorted(grupo["paginas"]):
                    novo_doc.insert_pdf(doc, from_page=p, to_page=p)
                
                pdf_bytes_out = novo_doc.tobytes()
                nome_final = f"{grupo['rep_nome']}.pdf"
                zip_file.writestr(nome_final, pdf_bytes_out)
                novo_doc.close()
                
                full_log += f"✅ **Grupo salvo**: `{grupo['rep_nome']}` • {len(grupo['paginas'])} páginas\n"
                log_area.markdown(full_log)
            
            doc.close()
            time.sleep(0.3)  # delay para visualizar o log

    # Final
    zip_buffer.seek(0)
    progress_bar.progress(100)
    status_text.success("✅ Processamento exclusivo com IA concluído!")
    
    data_atual = date.today().isoformat()
    st.download_button(
        label="📥 Baixar ZIP com todos os PDFs",
        data=zip_buffer,
        file_name=f"Lote_IA_Nemotron_{data_atual}.zip",
        mime="application/zip",
        type="primary"
    )

st.caption("Modo Exclusivo com Nemotron Nano 12B 2 VL (free) via OpenRouter • Teste de qualidade da IA")
