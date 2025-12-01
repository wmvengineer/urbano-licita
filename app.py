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
# Define o ícone da página (Favicon)
icon_file = "LOGO URBANO OFICIAL.png" if os.path.exists("LOGO URBANO OFICIAL.png") else "🏢"
st.set_page_config(page_title="Urbano", layout="wide", page_icon=icon_file)

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

# --- CSS LIMPO (A Guilhotina resolve o rodapé no HTML) ---
st.markdown("""
    <style>
        /* Esconde menu superior (3 pontinhos) e cabeçalho */
        [data-testid="stToolbar"], [data-testid="stDecoration"], header {
            display: none !important;
        }
        
        /* Remove padding extra no fundo para aproveitar o espaço */
        .main .block-container {
            padding-bottom: 0px !important;
        }
    </style>
""", unsafe_allow_html=True)


# --- AUTOMAÇÃO DE E-MAILS (Disparo Diário) ---
try:
    if "daily_check_done" not in st.session_state:
        pass
        st.session_state.daily_check_done = True
except:
    pass

# --- ESTRUTURA DE DOCUMENTOS ---
DOC_STRUCTURE = {
    "1. Habilitacao Juridica": ["Contrato Social", "CNPJ", "Documentos Sócios"],
    "2. Habilitacao Fiscal": ["Federal", "Estadual", "Municipal", "FGTS", "Trabalhista"],
    "3. Qualificacao Tecnica": ["Atestados Operacionais", "Atestados Profissionais", "Certidao de Registro no Conselho - Profissionais", "Certidao de Registro no Conselho - Empresa"],
    "4. Habilitacao Financeira": ["Balanco Patrimonial", "Indices Financeiros", "Certidao Falencia"]
}

# --- FUNÇÕES AUXILIARES ---

def get_base64_image(image_path):
    """Converte imagem local para base64 para uso em HTML."""
    if os.path.exists(image_path):
        with open(image_path, "rb") as img_file:
            return base64.b64encode(img_file.read()).decode()
    return None

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

def extract_title(text):
    try:
        orgao = "Órgão Indefinido"
        match_orgao = re.search(r"(?:1\.|órgão).*?[:\-\?]\s*(.*?)(?:\n|2\.|Qual|$)", text, re.IGNORECASE)
        if match_orgao: 
            orgao = match_orgao.group(1).replace("*", "").strip()

        data_sessao = "Data Pendente"
        match_data_tag = re.search(r"DATA_CHAVE:\s*(\d{2}/\d{2}/\d{4})", text)
        
        if match_data_tag:
            data_sessao = match_data_tag.group(1)
        else:
            match_q5 = re.search(r"5\.(.*?)(?:6\.|CRONOGRAMA|\n\n|$)", text, re.DOTALL | re.IGNORECASE)
            if match_q5:
                match_generic = re.search(r"(\d{2}/\d{2}/\d{4})", match_q5.group(1))
                if match_generic: data_sessao = match_generic.group(1)

        return f"Edital {orgao} | {data_sessao}"
    except:
        return f"Edital Processado em {datetime.now().strftime('%d/%m/%Y')}"

def extract_date_for_calendar(title_str):
    try:
        match = re.search(r"(\d{2})/(\d{2})/(\d{4})", title_str)
        if match:
            return f"{match.group(3)}-{match.group(2)}-{match.group(1)}"
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
        elif new_status == 'yellow': placeholder_text = "Quais ajustes são necessários na documentação?"
        elif new_status == 'green': placeholder_text = "Observações para a participação..."
        
        new_note = st.text_area("Observações:", value=current_note, placeholder=placeholder_text, key=f"note_{item_id}")
        
        if st.button("💾 Salvar Observação", key=f"save_{item_id}"):
            db.update_analysis_status(st.session_state.user['username'], item_id, new_status, new_note)
            st.toast("Observação salva com sucesso!")

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

# --- TELA DE LOGIN (Redesign V3) ---
if not st.session_state.user:
    st.markdown("""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;700&display=swap');

        .stApp {
            background-image: url('https://colorlib.com/etc/lf/Login_v3/images/bg-01.jpg');
            background-size: cover;
            background-position: center;
            background-repeat: no-repeat;
            font-family: 'Poppins', sans-serif;
        }

        header {visibility: hidden;}
        footer {visibility: hidden;}
        .block-container {
            padding-top: 5rem;
            padding-bottom: 5rem;
        }

        div[data-testid="stForm"] {
            border-radius: 10px;
            padding: 55px 55px 37px 55px;
            overflow: hidden;
            background: #20404F;
            background: -webkit-linear-gradient(top, #394E53, #173a50);
            background: linear-gradient(top, #394E53, #173a50);
            box-shadow: 0 5px 15px rgba(0,0,0,0.3);
            border: none;
        }

        div[data-testid="stTextInput"] label, div[data-testid="stNumberInput"] label {
            color: #eeeeee !important;
            font-family: 'Poppins', sans-serif;
            font-size: 13px;
        }
        
        /* ALTERAÇÃO AQUI: Cor do texto mudada para #364C50 */
        div[data-testid="stTextInput"] input, div[data-testid="stNumberInput"] input {
            background-color: transparent !important;
            color: #364C50 !important; 
            border: none !important;
            border-bottom: 2px solid rgba(255,255,255,0.24) !important;
            border-radius: 0px !important;
            padding-left: 5px !important;
            font-family: 'Poppins', sans-serif;
        }
        
        div[data-testid="stTextInput"] input:focus, div[data-testid="stNumberInput"] input:focus {
            border-bottom: 2px solid #fff !important;
            box-shadow: none !important;
        }

        /* NOVA REGRA: Remove o texto "Press Enter to Submit Form" */
        [data-testid="InputInstructions"] {
            display: none !important;
        }

        /* Botões Gerais do Formulário */
        div.stButton > button {
            font-family: 'Poppins', sans-serif;
            font-size: 16px;
            color: #555555 !important;
            line-height: 1.2;
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 0 20px;
            min-width: 120px;
            height: 50px;
            border-radius: 25px;
            background: #fff !important;
            border: none !important;
            width: 100%;
            margin-top: 20px;
            font-weight: 600;
            transition: all 0.4s;
        }
        div.stButton > button:hover {
            background-color: #333 !important;
            color: #fff !important;
        }

        /* --- ESTILO DAS ABAS (Cor #364C50 Opaca) --- */
        .stTabs [data-baseweb="tab-list"] {
            gap: 10px;
            justify-content: center;
            margin-bottom: 20px;
            border-bottom: 1px solid rgba(255,255,255,0.1);
        }
        .stTabs [data-baseweb="tab"] {
            background-color: #364C50 !important;
            color: #fff !important;
            font-family: 'Poppins', sans-serif;
            font-size: 14px;
            border: none;
            border-radius: 15px 15px 0 0;
            padding: 10px 20px;
            margin-right: 2px;
            transition: all 0.3s;
            opacity: 1 !important;
        }
        .stTabs [aria-selected="true"] {
            background-color: #364C50 !important;
            font-weight: bold;
            opacity: 1 !important;
            border-bottom: 2px solid #fff;
        }
        .stTabs [data-baseweb="tab-highlight"] {
            background-color: transparent; 
        }

        /* 2. Botão Recuperar Senha (#babac2) */
        [data-testid="stForm"] [data-testid="stHorizontalBlock"] [data-testid="stColumn"]:nth-of-type(2) button {
            background-color: #babac2 !important;
            color: #fff !important;
        }
        [data-testid="stForm"] [data-testid="stHorizontalBlock"] [data-testid="stColumn"]:nth-of-type(2) button:hover {
            background-color: #9a9a9f !important;
        }

        /* Alerts */
        div[data-baseweb="notification"] {
            background-color: rgba(255, 255, 255, 0.9);
            border-radius: 10px;
        }
        
        [data-testid="stVerticalBlock"] > [style*="flex-direction: column;"] > [data-testid="stVerticalBlock"] {
            align-items: center;
        }
        </style>
    """, unsafe_allow_html=True)

    col_spacer_l, col_login, col_spacer_r = st.columns([1, 1.5, 1])
    
    with col_login:
        # Carrega imagem em Base64 para HTML
        img_b64 = get_base64_image("LOGO URBANO OFICIAL.png")
        img_src = f"data:image/png;base64,{img_b64}" if img_b64 else ""

        # Cabeçalho Visual (Logo e Título)
        # CONTAINER AUMENTADO (160px) COM IMAGEM FIXA (110px) PARA AUMENTAR BORDA BRANCA
        if img_src:
            html_logo = f"""
            <div style="text-align: center; margin-bottom: 30px;">
                <div style="
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    width: 160px;
                    height: 160px;
                    border-radius: 50%;
                    background-color: #fff;
                    margin: 0 auto;
                    overflow: hidden;
                    box-shadow: 0 4px 10px rgba(0,0,0,0.2);
                ">
                    <img src="{img_src}" style="width: 110px; height: auto; object-fit: contain;" />
                </div>
            </div>
            """
        else:
            # Fallback se a imagem não existir
            html_logo = """<div style="text-align: center; margin-bottom: 30px; font-size: 50px;">🏢</div>"""

        st.markdown(html_logo, unsafe_allow_html=True)

        t1, t2 = st.tabs(["ENTRAR", "CRIAR CONTA"])
        
        # --- ABA LOGIN ---
        with t1:
            with st.form("f_login"):
                u = st.text_input("Usuário ou E-mail", placeholder="Digite seu usuário ou e-mail")
                p = st.text_input("Senha", type="password", placeholder="Digite sua senha")
                
                # eCaptcha Login
                if 'log_n1' not in st.session_state: st.session_state.log_n1 = random.randint(1, 9)
                if 'log_n2' not in st.session_state: st.session_state.log_n2 = random.randint(1, 9)
                
                st.markdown(f"<p style='color: white; font-size: 12px; margin-bottom: 0px; margin-top: 15px;'>Segurança: Quanto é {st.session_state.log_n1} + {st.session_state.log_n2}?</p>", unsafe_allow_html=True)
                captcha_ans = st.number_input("Resultado Captcha", step=1, label_visibility="collapsed", key="in_cap_log")

                # Layout de Botões Lado a Lado
                c_btn_log, c_btn_rec = st.columns(2)
                
                with c_btn_log:
                    submitted_login = st.form_submit_button("LOGIN")
                with c_btn_rec:
                    submitted_recover = st.form_submit_button("RECUPERAR")

                if submitted_recover:
                    # Lógica de Recuperação
                    if not u or "@" not in u:
                        st.warning("Para recuperar sua senha, digite seu E-MAIL no campo 'Usuário ou E-mail' acima e clique em Recuperar novamente.")
                        st.session_state.log_n1 = random.randint(1, 9) # Reset Captcha
                    else:
                        real_ans = st.session_state.log_n1 + st.session_state.log_n2
                        if captcha_ans != real_ans:
                            st.error("Captcha incorreto.")
                        else:
                            with st.spinner("Enviando senha temporária..."):
                                ok, msg = db.recover_user_password(u)
                                if ok: st.success(msg)
                                else: st.error(msg)
                                time.sleep(2) # Dar tempo de ler

                elif submitted_login:
                    # Lógica de Login
                    real_ans = st.session_state.log_n1 + st.session_state.log_n2
                    if captcha_ans != real_ans:
                        st.error("eCaptcha incorreto.")
                        st.session_state.log_n1 = random.randint(1, 9)
                        st.session_state.log_n2 = random.randint(1, 9)
                        time.sleep(1)
                        st.rerun()
                    else:
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
        
        # --- ABA CADASTRO ---
        with t2:
            with st.form("f_cad"):
                nu = st.text_input("Usuário", placeholder="Escolha um usuário")
                nn = st.text_input("Nome", placeholder="Seu nome completo")
                ne = st.text_input("Email", placeholder="Seu melhor e-mail")
                np = st.text_input("Senha", type="password", placeholder="Escolha uma senha")
                
                # eCaptcha Cadastro
                if 'cad_n1' not in st.session_state: st.session_state.cad_n1 = random.randint(1, 9)
                if 'cad_n2' not in st.session_state: st.session_state.cad_n2 = random.randint(1, 9)
                
                st.markdown(f"<p style='color: white; font-size: 12px; margin-bottom: 0px; margin-top: 15px;'>Segurança: Quanto é {st.session_state.cad_n1} + {st.session_state.cad_n2}?</p>", unsafe_allow_html=True)
                cad_captcha_ans = st.number_input("Resultado Captcha Cad", step=1, label_visibility="collapsed", key="in_cap_cad")

                if st.form_submit_button("CADASTRAR"):
                    # Validação Captcha
                    real_cad_ans = st.session_state.cad_n1 + st.session_state.cad_n2
                    if cad_captcha_ans != real_cad_ans:
                        st.error("eCaptcha incorreto.")
                        st.session_state.cad_n1 = random.randint(1, 9)
                        st.session_state.cad_n2 = random.randint(1, 9)
                        time.sleep(1)
                        st.rerun()
                    else:
                        ok, m = db.register_user(nu, nn, ne, np)
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
    limit = db.get_plan_limit(user['plan'])
else: logout()

# --- CSS PARA A SIDEBAR (Barra Lateral) ---
st.markdown("""
    <style>
    /* Altera o fundo da Sidebar para #364C50 */
    [data-testid="stSidebar"] {
        background-color: #364C50;
    }
    
    /* Altera todos os textos da Sidebar para Branco */
    [data-testid="stSidebar"] h1, 
    [data-testid="stSidebar"] h2, 
    [data-testid="stSidebar"] h3, 
    [data-testid="stSidebar"] span, 
    [data-testid="stSidebar"] div, 
    [data-testid="stSidebar"] label, 
    [data-testid="stSidebar"] p {
        color: #FFFFFF !important;
    }
    
    /* Mantém o texto interno do botão "Sair" na cor original (escuro) para contraste com o botão branco */
    [data-testid="stSidebar"] .stButton button div,
    [data-testid="stSidebar"] .stButton button p {
        color: #31333F !important;
    }
    </style>
""", unsafe_allow_html=True)

with st.sidebar:
    # LOGO EM CÍRCULO BRANCO (250px container / 150px logo)
    img_b64_side = get_base64_image("LOGO URBANO OFICIAL.png")
    if img_b64_side:
        st.markdown(f"""
            <div style="display: flex; justify-content: center; margin-bottom: 20px;">
                <div style="
                    width: 200px;
                    height: 200px;
                    background-color: white;
                    border-radius: 50%;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    overflow: hidden;
                    box-shadow: 0 4px 6px rgba(0,0,0,0.3);
                ">
                    <img src="data:image/png;base64,{img_b64_side}" style="width: 150px; height: auto; object-fit: contain;">
                </div>
            </div>
        """, unsafe_allow_html=True)
    else:
        # Fallback
        st.markdown("<div style='font-size: 80px; text-align: center; color: white;'>🏢</div>", unsafe_allow_html=True)

    st.markdown(f"### Olá, {user['name']}")
    st.caption(f"Plano: **{user['plan'].upper()}**")
    pct = min(user['credits']/limit, 1.0) if limit > 0 else 1.0
    st.progress(pct)
    st.write(f"Análises: {user['credits']} / {limit}")
    if user['credits'] >= limit and limit < 9999: st.error("Limite atingido!")

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
        st.divider()
        st.subheader("📧 Central de Notificações")
        
        col_test, col_run = st.columns(2)
        
        with col_test:
            st.markdown("#### Teste de SMTP")
            test_email = st.text_input("E-mail para teste", value=st.session_state.user['email'] if st.session_state.user.get('email') else "")
            if st.button("📨 Enviar E-mail de Teste"):
                if test_email:
                    with st.spinner("Conectando ao Zoho..."):
                        ok, msg = db.send_email(
                            test_email, 
                            "Teste de SMTP - Urbano", 
                            "<h1>Funciona!</h1><p>Seu sistema de e-mail está configurado corretamente.</p>"
                        )
                        if ok: st.success(msg)
                        else: st.error(msg)
                else:
                    st.warning("Preencha um e-mail.")

        with col_run:
            st.markdown("#### Disparo Manual de Avisos")
            if st.button("🚀 Rodar Verificação de Prazos"):
                with st.spinner("Verificando datas e enviando e-mails..."):
                    log = db.check_deadlines_and_notify()
                    st.text_area("Log de Execução", value=log, height=200)

        st.divider()            

# 2. DOCUMENTOS
elif menu == "📂 Documentos da Empresa":
    st.title("📂 Acervo Digital")
    st.info("Estes documentos serão usados para o Cruzamento Automático.")
    
    with st.expander("⬆️ Upload", expanded=False):
        c1, c2 = st.columns(2)
        s = c1.selectbox("Pasta", list(DOC_STRUCTURE.keys()))
        t = c2.selectbox("Tipo", DOC_STRUCTURE[s])
        
        # --- LÓGICA DE LIMPEZA DO UPLOADER ---
        # Inicializa um contador na sessão para controlar o reset do uploader
        if "uploader_key" not in st.session_state:
            st.session_state["uploader_key"] = 0
            
        # O parâmetro 'key' dinâmico força o componente a resetar quando o número muda
        files = st.file_uploader(
            "Arquivos PDF", 
            type=["pdf"], 
            accept_multiple_files=True, 
            key=f"uploader_{st.session_state['uploader_key']}"
        )
        
        if files and st.button("Salvar na Nuvem"):
            with st.spinner(f"Enviando {len(files)} arquivos..."):
                count_success = 0
                for f in files:
                    safe = re.sub(r'[\\/*?:"<>|]', "", f.name)
                    if db.upload_file_to_storage(f.getvalue(), safe, user['username'], s, t):
                        count_success += 1
                    else:
                        st.error(f"Erro ao enviar: {f.name}")
                
                if count_success > 0:
                    st.success(f"{count_success} arquivo(s) salvo(s) com sucesso!")
                    # INCREMENTA A CHAVE PARA LIMPAR O CAMPO NO PRÓXIMO RERUN
                    st.session_state["uploader_key"] += 1
                    time.sleep(1)
                    st.rerun()

    st.divider()
    for sec, types in DOC_STRUCTURE.items():
        st.markdown(f"**{sec}**")
        cols = st.columns(3)
        for i, t in enumerate(types):
            with cols[i%3]:
                files = db.list_files_from_storage(user['username'], sec, t)
                with st.expander(f"{t} ({len(files)})"):
                    # ALTERAÇÃO AQUI: Adicionamos 'idx' (índice) no loop
                    for idx, file in enumerate(files):
                        c_tx, c_del = st.columns([0.8, 0.2])
                        c_tx.caption(file[:20]+"...")
                        
                        # ALTERAÇÃO AQUI: A key agora é única combinando: seção + tipo + indice + nome
                        unique_key = f"del_{sec}_{t}_{idx}_{file}"
                        
                        if c_del.button("🗑️", key=unique_key):
                            db.delete_file_from_storage(file, user['username'], sec, t)
                            st.rerun()

# 3. ANÁLISE
elif menu == "Análise de Editais":
    st.title("🔍 Analisar Novo Edital")
    
    if st.session_state.analise_atual:
        if st.button("🔄 Nova Análise"):
            st.session_state.analise_atual = None
            st.session_state.gemini_files_handles = []
            st.session_state.chat_history = []
            st.session_state.last_analysis_id = None
            st.rerun()
    
    if not st.session_state.analise_atual:
        if user['credits'] >= limit: st.warning("Limite atingido."); st.stop()
        
        st.markdown("""
            <style>
            [data-testid='stFileUploaderDropzoneInstructions'] > div > span {
                display: none;
            }
            [data-testid='stFileUploaderDropzoneInstructions'] > div > small {
                display: none;
            }
            [data-testid='stFileUploaderDropzoneInstructions'] > div::after {
                content: "Arraste e solte arquivos aqui \\A Limite 25MB por arquivo • PDF";
                white-space: pre-wrap;
                text-align: center;
                display: block;
                color: rgba(49, 51, 63, 0.6);
                font-size: 14px;
            }
            [data-testid='stFileUploader'] button {
                color: transparent !important;
                position: relative;
                min-width: 180px;
            }
            [data-testid='stFileUploader'] button::after {
                content: "Procurar arquivos";
                color: rgb(49, 51, 63);
                font-size: 14px;
                position: absolute;
                left: 0;
                top: 0;
                width: 100%;
                height: 100%;
                display: flex;
                align-items: center;
                justify-content: center;
                pointer-events: none;
            }
            </style>
        """, unsafe_allow_html=True)

        ups = st.file_uploader("Upload Edital + Anexos", type=["pdf"], accept_multiple_files=True)
        
        valid_files = []
        if ups:
            for up in ups:
                if up.size > 25 * 1024 * 1024:
                    st.error(f"⚠️ O arquivo '{up.name}' excede o limite de 25MB e foi ignorado.")
                else:
                    valid_files.append(up)
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
                    
                    status.write("Gerando Relatório Detalhado...")
                    model = genai.GenerativeModel('gemini-pro-latest')
                    
                    prompt = """
                    ATUE COMO AUDITOR SÊNIOR DE ENGENHARIA.
                    Analise TODOS os documentos fornecidos (Edital e Anexos) com extremo rigor.
                    Responda pontualmente às 16 questões abaixo. Use Markdown para formatar.

                    1. Qual o nome do órgão contratante?
                    2. Qual o objeto do edital? (Resumo completo)
                    3. Qual o valor estimado para a realização dos serviços?
                    4. Qual a plataforma onde será realizado o certame?
                    5. Qual a data de realização do certame? (Inicie sua resposta EXATAMENTE com "DATA_CHAVE: DD/MM/YYYY". Se não houver sessão física, coloque a data limite de propostas neste formato).
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
            st.info("Classifique este edital para organizá-lo no Histórico e Calendário:")
            curr_item = db.get_history_item(user['username'], st.session_state.last_analysis_id)
            if curr_item:
                render_status_controls(st.session_state.last_analysis_id, curr_item.get('status'), curr_item.get('note', ''))
            st.divider()

        st.markdown(st.session_state.analise_atual)
        st.divider()
        
        st.subheader("🚀 Cruzamento de Dados")
        if user['plan'] == 'free': st.info("🔒 Upgrade necessário.")
        else:
            if st.button("Verificar Minha Viabilidade"):
                with st.spinner("Comparando documentos..."):
                    c_files = db.get_all_company_files_as_bytes(user['username'])
                    if not c_files: st.warning("Sem docs da empresa.")
                    else:
                        temps = []
                        for n, d in c_files:
                            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as t:
                                t.write(d); tp = t.name
                            temps.append(genai.upload_file(tp, display_name=n)); os.remove(tp)
                        
                        prompt = "Checklist de Viabilidade: Edital vs Empresa. Para cada item: Edital pede X -> Empresa tem Y -> Veredito."
                        model = genai.GenerativeModel('gemini-pro-latest')
                        resp = model.generate_content(st.session_state.gemini_files_handles + temps + [prompt])
                        st.session_state.analise_atual += "\n\n---\n\n# 🛡️ VIABILIDADE\n" + resp.text
                        st.rerun()
        
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
                    content += "\n\n<div class='chat-section'><h1>💬 Histórico de Dúvidas</h1>"
                    for r, t in st.session_state.chat_history:
                        content += f"<p class='chat-q'>{r.upper()}: {t}</p>"
                    content += "</div>"
                pdf = convert_to_pdf(content)
                if pdf: st.download_button("⬇️ Download PDF", data=pdf, file_name=f"Analise_{datetime.now().strftime('%Y%m%d')}.pdf", mime="application/pdf")
                else: st.error("Erro PDF.")

# 4. HISTÓRICO
elif menu == "📜 Histórico":
    st.title("Biblioteca de Análises")
    lst = db.get_user_history_list(user['username'])
    
    if not lst: 
        st.info("Vazio.")
    else:
        # --- EXCLUSÃO EM MASSA (MANTIDO) ---
        with st.expander("🗑️ Gerenciar / Excluir Vários"):
            st.caption("Selecione os itens que deseja excluir permanentemente e clique no botão abaixo.")
            
            table_data = []
            for item in lst:
                # Extração simples para a tabela de gestão
                raw_t = extract_title(item['content'])
                d_str = item['created_at'].strftime("%d/%m/%Y")
                table_data.append({"id": item['id'], "Excluir": False, "Data": d_str, "Título": raw_t})
            
            df_hist = pd.DataFrame(table_data)
            edited_df = st.data_editor(
                df_hist,
                column_config={
                    "id": None, 
                    "Excluir": st.column_config.CheckboxColumn("Selecionar", default=False, width="small"),
                    "Data": st.column_config.TextColumn("Data", disabled=True, width="small"),
                    "Título": st.column_config.TextColumn("Edital", disabled=True, width="large")
                },
                hide_index=True, use_container_width=True, key="editor_mass_delete"
            )
            
            if st.button("🗑️ Excluir Selecionados", type="primary"):
                selected_rows = edited_df[edited_df["Excluir"] == True]
                if not selected_rows.empty:
                    count_del = 0
                    with st.spinner("Excluindo itens..."):
                        for index, row in selected_rows.iterrows():
                            if db.delete_history_item(user['username'], row['id']): count_del += 1
                    if count_del > 0:
                        st.success(f"{count_del} análises excluídas!"); time.sleep(1); st.rerun()
                else: st.warning("Nenhum item selecionado.")
        
        st.divider()

    # --- LISTAGEM COM NOVO PADRÃO DE TÍTULO E CRUZAMENTO ---
    for item in lst:
        chat_key = f"hist_chat_{item['id']}"
        if chat_key not in st.session_state: st.session_state[chat_key] = []
        
        # 1. Extração de Dados para o Título Personalizado
        dt_consulta = item['created_at'].strftime("%d/%m/%Y")
        content_txt = item['content']
        
        # Extrair Órgão
        match_org = re.search(r"(?:1\.|órgão).*?[:\-\?]\s*(.*?)(?:\n|2\.|Qual|$)", content_txt, re.IGNORECASE)
        orgao = match_org.group(1).replace("*", "").strip() if match_org else "Órgão Indefinido"
        
        # Extrair Objeto (Limita a 80 caracteres para não quebrar layout)
        match_obj = re.search(r"(?:2\.|objeto).*?[:\-\?]\s*(.*?)(?:\n|3\.|Qual|$)", content_txt, re.IGNORECASE | re.DOTALL)
        objeto = "Objeto Indefinido"
        if match_obj:
            raw_obj = match_obj.group(1).replace("*", "").replace("\n", " ").strip()
            objeto = (raw_obj[:75] + '...') if len(raw_obj) > 75 else raw_obj

        # Extrair Data Sessão
        match_sessao = re.search(r"DATA_CHAVE:\s*(\d{2}/\d{2}/\d{4})", content_txt)
        dt_sessao = match_sessao.group(1) if match_sessao else "Data Pendente"

        # TÍTULO FORMATADO: {Data da Consulta}| Edital | {Órgão} | {Objeto} | {Data da Sessão}
        full_display_title = f"{dt_consulta} | Edital | {orgao} | {objeto} | {dt_sessao}"
        
        # Aplicação de Cores baseada no Status
        status = item.get('status')
        if status == 'red': full_display_title = f":red[{full_display_title}]"
        elif status == 'yellow': full_display_title = f":orange[{full_display_title}]"
        elif status == 'green': full_display_title = f"**:green[{full_display_title}]**"
        
        with st.expander(full_display_title):
            render_status_controls(item['id'], status, item.get('note', ''))
            
            # --- NOVO RECURSO: CRUZAMENTO DE DADOS NO HISTÓRICO ---
            st.info("🧠 Inteligência Artificial")
            col_ia_btn, col_ia_info = st.columns([0.4, 0.6])
            
            with col_ia_btn:
                # Verifica se já foi feita viabilidade (busca string chave no conteúdo)
                has_viability = "🛡️ VIABILIDADE" in content_txt
                btn_label = "🔄 Refazer Cruzamento (Viabilidade)" if has_viability else "🚀 Cruzar Dados (Edital x Empresa)"
                
                if st.button(btn_label, key=f"via_{item['id']}"):
                    if user['plan'] == 'free':
                        st.warning("Recurso exclusivo para assinantes.")
                    else:
                        with st.spinner("Baixando documentos e analisando compatibilidade..."):
                            # 1. Baixar Docs da Empresa
                            c_files = db.get_all_company_files_as_bytes(user['username'])
                            if not c_files:
                                st.error("Você não tem documentos na pasta da empresa.")
                            else:
                                try:
                                    # 2. Preparar Upload para Gemini
                                    temps = []
                                    gemini_files = []
                                    for n, d in c_files:
                                        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as t:
                                            t.write(d); tp = t.name
                                        temps.append(tp)
                                        gemini_files.append(genai.upload_file(tp, display_name=n))
                                    
                                    # 3. Gerar Análise
                                    prompt_hist = f"""
                                    ATUE COMO AUDITOR. 
                                    Compare os documentos anexados da empresa com o seguinte resumo de edital:
                                    
                                    --- INÍCIO RESUMO EDITAL ---
                                    {content_txt}
                                    --- FIM RESUMO EDITAL ---
                                    
                                    Gere um Checklist de Viabilidade: Item do Edital pede X -> Empresa tem Y -> Veredito (Apto/Inapto/Atenção).
                                    """
                                    model = genai.GenerativeModel('gemini-pro-latest')
                                    resp = model.generate_content(gemini_files + [prompt_hist])
                                    
                                    # 4. Atualizar no Banco de Dados (Append)
                                    new_content = content_txt + "\n\n---\n\n# 🛡️ VIABILIDADE (Gerada via Histórico)\n" + resp.text
                                    
                                    # Atualiza no Firestore diretamente para persistir
                                    db.db.collection('users').document(user['username']).collection('history').document(item['id']).update({
                                        'content': new_content
                                    })
                                    
                                    # Limpeza
                                    for tp in temps: os.remove(tp)
                                    
                                    st.success("Análise de viabilidade adicionada ao registro!")
                                    time.sleep(1.5)
                                    st.rerun()
                                    
                                except Exception as e:
                                    st.error(f"Erro na análise IA: {e}")

            st.divider()
            
            # Exibição do Conteúdo
            st.markdown(item['content'])
            
            c1, c2 = st.columns([0.8, 0.2])
            with c1:
                pdf = convert_to_pdf(item['content'])
                if pdf: st.download_button("📄 PDF", data=pdf, file_name=f"Relatorio_{item['id'][:6]}.pdf")
            with c2:
                if st.button("🗑️", key=f"d_{item['id']}"):
                    db.delete_history_item(user['username'], item['id']); st.rerun()
            
            st.markdown("---")
            st.subheader("💬 Dúvidas (Histórico)")
            for r, t in st.session_state[chat_key]:
                with st.chat_message(r): st.markdown(t)
            if q := st.chat_input("Pergunta sobre este edital...", key=f"in_{item['id']}"):
                st.session_state[chat_key].append(("user", q))
                with st.chat_message("user"): st.markdown(q)
                with st.chat_message("assistant"):
                    with st.spinner("..."):
                        try:
                            m = genai.GenerativeModel('gemini-pro-latest')
                            # Contexto é o texto do edital salvo
                            res = m.generate_content(f"Contexto do Edital: {item['content']}\nPergunta do Usuário: {q}")
                            st.markdown(res.text)
                            st.session_state[chat_key].append(("assistant", res.text))
                        except: st.error("Erro na resposta IA.")

# 5. CALENDÁRIO
elif menu == "📅 Calendário":
    st.title("📅 Calendário de Licitações")
    st.caption("Apenas editais marcados como 'Apto' (Verde).")
    st.info("💡 Clique em uma barra verde para ver os detalhes abaixo.")
    
    lst = db.get_user_history_list(user['username'])
    events = []
    
    for item in lst:
        if item.get('status') == 'green':
            full_title = extract_title(item['content'])
            date_iso = extract_date_for_calendar(full_title)
            
            if date_iso:
                orgao_cal = "Órgão"
                match_org = re.search(r"(?:1\.|órgão).*?[:\-\?]\s*(.*?)(?:\n|2\.|Qual|$)", item['content'], re.IGNORECASE)
                if match_org: orgao_cal = match_org.group(1).replace("*", "").strip()[:30]

                obj_cal = "Geral"
                match_obj = re.search(r"(?:2\.|objeto).*?[:\-\?]\s*(.*?)(?:\n|3\.|Qual|$)", item['content'], re.IGNORECASE | re.DOTALL)
                if match_obj:
                    raw_o = match_obj.group(1).replace("*", "").strip()
                    raw_o = re.sub(r'[^\w\s]', '', raw_o)
                    obj_cal = " ".join(raw_o.split()[:3])
                
                title_for_event = f"{orgao_cal} - {obj_cal}"

                events.append({
                    "title": title_for_event,
                    "start": date_iso,
                    "backgroundColor": "#28a745",
                    "borderColor": "#28a745",
                    "extendedProps": {
                        "content": item['content'],
                        "original_title": full_title
                    }
                })
    
    if not events:
        st.info("Nenhum edital verde com data encontrada. O calendário aparecerá vazio.")

    calendar_options = {
        "headerToolbar": {"left": "today prev,next", "center": "title", "right": "dayGridMonth,listMonth"},
        "initialView": "dayGridMonth",
        "locale": "pt-br"
    }
    
    cal_state = calendar(
        events=events,
        options=calendar_options,
        custom_css=".fc-event-title { white-space: normal !important; cursor: pointer !important; }",
        key="cal_licita"
    )
    
    if cal_state.get("eventClick"):
        clicked_event = cal_state["eventClick"]["event"]
        
        title_clk = clicked_event.get("title", "Sem título")
        props = clicked_event.get("extendedProps", {})
        content_view = props.get("content", "")
        
        st.divider()
        st.subheader(f"📌 {title_clk}")
        
        with st.expander("📄 Ver Análise Completa (Clique para expandir)"):
            st.markdown(content_view)
            st.divider()
            pdf = convert_to_pdf(content_view)
            if pdf: 
                st.download_button("⬇️ Baixar PDF da Análise", data=pdf, file_name="analise_completa.pdf")

# 6. ASSINATURA
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