import streamlit as st
import fitz  # PyMuPDF
import pytesseract
from PIL import Image
import re
import io
import zipfile
from collections import defaultdict

st.set_page_config(page_title="REFRAMINAS Automático", page_icon="⚙️", layout="centered")

# ==============================================================================
# FUNÇÃO DE EXTRAÇÃO DA TAG (Híbrida: Texto Nativo ou OCR)
# ==============================================================================
def extrair_tag_pagina(pagina_pdf):
    # Tenta extração de texto nativo primeiro (Super Rápido)
    texto = pagina_pdf.get_text()
    
    # Se não houver texto nativo (é uma imagem/scan), aplica OCR
    if len(texto.strip()) < 10:
        pix = pagina_pdf.get_pixmap(matrix=fitz.Matrix(2, 2))
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        texto = pytesseract.image_to_string(img, lang='por')
    
    # RegEx para capturar: XXXXX [NOME DO ARQUIVO.pdf] XXXXX Página [Y] de [Z]
    padrao = r'XXXXX\s*(.*?\.pdf)\s*XXXXX.*?P[aá]gina\s*(\d+)\s*de\s*(\d+)'
    match = re.search(padrao, texto, re.IGNORECASE | re.DOTALL)
    
    if match:
        titulo_arquivo = match.group(1).strip()
        # Se o OCR comer o ".pdf", garantimos que ele existe
        if not titulo_arquivo.lower().endswith('.pdf'):
            titulo_arquivo += '.pdf'
            
        return {
            "sucesso": True,
            "titulo": titulo_arquivo,
            "pag_atual": int(match.group(2)),
            "pag_total": int(match.group(3))
        }
    return {"sucesso": False}

# ==============================================================================
# INTERFACE DO UTILIZADOR
# ==============================================================================
st.title("⚙️ REFRAMINAS Automático")
st.markdown("### Processamento Rápido por TAG")
st.markdown("Montagem determinística baseada na regra `XXXXX Titulo.pdf XXXXX Página Y de Z`.")

arquivos_upados = st.file_uploader("Selecione os ficheiros PDF", type=["pdf"], accept_multiple_files=True)

if st.button("Processar Documentos", type="primary"):
    if not arquivos_upados:
        st.warning("Selecione pelo menos um ficheiro.")
        st.stop()

    arquivos_para_zip = {}
    log_divergencias = "RELATÓRIO DE DIVERGÊNCIAS\n=========================\n\n"
    houve_divergencias = False

    with st.status("A iniciar processamento e montagem...", expanded=True) as status_box:
        
        for idx_arq, arquivo in enumerate(arquivos_upados):
            status_box.update(label=f"A ler: {arquivo.name}...")
            
            pdf_bytes = arquivo.read()
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            total_paginas = len(doc)
            
            # Dicionário: { "Titulo_do_PDF.pdf": {"total_esperado": Z, "paginas": { Y: index_no_pdf_original }} }
            documentos_em_construcao = defaultdict(lambda: {"total_esperado": 0, "paginas": {}})

            # 1. VARREDURA DAS PÁGINAS
            for num_pagina in range(total_paginas):
                status_box.update(label=f"A procurar TAG na página {num_pagina + 1}/{total_paginas}...")
                pagina = doc.load_page(num_pagina)
                pagina.set_rotation(0)
                
                dados = extrair_tag_pagina(pagina)
                
                if dados["sucesso"]:
                    titulo = dados["titulo"]
                    documentos_em_construcao[titulo]["total_esperado"] = dados["pag_total"]
                    # Guarda o index da página mapeado à sua ordem correta (pag_atual)
                    documentos_em_construcao[titulo]["paginas"][dados["pag_atual"]] = num_pagina
                else:
                    log_divergencias += f"[AVISO] Ficheiro original {arquivo.name} | Página {num_pagina + 1}: Nenhuma TAG válida identificada. Página ignorada.\n"
                    houve_divergencias = True

            status_box.update(label=f"A validar e a fechar documentos de {arquivo.name}...")

            # 2. MONTAGEM DOS PDFs FINAIS
            for titulo_doc, info in documentos_em_construcao.items():
                total_esperado = info["total_esperado"]
                paginas_encontradas = info["paginas"]
                
                # Verifica se encontrou todas as páginas de 1 até Z
                if len(paginas_encontradas) == total_esperado:
                    novo_pdf = fitz.open()
                    
                    # Insere as páginas na ordem exata (1 a Z)
                    for ordem in range(1, total_esperado + 1):
                        if ordem in paginas_encontradas:
                            index_original = paginas_encontradas[ordem]
                            novo_pdf.insert_pdf(doc, from_page=index_original, to_page=index_original)
                    
                    pdf_final_bytes = novo_pdf.write()
                    
                    # Evitar sobrescrever ficheiros com o mesmo nome exato
                    titulo_final = titulo_doc
                    contador = 1
                    while titulo_final in arquivos_para_zip:
                        titulo_final = titulo_doc.replace(".pdf", f"({contador}).pdf")
                        contador += 1
                        
                    arquivos_para_zip[titulo_final] = pdf_final_bytes
                else:
                    # Faltaram páginas para fechar este documento
                    paginas_presentes = list(paginas_encontradas.keys())
                    msg_erro = f"[FALHA DE MONTAGEM] Documento: {titulo_doc} | Era esperado {total_esperado} páginas, mas apenas as páginas {paginas_presentes} foram encontradas."
                    log_divergencias += msg_erro + "\n"
                    houve_divergencias = True

        status_box.update(label="Processamento finalizado!", state="complete", expanded=False)

    # 3. GERAÇÃO DO ZIP
    if arquivos_para_zip or houve_divergencias:
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
            for nome_arquivo, data in arquivos_para_zip.items():
                zip_file.writestr(nome_arquivo, data)
            if houve_divergencias:
                zip_file.writestr("log_divergencias.txt", log_divergencias.encode("utf-8"))
        
        st.success("Tudo pronto! Ficheiros extraídos rigorosamente pela regra da TAG.")
        if houve_divergencias:
            st.warning("Atenção: Houve divergências (Páginas sem TAG ou documentos incompletos).")
            
        st.download_button(
            label="📦 Descarregar Documentos Montados (ZIP)",
            data=zip_buffer.getvalue(),
            file_name="Processos_REFRAMINAS_TAG.zip",
            mime="application/zip",
            type="primary"
        )
    else:
        st.error("Nenhum ficheiro pôde ser gerado. Verifique se as TAGs estão legíveis.")
