import streamlit as st
import google.generativeai as genai
import os
import re
import time
import tempfile
import pandas as pd
from datetime import datetime, timedelta
import database as db
import extra_streamlit_components as stx
from io import BytesIO

# --- IMPORTAÇÕES PARA O PDF ---
from xhtml2pdf import pisa
import markdown

# --- CONFIGURAÇÃO ---
st.set_page_config(page_title="Urbano", layout="wide", page_icon="🏢")

# API KEY
try:
    if "GOOGLE_API_KEY" in st.secrets:
        genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
    else:
        pass
except:
    st.error("Configure a API Key.")
    st.stop()

db.init_db()

# --- ESTRUTURA DE DOCUMENTOS ---
DOC_STRUCTURE = {
    "1. Habilitacao Juridica": ["Contrato Social", "CNPJ", "Documentos Sócios"],
    "2. Habilitacao Fiscal": ["Federal", "Estadual", "Municipal", "FGTS", "Trabalhista"],
    "3. Qualificacao Tecnica": ["Atestados Operacionais", "Atestados Profissionais", "CAT"],
    "4. Habilitacao Financeira": ["Balanco Patrimonial", "Indices Financeiros", "Certidao Falencia"]
}

# --- FUNÇÃO GERADORA DE PDF ---
def convert_to_pdf(source_md):
    """Converte Markdown para PDF com estilo profissional."""
    html_text = markdown.markdown(source_md)
    styles = """
    <style>
        @page { size: A4; margin: 2cm; }
        body { font-family: Helvetica, sans-serif; font-size: 11px; line-height: 1.5; color: #333; text-align: justify; }
        h1 { color: #003366; font-size: 16px; border-bottom: 1px solid #ddd; padding-bottom: 5px; margin-top: 20px; }
        h2 { color: #005599; font-size: 14px; margin-top: 15px; margin-bottom: 5px; }
        h3 { color: #0077CC; font-size: 12px; margin-top: 10px; }
        p { margin-bottom: 8px; }
        strong { color: #000; font-weight: bold; }
        .chat-section { margin-top: 30px; border-top: 2px solid #eee; padding-top: 20px; }
        .chat-q { font-weight: bold; color: #444; margin-top: 10px; }
        .chat-a { color: #555; font-style: italic; margin-left: 15px; margin-bottom: 10px; }
    </style>
    """
    full_html = f"<html><head>{styles}</head><body>{html_text}</body></html>"
    result_file = BytesIO()
    pisa_status = pisa.CreatePDF(full_html, dest=result_file)
    if pisa_status.err: return None
    return result_file.getvalue()

# --- HELPER: EXTRAIR TÍTULO (PADRÃO 5 PALAVRAS) ---
def extract_title(text):
    """
    Extrai título no padrão estrito:
    "Edital" + "Órgão" + "Objeto (max 5 palavras)" + "Data da Sessão"
    """
    try:
        # 1. Extração do Órgão (Baseado na Pergunta 1)
        orgao = "Órgão Indefinido"
        # Tenta pegar a resposta da pergunta 1
        match_orgao = re.search(r"(?:1\.|órgão).*?[:\-\?]\s*(.*?)(?:\n|2\.|Qual|$)", text, re.IGNORECASE)
        if match_orgao: 
            orgao = match_orgao.group(1).replace("*", "").strip()

        # 2. Extração do Objeto (Baseado na Pergunta 2 - Max 5 Palavras)
        objeto_resumo = "Objeto Geral"
        match_objeto = re.search(r"(?:2\.|objeto).*?[:\-\?]\s*(.*?)(?:\n|3\.|Qual|$)", text, re.IGNORECASE | re.DOTALL)
        
        if match_objeto:
            raw_obj = match_objeto.group(1).replace("*", "").strip()
            # Lógica das 5 palavras
            palavras = raw_obj.split()
            if len(palavras) > 5:
                objeto_resumo = " ".join(palavras[:5]) + "..."
            else:
                objeto_resumo = " ".join(palavras)

        # 3. Extração da Data da Sessão (Baseado na Pergunta 5)
        data_sessao = "Data a definir"
        match_data = re.search(r"(?:5\.|data).*?(\d{2}/\d{2}/\d{4})", text, re.IGNORECASE)
        if match_data:
            data_sessao = match_data.group(1)

        # Formatação Final Solicitada
        return f"Edital {orgao} | {objeto_resumo} | Sessão: {data_sessao}"
    except:
        return f"Edital {datetime.now().strftime('%d/%m/%Y')} - Processado"

# --- SESSÃO & COOKIES ---
cookie_manager = stx.CookieManager(key="urbano_cookies")
if 'user' not in st.session_state: st.session_state.user = None

if not st.session_state.user:
    time.sleep(0.1)
    c = cookie_manager.get("urbano_auth")
    if c:
        try:
            u, t = c.split('|')
            if db.check_session_valid(u, t):
                raw = db.get_user_by_username(u)
                if raw:
                    st.session_state.user = {
                        "username": raw.get('username'), "name": raw.get('name'),
                        "role": raw.get('role'), "plan": raw.get('plan_type', 'free'),
                        "credits": raw.get('credits_used', 0), "token": raw.get('token')
                    }
                    st.rerun()
        except: pass

def logout():
    st.session_state.user = None
    cookie_manager.delete("urbano_auth")
    time.sleep(1)
    st.rerun()

# --- TELA DE LOGIN ---
if not st.session_state.user:
    c1, c2 = st.columns([1, 2])
    with c1:
        if os.path.exists("LOGO URBANO OFICIAL.png"): st.image("LOGO URBANO OFICIAL.png", width=150)
        else: st.title("🏢")
    with c2: st.title("Urbano - Inteligência em Licitações")
    
    t1, t2 = st.tabs(["Login", "Cadastro"])
    with t1:
        with st.form("f_login"):
            u = st.text_input("Usuário"); p = st.text_input("Senha", type="password")
            if st.form_submit_button("Entrar"):
                ok, d = db.login_user(u, p)
                if ok:
                    st.session_state.user = {
                        "username": d.get('username'), "name": d.get('name'),
                        "role": d.get('role'), "plan": d.get('plan_type', 'free'),
                        "credits": d.get('credits_used', 0), "token": d.get('token')
                    }
                    cookie_manager.set("urbano_auth", f"{u}|{d['token']}", expires_at=datetime.now()+timedelta(days=5))
                    st.rerun()
                else: st.error("Erro no login.")
    with t2:
        with st.form("f_cad"):
            nu = st.text_input("Usuário"); nn = st.text_input("Nome"); ne = st.text_input("Email"); np = st.text_input("Senha", type="password")
            if st.form_submit_button("Criar Conta"):
                ok, m = db.register_user(nu, nn, ne, np)
                if ok: st.success("Criado! Faça login."); time.sleep(1)
                else: st.error(m)
    st.stop()

# --- ÁREA LOGADA ---
user = st.session_state.user
if 'analise_atual' not in st.session_state: st.session_state.analise_atual = None
if 'chat_history' not in st.session_state: st.session_state.chat_history = []
if 'gemini_files_handles' not in st.session_state: st.session_state.gemini_files_handles = []

fresh = db.get_user_by_username(user['username'])
if fresh: 
    user['credits'] = fresh.get('credits_used', 0)
    user['plan'] = fresh.get('plan_type', 'free')
    limit = db.get_plan_limit(user['plan'])
else: logout()

with st.sidebar:
    st.markdown(f"### Olá, {user['name']}")
    st.caption(f"Plano: **{user['plan'].upper()}**")
    pct = min(user['credits']/limit, 1.0) if limit > 0 else 1.0
    st.progress(pct)
    st.write(f"Análises: {user['credits']} / {limit}")
    if user['credits'] >= limit and limit < 9999: st.error("Limite atingido!")

    st.divider()
    menu = st.radio("Menu", ["Análise de Editais", "📂 Documentos da Empresa", "📜 Histórico", "Assinatura"])
    if user.get('role') == 'admin':
        st.divider()
        if st.checkbox("Painel Admin"): menu = "Admin"
    
    if st.button("Sair"): logout()

# --- TELAS ---

# 1. ADMIN
if menu == "Admin":
    st.title("🔧 Gestão Administrativa")
    stats = db.admin_get_users_stats()
    df = pd.DataFrame(stats)
    
    if not df.empty:
        k1, k2, k3 = st.columns(3)
        k1.metric("Usuários", len(df))
        k2.metric("Análises", df['credits'].sum() if 'credits' in df.columns else 0)
        
        st.divider()
        c_search, c_clear = st.columns([0.8, 0.2])
        search_term = c_search.text_input("🔍 Pesquisar", placeholder="Nome ou Email...")
        
        if search_term:
            mask = df['username'].astype(str).str.contains(search_term, case=False) | \
                   df['name'].astype(str).str.contains(search_term, case=False)
            df_display = df[mask]
        else:
            df_display = df

        st.subheader("Base de Usuários")
        edited_df = st.data_editor(
            df_display,
            column_config={
                "username": st.column_config.TextColumn("Usuário", disabled=True),
                "credits": st.column_config.NumberColumn("Usados", disabled=True),
                "plan": st.column_config.SelectboxColumn("Plano", options=['free', 'plano_15', 'plano_30', 'plano_60', 'plano_90', 'unlimited'], required=True)
            },
            hide_index=True, use_container_width=True, key="users_editor"
        )

        if st.button("💾 Salvar Planos"):
            count = 0
            for i, row in edited_df.iterrows():
                orig = df[df['username']==row['username']].iloc[0]
                if orig['plan'] != row['plan']:
                    db.admin_update_plan(row['username'], row['plan']); count+=1
            if count: st.success(f"{count} atualizados!"); time.sleep(1); st.rerun()

        st.divider()
        st.subheader("🛠️ Gestão Individual")
        col_sel, col_act = st.columns([0.4, 0.6])
        with col_sel:
            sel_user = st.selectbox("Editar Usuário:", options=df_display['username'].tolist())
            if sel_user:
                u_info = df[df['username'] == sel_user].iloc[0]
                st.info(f"Plano: {u_info['plan']} | Usados: {u_info['credits']}")
        with col_act:
            if sel_user:
                with st.form("edit_cred"):
                    nc = st.number_input("Definir 'Créditos Usados':", min_value=0, value=int(u_info['credits']))
                    np = st.selectbox("Plano:", ['free', 'plano_15', 'plano_30', 'plano_60', 'plano_90', 'unlimited'], index=['free', 'plano_15', 'plano_30', 'plano_60', 'plano_90', 'unlimited'].index(u_info['plan']))
                    if st.form_submit_button("✅ Atualizar"):
                        db.admin_set_credits_used(sel_user, nc)
                        db.admin_update_plan(sel_user, np)
                        st.toast("Atualizado!"); time.sleep(1); st.rerun()
                if st.button("🔄 Resetar Créditos (Zero)"):
                    db.admin_set_credits_used(sel_user, 0)
                    st.toast("Resetado!"); time.sleep(1); st.rerun()

# 2. DOCUMENTOS
elif menu == "📂 Documentos da Empresa":
    st.title("📂 Acervo Digital")
    st.info("Estes documentos serão usados para o Cruzamento Automático.")
    with st.expander("⬆️ Upload", expanded=False):
        c1, c2 = st.columns(2)
        s = c1.selectbox("Pasta", list(DOC_STRUCTURE.keys()))
        t = c2.selectbox("Tipo", DOC_STRUCTURE[s])
        f = st.file_uploader("Arquivo PDF", type=["pdf"])
        if f and st.button("Salvar na Nuvem"):
            with st.spinner("Enviando..."):
                safe = re.sub(r'[\\/*?:"<>|]', "", f.name)
                if db.upload_file_to_storage(f.getvalue(), safe, user['username'], s, t):
                    st.success("Salvo!"); time.sleep(1); st.rerun()
                else: st.error("Erro upload.")
    
    st.divider()
    for sec, types in DOC_STRUCTURE.items():
        st.markdown(f"**{sec}**")
        cols = st.columns(3)
        for i, t in enumerate(types):
            with cols[i%3]:
                files = db.list_files_from_storage(user['username'], sec, t)
                with st.expander(f"{t} ({len(files)})"):
                    for file in files:
                        c_tx, c_del = st.columns([0.8, 0.2])
                        c_tx.caption(file[:20]+"...")
                        if c_del.button("🗑️", key=f"d_{file}"):
                            db.delete_file_from_storage(file, user['username'], sec, t); st.rerun()

# 3. ANÁLISE (O CORAÇÃO DO SISTEMA)
elif menu == "Análise de Editais":
    st.title("🔍 Analisar Novo Edital")
    
    if 'gemini_files_handles' not in st.session_state: 
        st.session_state.gemini_files_handles = []

    if st.session_state.analise_atual:
        if st.button("🔄 Nova Análise"):
            st.session_state.analise_atual = None
            st.session_state.gemini_files_handles = []
            st.session_state.chat_history = []
            st.rerun()
    
    if not st.session_state.analise_atual:
        if user['credits'] >= limit:
            st.warning("Seu plano atingiu o limite de análises."); st.stop()
            
        uploaded_files = st.file_uploader("Upload do Edital e Anexos (PDF)", type=["pdf"], accept_multiple_files=True)
        
        if uploaded_files and st.button("🚀 Iniciar Auditoria IA"):
            
            with st.status("O Urbano está processando os documentos...", expanded=True) as status:
                try:
                    status.write("Validando plano...")
                    if not db.consume_credit_atomic(user['username']): st.error("Erro crédito"); st.stop()
                    
                    status.write(f"Lendo {len(uploaded_files)} arquivos...")
                    files_for_ai = [] 
                    temp_paths_cleanup = []

                    for upl in uploaded_files:
                        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                            tmp.write(upl.getvalue())
                            tmp_path = tmp.name
                            temp_paths_cleanup.append(tmp_path)
                        g_file = genai.upload_file(tmp_path, display_name=upl.name)
                        files_for_ai.append(g_file)
                    
                    st.session_state.gemini_files_handles = files_for_ai
                    
                    # --- NOVO PROMPT DE 14 PONTOS ---
                    status.write("Gerando Relatório Detalhado...")
                    model = genai.GenerativeModel('gemini-pro-latest')
                    prompt_inicial = """
                    ATUE COMO AUDITOR SÊNIOR DE ENGENHARIA.
                    Analise TODOS os documentos fornecidos (Edital e Anexos) com extremo rigor.
                    Responda pontualmente às 16 questões abaixo. Use Markdown para formatar.

                    Ao responder as questões dos 16 pontos do prompt inicial, não há necessidade de apresentar o texto das perguntas de forma literal como estão escritas. A IA pode proceder de maneira mais didática nas perguntas, mas precisa manter as respostas à tais questões.


                    1. Qual o nome do órgão contratante?
                    2. Qual o objeto do edital? (Resumo completo)
                    3. Qual o valor estimado para a realização dos serviços?
                    4. Qual a plataforma onde será realizado o certame?
                    5. Qual a data de realização do certame e até quando é possível enviar a proposta?
                    6. **CRONOGRAMA**: Datas e Prazos.
                    7. **HABILITAÇÃO JURÍDICA/FISCAL**: Exigências.
                    8. **FINANCEIRO**: Índices (LG, SG, LC) e valores.
                    9. Quais as exigências para qualificação técnica deste certame? (Esmiuce com detalhes, incluindo apresentação de declarações e demais documentos exigidos)
                    10. Elenque TODOS os profissionais exigidos pelo edital e também a experiência necessária.
                    11. Não oculte nenhuma exigência técnica, por mais simples que pareça.
                    12. É exigida algum tipo de garantia? Se sim, quais?
                    13. Qual o entendimento do edital acerca de propostas com descontos acima de 25% do valor global?
                    14. Qual o formato e o período destinado para a fase de lances?
                    15. O que o edital versa sobre identificação da empresa no envio da documentação ou proposta?
                    16. Analise os riscos envolvidos na participação da empresa nesse serviço.
                    """
                    
                    resp = model.generate_content(files_for_ai + [prompt_inicial])
                    
                    st.session_state.analise_atual = resp.text
                    title = extract_title(resp.text)
                    db.save_analysis_history(user['username'], title, resp.text)
                    
                    status.update(label="Concluído!", state="complete", expanded=False)
                    for p in temp_paths_cleanup: os.remove(p)
                    st.rerun()
                    
                except Exception as e:
                    db.refund_credit_atomic(user['username'])
                    st.error(f"Falha: {e}. Crédito estornado.")
    
    else:
        st.markdown(st.session_state.analise_atual)
        st.divider()
        
        st.subheader("🚀 Cruzamento de Dados")
        if user['plan'] == 'free':
            st.info("🔒 Upgrade necessário.")
        else:
            if st.button("Verificar Minha Viabilidade"):
                with st.spinner("Comparando documentos..."):
                    c_files = db.get_all_company_files_as_bytes(user['username'])
                    if not c_files:
                        st.warning("Sem documentos da empresa.")
                    else:
                        temp_handles = []
                        for name, data in c_files:
                            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as t:
                                t.write(data); t_path = t.name
                            temp_handles.append(genai.upload_file(t_path, display_name=name))
                            os.remove(t_path)
                        
                        prompt_cross = "Checklist de Viabilidade: Edital vs Empresa. Para cada item: Edital pede X -> Empresa tem Y -> Veredito."
                        model = genai.GenerativeModel('gemini-pro-latest')
                        inputs = st.session_state.gemini_files_handles + temp_handles + [prompt_cross]
                        resp_cross = model.generate_content(inputs)
                        
                        st.session_state.analise_atual += "\n\n---\n\n# 🛡️ VIABILIDADE\n" + resp_cross.text
                        db.save_analysis_history(user['username'], "Update Cruzamento", st.session_state.analise_atual)
                        st.rerun()

        st.divider()
        st.subheader("💬 Chat")
        for role, txt in st.session_state.chat_history:
            with st.chat_message(role): st.markdown(txt)
            
        if q := st.chat_input("Dúvida?"):
            st.session_state.chat_history.append(("user", q))
            with st.chat_message("user"): st.markdown(q)
            with st.chat_message("assistant"):
                with st.spinner("..."):
                    try:
                        model = genai.GenerativeModel('gemini-pro-latest')
                        inputs = st.session_state.gemini_files_handles + [f"Responda baseado no edital: {q}"]
                        r = model.generate_content(inputs)
                        st.markdown(r.text)
                        st.session_state.chat_history.append(("assistant", r.text))
                    except: st.error("Erro IA.")

        st.divider()
        if st.button("📄 Baixar PDF Completo"):
            with st.spinner("Gerando PDF..."):
                content = st.session_state.analise_atual
                if st.session_state.chat_history:
                    content += "\n\n<div class='chat-section'><h1>💬 Histórico de Dúvidas</h1>"
                    for role, text in st.session_state.chat_history:
                        content += f"<p class='chat-q'>{role.upper()}: {text}</p>"
                    content += "</div>"
                pdf_bytes = convert_to_pdf(content)
                if pdf_bytes:
                    st.download_button("⬇️ Download PDF", data=pdf_bytes, file_name=f"Analise_{datetime.now().strftime('%Y%m%d')}.pdf", mime="application/pdf")
                else: st.error("Erro PDF.")

# 4. HISTÓRICO (ATUALIZADO PARA EXIBIR TÍTULO PADRONIZADO)
elif menu == "📜 Histórico":
    st.title("Biblioteca de Análises")
    
    lst = db.get_user_history_list(user['username'])
    if not lst: st.info("Nenhuma análise salva.")
    
    for item in lst:
        chat_key = f"hist_chat_{item['id']}"
        if chat_key not in st.session_state: st.session_state[chat_key] = []
        
        dt = item['created_at'].strftime("%d/%m/%Y")
        
        # AQUI: Gera o título dinamicamente baseado no conteúdo salvo
        # Isso garante que análises antigas também sigam o padrão "5 palavras"
        display_title = extract_title(item['content'])
        
        with st.expander(f"📅 {dt} | {display_title}"):
            st.markdown(item['content'])
            st.divider()
            
            c_pdf, c_del = st.columns([0.8, 0.2])
            with c_pdf:
                pdf_bytes = convert_to_pdf(item['content'])
                if pdf_bytes:
                    st.download_button("📄 Baixar PDF", data=pdf_bytes, file_name=f"Relatorio_{item['id'][:6]}.pdf", mime="application/pdf")
            with c_del:
                if st.button("🗑️", key=f"del_{item['id']}"):
                    db.delete_history_item(user['username'], item['id']); st.rerun()

            st.markdown("---")
            st.subheader("💬 Dúvidas (Modo Histórico)")
            for role, text in st.session_state[chat_key]:
                with st.chat_message(role): st.markdown(text)
            
            if q := st.chat_input("Dúvida sobre este relatório?", key=f"in_{item['id']}"):
                st.session_state[chat_key].append(("user", q))
                with st.chat_message("user"): st.markdown(q)
                with st.chat_message("assistant"):
                    with st.spinner("Lendo relatório salvo..."):
                        try:
                            model = genai.GenerativeModel('gemini-1.5-flash')
                            prompt = f"Contexto: {item['content']}\nPergunta: {q}"
                            res = model.generate_content(prompt)
                            st.markdown(res.text)
                            st.session_state[chat_key].append(("assistant", res.text))
                        except: st.error("Erro.")

# 5. ASSINATURA
elif menu == "Assinatura":
    st.title("💎 Planos")
    st.info(f"Plano Atual: **{user['plan'].upper()}**")
    cols = st.columns(4)
    plans = [("🥉 Plano 15", "15 Editais", "R$ 39,90"), ("🥈 Plano 30", "30 Editais", "R$ 69,90"), 
             ("🥇 Plano 60", "60 Editais", "R$ 109,90"), ("💎 Plano 90", "90 Editais", "R$ 149,90")]
    for i, (n, q, v) in enumerate(plans):
        with cols[i]:
            st.markdown(f"### {n}\n**{q}**\n### {v}"); st.button(f"Assinar {n}", key=f"b_{i}")
    st.markdown("---"); st.caption("Envie comprovante para o Suporte.")