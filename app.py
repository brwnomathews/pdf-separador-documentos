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
# FUNÇÃO DE EXTRAÇÃO (Dupla Verificação + Rotação 360º + OCR)
# ==============================================================================
def extrair_tag_pagina(pagina_pdf):
    # Padrão blindado para OCR: Aceita "XXXXX" com espaços sujos, captura o nome, a 2ª TAG e os números
    padrao = r'[xX][\sxX]{3,}[xX]\s*(.*?)\s*[xX][\sxX]{3,}[xX].*?P[aá]g(?:ina)?\s*(\d+)\s*(?:de|/|d)\s*(\d+)'
    
    def formatar_sucesso(m, metodo):
        titulo_arquivo = m.group(1).strip()
        if not titulo_arquivo.lower().endswith('.pdf'):
            titulo_arquivo += '.pdf'
        return {
            "sucesso": True,
            "titulo": titulo_arquivo,
            "pag_atual": int(m.group(2)),
            "pag_total": int(m.group(3)),
            "metodo": metodo
        }

    # 1ª TENTATIVA: Texto Nativo (Rápido)
    texto_nativo = re.sub(r'\s+', ' ', pagina_pdf.get_text())
    match_nativo = re.search(padrao, texto_nativo, re.IGNORECASE)
    if match_nativo:
        return formatar_sucesso(match_nativo, "Texto Nativo")

    # 2ª TENTATIVA: OCR com Roleta 360º (Para imagens, scans e páginas tortas)
    # matriz 3x3 para altíssima resolução e alpha=False para garantir fundo branco
    pix = pagina_pdf.get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False)
    img_original = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    
    textos_lidos_debug = []
    angulos = [0, 90, 180, 270]
    
    for angulo in angulos:
        img = img_original if angulo == 0 else img_original.rotate(angulo, expand=True, fillcolor="white")
        
        texto_ocr = pytesseract.image_to_string(img, lang='por')
        texto_ocr_limpo = re.sub(r'\s+', ' ', texto_ocr) # Acha as quebras de linha
        
        match_ocr = re.search(padrao, texto_ocr_limpo, re.IGNORECASE)
        if match_ocr:
            return formatar_sucesso(match_ocr, f"OCR ({angulo}º)")
            
        # Se falhou nesta rotação, guarda uma amostra do que foi lido para o log
        amostra = texto_ocr_limpo[:150].strip()
        if amostra:
            textos_lidos_debug.append(f"[{angulo}º: {amostra}...]")
        else:
            textos_lidos_debug.append(f"[{angulo}º: IMAGEM ILEGÍVEL/VAZIA]")

    # Se falhou tudo (Nativo e as 4 rotações de OCR)
    debug_string = " | ".join(textos_lidos_debug)
    return {"sucesso": False, "debug": debug_string}

# ==============================================================================
# INTERFACE DO UTILIZADOR
# ==============================================================================
st.title("⚙️ REFRAMINAS Automático")
st.markdown("### Processamento Deterministico por TAG")
st.markdown("Montagem baseada na regra: `XXXXX Nome - Doc.pdf XXXXX Página Y de Z`")

arquivos_upados = st.file_uploader("Selecione os ficheiros PDF", type=["pdf"], accept_multiple_files=True)

if st.button("Processar Documentos", type="primary"):
    if not arquivos_upados:
        st.warning("Selecione pelo menos um ficheiro.")
        st.stop()

    arquivos_para_zip = {}
    log_divergencias = "RELATÓRIO DE DIVERGÊNCIAS (DEBUG)\n=================================\n\n"
    houve_divergencias = False

    with st.status("A iniciar varredura de páginas...", expanded=True) as status_box:
        
        for idx_arq, arquivo in enumerate(arquivos_upados):
            status_box.update(label=f"A ler: {arquivo.name}...")
            
            pdf_bytes = arquivo.read()
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            total_paginas = len(doc)
            
            documentos_em_construcao = defaultdict(lambda: {"total_esperado": 0, "paginas": {}})

            for num_pagina in range(total_paginas):
                status_box.update(label=f"A ler página {num_pagina + 1}/{total_paginas} (Verificação Dupla e Rotação)...")
                pagina = doc.load_page(num_pagina)
                
                dados = extrair_tag_pagina(pagina)
                
                if dados["sucesso"]:
                    titulo = dados["titulo"]
                    documentos_em_construcao[titulo]["total_esperado"] = dados["pag_total"]
                    documentos_em_construcao[titulo]["paginas"][dados["pag_atual"]] = num_pagina
                else:
                    texto_debug = dados.get('debug', '')
                    log_divergencias += f"[FALHA DE LEITURA] Ficheiro: {arquivo.name} | Página: {num_pagina + 1}\n"
                    log_divergencias += f"   Motivo: O script não encontrou a TAG.\n"
                    log_divergencias += f"   O que a máquina conseguiu ler (Amostras):\n   -> {texto_debug}\n\n"
                    houve_divergencias = True

            status_box.update(label=f"A montar PDFs finais para {arquivo.name}...")

            for titulo_doc, info in documentos_em_construcao.items():
                total_esperado = info["total_esperado"]
                paginas_encontradas = info["paginas"]
                
                if len(paginas_encontradas) == total_esperado:
                    novo_pdf = fitz.open()
                    
                    # Monta na ordem certa (1 a Z) mesmo que o scanner tenha lido fora de ordem
                    for ordem in range(1, total_esperado + 1):
                        if ordem in paginas_encontradas:
                            index_original = paginas_encontradas[ordem]
                            novo_pdf.insert_pdf(doc, from_page=index_original, to_page=index_original)
                    
                    pdf_final_bytes = novo_pdf.write()
                    
                    titulo_final = titulo_doc
                    contador = 1
                    while titulo_final in arquivos_para_zip:
                        titulo_final = titulo_doc.replace(".pdf", f"({contador}).pdf")
                        contador += 1
                        
                    arquivos_para_zip[titulo_final] = pdf_final_bytes
                else:
                    paginas_presentes = list(paginas_encontradas.keys())
                    msg_erro = f"[FALHA DE MONTAGEM] Documento: {titulo_doc}\n   Motivo: O rodapé pedia {total_esperado} páginas, mas apenas as páginas {paginas_presentes} foram encontradas/lidas com sucesso.\n\n"
                    log_divergencias += msg_erro
                    houve_divergencias = True

        status_box.update(label="Processamento finalizado com sucesso!", state="complete", expanded=False)

    if arquivos_para_zip or houve_divergencias:
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
            for nome_arquivo, data in arquivos_para_zip.items():
                zip_file.writestr(nome_arquivo, data)
            if houve_divergencias:
                zip_file.writestr("log_divergencias.txt", log_divergencias.encode("utf-8"))
        
        st.success("Tudo pronto! Ficheiros extraídos rigorosamente.")
        if houve_divergencias:
            st.warning("Atenção: Houve divergências. Consulte o relatório dentro do ZIP para ver o diagnóstico exato.")
            
        st.download_button(
            label="📦 Descarregar Documentos Montados (ZIP)",
            data=zip_buffer.getvalue(),
            file_name="Processos_REFRAMINAS_TAG_OCR.zip",
            mime="application/zip",
            type="primary"
        )
    else:
        st.error("Nenhum ficheiro pôde ser gerado. Verifique o relatório de divergências (se aplicável).")
