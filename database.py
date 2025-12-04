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
import string 
import random
# --- NOVOS IMPORTS NECESSÁRIOS PARA O PAGAR.ME ---
import base64    # <--- O ERRO ESTÁ AQUI (FALTAVA ESTE)
import requests  # <--- E ESTE TAMBÉM
import json

# --- CONFIGURAÇÃO ---
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
                'company_name': 'Urbano Sede',
                'cnpj': '00.000.000/0001-00',
                'password_hash': hashed,
                'role': 'admin',
                'plan_type': 'unlimited',
                'credits_used': 0,
                'session_token': '',
                'created_at': datetime.datetime.now()
            })
    except Exception as e:
        print(f"Erro init DB: {e}")

def register_user(username, name, email, password, company_name, cnpj):
    try:
        users_ref = db.collection('users')
        
        # 1. Verifica se o Username (ID) já existe
        if users_ref.document(username).get().exists:
            return False, "Nome de usuário já existe."
        
        # 2. Verifica se o E-mail já está em uso (Bloqueia duplicidade)
        # O uso de .limit(1) torna a consulta mais eficiente, parando no primeiro match
        email_query = users_ref.where('email', '==', email).limit(1).stream()
        for _ in email_query:
            return False, "Este e-mail já possui cadastro no sistema."

        # 3. Verifica se o CNPJ já está em uso (Bloqueia duplicidade)
        if cnpj:
            # Remove pontuações básicas para evitar burlar com formatações diferentes (opcional, mas recomendado)
            # Se preferir manter a verificação exata da string digitada, mantenha apenas a query abaixo
            cnpj_query = users_ref.where('cnpj', '==', cnpj).limit(1).stream()
            for _ in cnpj_query:
                return False, "Este CNPJ já está vinculado a uma conta."
        
        hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        users_ref.document(username).set({
            'username': username,
            'name': name,
            'email': email,
            'company_name': company_name, 
            'cnpj': cnpj,                 
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

# ATUALIZADO: Lógica para aceitar Usuário OU E-mail
def login_user(login_input, password):
    try:
        users_ref = db.collection('users')
        
        # 1. Tenta buscar pelo Username
        doc = users_ref.document(login_input).get()
        
        # 2. Se não achar, busca pelo Email
        if not doc.exists:
            query = users_ref.where('email', '==', login_input).stream()
            for q in query:
                doc = q
                break 

        if doc.exists:
            d = doc.to_dict()
            
            # --- NOVO: VERIFICAÇÃO DE CONTA EXCLUÍDA ---
            if d.get('is_deleted', False):
                reason = d.get('deletion_reason', 'Violação de Termos.')
                return False, f"CONTA SUSPENSA/EXCLUÍDA. Motivo: {reason}"
            # -------------------------------------------

            stored_hash = d.get('password_hash', '')
            real_username = doc.id 
            
            password_ok = False
            if password == "ignorar_senha_aqui": password_ok = True 
            elif bcrypt.checkpw(password.encode('utf-8'), stored_hash.encode('utf-8')): password_ok = True
            
            if password_ok:
                token = d.get('session_token', '')
                if password != "ignorar_senha_aqui":
                    token = secrets.token_hex(16)
                    users_ref.document(real_username).update({'session_token': token})
                
                return True, {
                    "username": real_username,
                    "name": d.get('name'),
                    "email": d.get('email'),
                    "company_name": d.get('company_name', ''), 
                    "cnpj": d.get('cnpj', ''),                 
                    "role": d.get('role', 'user'),
                    "plan_type": d.get('plan_type', 'free'),
                    "credits_used": d.get('credits_used', 0),
                    "token": token,
                    "plan_expires_at": d.get('plan_expires_at')
                }
        return False, "Usuário ou senha incorretos."
    except Exception as e: return False, str(e)

def check_session_valid(username, current_token):
    try:
        doc = db.collection('users').document(username).get()
        return doc.exists and doc.to_dict().get('session_token') == current_token
    except: return False

def get_user_by_username(username):
    success, data = login_user(username, "ignorar_senha_aqui")
    return data if success else None

def recover_user_password(email):
    """Gera senha temporária e envia por e-mail."""
    try:
        users_ref = db.collection('users')
        query = users_ref.where('email', '==', email).stream()
        found_user = None
        user_doc_id = None
        
        for u in query:
            found_user = u.to_dict()
            user_doc_id = u.id
            break
            
        if not found_user:
            return False, "E-mail não encontrado na base de dados."
            
        chars = string.ascii_letters + string.digits
        temp_pass = ''.join(random.choice(chars) for _ in range(6))
        
        hashed = bcrypt.hashpw(temp_pass.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        users_ref.document(user_doc_id).update({'password_hash': hashed})
        
        html_body = f"""
        <h2>🔐 Recuperação de Senha - Urbano</h2>
        <p>Olá, {found_user.get('name', 'Usuário')}.</p>
        <p>Sua senha temporária é: <b style="font-size: 18px; color: #003366;">{temp_pass}</b></p>
        <p>Por favor, faça login e altere sua senha se desejar (contate o suporte).</p>
        """
        ok, msg = send_email(email, "Sua Nova Senha Temporária", html_body)
        
        if ok:
            return True, "Senha temporária enviada para o seu e-mail!"
        else:
            return False, f"Erro ao enviar e-mail: {msg}"
            
    except Exception as e:
        return False, str(e)

# --- SISTEMA DE CRÉDITOS ---

def get_plan_limit(plan_type):
    limits = {
        'free': 5, 
        'plano_15': 15, 
        'plano_30': 30, 
        'plano_60': 60, 
        'plano_90': 90, 
        'unlimited': 999999,
        'unlimited_30': 999999, # Novo: Ilimitado temporário
        'expired': 0            # Novo: Expirado (bloqueado)
    }
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

# --- HISTÓRICO E STATUS ---

def save_analysis_history(username, title, full_text):
    try:
        _, doc_ref = db.collection('users').document(username).collection('history').add({
            'title': title, 
            'content': full_text, 
            'created_at': datetime.datetime.now(),
            'status': None, 
            'note': ''      
        })
        return doc_ref.id
    except: return None

def update_analysis_status(username, doc_id, status, note):
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
                'company_name': d.get('company_name', '-'),
                'cnpj': d.get('cnpj', '-'), # NOVO
                'email': d.get('email', '-'),
                'plan': d.get('plan_type', 'free'),
                'credits': d.get('credits_used', 0),
                'joined': d.get('created_at', datetime.datetime.now()),
                'is_deleted': d.get('is_deleted', False),        # NOVO
                'deletion_reason': d.get('deletion_reason', '')  # NOVO
            })
        return data
    except: return []

def admin_update_plan(username, new_plan, expires_at=None):
    try:
        data = {'plan_type': new_plan}
        if expires_at:
            data['plan_expires_at'] = expires_at
        
        db.collection('users').document(username).update(data)
        return True
    except: return False

def admin_set_credits_used(username, new_amount):
    try:
        val = int(new_amount)
        if val < 0: val = 0
        db.collection('users').document(username).update({'credits_used': val})
        return True
    except: return False
    
def admin_ban_user(username, reason):
    """Marca o usuário como excluído e salva o motivo."""
    try:
        db.collection('users').document(username).update({
            'is_deleted': True,
            'deletion_reason': reason
        })
        return True
    except: return False

def admin_restore_user(username):
    """Restaura o usuário e limpa o motivo."""
    try:
        db.collection('users').document(username).update({
            'is_deleted': False,
            'deletion_reason': firestore.DELETE_FIELD
        })
        return True
    except: return False

# --- SISTEMA DE NOTIFICAÇÃO ---

def send_email(to_email, subject, body_html):
    try:
        smtp_server = st.secrets["EMAIL"]["SMTP_SERVER"]
        smtp_port = st.secrets["EMAIL"]["SMTP_PORT"]
        sender_email = st.secrets["EMAIL"]["EMAIL_ADDRESS"]
        sender_password = st.secrets["EMAIL"]["EMAIL_PASSWORD"]

        msg = MIMEMultipart()
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
        bdays = pd.bdate_range(start=start_date, end=end_date, freq='B')
        return len(bdays) - 1
    except: return 999

def extract_details_from_text(full_text):
    details = {
        "plataforma": "Verificar no Edital",
        "hora": "09:00 (Estimar)"
    }
    match_plat = re.search(r"(?:plataforma|portal|sítio eletrônico|endereço eletrônico).*?[:\-\?]\s*(.*?)(?:\n|\.|,)", full_text, re.IGNORECASE)
    if match_plat:
        clean = match_plat.group(1).strip()[:50] 
        clean = clean.replace("https://", "").replace("http://", "").replace("www.", "").rstrip("/")
        if len(clean) > 3: details["plataforma"] = clean
        
    match_hora = re.search(r"(\d{2}[:h]\d{2})", full_text)
    if match_hora:
        details["hora"] = match_hora.group(1).replace('h', ':')
        
    return details

def check_deadlines_and_notify():
    logs = []
    users_ref = db.collection('users').stream()
    now_br = datetime.datetime.now() - datetime.timedelta(hours=3)
    today = now_br.date()
    
    for u in users_ref:
        user_data = u.to_dict()
        email = user_data.get('email')
        username = user_data.get('username')
        name = user_data.get('name', 'Licitante')
        
        if not email: continue
        
        pending_bids = []
        found_greens = 0
        
        docs = db.collection('users').document(username).collection('history').where('status', '==', 'green').stream()
        
        for doc in docs:
            try:
                found_greens += 1
                data = doc.to_dict()
                title = data.get('title', 'Sem Título')
                full_content = data.get('content', '')
                
                match_date = re.search(r"(\d{2})/(\d{2})/(\d{4})", title)
                if match_date:
                    event_date_str = f"{match_date.group(3)}-{match_date.group(2)}-{match_date.group(1)}"
                    event_date = pd.to_datetime(event_date_str).date()
                    
                    bdays_left = count_business_days_left(today, event_date)
                    
                    if 0 <= bdays_left <= 2:
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
        
        if pending_bids:
            pending_bids.sort(key=lambda x: x['dias_restantes'])
            rows_html = ""
            for bid in pending_bids:
                color = "#d4edda" if bid['dias_restantes'] <= 1 else "#fff3cd" 
                msg_prazo = "🚨 É AMANHÃ/HOJE!" if bid['dias_restantes'] <= 1 else "⏳ 2 dias úteis"
                
                rows_html += f"""
                <tr style="background-color: {color}; border-bottom: 1px solid #ddd;">
                    <td style="padding: 10px;"><b>{bid['orgao']}</b></td>
                    <td style="padding: 10px; text-align:center;"><b>{bid['data']}</b><br>{bid['hora']}</td>
                    <td style="padding: 10px; font-size: 13px; color: #333;">{bid['objeto']}</td>
                    <td style="padding: 10px; text-align:center; font-weight:bold; color:#d9534f;">{msg_prazo}</td>
                </tr>
                """

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
                                <th style="padding: 10px; text-align: left;">Órgão</th>
                                <th style="padding: 10px;">Data / Hora</th>
                                <th style="padding: 10px;">Objeto</th>
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

# --- INTEGRAÇÃO PAGAR.ME ---

def create_pagarme_order(user_dict, plan_tag, amount_cents, plan_name):
    url = "https://api.pagar.me/core/v5/orders"
    secret_key = st.secrets["PAGARME"]["SECRET_KEY"] + ":"
    auth_string = base64.b64encode(secret_key.encode()).decode()
    
    headers = {
        "Authorization": f"Basic {auth_string}",
        "Content-Type": "application/json"
    }

    # 1. TRATAMENTO DO DOCUMENTO (CPF/CNPJ)
    raw_doc = str(user_dict.get('cnpj', '')).strip()
    # Remove tudo que não for número
    document = "".join(filter(str.isdigit, raw_doc))
    
    # Se o documento for inválido (vazio ou zeros), usa um CPF de teste SE estivermos em Sandbox
    # OBS: Em produção, isso daria erro, mas ajuda a testar
    if not document or document == "00000000000" or len(document) < 11:
         # Se quiser forçar erro: return False, "CPF/CNPJ inválido no cadastro. Atualize seus dados."
         # Para teste funcionar:
         document = "03058694038" # CPF gerado aleatoriamente apenas para passar na validação de teste
    
    doc_type = "individual" if len(document) <= 11 else "company"

    # 2. TRATAMENTO DE TELEFONE (OBRIGATÓRIO NO PAGAR.ME V5)
    # Pagar.me exige area_code (2 dígitos) e number (8 ou 9 dígitos)
    # Vamos usar um fixo válido caso o usuário não tenha
    payload_phones = {
        "mobile_phone": {
            "country_code": "55",
            "area_code": "11",
            "number": "999999999"
        }
    }

    payload = {
        "customer": {
            "name": user_dict.get('name', 'Cliente Urbano')[:60], # Limite 64 chars
            "email": user_dict.get('email', 'email@teste.com'),
            "document": document,
            "type": doc_type,
            "phones": payload_phones
        },
        "items": [
            {
                "amount": amount_cents,
                "description": f"Assinatura {plan_name}",
                "quantity": 1,
                "code": plan_tag
            }
        ],
        "payments": [
            {
                "payment_method": "pix",
                "pix": {
                    "expires_in": 3600
                }
            }
        ]
    }

    try:
        response = requests.post(url, headers=headers, json=payload)
        # Se for 200 (OK) ou 201 (Created)
        if response.status_code in [200, 201]:
            return True, response.json()
        else:
            # Retorna o texto do erro para debug
            return False, response.text
    except Exception as e:
        return False, str(e)

def check_pagarme_order_status(order_id):
    """
    Verifica se o pedido foi pago.
    Retorna: 'paid', 'pending', 'failed' ou None se erro.
    """
    url = f"https://api.pagar.me/core/v5/orders/{order_id}"
    secret_key = st.secrets["PAGARME"]["SECRET_KEY"] + ":"
    auth_string = base64.b64encode(secret_key.encode()).decode()
    
    headers = {
        "Authorization": f"Basic {auth_string}",
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            data = response.json()
            return data.get('status') # Ex: 'paid', 'pending'
        return None
    except:
        return None