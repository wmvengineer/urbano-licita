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
import random
import base64 

# --- LIBS PARA PDF E CALENDÁRIO ---
from xhtml2pdf import pisa
import markdown
from streamlit_calendar import calendar

# --- CONFIGURAÇÃO ---
icon_file = "LOGO URBANO OFICIAL.png" if os.path.exists("LOGO URBANO OFICIAL.png") else "🏢"
st.set_page_config(page_title="Urbano", layout="wide", page_icon=icon_file)

# API KEY
try:
    if "GOOGLE_API_KEY" in st.secrets:
        genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
    else: pass
except:
    st.error("Configure a API Key.")
    st.stop()

db.init_db()

# --- MAPA DE NOMES DE PLANOS (NOVOS REQUISITOS) ---
PLAN_MAP = {
    'unlimited': 'Nível Administrador',
    'free': 'Teste Gratuito',
    'plano_15': 'Plano 15 análises',
    'plano_30': 'Plano 30 análises',
    'plano_60': 'Plano 60 análises',
    'plano_90': 'Plano 90 análises',
    'unlimited_30': 'Ilimitado - 30 DIAS',
    'expired': 'Expirado'
}

# --- CSS LIMPO ---
st.markdown("""
    <style>
        [data-testid="stToolbar"], [data-testid="stDecoration"], header {display: none !important;}
        .main .block-container {padding-bottom: 0px !important;}
    </style>
""", unsafe_allow_html=True)

try:
    if "daily_check_done" not in st.session_state: st.session_state.daily_check_done = True
except: pass

DOC_STRUCTURE = {
    "1. Habilitacao Juridica": ["Contrato Social", "CNPJ", "Documentos Sócios"],
    "2. Habilitacao Fiscal": ["Federal", "Estadual", "Municipal", "FGTS", "Trabalhista"],
    "3. Qualificacao Tecnica": ["Atestados Operacionais", "Atestados Profissionais", "Certidao de Registro no Conselho - Profissionais", "Certidao de Registro no Conselho - Empresa"],
    "4. Habilitacao Financeira": ["Balanco Patrimonial", "Indices Financeiros", "Certidao Falencia"]
}

# --- FUNÇÕES AUXILIARES ---
def get_base64_image(image_path):
    if os.path.exists(image_path):
        with open(image_path, "rb") as img_file:
            return base64.b64encode(img_file.read()).decode()
    return None

def convert_to_pdf(source_md):
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

def extract_title(text):
    try:
        orgao = "Órgão Indefinido"
        match_orgao = re.search(r"(?:1\.|órgão).*?[:\-\?]\s*(.*?)(?:\n|2\.|Qual|$)", text, re.IGNORECASE)
        if match_orgao: orgao = match_orgao.group(1).replace("*", "").strip()

        data_sessao = "Data Pendente"
        match_data_tag = re.search(r"DATA_CHAVE:\s*(\d{2}/\d{2}/\d{4})", text)
        
        if match_data_tag: data_sessao = match_data_tag.group(1)
        else:
            match_q5 = re.search(r"5\.(.*?)(?:6\.|CRONOGRAMA|\n\n|$)", text, re.DOTALL | re.IGNORECASE)
            if match_q5:
                match_generic = re.search(r"(\d{2}/\d{2}/\d{4})", match_q5.group(1))
                if match_generic: data_sessao = match_generic.group(1)
        return f"Edital {orgao} | {data_sessao}"
    except: return f"Edital Processado em {datetime.now().strftime('%d/%m/%Y')}"

def extract_date_for_calendar(title_str):
    try:
        match = re.search(r"(\d{2})/(\d{2})/(\d{4})", title_str)
        if match: return f"{match.group(3)}-{match.group(2)}-{match.group(1)}"
    except: pass
    return None

def render_status_controls(item_id, current_status, current_note):
    st.caption("Classificação do Edital (Marque uma opção):")
    c1, c2, c3 = st.columns([0.15, 0.15, 0.7])
    
    is_red = c1.checkbox("🟥 Inviável", value=(current_status=='red'), key=f"r_{item_id}")
    is_yellow = c2.checkbox("🟨 Ajustes", value=(current_status=='yellow'), key=f"y_{item_id}")
    is_green = c3.checkbox("🟩 Apto", value=(current_status=='green'), key=f"g_{item_id}")

    new_status = current_status
    if is_red and current_status != 'red': new_status = 'red'
    elif is_yellow and current_status != 'yellow': new_status = 'yellow'
    elif is_green and current_status != 'green': new_status = 'green'
    if not is_red and not is_yellow and not is_green: new_status = None

    if new_status != current_status:
        db.update_analysis_status(st.session_state.user['username'], item_id, new_status, current_note)
        st.rerun()

    if new_status:
        placeholder_text = ""
        if new_status == 'red': placeholder_text = "Descreva os motivos da inviabilidade..."
        elif new_status == 'yellow': placeholder_text = "Quais ajustes são necessários?"
        elif new_status == 'green': placeholder_text = "Observações..."
        
        new_note = st.text_area("Observações:", value=current_note, placeholder=placeholder_text, key=f"note_{item_id}")
        if st.button("💾 Salvar Observação", key=f"save_{item_id}"):
            db.update_analysis_status(st.session_state.user['username'], item_id, new_status, new_note)
            st.toast("Observação salva com sucesso!")

# --- SESSÃO & COOKIES ---
cookie_manager = stx.CookieManager(key="urbano_cookies")
if 'user' not in st.session_state: st.session_state.user = None

if st.session_state.user is None:
    time.sleep(0.3)
    auth_cookie = cookie_manager.get("urbano_auth")
    if auth_cookie:
        try:
            u, t = auth_cookie.split('|')
            if db.check_session_valid(u, t):
                raw = db.get_user_by_username(u)
                if raw:
                    st.session_state.user = {
                        "username": raw.get('username'), "name": raw.get('name'),
                        "role": raw.get('role'), "plan": raw.get('plan_type', 'free'),
                        "credits": raw.get('credits_used', 0), "token": raw.get('token'),
                        "company_name": raw.get('company_name', ''), "cnpj": raw.get('cnpj', ''),
                        "plan_expires_at": raw.get('plan_expires_at')
                    }
                    st.rerun()
        except: pass

def logout():
    st.session_state.user = None
    try: cookie_manager.delete("urbano_auth")
    except KeyError: pass
    except Exception: pass
    time.sleep(1); st.rerun()

# --- TELA DE LOGIN ---
if not st.session_state.user:
    st.markdown("""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;700&display=swap');
        .stApp {background-image: url('https://colorlib.com/etc/lf/Login_v3/images/bg-01.jpg'); background-size: cover; font-family: 'Poppins', sans-serif;}
        header, footer {visibility: hidden;}
        div[data-testid="stForm"] {background: linear-gradient(top, #394E53, #173a50); border-radius: 10px; padding: 55px; border: none;}
        div[data-testid="stTextInput"] label {color: #eeeeee !important;}
        div[data-testid="stTextInput"] input {background-color: transparent !important; color: #364C50 !important; border: none !important; border-bottom: 2px solid rgba(255,255,255,0.24) !important;}
        div.stButton > button {background: #fff !important; color: #555 !important; border-radius: 25px; height: 50px; font-weight: 600;}
        .stTabs [data-baseweb="tab"] {background-color: #364C50 !important; color: #fff !important;}
        .stTabs [aria-selected="true"] {border-bottom: 2px solid #fff;}
        </style>
    """, unsafe_allow_html=True)

    col_l, col_login, col_r = st.columns([1, 1.5, 1])
    with col_login:
        img_b64 = get_base64_image("LOGO URBANO OFICIAL.png")
        if img_b64:
            st.markdown(f"<div style='text-align:center;margin-bottom:30px;'><div style='display:flex;justify-content:center;align-items:center;width:160px;height:160px;border-radius:50%;background-color:#fff;margin:0 auto;'><img src='data:image/png;base64,{img_b64}' style='width:110px;'/></div></div>", unsafe_allow_html=True)
        else: st.markdown("<div style='text-align:center;font-size:50px;'>🏢</div>", unsafe_allow_html=True)

        t1, t2 = st.tabs(["ENTRAR", "CRIAR CONTA"])
        
        with t1:
            with st.form("f_login"):
                u = st.text_input("Usuário ou E-mail")
                p = st.text_input("Senha", type="password")
                
                if 'log_n1' not in st.session_state: st.session_state.log_n1 = random.randint(1, 9)
                if 'log_n2' not in st.session_state: st.session_state.log_n2 = random.randint(1, 9)
                st.markdown(f"<p style='color:white;font-size:12px;'>Quanto é {st.session_state.log_n1} + {st.session_state.log_n2}?</p>", unsafe_allow_html=True)
                captcha_ans = st.number_input("Captcha", step=1, label_visibility="collapsed", key="in_cap_log")

                c_log, c_rec = st.columns(2)
                with c_log: sub_log = st.form_submit_button("LOGIN")
                with c_rec: sub_rec = st.form_submit_button("RECUPERAR")

                if sub_rec:
                    if not u or "@" not in u: st.warning("Digite seu E-mail acima.")
                    elif captcha_ans != (st.session_state.log_n1 + st.session_state.log_n2): st.error("Captcha incorreto.")
                    else:
                        ok, msg = db.recover_user_password(u)
                        if ok: st.success(msg)
                        else: st.error(msg)
                        time.sleep(2)

                elif sub_log:
                    if captcha_ans != (st.session_state.log_n1 + st.session_state.log_n2):
                        st.error("Captcha incorreto.")
                        st.session_state.log_n1 = random.randint(1, 9)
                        st.session_state.log_n2 = random.randint(1, 9)
                        time.sleep(1); st.rerun()
                    else:
                        ok, d = db.login_user(u, p)
                        if ok:
                            st.session_state.user = {
                                "username": d.get('username'), "name": d.get('name'),
                                "role": d.get('role'), "plan": d.get('plan_type', 'free'),
                                "credits": d.get('credits_used', 0), "token": d.get('token'),
                                "company_name": d.get('company_name', ''), "cnpj": d.get('cnpj', ''),
                                "plan_expires_at": d.get('plan_expires_at')
                            }
                            cookie_manager.set("urbano_auth", f"{u}|{d['token']}", expires_at=datetime.now()+timedelta(days=5))
                            st.rerun()
                        else: st.error("Erro no login.")
        
        with t2:
            with st.form("f_cad"):
                nc_empresa = st.text_input("Nome da Empresa")
                nc_cnpj = st.text_input("CNPJ")
                nu = st.text_input("Usuário")
                nn = st.text_input("Nome")
                ne = st.text_input("Email")
                np = st.text_input("Senha", type="password")
                
                if 'cad_n1' not in st.session_state: st.session_state.cad_n1 = random.randint(1, 9)
                if 'cad_n2' not in st.session_state: st.session_state.cad_n2 = random.randint(1, 9)
                st.markdown(f"<p style='color:white;font-size:12px;'>Quanto é {st.session_state.cad_n1} + {st.session_state.cad_n2}?</p>", unsafe_allow_html=True)
                cad_ans = st.number_input("Captcha Cad", step=1, label_visibility="collapsed", key="in_cap_cad")

                if st.form_submit_button("CADASTRAR"):
                    if cad_ans != (st.session_state.cad_n1 + st.session_state.cad_n2):
                        st.error("Captcha incorreto.")
                        st.session_state.cad_n1 = random.randint(1, 9)
                        st.session_state.cad_n2 = random.randint(1, 9)
                        time.sleep(1); st.rerun()
                    else:
                        ok, m = db.register_user(nu, nn, ne, np, nc_empresa, nc_cnpj)
                        if ok: st.success("Criado! Faça login."); time.sleep(1)
                        else: st.error(m)
    st.stop()

# --- ÁREA LOGADA ---
user = st.session_state.user
if 'analise_atual' not in st.session_state: st.session_state.analise_atual = None
if 'chat_history' not in st.session_state: st.session_state.chat_history = []
if 'gemini_files_handles' not in st.session_state: st.session_state.gemini_files_handles = []
if 'last_analysis_id' not in st.session_state: st.session_state.last_analysis_id = None

fresh = db.get_user_by_username(user['username'])
if fresh: 
    user['credits'] = fresh.get('credits_used', 0)
    user['plan'] = fresh.get('plan_type', 'free')
    user['plan_expires_at'] = fresh.get('plan_expires_at') # Atualiza data
    limit = db.get_plan_limit(user['plan'])
else: logout()

# --- LÓGICA DE VENCIMENTO DO PLANO ---
# Se for unlimited_30, verificamos a data. Se passou, muda para 'expired'
if user['plan'] == 'unlimited_30':
    expires = user.get('plan_expires_at')
    if expires:
        # Firestore retorna datetime com timezone, convertemos para naive para comparar
        if expires.replace(tzinfo=None) < datetime.now():
            db.admin_update_plan(user['username'], 'expired')
            st.toast("Seu plano de 30 dias expirou.")
            time.sleep(2)
            st.rerun()

# --- SIDEBAR ---
st.markdown("""
    <style>
    [data-testid="stSidebar"] {background-color: #364C50;}
    [data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3, 
    [data-testid="stSidebar"] span, [data-testid="stSidebar"] div, [data-testid="stSidebar"] label, 
    [data-testid="stSidebar"] p {color: #FFFFFF !important;}
    [data-testid="stSidebar"] .stButton button div, [data-testid="stSidebar"] .stButton button p {color: #31333F !important;}
    </style>
""", unsafe_allow_html=True)

with st.sidebar:
    img_b64_side = get_base64_image("LOGO URBANO OFICIAL.png")
    if img_b64_side:
        st.markdown(f"<div style='display:flex;justify-content:center;margin-bottom:20px;'><div style='width:200px;height:200px;background-color:white;border-radius:50%;display:flex;align-items:center;justify-content:center;'><img src='data:image/png;base64,{img_b64_side}' style='width:150px;'/></div></div>", unsafe_allow_html=True)
    else: st.markdown("<div style='font-size:80px;text-align:center;color:white;'>🏢</div>", unsafe_allow_html=True)

    if user.get('company_name'): st.markdown(f"#### {user['company_name']}")
    if user.get('cnpj'): st.caption(f"CNPJ: {user['cnpj']}")
        
    st.markdown(f"### Olá, {user['name']}")
    
    # Exibição do Nome do Plano Mapeado
    plan_display = PLAN_MAP.get(user['plan'], user['plan'])
    st.caption(f"Plano: **{plan_display}**")
    
    # Contador de Dias (Apenas para Unlimited 30)
    if user['plan'] == 'unlimited_30' and user.get('plan_expires_at'):
        exp = user['plan_expires_at'].replace(tzinfo=None)
        days_left = (exp - datetime.now()).days
        if days_left < 0: days_left = 0
        st.markdown(f"<p style='color:#FFDD00; font-weight:bold;'>⏳ Restam: {days_left} dias</p>", unsafe_allow_html=True)

    pct = min(user['credits']/limit, 1.0) if limit > 0 else 1.0
    st.progress(pct)
    st.write(f"Análises: {user['credits']} / {limit}")
    if user['credits'] >= limit and limit < 999990: st.error("Limite atingido!")

    st.divider()
    menu = st.radio("Menu", ["Análise de Editais", "📅 Calendário", "📂 Documentos da Empresa", "📜 Histórico", "Assinatura"])
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
    
    # Lista de chaves válidas no banco
    valid_plans = ['free', 'plano_15', 'plano_30', 'plano_60', 'plano_90', 'unlimited_30', 'unlimited', 'expired']
    
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
                "plan": st.column_config.SelectboxColumn("Plano", options=valid_plans, required=True)
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
                    
                    try: current_index = valid_plans.index(u_info['plan'])
                    except ValueError: current_index = 0
                    
                    np = st.selectbox("Plano:", valid_plans, index=current_index)
                    
                    if st.form_submit_button("✅ Atualizar"):
                        # Lógica Específica para Ilimitado 30 dias
                        expiration = None
                        if np == 'unlimited_30':
                            expiration = datetime.now() + timedelta(days=30)
                        
                        db.admin_set_credits_used(sel_user, nc)
                        db.admin_update_plan(sel_user, np, expires_at=expiration)
                        st.toast("Atualizado com Sucesso!"); time.sleep(1); st.rerun()
                        
                if st.button("🔄 Resetar Créditos (Zero)"):
                    db.admin_set_credits_used(sel_user, 0)
                    st.toast("Resetado!"); time.sleep(1); st.rerun()
        st.divider()
        st.subheader("📧 Central de Notificações")
        
        col_test, col_run = st.columns(2)
        with col_test:
            st.markdown("#### Teste de SMTP")
            test_email = st.text_input("E-mail para teste", value=st.session_state.user['email'])
            if st.button("📨 Enviar E-mail de Teste"):
                ok, msg = db.send_email(test_email, "Teste SMTP", "<h1>Funciona!</h1>")
                if ok: st.success(msg)
                else: st.error(msg)

        with col_run:
            st.markdown("#### Disparo Manual")
            if st.button("🚀 Rodar Verificação de Prazos"):
                with st.spinner("Processando..."):
                    log = db.check_deadlines_and_notify()
                    st.text_area("Log", value=log, height=200)

        st.divider()

# 2. DOCUMENTOS
elif menu == "📂 Documentos da Empresa":
    st.title("📂 Acervo Digital")
    st.info("Estes documentos serão usados para o Cruzamento Automático.")
    
    with st.expander("⬆️ Upload", expanded=False):
        c1, c2 = st.columns(2)
        s = c1.selectbox("Pasta", list(DOC_STRUCTURE.keys()))
        t = c2.selectbox("Tipo", DOC_STRUCTURE[s])
        
        if "uploader_key" not in st.session_state: st.session_state["uploader_key"] = 0
        files = st.file_uploader("Arquivos PDF", type=["pdf"], accept_multiple_files=True, key=f"uploader_{st.session_state['uploader_key']}")
        
        if files and st.button("Salvar na Nuvem"):
            with st.spinner(f"Enviando..."):
                count = 0
                for f in files:
                    safe = re.sub(r'[\\/*?:"<>|]', "", f.name)
                    if db.upload_file_to_storage(f.getvalue(), safe, user['username'], s, t): count += 1
                if count > 0:
                    st.success(f"{count} arquivos salvos!")
                    st.session_state["uploader_key"] += 1; time.sleep(1); st.rerun()

    st.divider()
    for sec, types in DOC_STRUCTURE.items():
        st.markdown(f"**{sec}**")
        cols = st.columns(3)
        for i, t in enumerate(types):
            with cols[i%3]:
                files = db.list_files_from_storage(user['username'], sec, t)
                with st.expander(f"{t} ({len(files)})"):
                    for idx, file in enumerate(files):
                        c_tx, c_del = st.columns([0.8, 0.2])
                        c_tx.caption(file[:20]+"...")
                        if c_del.button("🗑️", key=f"del_{sec}_{t}_{idx}_{file}"):
                            db.delete_file_from_storage(file, user['username'], sec, t); st.rerun()

# 3. ANÁLISE
elif menu == "Análise de Editais":
    st.title("🔍 Analisar Novo Edital")
    if user['plan'] == 'expired': st.error("Seu plano expirou. Contate o suporte."); st.stop()
    
    if st.session_state.analise_atual:
        if st.button("🔄 Nova Análise"):
            st.session_state.analise_atual = None
            st.session_state.gemini_files_handles = []
            st.session_state.chat_history = []
            st.session_state.last_analysis_id = None
            st.rerun()
    
    if not st.session_state.analise_atual:
        if user['credits'] >= limit: st.warning("Limite atingido."); st.stop()
        
        st.markdown("<style>[data-testid='stFileUploaderDropzoneInstructions'] > div > span {display: none;}</style>", unsafe_allow_html=True)
        ups = st.file_uploader("Upload Edital + Anexos", type=["pdf"], accept_multiple_files=True)
        
        if ups:
            valid_files = [up for up in ups if up.size <= 25*1024*1024]
            ups = valid_files

        if ups and st.button("🚀 Iniciar Auditoria IA"):
            with st.status("Processando...", expanded=True) as status:
                try:
                    status.write("Validando plano...")
                    if not db.consume_credit_atomic(user['username']): st.error("Erro crédito"); st.stop()
                    
                    status.write(f"Lendo {len(ups)} arquivos...")
                    files_ai = []; temps = []
                    for up in ups:
                        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                            tmp.write(up.getvalue()); tmp_path = tmp.name; temps.append(tmp_path)
                        files_ai.append(genai.upload_file(tmp_path, display_name=up.name))
                    st.session_state.gemini_files_handles = files_ai
                    
                    status.write("Gerando Relatório...")
                    model = genai.GenerativeModel('gemini-pro-latest')
                    prompt = """
                    ATUE COMO AUDITOR SÊNIOR DE ENGENHARIA.
                    Analise TODOS os documentos fornecidos.
                    Responda pontualmente às 16 questões:
                    1. Nome do órgão contratante?
                    2. Objeto do edital? (Resumo)
                    3. Valor estimado?
                    4. Plataforma do certame?
                    5. Data do certame? (Inicie com "DATA_CHAVE: DD/MM/YYYY").
                    6. CRONOGRAMA: Datas e Prazos.
                    7. HABILITAÇÃO JURÍDICA/FISCAL: Exigências.
                    8. FINANCEIRO: Índices e valores.
                    9. Qualificação técnica completa.
                    10. Profissionais exigidos e experiência.
                    11. Detalhes técnicos ocultos.
                    12. Garantias exigidas?
                    13. Propostas com descontos acima de 25%?
                    14. Formato da fase de lances?
                    15. Identificação da empresa?
                    16. Riscos envolvidos.
                    """
                    resp = model.generate_content(files_ai + [prompt])
                    st.session_state.analise_atual = resp.text
                    
                    title = extract_title(resp.text)
                    new_doc_id = db.save_analysis_history(user['username'], title, resp.text)
                    st.session_state.last_analysis_id = new_doc_id
                    
                    status.update(label="Pronto!", state="complete", expanded=False)
                    for p in temps: os.remove(p)
                    st.rerun()
                except Exception as e:
                    db.refund_credit_atomic(user['username'])
                    st.error(f"Erro: {e}. Crédito devolvido.")
    else:
        if st.session_state.last_analysis_id:
            st.info("Classifique este edital:")
            curr_item = db.get_history_item(user['username'], st.session_state.last_analysis_id)
            if curr_item: render_status_controls(st.session_state.last_analysis_id, curr_item.get('status'), curr_item.get('note', ''))
            st.divider()

        st.markdown(st.session_state.analise_atual)
        st.divider()
        st.subheader("🚀 Cruzamento de Dados")
        
        if user['plan'] == 'free': st.info("🔒 Upgrade necessário.")
        else:
            if st.button("Verificar Minha Viabilidade"):
                with st.spinner("Analisando com documentos da empresa..."):
                    c_files = db.get_all_company_files_as_bytes(user['username'])
                    if not c_files: st.warning("Sem documentos da empresa.")
                    else:
                        local_paths = []; company_ai_files = []
                        try:
                            for n, d in c_files:
                                with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as t:
                                    t.write(d); local_paths.append(t.name)
                                company_ai_files.append(genai.upload_file(t.name, display_name=n))
                            
                            all_files = st.session_state.gemini_files_handles + company_ai_files
                            prompt_cross = """
                            ATUE COMO AUDITOR SÊNIOR.
                            CONTEXTO: EDITAL (primeiros arquivos) vs EMPRESA (últimos arquivos).
                            Gere Checklist de Viabilidade:
                            1. HABILITAÇÃO JURÍDICA E FISCAL (Itens vs Docs)
                            2. QUALIFICAÇÃO TÉCNICA OPERACIONAL (PJ) (Apto/Não Apto)
                            3. QUALIFICAÇÃO TÉCNICA PROFISSIONAL (PF) (Apto/Não Apto)
                            4. HABILITAÇÃO FINANCEIRA
                            5. PARECER FINAL
                            """
                            model = genai.GenerativeModel('gemini-pro-latest')
                            resp = model.generate_content(all_files + [prompt_cross])
                            st.session_state.analise_atual += "\n\n---\n\n# 🛡️ VIABILIDADE (IA Visual)\n" + resp.text
                            st.rerun()
                        except Exception as e: st.error(f"Erro IA: {e}")
                        finally:
                            for p in local_paths: os.remove(p)
        
        st.divider()
        st.subheader("💬 Chat")
        for r, t in st.session_state.chat_history:
            with st.chat_message(r): st.markdown(t)
        if q := st.chat_input("Dúvida?"):
            st.session_state.chat_history.append(("user", q))
            with st.chat_message("user"): st.markdown(q)
            with st.chat_message("assistant"):
                with st.spinner("..."):
                    try:
                        m = genai.GenerativeModel('gemini-pro-latest')
                        res = m.generate_content(st.session_state.gemini_files_handles + [f"Responda baseado no edital: {q}"])
                        st.markdown(res.text)
                        st.session_state.chat_history.append(("assistant", res.text))
                    except: st.error("Erro IA.")

        st.divider()
        if st.button("📄 Baixar PDF Completo"):
            with st.spinner("Gerando PDF..."):
                content = st.session_state.analise_atual
                if st.session_state.chat_history:
                    content += "\n\n<div class='chat-section'><h1>💬 Histórico</h1>"
                    for r, t in st.session_state.chat_history: content += f"<p class='chat-q'>{r.upper()}: {t}</p>"
                    content += "</div>"
                pdf = convert_to_pdf(content)
                if pdf: st.download_button("⬇️ Download PDF", data=pdf, file_name=f"Analise.pdf", mime="application/pdf")
                else: st.error("Erro PDF.")

# 4. HISTÓRICO
elif menu == "📜 Histórico":
    st.title("Biblioteca de Análises")
    lst = db.get_user_history_list(user['username'])
    
    if not lst: st.info("Vazio.")
    else:
        with st.expander("🗑️ Excluir Vários"):
            table_data = []
            for item in lst:
                raw_t = extract_title(item['content'])
                table_data.append({"id": item['id'], "Excluir": False, "Data": item['created_at'].strftime("%d/%m/%Y"), "Título": raw_t})
            
            edited_df = st.data_editor(pd.DataFrame(table_data), column_config={"id": None, "Excluir": st.column_config.CheckboxColumn("Sel.")}, hide_index=True, use_container_width=True)
            if st.button("🗑️ Excluir Selecionados", type="primary"):
                sel = edited_df[edited_df["Excluir"] == True]
                for i, r in sel.iterrows(): db.delete_history_item(user['username'], r['id'])
                st.rerun()
        st.divider()

    for item in lst:
        chat_key = f"hist_chat_{item['id']}"
        if chat_key not in st.session_state: st.session_state[chat_key] = []
        
        dt_c = item['created_at'].strftime("%d/%m/%Y")
        content = item['content']
        orgao = "Indefinido"
        try: orgao = content.split("1.")[1].split("2.")[0].replace("Qual o nome do órgão contratante?", "").strip()[:60]
        except: pass
        
        ft = f"{dt_c} | {orgao}"
        status = item.get('status')
        if status == 'red': ft = f":red[{ft}]"
        elif status == 'yellow': ft = f":orange[{ft}]"
        elif status == 'green': ft = f"**:green[{ft}]**"
        
        with st.expander(ft):
            render_status_controls(item['id'], status, item.get('note', ''))
            
            col_ia_btn, col_ia_info = st.columns([0.4, 0.6])
            with col_ia_btn:
                has_via = "🛡️ VIABILIDADE" in content
                if st.button("🔄 Refazer Cruzamento" if has_via else "🚀 Cruzar Dados (Histórico)", key=f"via_{item['id']}"):
                    if user['plan'] == 'free': st.warning("Exclusivo Assinantes.")
                    else:
                        with st.spinner("Analisando..."):
                            c_files = db.get_all_company_files_as_bytes(user['username'])
                            if c_files:
                                try:
                                    gf = []; tps = []
                                    for n, d in c_files:
                                        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as t: t.write(d); tps.append(t.name)
                                        gf.append(genai.upload_file(t.name, display_name=n))
                                    
                                    prompt_h = f"ATUE COMO AUDITOR. Compare documentos anexos com este edital:\n{content}\nGere Checklist Viabilidade."
                                    res = genai.GenerativeModel('gemini-pro-latest').generate_content(gf + [prompt_h])
                                    db.db.collection('users').document(user['username']).collection('history').document(item['id']).update({'content': content + "\n\n---\n\n# 🛡️ VIABILIDADE\n" + res.text})
                                    for p in tps: os.remove(p)
                                    st.success("Atualizado!"); time.sleep(1); st.rerun()
                                except Exception as e: st.error(str(e))
                            else: st.error("Sem docs da empresa.")

            st.markdown(content)
            c1, c2 = st.columns([0.8, 0.2])
            with c1:
                pdf = convert_to_pdf(content)
                if pdf: st.download_button("📄 PDF", data=pdf, file_name=f"Relatorio_{item['id'][:6]}.pdf")
            with c2:
                if st.button("🗑️", key=f"d_{item['id']}"): db.delete_history_item(user['username'], item['id']); st.rerun()

# 5. CALENDÁRIO
elif menu == "📅 Calendário":
    st.title("📅 Calendário de Licitações")
    lst = db.get_user_history_list(user['username'])
    events = []
    
    for item in lst:
        if item.get('status') == 'green':
            full_title = extract_title(item['content'])
            date_iso = extract_date_for_calendar(full_title)
            if date_iso:
                events.append({"title": full_title[:50], "start": date_iso, "backgroundColor": "#28a745", "borderColor": "#28a745", "extendedProps": {"content": item['content']}})
    
    cal_state = calendar(events=events, options={"headerToolbar": {"left": "today prev,next", "center": "title", "right": "dayGridMonth,listMonth"}, "initialView": "dayGridMonth", "locale": "pt-br"}, key="cal_licita")
    
    if cal_state.get("eventClick"):
        props = cal_state["eventClick"]["event"].get("extendedProps", {})
        st.divider()
        with st.expander("📄 Ver Detalhes"):
            st.markdown(props.get("content", ""))

# 6. ASSINATURA
elif menu == "Assinatura":
    st.title("💎 Planos")
    st.info(f"Plano Atual: **{PLAN_MAP.get(user['plan'], user['plan']).upper()}**")
    cols = st.columns(4)
    plans = [("🥉 Plano 15", "15 Editais", "R$ 39,90"), ("🥈 Plano 30", "30 Editais", "R$ 69,90"), 
             ("🥇 Plano 60", "60 Editais", "R$ 109,90"), ("💎 Plano 90", "90 Editais", "R$ 149,90")]
    for i, (n, q, v) in enumerate(plans):
        with cols[i]:
            st.markdown(f"### {n}\n**{q}**\n### {v}"); st.button(f"Assinar {n}", key=f"b_{i}")
    st.markdown("---"); st.caption("Envie comprovante para o Suporte.")