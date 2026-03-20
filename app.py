import streamlit as st
import fitz  # PyMuPDF
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
import json
import io
import zipfile
import time
from collections import defaultdict

# ==============================================================================
# CONFIGURAÇÃO DA PÁGINA E DA IA
# ==============================================================================
st.set_page_config(page_title="REFRAMINAS AI", page_icon="📄", layout="centered")

try:
    API_KEY = st.secrets["GEMINI_API_KEY"]
    genai.configure(api_key=API_KEY)
except Exception as e:
    st.error("⚠️ Chave da API do Gemini não encontrada. Configure os 'Secrets' no Streamlit Cloud.")
    st.stop()

# Configuração para forçar JSON e Desligar Filtros de Segurança
generation_config = {"response_mime_type": "application/json"}

safety_settings = {
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}

model = genai.GenerativeModel('gemini-2.5-pro', generation_config=generation_config)

# ==============================================================================
# REGRAS DE NEGÓCIO (Páginas Esperadas)
# ==============================================================================
EXPECTED_PAGES = {
    "CONTRATO": 2, "FICHA_REGISTRO": 2, "ORDEM_SERVICO": 3, "NI": 2, "FICHA_EPI": 2,
    "NR01": 2, "NR06": 2, "NR12": 2, "NR18": 2, "NR26": 2, "NR33": 2, "NR34": 2, "NR35": 2,
    "IT": 1, "LISTA_PRESENCA": 1, "VALE_TRANSPORTE": 1, "PPAE": 1, 
    "TERMO_RESPONSABILIDADE": 1, "TESTE_VEDACAO": 1, "DESCONHECIDO": 1
}

# ==============================================================================
# O SUPER PROMPT (O CÉREBRO VISUAL DA IA)
# ==============================================================================
SUPER_PROMPT_RH = """
Atuas como um assistente de Recursos Humanos especialista em análise de documentos admissionais.
Analisa a imagem desta página digitalizada e devolve APENAS um JSON válido.

REGRAS PARA CLASSIFICAR O "tipo_documento":
- CONTRATO: Título contém 'CONTRATO DE TRABALHO'. Pode ter a seção de 'TESTEMUNHAS' no final.
- FICHA_REGISTRO: Cabeçalho 'FICHA DE REGISTRO DE EMPREGADO' ou contém tabela de 'Férias' com palavra 'Gozadas'.
- ORDEM_SERVICO: Título 'Ordem de Serviço de Segurança e Saúde' ou 'ORDEM DE SERVIÇO HIGIENE, SEGURANÇA'. Possui listas de Direitos e Deveres.
- NI: Título 'FICHA DE EPIS' (com 'S' no final) e subtítulo 'FICHA DE FORNECIMENTO DE EQUIPAMENTO PROTEÇÃO INDIVIDUAL' (sem a palavra 'DE' antes de proteção).
- FICHA_EPI: Título 'FICHA DE EPI' (sem 'S') e subtítulo 'FICHA DE FORNECIMENTO DE EQUIPAMENTO DE PROTEÇÃO INDIVIDUAL' ou página composta por tabela com 'CA', 'DATA DEVOLUÇÃO', 'ASSINATURA RECEPTOR'.
- NR01, NR06, NR12, NR18, NR33, NR34, NR35: Certificados com a placa de sinalização amarela (losango) indicando o número da NR no canto, ou página de 'CONTEÚDO PROGRAMÁTICO' indicando a respectiva NR.
- IT: Título 'LISTA DE PRESENÇA DE TREINAMENTO' indicando 'Instrução de Trabalho'.
- VALE_TRANSPORTE: 'FORMULÁRIO DE OPÇÃO DO VALE-TRANSPORTE' com quadros SIM/NÃO.
- PPAE: 'PROGRAMA DE PREVENÇÃO PARA ÁLCOOL E ENTORPECENTES'.
- TERMO_RESPONSABILIDADE: Título 'TERMO DE RESPONSABILIDADE' com regras de hospedagem, álcool e drogas.
- TESTE_VEDACAO: 'FORMULÁRIO - ENSAIO DE VEDAÇÃO' com opções de Pêlos na face e acuidade de paladar.
- DESCONHECIDO: Se não se enquadrar em nenhum destes de forma clara.

REGRAS PARA "nome_colaborador":
Procura no documento por 'Nome do Trabalhador', 'Nome do Empregado', 'Nome:' ou lê diretamente do texto da TAG XXXXX. Devolve o nome completo em letras MAIÚSCULAS. Se não encontrares de todo, devolve null.

REGRAS PARA TAGS ("is_tag" e "texto_tag"):
- "is_tag" será true APENAS se a página for exclusivamente uma folha de rosto/fecho com um texto delimitado por 'XXXXX' (ex: XXXXX BRUNO CESAR - CONTRATO XXXXX). Não marques true se for um documento normal.
- "texto_tag" será esse texto exato, limpo dos XXXXX das pontas. Se não for tag, devolve null.

FORMATO DE RESPOSTA (JSON ESTRITO):
{
    "nome_colaborador": "...",
    "tipo_documento": "...",
    "is_tag": true ou false,
    "texto_tag": "..."
}
"""

# ==============================================================================
# INTERFACE DO UTILIZADOR
# ==============================================================================
st.title("🏭 REFRAMINAS AI")
st.markdown("### Processamento Admissional Inteligente (Modo Híbrido)")
st.markdown("Reconhecimento por TAGs ou Leitura Visual Automática com Proteção de Incompletos.")

arquivos_upados = st.file_uploader("Arraste ou selecione os ficheiros PDF", type=["pdf"], accept_multiple_files=True)

if st.button("Processar Documentos", type="primary"):
    if not arquivos_upados:
        st.warning("Por favor, selecione pelo menos um ficheiro PDF.")
        st.stop()

    arquivos_para_zip = {}
    log_divergencias = "RELATÓRIO DE DIVERGÊNCIAS E DOCUMENTOS INCOMPLETOS\n====================================================\n\n"
    houve_divergencias = False

    with st.status("A processar documentos de forma precisa...", expanded=True) as status_box:
        
        for idx_arq, arquivo in enumerate(arquivos_upados):
            pdf_bytes = arquivo.read()
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            total_paginas = len(doc)
            
            todas_paginas_analisadas = []

            # 1. LEITURA VISUAL PÁGINA A PÁGINA
            for num_pagina in range(total_paginas):
                status_box.update(label=f"A analisar {arquivo.name}: Página {num_pagina + 1} de {total_paginas} (A ler estrutura visual...)")
                
                pagina = doc.load_page(num_pagina)
                pagina.set_rotation(0) 
                
                pix = pagina.get_pixmap(matrix=fitz.Matrix(2, 2))
                img_bytes = pix.tobytes("jpeg")
                imagem_ia = {"mime_type": "image/jpeg", "data": img_bytes}
                
                tentativas = 3
                for tentativa in range(tentativas):
                    try:
                        resposta = model.generate_content([SUPER_PROMPT_RH, imagem_ia], safety_settings=safety_settings)
                        dados = json.loads(resposta.text)
                        
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
                        
                        time.sleep(4.2) # Proteção do Limite da Cota Gratuita
                        break 
                        
                    except Exception as e:
                        if tentativa < tentativas - 1:
                            time.sleep(5)
                        else:
                            log_divergencias += f"[ERRO IA] Ficheiro {arquivo.name} | Página {num_pagina + 1}: {str(e)}\n"
                            houve_divergencias = True

            # 2. AGRUPAMENTO POR COLABORADOR
            paginas_por_colaborador = defaultdict(list)
            for p in todas_paginas_analisadas:
                paginas_por_colaborador[p["nome_dono"]].append(p)

            status_box.update(label=f"A cruzar dados e a montar PDFs Híbridos para {arquivo.name}...")
            
            # 3. LÓGICA DE MONTAGEM HÍBRIDA (TAGS + CONTEÚDO VISUAL + INCOMPLETOS)
            for nome, paginas in paginas_por_colaborador.items():
                if nome == "DESCONHECIDO":
                    continue 

                # Processar primeiro os documentos de 1 página para evitar roubo de folhas
                tipos_encontrados = list(set([p["tipo_documento"] for p in paginas]))
                tipos_encontrados.sort(key=lambda t: EXPECTED_PAGES.get(t, 99))

                for tipo_doc in tipos_encontrados:
                    if tipo_doc == "DESCONHECIDO":
                        continue
                        
                    esperado = EXPECTED_PAGES.get(tipo_doc, 1)
                    pag_do_tipo = [p for p in paginas if p["tipo_documento"] == tipo_doc]
                    
                    tags_disponiveis = [p for p in pag_do_tipo if p["is_tag"] and not p["usada"]]
                    normais_disponiveis = [p for p in pag_do_tipo if not p["is_tag"] and not p["usada"]]

                    # Cenario A: Montagem orientada pela TAG (Se existir TAG)
                    for tag_p in tags_disponiveis:
                        if len(normais_disponiveis) >= (esperado - 1):
                            # Montagem COMPLETA baseada na TAG
                            paginas_selecionadas = normais_disponiveis[:esperado - 1]
                            normais_disponiveis = normais_disponiveis[esperado - 1:] # Remove as usadas da lista
                            
                            doc_pages = paginas_selecionadas + [tag_p]
                            titulo_base = str(tag_p["texto_tag"]).strip().upper() if tag_p["texto_tag"] else f"{nome} - {tipo_doc}"
                            
                        else:
                            # Montagem INCOMPLETA (Faltam páginas normais para esta TAG)
                            doc_pages = normais_disponiveis + [tag_p]
                            normais_disponiveis = [] 
                            titulo_puro = str(tag_p["texto_tag"]).strip().upper() if tag_p["texto_tag"] else f"{nome} - {tipo_doc}"
                            titulo_base = f"INCOMPLETO - {titulo_puro}"
                            
                            log_divergencias += f"[AVISO] Foi gerado o ficheiro '{titulo_base}.pdf' pois só foram encontradas {len(doc_pages)} das {esperado} páginas exigidas.\n"
                            houve_divergencias = True

                        # Marcar como usadas
                        for p_obj in doc_pages: p_obj["usada"] = True
                        
                        # Geração do ficheiro em memória
                        doc_pages.sort(key=lambda x: x["index"]) # Garante a ordem original das páginas
                        novo_pdf = fitz.open()
                        for p_obj in doc_pages:
                            novo_pdf.insert_pdf(doc, from_page=p_obj["index"], to_page=p_obj["index"])
                        
                        titulo_final = f"{titulo_base}.pdf"
                        contador = 1
                        while titulo_final in arquivos_para_zip:
                            titulo_final = f"{titulo_base} ({contador}).pdf"
                            contador += 1
                        arquivos_para_zip[titulo_final] = novo_pdf.write()

                    # Cenario B: Montagem HÍBRIDA Visual (Páginas normais que sobraram SEM TAG)
                    while len(normais_disponiveis) > 0:
                        if len(normais_disponiveis) >= esperado:
                            # Montagem COMPLETA gerada apenas pela Visão da IA
                            doc_pages = normais_disponiveis[:esperado]
                            normais_disponiveis = normais_disponiveis[esperado:]
                            titulo_base = f"{nome} - {tipo_doc}"
                        else:
                            # Montagem INCOMPLETA gerada pela Visão da IA
                            doc_pages = normais_disponiveis
                            normais_disponiveis = []
                            titulo_base = f"INCOMPLETO - {nome} - {tipo_doc}"
                            
                            log_divergencias += f"[AVISO] Sem TAG: Gerado '{titulo_base}.pdf' com {len(doc_pages)} das {esperado} páginas exigidas.\n"
                            houve_divergencias = True

                        for p_obj in doc_pages: p_obj["usada"] = True
                        
                        doc_pages.sort(key=lambda x: x["index"])
                        novo_pdf = fitz.open()
                        for p_obj in doc_pages:
                            novo_pdf.insert_pdf(doc, from_page=p_obj["index"], to_page=p_obj["index"])
                        
                        titulo_final = f"{titulo_base}.pdf"
                        contador = 1
                        while titulo_final in arquivos_para_zip:
                            titulo_final = f"{titulo_base} ({contador}).pdf"
                            contador += 1
                        arquivos_para_zip[titulo_final] = novo_pdf.write()

        status_box.update(label="Análise e separação concluídas com sucesso!", state="complete", expanded=False)

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
        
        st.success("Tudo pronto!")
        if houve_divergencias:
            st.warning("Atenção: Alguns documentos ficaram Incompletos. Consulte o 'log_divergencias.txt' dentro do ZIP para os localizar facilmente.")
            
        st.download_button(
            label="📦 Descarregar Ficheiros Separados (ZIP)",
            data=zip_buffer.getvalue(),
            file_name="Processos_REFRAMINAS.zip",
            mime="application/zip",
            type="primary"
        )
    else:
        st.error("Nenhum ficheiro pôde ser gerado. Verifique a qualidade dos PDFs.")
