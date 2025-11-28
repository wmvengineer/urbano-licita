import bcrypt

# Digite aqui as senhas que você quer criar
senhas = ["senhaadmin123", "cliente01senha"]

print("--- COPIE OS CÓDIGOS ABAIXO PARA O SEU ARQUIVO CONFIG.YAML ---")
print("")

for senha in senhas:
    # Converte a senha para o formato que o sistema entende
    senha_bytes = senha.encode('utf-8')
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(senha_bytes, salt)
    
    # Exibe na tela
    print(f"Senha original: {senha}")
    print(f"HASH (Copie isto): {hashed.decode('utf-8')}")
    print("------------------------------------------------------")