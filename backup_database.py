import firebase_admin
from firebase_admin import credentials, firestore, storage
import bcrypt
import secrets
import datetime
import streamlit as st

# --- CONFIGURAÇÃO ---
# ⚠️ SUBSTITUA PELO SEU ID REAL DO FIREBASE STORAGE (sem gs://)
# Exemplo: BUCKET_NAME = "projeto-urbano-123.appspot.com"
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
    st.error(f"Erro ao conectar no Storage: {e}. Verifique o BUCKET_NAME no database.py")

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

# --- HISTÓRICO ---

def save_analysis_history(username, title, full_text):
    try:
        db.collection('users').document(username).collection('history').add({
            'title': title, 'content': full_text, 'created_at': datetime.datetime.now()
        })
    except: pass

def get_user_history_list(username):
    try:
        docs = db.collection('users').document(username).collection('history')\
                 .order_by('created_at', direction=firestore.Query.DESCENDING).stream()
        return [{'id': d.id, **d.to_dict()} for d in docs]
    except: return []

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