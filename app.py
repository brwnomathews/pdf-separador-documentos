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
# FUNÇÃO DE EXTRAÇÃO DA TAG (Limpeza de Quebras de Linha + Roleta 360º)
# ==============================================================================
def extrair_tag_pagina(pagina_pdf):
    # Padrão blindado: Aceita XXXXX ou X X X X X, ignora quebras de linha e acha os números
    padrao = r'X[\sX]{3,}X\s*(.*?)\s*X[\sX]{3,}X.*?P[aá]gina\s*(\d+)\s*de\s*(\d+)'
    
    # 1ª TENTATIVA: Texto Nativo
    # Transforma todo o texto da página numa linha única (remove quebras de linha invisíveis)
    texto_nativo = re.sub(r'\s+', ' ', pagina_pdf.get_text())
    
    def formatar_sucesso(m):
        titulo_arquivo = m.group(1).strip()
        if not titulo_arquivo.lower().endswith('.pdf'):
            titulo_arquivo += '.pdf'
        return {
            "sucesso": True,
            "titulo": titulo_arquivo,
            "pag_atual": int(m.group(2)),
            "pag_total": int(m.group(3))
        }

    match = re.search(padrao, texto_nativo, re.IGNORECASE)
    if match:
        return formatar_sucesso(match)
        
    # 2ª TENTATIVA: OCR com Roleta 360 Graus
    pix = pagina_pdf.get_pixmap(matrix=fitz.Matrix(2.5, 2.5))
    img_original = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    
    angulos = [0, 90, 180, 270]
    for angulo in angulos:
        img = img_original if angulo == 0 else img_original.rotate(angulo, expand=True)
        texto_ocr = pytesseract.image_to_string(img, lang='por')
        texto_ocr_limpo = re.sub(r'\s+', ' ', texto_ocr)
        
        match = re.search(padrao, texto_ocr_limpo, re.IGNORECASE)
        if match:
            return formatar_sucesso(match)
            
    # Se falhar totalmente, devolve os primeiros 100 caracteres que conseguiu ler para depuração
    return {"sucesso": False, "debug": texto_nativo[:100]}

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
            status_box.update(label=f"A preparar: {arquivo.name}...")
            
            pdf_bytes = arquivo.read()
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            total_paginas = len(doc)
            
            documentos_em_construcao = defaultdict(lambda: {"total_esperado": 0, "paginas": {}})

            for num_pagina in range(total_paginas):
                status_box.update(label=f"A ler página {num_pagina + 1}/{total_paginas} (Verificação Dupla)...")
                pagina = doc.load_page(num_pagina)
                
                # REMOVIDO: pagina.set_rotation(0) -> Agora o script respeita a rotação nativa do PDF!
                
                dados = extrair_tag_pagina(pagina)
                
                if dados["sucesso"]:
                    titulo = dados["titulo"]
                    documentos_em_construcao[titulo]["total_esperado"] = dados["pag_total"]
                    documentos_em_construcao[titulo]["paginas"][dados["pag_atual"]] = num_pagina
                else:
                    texto_debug = dados.get('debug', '').strip()
                    log_divergencias += f"[AVISO] Ficheiro {arquivo.name} | Página {num_pagina + 1}: Nenhuma TAG válida. O que o script leu: '{texto_debug}'...\n"
                    houve_divergencias = True

            status_box.update(label=f"A validar e a fechar documentos de {arquivo.name}...")

            for titulo_doc, info in documentos_em_construcao.items():
                total_esperado = info["total_esperado"]
                paginas_encontradas = info["paginas"]
                
                if len(paginas_encontradas) == total_esperado:
                    novo_pdf = fitz.open()
                    
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
                    msg_erro = f"[FALHA DE MONTAGEM] Documento: {titulo_doc} | Era esperado {total_esperado} páginas, mas apenas as páginas {paginas_presentes} foram encontradas."
                    log_divergencias += msg_erro + "\n"
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
            st.warning("Atenção: Houve divergências. Consulte o relatório dentro do ZIP para ver o que o script leu de errado nas páginas.")
            
        st.download_button(
            label="📦 Descarregar Documentos Montados (ZIP)",
            data=zip_buffer.getvalue(),
            file_name="Processos_REFRAMINAS_TAG.zip",
            mime="application/zip",
            type="primary"
        )
    else:
        st.error("Nenhum ficheiro pôde ser gerado. Verifique o relatório de divergências (se aplicável).")
