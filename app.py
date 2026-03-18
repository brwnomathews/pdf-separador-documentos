import streamlit as st
import fitz  # PyMuPDF
import google.generativeai as genai
import json
import io
import zipfile
from collections import defaultdict

# ==============================================================================
# CONFIGURAÇÃO DA PÁGINA E DA IA
# ==============================================================================
st.set_page_config(page_title="REFRAMINAS AI", page_icon="📄", layout="centered")

# Tenta carregar a chave da API das variáveis de ambiente (Secrets do Streamlit)
try:
    API_KEY = st.secrets["GEMINI_API_KEY"]
    genai.configure(api_key=API_KEY)
except Exception as e:
    st.error("⚠️ Chave da API do Gemini não encontrada. Configure os 'Secrets' no Streamlit Cloud.")
    st.stop()

# Configuração do modelo para forçar a resposta em JSON
generation_config = {"response_mime_type": "application/json"}
model = genai.GenerativeModel('gemini-1.5-flash', generation_config=generation_config)

# ==============================================================================
# REGRAS DE NEGÓCIO (Páginas Esperadas)
# ==============================================================================
EXPECTED_PAGES = {
    "CONTRATO": 2, "FICHA_REGISTRO": 2, "ORDEM_SERVICO": 3, "NI": 2, "FICHA_EPI": 2,
    "NR01": 2, "NR06": 2, "NR12": 2, "NR18": 2, "NR26": 2, "NR33": 2, "NR34": 2, "NR35": 2,
    "IT": 1, "LISTA_PRESENCA": 1, "VALE_TRANSPORTE": 1, "PPAE": 1, "DESCONHECIDO": 1
}

# ==============================================================================
# INTERFACE DO UTILIZADOR
# ==============================================================================
st.title("🏭 REFRAMINAS AI")
st.markdown("### Processamento Admissional Inteligente")
st.markdown("O sistema analisa visualmente os ficheiros e separa-os por colaborador utilizando a Inteligência Artificial do Google Gemini.")

arquivos_upados = st.file_uploader("Arraste ou selecione os ficheiros PDF", type=["pdf"], accept_multiple_files=True)

if st.button("Processar Documentos", type="primary"):
    if not arquivos_upados:
        st.warning("Por favor, selecione pelo menos um ficheiro PDF.")
        st.stop()

    # Variáveis globais para armazenar os PDFs gerados e os logs de erro
    arquivos_para_zip = {}
    log_divergencias = "RELATÓRIO DE DIVERGÊNCIAS E EXCLUSÕES\n=========================================\n\n"
    houve_divergencias = False

    barra_progresso = st.progress(0)
    status_texto = st.empty()

    for idx_arq, arquivo in enumerate(arquivos_upados):
        status_texto.text(f"A ler o ficheiro: {arquivo.name}...")
        
        # 1. Carregar o PDF em memória utilizando o PyMuPDF
        pdf_bytes = arquivo.read()
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        total_paginas = len(doc)
        
        todas_paginas_analisadas = []

        # 2. Análise Visual (IA) de cada página individual
        for num_pagina in range(total_paginas):
            status_texto.text(f"A analisar {arquivo.name}: Página {num_pagina + 1} de {total_paginas} (IA em ação...)")
            
            pagina = doc.load_page(num_pagina)
            # Força a rotação visual a zeros antes de capturar a imagem
            pagina.set_rotation(0) 
            
            # Converte a página para uma imagem de alta qualidade
            pix = pagina.get_pixmap(matrix=fitz.Matrix(2, 2))
            img_bytes = pix.tobytes("jpeg")
            
            prompt = """
            Atuas como assistente de Recursos Humanos especialista em admissões. Analisa a imagem deste documento digitalizado e devolve APENAS um JSON estrito com as seguintes chaves:
            {
                "nome_colaborador": "O nome completo do funcionário a que o documento pertence. Se não encontrares, devolve null. Se houver uma TAG com 'XXXXX', extrai o nome exato antes do primeiro traço.",
                "tipo_documento": "Classifica o documento EXATAMENTE num destes tipos: CONTRATO, FICHA_REGISTRO, ORDEM_SERVICO, NI, FICHA_EPI, NR01, NR06, NR12, NR18, NR26, NR33, NR34, NR35, IT, LISTA_PRESENCA, VALE_TRANSPORTE, PPAE, DESCONHECIDO",
                "is_tag": booleano (true ou false). Coloca true APENAS se encontrares uma zona de fecho delimitada por 'XXXXX'. Caso contrário, é false.,
                "texto_tag": "O texto exato contido entre os 'XXXXX' (ou null se não for tag)"
            }
            """
            
            # Envia a imagem para a IA analisar
            imagem_ia = {"mime_type": "image/jpeg", "data": img_bytes}
            try:
                resposta = model.generate_content([prompt, imagem_ia])
                dados = json.loads(resposta.text)
                
                # Normaliza o nome do colaborador
                nome_dono = str(dados.get("nome_colaborador") or "DESCONHECIDO").strip().upper()
                tipo_doc = dados.get("tipo_documento", "DESCONHECIDO")
                
                todas_paginas_analisadas.append({
                    "index": num_pagina,
                    "nome_dono": nome_dono,
                    "tipo_documento": tipo_doc,
                    "is_tag": dados.get("is_tag", False),
                    "texto_tag": dados.get("texto_tag", ""),
                    "usada": False
                })
            except Exception as e:
                log_divergencias += f"[ERRO IA] Ficheiro {arquivo.name} | Página {num_pagina + 1}: Falha ao processar com a IA.\n"
                houve_divergencias = True

        # 3. Agrupar as páginas por colaborador
        paginas_por_colaborador = defaultdict(list)
        for p in todas_paginas_analisadas:
            paginas_por_colaborador[p["nome_dono"]].append(p)

        # 4. Aplicar a lógica de montagem dos Documentos
        status_texto.text(f"A montar ficheiros e a validar regras para {arquivo.name}...")
        
        for nome, paginas in paginas_por_colaborador.items():
            if nome == "DESCONHECIDO":
                continue # Ignora páginas onde a IA não conseguiu determinar o dono

            # Extrai apenas as páginas classificadas como TAG
            paginas_tag = [p for p in paginas if p["is_tag"]]
            
            # Ordenação de Prioridade (1 Página primeiro)
            paginas_tag.sort(key=lambda p: EXPECTED_PAGES.get(p["tipo_documento"], 1))

            for p_tag in paginas_tag:
                tipo_doc = p_tag["tipo_documento"]
                esperado = EXPECTED_PAGES.get(tipo_doc, 1)
                
                if p_tag["texto_tag"]:
                    titulo_base = str(p_tag["texto_tag"]).strip().upper()
                else:
                    titulo_base = f"{nome} - {tipo_doc}"

                # Filtra páginas normais (não TAG) e não usadas, do mesmo tipo e do mesmo colaborador
                candidatas = [p for p in paginas if not p["is_tag"] and not p["usada"] and p["tipo_documento"] == tipo_doc]

                paginas_do_doc = []
                
                if esperado == 1:
                    paginas_do_doc = [p_tag]
                    p_tag["usada"] = True
                else:
                    necessarias = esperado - 1
                    if len(candidatas) >= necessarias:
                        # Seleciona a quantidade necessária e adiciona a TAG no final
                        paginas_selecionadas = candidatas[:necessarias]
                        paginas_do_doc = paginas_selecionadas + [p_tag]
                        
                        # Marca como usadas
                        for ps in paginas_selecionadas:
                            ps["usada"] = True
                        p_tag["usada"] = True
                    else:
                        # Divergência! Faltam páginas
                        msg_erro = f"[EXCLUÍDO] Ficheiro: {arquivo.name} | Colaborador: {nome} | Documento: {titulo_base} | Motivo: IA encontrou apenas {len(candidatas) + 1} de {esperado} páginas exigidas."
                        log_divergencias += msg_erro + "\n"
                        houve_divergencias = True
                        continue

                # ==========================================
                # RECORTAR E GERAR O NOVO PDF
                # ==========================================
                if paginas_do_doc:
                    novo_pdf = fitz.open()
                    for p_obj in paginas_do_doc:
                        # Extrai a página do documento original em memória
                        novo_pdf.insert_pdf(doc, from_page=p_obj["index"], to_page=p_obj["index"])
                    
                    pdf_final_bytes = novo_pdf.write()
                    
                    titulo_final = f"{titulo_base}.pdf"
                    contador = 1
                    while titulo_final in arquivos_para_zip:
                        titulo_final = f"{titulo_base}({contador}).pdf"
                        contador += 1
                        
                    arquivos_para_zip[titulo_final] = pdf_final_bytes

        # Atualiza a barra de progresso
        barra_progresso.progress((idx_arq + 1) / len(arquivos_upados))

    status_texto.text("A gerar o ficheiro ZIP final...")

    # ==============================================================================
    # CRIAÇÃO DO ZIP EM MEMÓRIA
    # ==============================================================================
    if arquivos_para_zip or houve_divergencias:
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
            for nome_arquivo, data in arquivos_para_zip.items():
                zip_file.writestr(nome_arquivo, data)
                
            if houve_divergencias:
                zip_file.writestr("log_divergencias.txt", log_divergencias.encode("utf-8"))
        
        # Oferece o botão de Download no Streamlit
        st.success("Processamento concluído com sucesso!")
        if houve_divergencias:
            st.warning("Atenção: Houve divergências. Consulte o 'log_divergencias.txt' dentro do ZIP.")
            
        st.download_button(
            label="📦 Descarregar Ficheiros Separados (ZIP)",
            data=zip_buffer.getvalue(),
            file_name="Processos_REFRAMINAS.zip",
            mime="application/zip",
            type="primary"
        )
    else:
        st.error("Nenhum ficheiro pôde ser gerado. Verifique a qualidade dos PDFs.")
