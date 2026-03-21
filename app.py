import streamlit as st
import fitz  # PyMuPDF
import pytesseract
from PIL import Image
import re
import io
import zipfile
from collections import defaultdict

st.set_page_config(page_title="REFRAMINAS Simplificado", page_icon="⚡", layout="centered")

# ==============================================================================
# FUNÇÃO DE EXTRAÇÃO (Apenas TAG + Rotação 360º)
# ==============================================================================
def extrair_tag_pagina(pagina_pdf):
    # Procura estritamente por XXXXX [Qualquer Coisa] XXXXX
    padrao_tag = r'[xX][\sxX]{3,}[xX]\s*(.*?)\s*[xX][\sxX]{3,}[xX]'
    
    # 1ª TENTATIVA: Texto Nativo
    texto_nativo = re.sub(r'\s+', ' ', pagina_pdf.get_text())
    match_nativo = re.search(padrao_tag, texto_nativo, re.IGNORECASE)
    
    if match_nativo:
        tag = match_nativo.group(1).strip()
        if not tag.lower().endswith('.pdf'): tag += '.pdf'
        return {"sucesso": True, "tag": tag, "metodo": "Texto Nativo"}

    # 2ª TENTATIVA: OCR com Rotação 360º
    pix = pagina_pdf.get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False)
    img_original = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    
    textos_lidos_debug = []
    angulos = [0, 90, 180, 270]
    
    for angulo in angulos:
        img = img_original if angulo == 0 else img_original.rotate(angulo, expand=True, fillcolor="white")
        
        # --psm 11 ajuda a ler textos espalhados ou soltos nas margens
        texto_ocr = pytesseract.image_to_string(img, lang='por', config='--psm 11')
        texto_ocr_limpo = re.sub(r'\s+', ' ', texto_ocr)
        
        # Guarda amostra para o log
        amostra = texto_ocr_limpo[:100].strip()
        if amostra:
            textos_lidos_debug.append(f"[{angulo}º: {amostra}...]")
            
        match_ocr = re.search(padrao_tag, texto_ocr_limpo, re.IGNORECASE)
        
        if match_ocr:
            tag = match_ocr.group(1).strip()
            
            # Correção rápida para o efeito espelho (caso o scanner leia de trás para a frente)
            if tag.startswith("VAIS") or tag.startswith("VAI"):
                tag = tag[::-1]
                
            if not tag.lower().endswith('.pdf'): tag += '.pdf'
            return {"sucesso": True, "tag": tag, "metodo": f"OCR ({angulo}º)"}

    # Se falhou, verifica se é uma página em branco para não poluir o log desnecessariamente
    if not any(t for t in textos_lidos_debug if t and "ILEGÍVEL" not in t.upper()):
         return {"sucesso": False, "debug": "PÁGINA EM BRANCO OU ILEGÍVEL", "is_blank": True}

    debug_string = " | ".join(textos_lidos_debug)
    return {"sucesso": False, "debug": debug_string, "is_blank": False}

# ==============================================================================
# INTERFACE DO UTILIZADOR
# ==============================================================================
st.title("⚡ REFRAMINAS Simplificado")
st.markdown("### Agrupamento Direto por TAG")
st.markdown("Agrupa todas as páginas que possuam a mesma marcação `XXXXX Nome do Arquivo XXXXX`.")

arquivos_upados = st.file_uploader("Selecione os ficheiros PDF", type=["pdf"], accept_multiple_files=True)

if st.button("Processar Documentos", type="primary"):
    if not arquivos_upados:
        st.warning("Selecione pelo menos um ficheiro.")
        st.stop()

    arquivos_para_zip = {}
    log_divergencias = "RELATÓRIO DE PÁGINAS SEM TAG\n============================\n\n"
    houve_divergencias = False

    with st.status("A iniciar varredura e agrupamento...", expanded=True) as status_box:
        
        for arquivo in arquivos_upados:
            status_box.update(label=f"A ler: {arquivo.name}...")
            
            pdf_bytes = arquivo.read()
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            total_paginas = len(doc)
            
            # Dicionário simples: { "NomeDaTag.pdf": [0, 1, 4, 5] }
            grupos_de_paginas = defaultdict(list)

            for num_pagina in range(total_paginas):
                status_box.update(label=f"A analisar página {num_pagina + 1}/{total_paginas}...")
                pagina = doc.load_page(num_pagina)
                
                dados = extrair_tag_pagina(pagina)
                
                if dados["sucesso"]:
                    tag_arquivo = dados["tag"]
                    grupos_de_paginas[tag_arquivo].append(num_pagina)
                else:
                    if not dados.get("is_blank", False):
                        texto_debug = dados.get('debug', '')
                        log_divergencias += f"[SEM TAG] Ficheiro: {arquivo.name} | Página: {num_pagina + 1}\n"
                        log_divergencias += f"   Amostra do que foi lido: {texto_debug}\n\n"
                        houve_divergencias = True

            status_box.update(label=f"A gerar PDFs agrupados para {arquivo.name}...")

            # Montagem dos PDFs finais baseada nos grupos criados
            for tag_doc, indices_paginas in grupos_de_paginas.items():
                novo_pdf = fitz.open()
                
                for idx in indices_paginas:
                    novo_pdf.insert_pdf(doc, from_page=idx, to_page=idx)
                
                pdf_final_bytes = novo_pdf.write()
                
                # Evita sobrepor ficheiros com o mesmo nome se enviar vários PDFs originais
                titulo_final = tag_doc
                contador = 1
                while titulo_final in arquivos_para_zip:
                    titulo_final = tag_doc.replace(".pdf", f"({contador}).pdf")
                    contador += 1
                    
                arquivos_para_zip[titulo_final] = pdf_final_bytes

        status_box.update(label="Processamento finalizado!", state="complete", expanded=False)

    if arquivos_para_zip:
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
            for nome_arquivo, data in arquivos_para_zip.items():
                zip_file.writestr(nome_arquivo, data)
            if houve_divergencias:
                zip_file.writestr("log_paginas_sem_tag.txt", log_divergencias.encode("utf-8"))
        
        st.success("Tudo agrupado com sucesso!")
        if houve_divergencias:
            st.warning("Atenção: Algumas páginas não possuíam TAG ou estavam ilegíveis. Consulte o log no ZIP.")
            
        st.download_button(
            label="📦 Descarregar Documentos Agrupados (ZIP)",
            data=zip_buffer.getvalue(),
            file_name="Processos_REFRAMINAS_Agrupados.zip",
            mime="application/zip",
            type="primary"
        )
    else:
        st.error("Nenhuma TAG foi encontrada nos ficheiros. Verifique se as marcações existem.")
