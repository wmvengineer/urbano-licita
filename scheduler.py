# --- ARQUIVO: scheduler.py ---
import os
import json
import sys
from unittest.mock import MagicMock

# --- CONFIGURAÇÃO DO MOCK (Simula o Streamlit) ---
# O GitHub não tem o arquivo secrets.toml, ele usa Variáveis de Ambiente.
# Aqui nós pegamos as variáveis do GitHub e montamos um dicionário falso
# para o database.py achar que está lendo o st.secrets

mock_st = MagicMock()
secrets_dict = {}

try:
    # 1. Tenta pegar a chave do Firebase (que virá como texto JSON)
    fb_key_content = os.environ.get("FIREBASE_KEY_JSON")
    if fb_key_content:
        fb_json = json.loads(fb_key_content)
        secrets_dict["FIREBASE_KEY"] = fb_json

    # 2. Configurações de E-mail
    secrets_dict["EMAIL"] = {
        "SMTP_SERVER": "smtp.zoho.com",
        "SMTP_PORT": 465,
        "EMAIL_ADDRESS": os.environ.get("EMAIL_ADDRESS"),
        "EMAIL_PASSWORD": os.environ.get("EMAIL_PASSWORD")
    }
    
    # 3. Injeta no mock
    mock_st.secrets = secrets_dict
    sys.modules["streamlit"] = mock_st
    print("✅ Ambiente configurado para GitHub Actions.")

except Exception as e:
    print(f"⚠️ Aviso na configuração de secrets: {e}")

# --- AGORA IMPORTAMOS O BANCO ---
import database as db

if __name__ == "__main__":
    print("🚀 INICIANDO AUTOMAÇÃO DE E-MAILS...")
    try:
        # Chama a função que verifica os 2 dias úteis
        logs = db.check_deadlines_and_notify()
        if logs:
            print(logs)
        else:
            print("💤 Nenhum e-mail enviado hoje.")
    except Exception as e:
        print(f"❌ Erro fatal: {e}")
        exit(1)