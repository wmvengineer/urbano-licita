import firebase_admin
from firebase_admin import credentials, firestore, storage
import bcrypt
import secrets
import datetime
import streamlit as st
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr 
import re
import pandas as pd


# --- CONFIGURAÇÃO ---
# ⚠️ SUBSTITUA PELO SEU ID REAL DO FIREBASE STORAGE (sem gs://)
BUCKET_NAME = "urbano-licita.firebasestorage.app" 

# --- CONEXÃO COM O FIREBASE (SINGLETON) ---
if not firebase_admin._apps:
    try:
        if "FIREBASE_KEY" in st.secrets:
            key_dict = dict(st.secrets["FIREBASE_KEY"])
            cred = credentials.Certificate(key_dict)
            firebase_admin.initialize_app(cred, {
                'storageBucket': BUCKET_NAME
            })
        else:
            cred = credentials.Certificate("firebase_key.json")
            firebase_admin.initialize_app(cred, {
                'storageBucket': BUCKET_NAME
            })
    except Exception as e:
        st.error(f"Erro crítico no Banco de Dados: {e}")
        st.stop()

# Clientes
db = firestore.client()
try:
    bucket = storage.bucket(name=BUCKET_NAME)
except Exception as e:
    st.error(f"Erro ao conectar no Storage: {e}")

# --- AUTENTICAÇÃO E USUÁRIOS ---

def init_db():
    """Cria o usuário Admin padrão se não existir."""
    try:
        users_ref = db.collection('users')
        if not users_ref.document('admin').get().exists:
            pwd_bytes = "admin123".encode('utf-8')
            hashed = bcrypt.hashpw(pwd_bytes, bcrypt.gensalt()).decode('utf-8')
            users_ref.document('admin').set({
                'username': 'admin',
                'name': 'Administrador Urbano',
                'email': 'admin@urbano.com',
                'password_hash': hashed,
                'role': 'admin',
                'plan_type': 'unlimited',
                'credits_used': 0,
                'session_token': '',
                'created_at': datetime.datetime.now()
            })
    except Exception as e:
        print(f"Erro init DB: {e}")

def register_user(username, name, email, password):
    try:
        users_ref = db.collection('users')
        if users_ref.document(username).get().exists:
            return False, "Nome de usuário já existe."
        
        hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        users_ref.document(username).set({
            'username': username,
            'name': name,
            'email': email,
            'password_hash': hashed,
            'role': 'user',
            'plan_type': 'free',
            'credits_used': 0,
            'session_token': '',
            'created_at': datetime.datetime.now()
        })
        return True, "Cadastro realizado!"
    except Exception as e:
        return False, str(e)

def login_user(username, password):
    try:
        doc = db.collection('users').document(username).get()
        if doc.exists:
            d = doc.to_dict()
            stored_hash = d.get('password_hash', '')
            
            password_ok = False
            if password == "ignorar_senha_aqui": password_ok = True 
            elif bcrypt.checkpw(password.encode('utf-8'), stored_hash.encode('utf-8')): password_ok = True
            
            if password_ok:
                token = d.get('session_token', '')
                if password != "ignorar_senha_aqui":
                    token = secrets.token_hex(16)
                    db.collection('users').document(username).update({'session_token': token})
                
                return True, {
                    "username": username,
                    "name": d.get('name'),
                    "role": d.get('role', 'user'),
                    "plan_type": d.get('plan_type', 'free'),
                    "credits_used": d.get('credits_used', 0),
                    "token": token
                }
        return False, None
    except: return False, None

def check_session_valid(username, current_token):
    try:
        doc = db.collection('users').document(username).get()
        return doc.exists and doc.to_dict().get('session_token') == current_token
    except: return False

def get_user_by_username(username):
    success, data = login_user(username, "ignorar_senha_aqui")
    return data if success else None

# --- SISTEMA DE CRÉDITOS ---

def get_plan_limit(plan_type):
    limits = {'free': 5, 'plano_15': 15, 'plano_30': 30, 'plano_60': 60, 'plano_90': 90, 'unlimited': 999999}
    return limits.get(plan_type, 5)

def consume_credit_atomic(username):
    try:
        db.collection('users').document(username).update({'credits_used': firestore.Increment(1)})
        return True
    except: return False

def refund_credit_atomic(username):
    try:
        db.collection('users').document(username).update({'credits_used': firestore.Increment(-1)})
    except: pass

# --- SISTEMA DE ARQUIVOS (STORAGE) ---

def upload_file_to_storage(file_bytes, filename, user_folder, section, sub_item):
    try:
        path = f"{user_folder}/{section}/{sub_item}/{filename}"
        bucket.blob(path).upload_from_string(file_bytes, content_type='application/pdf')
        return True
    except: return False

def list_files_from_storage(user_folder, section, sub_item):
    try:
        blobs = bucket.list_blobs(prefix=f"{user_folder}/{section}/{sub_item}/")
        return [b.name.split('/')[-1] for b in blobs if b.name.split('/')[-1]]
    except: return []

def delete_file_from_storage(filename, user_folder, section, sub_item):
    try:
        path = f"{user_folder}/{section}/{sub_item}/{filename}"
        bucket.blob(path).delete()
        return True
    except: return False

def get_all_company_files_as_bytes(username):
    """Baixa arquivos da empresa para memória (para o cruzamento)."""
    files_data = []
    try:
        blobs = bucket.list_blobs(prefix=f"{username}/")
        for blob in blobs:
            if blob.name.endswith(".pdf"):
                name = blob.name.split('/')[-1]
                data = blob.download_as_bytes()
                files_data.append((name, data))
        return files_data
    except: return []

# --- HISTÓRICO E STATUS (ATUALIZADO) ---

def save_analysis_history(username, title, full_text):
    """Salva e retorna o ID do documento criado."""
    try:
        _, doc_ref = db.collection('users').document(username).collection('history').add({
            'title': title, 
            'content': full_text, 
            'created_at': datetime.datetime.now(),
            'status': None, # red, yellow, green
            'note': ''      # Observação do cliente
        })
        return doc_ref.id
    except: return None

def update_analysis_status(username, doc_id, status, note):
    """Atualiza a cor e observação de um edital."""
    try:
        db.collection('users').document(username).collection('history').document(doc_id).update({
            'status': status,
            'note': note
        })
        return True
    except: return False

def get_user_history_list(username):
    try:
        docs = db.collection('users').document(username).collection('history')\
                 .order_by('created_at', direction=firestore.Query.DESCENDING).stream()
        return [{'id': d.id, **d.to_dict()} for d in docs]
    except: return []

def get_history_item(username, doc_id):
    """Busca um item específico do histórico pelo ID (Correção do Loop)."""
    try:
        doc = db.collection('users').document(username).collection('history').document(doc_id).get()
        if doc.exists:
            return doc.to_dict()
        return None
    except: return None

def delete_history_item(username, doc_id):
    try:
        db.collection('users').document(username).collection('history').document(doc_id).delete()
        return True
    except: return False

# --- FUNÇÕES ADMIN ---

def admin_get_users_stats():
    try:
        users = db.collection('users').stream()
        data = []
        for u in users:
            d = u.to_dict()
            data.append({
                'username': d['username'],
                'name': d['name'],
                'email': d.get('email', '-'),
                'plan': d.get('plan_type', 'free'),
                'credits': d.get('credits_used', 0),
                'joined': d.get('created_at', datetime.datetime.now())
            })
        return data
    except: return []

def admin_update_plan(username, new_plan):
    try:
        db.collection('users').document(username).update({'plan_type': new_plan})
        return True
    except: return False

def admin_set_credits_used(username, new_amount):
    try:
        val = int(new_amount)
        if val < 0: val = 0
        db.collection('users').document(username).update({'credits_used': val})
        return True
    except: return False

    
# --- SISTEMA DE NOTIFICAÇÃO E E-MAIL (ATUALIZADO - RESUMO DIÁRIO) ---

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import re
import pandas as pd
import datetime

def send_email(to_email, subject, body_html):
    """Envia um e-mail genérico usando as configurações do secrets."""
    try:
        smtp_server = st.secrets["EMAIL"]["SMTP_SERVER"]
        smtp_port = st.secrets["EMAIL"]["SMTP_PORT"]
        sender_email = st.secrets["EMAIL"]["EMAIL_ADDRESS"]
        sender_password = st.secrets["EMAIL"]["EMAIL_PASSWORD"]

        msg = MIMEMultipart()
        
        # ATUALIZAÇÃO: Uso de formataddr para "Nome <email>" sem erro 553
        msg['From'] = formataddr(("Urbano Soluções Integradas", sender_email))
        
        msg['To'] = to_email
        msg['Subject'] = subject

        msg.attach(MIMEText(body_html, 'html'))

        with smtplib.SMTP_SSL(smtp_server, smtp_port) as server:
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, to_email, msg.as_string())
        
        return True, "Enviado"
    except Exception as e:
        return False, str(e)

def count_business_days_left(start_date, end_date):
    if start_date >= end_date: return 0
    try:
        # Freq='B' força dias úteis.
        bdays = pd.bdate_range(start=start_date, end=end_date, freq='B')
        # Subtrai 1 pois o range é inclusivo
        return len(bdays) - 1
    except: return 999

def extract_details_from_text(full_text):
    """Tenta pescar Plataforma e Horário do texto do edital."""
    details = {
        "plataforma": "Verificar no Edital",
        "hora": "09:00 (Estimar)"
    }
    
    # Tenta achar plataforma
    match_plat = re.search(r"(?:plataforma|portal|sítio eletrônico|endereço eletrônico).*?[:\-\?]\s*(.*?)(?:\n|\.|,)", full_text, re.IGNORECASE)
    if match_plat:
        clean = match_plat.group(1).strip()[:50] # Limita caracteres
        
        # [MODIFICAÇÃO] Limpeza de prefixos de URL para exibir apenas o nome
        clean = clean.replace("https://", "").replace("http://", "").replace("www.", "").rstrip("/")
        
        if len(clean) > 3: details["plataforma"] = clean
        
    # Tenta achar horário (padrão HH:MM ou HHhMM)
    match_hora = re.search(r"(\d{2}[:h]\d{2})", full_text)
    if match_hora:
        details["hora"] = match_hora.group(1).replace('h', ':')
        
    return details

def check_deadlines_and_notify():
    """
    Gera um RESUMO agrupado por usuário com todos os editais próximos.
    Roda às 08h e 16h (definido no GitHub Actions).
    """
    logs = []
    users_ref = db.collection('users').stream()
    
    # Ajuste de Fuso Horário Manual (UTC-3 para garantir data do Brasil)
    now_br = datetime.datetime.now() - datetime.timedelta(hours=3)
    today = now_br.date()
    
    # 1. VARRER USUÁRIOS
    for u in users_ref:
        user_data = u.to_dict()
        email = user_data.get('email')
        username = user_data.get('username')
        name = user_data.get('name', 'Licitante')
        
        if not email: continue
        
        # Lista para armazenar os editais deste usuário
        pending_bids = []
        found_greens = 0
        
        # Busca histórico VERDE (Apto)
        docs = db.collection('users').document(username).collection('history').where('status', '==', 'green').stream()
        
        for doc in docs:
            try:
                found_greens += 1
                data = doc.to_dict()
                title = data.get('title', 'Sem Título')
                full_content = data.get('content', '')
                
                # Extrai Data (Procura padrão DD/MM/YYYY em qualquer lugar do título)
                match_date = re.search(r"(\d{2})/(\d{2})/(\d{4})", title)
                if match_date:
                    event_date_str = f"{match_date.group(3)}-{match_date.group(2)}-{match_date.group(1)}"
                    event_date = pd.to_datetime(event_date_str).date()
                    
                    bdays_left = count_business_days_left(today, event_date)
                    
                    # CRITÉRIO: Entre 0 e 2 dias úteis restantes
                    if 0 <= bdays_left <= 2:
                        
                        # Tenta extrair Órgão/Objeto do pipe, senão usa título todo
                        parts = title.split('|')
                        orgao = parts[0].replace("Edital", "").strip() if len(parts) > 1 else title[:30]
                        objeto = parts[1].strip() if len(parts) > 1 else "Ver Detalhes"
                        
                        extracted = extract_details_from_text(full_content)
                        
                        pending_bids.append({
                            "orgao": orgao,
                            "objeto": objeto,
                            "data": match_date.group(0),
                            "dias_restantes": bdays_left,
                            "hora": extracted['hora'],
                            "plataforma": extracted['plataforma']
                        })
            except Exception as e_item:
                print(f"Erro item {doc.id}: {e_item}")
                continue
        
        # 2. SE HOUVER EDITAIS, ENVIA 1 E-MAIL AGREGADO
        if pending_bids:
            # Ordena por data (mais urgente primeiro)
            pending_bids.sort(key=lambda x: x['dias_restantes'])
            
            # Monta linhas da tabela HTML
            rows_html = ""
            for bid in pending_bids:
                color = "#d4edda" if bid['dias_restantes'] <= 1 else "#fff3cd" # Verde se urgente, Amarelo se atenção
                msg_prazo = "🚨 É AMANHÃ/HOJE!" if bid['dias_restantes'] <= 1 else "⏳ 2 dias úteis"
                
                rows_html += f"""
                <tr style="background-color: {color}; border-bottom: 1px solid #ddd;">
                    <td style="padding: 10px;"><b>{bid['orgao']}</b><br><span style="font-size:12px; color:#555">{bid['objeto']}</span></td>
                    <td style="padding: 10px; text-align:center;"><b>{bid['data']}</b><br>{bid['hora']}</td>
                    <td style="padding: 10px; text-align:center;">{bid['plataforma']}</td>
                    <td style="padding: 10px; text-align:center; font-weight:bold; color:#d9534f;">{msg_prazo}</td>
                </tr>
                """

            # Monta Corpo do E-mail (COM LINK NO FINAL)
            email_body = f"""
            <html>
            <body style="font-family: Arial, sans-serif; color: #333;">
                <div style="max-width: 600px; margin: 0 auto; border: 1px solid #eee; padding: 20px; border-radius: 8px;">
                    <h2 style="color: #0044cc; text-align: center;">📅 Resumo de Licitações</h2>
                    <p>Olá, <b>{name}</b>!</p>
                    <p>Aqui está o resumo atualizado dos seus certames marcados como <b>APTO</b> para os próximos dias.</p>
                    
                    <table style="width: 100%; border-collapse: collapse; margin-top: 20px; font-size: 14px;">
                        <thead>
                            <tr style="background-color: #0044cc; color: white;">
                                <th style="padding: 10px; text-align: left;">Órgão / Objeto</th>
                                <th style="padding: 10px;">Data / Hora</th>
                                <th style="padding: 10px;">Plataforma</th>
                                <th style="padding: 10px;">Prazo</th>
                            </tr>
                        </thead>
                        <tbody>
                            {rows_html}
                        </tbody>
                    </table>
                    
                    <div style="text-align: center; margin-top: 30px; margin-bottom: 20px;">
                        <a href="https://urbano-licita-5idyvxrxmw58ucexzbuwwm.streamlit.app/" target="_blank"
                           style="background-color: #0044cc; color: white; padding: 12px 24px; text-decoration: none; border-radius: 5px; font-weight: bold; font-size: 14px;">
                           Acessar Plataforma Urbano
                        </a>
                    </div>
                    
                    <p style="margin-top: 30px; font-size: 12px; color: #888; text-align: center;">
                        Este resumo é gerado automaticamente às 08h e às 16h.<br>
                        Urbano - Inteligência em Licitações
                    </p>
                </div>
            </body>
            </html>
            """
            
            # Dispara
            subject = f"📅 Resumo de Licitações: {len(pending_bids)} oportunidades próximas"
            ok, msg = send_email(email, subject, email_body)
            
            status_icon = "✅" if ok else "❌"
            log_message = f"{status_icon} {username}: {len(pending_bids)} editais urgentes (de {found_greens} verdes)."
            if not ok:
                log_message += f" ERRO SMTP: {msg}"
            
            logs.append(log_message)
        else:
            if found_greens > 0:
                logs.append(f"ℹ️ {username}: {found_greens} verdes analisados, nenhum no prazo (0-2 dias úteis).")
    
    return logs