# --- ARQUIVO: scheduler_local.py ---
import toml
import sys
from unittest.mock import MagicMock
import os

# --- 1. CONFIGURAÇÃO DO AMBIENTE (MOCK) ---
# O database.py espera encontrar 'st.secrets'. Como não estamos rodando
# pelo comando 'streamlit run', precisamos enganar o script.

print("🔧 Lendo arquivo de segredos local (.streamlit/secrets.toml)...")

try:
    # Carrega o arquivo de senhas que você já usa
    local_secrets = toml.load(".streamlit/secrets.toml")
    
    # Cria um objeto falso (Mock) para substituir o 'st'
    mock_st = MagicMock()
    mock_st.secrets = local_secrets
    
    # Injeta o mock no sistema
    sys.modules["streamlit"] = mock_st
    print("✅ Segredos carregados com sucesso.")

except Exception as e:
    print(f"❌ Erro ao ler secrets.toml: {e}")
    exit(1)

# --- 2. IMPORTAÇÃO DO BANCO DE DADOS ---
# Só importamos agora, DEPOIS de ter configurado o mock
try:
    import database as db
    print("✅ Conexão com banco de dados estabelecida.")
except Exception as e:
    print(f"❌ Erro ao importar database.py: {e}")
    print("Dica: Verifique se as credenciais do Firebase estão corretas.")
    exit(1)

# --- 3. EXECUÇÃO DA ROTINA ---
if __name__ == "__main__":
    print("\n🚀 INICIANDO VERIFICAÇÃO DE PRAZOS (MODO LOCAL)...")
    print("---------------------------------------------------")
    
    try:
        # Chama a função que criamos no database.py
        # Ela vai procurar editais VERDES faltando <= 2 dias úteis
        logs = db.check_deadlines_and_notify()
        
        if logs:
            print(logs)
        else:
            print("💤 Nenhum e-mail precisou ser enviado hoje.")
            print("(Ou os editais não são 'green', ou o prazo > 2 dias úteis, ou já foram notificados).")
            
    except Exception as e:
        print(f"❌ Erro durante a execução: {e}")

    print("---------------------------------------------------")
    print("🏁 Fim da execução.")