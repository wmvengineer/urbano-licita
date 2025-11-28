import google.generativeai as genai

print("--- INICIANDO VERIFICAÇÃO ---")
api_key = input("Cole sua API Key (AIza...) aqui e aperte Enter: ")

try:
    genai.configure(api_key=api_key)
    print("\nConectado! Listando modelos disponíveis para sua conta:\n")
    
    modelos_encontrados = []
    for m in genai.list_models():
        if 'generateContent' in m.supported_generation_methods:
            print(f"- {m.name}")
            modelos_encontrados.append(m.name)
            
    if not modelos_encontrados:
        print("\nNenhum modelo de geração de texto encontrado. Verifique se sua chave API está ativa.")
    else:
        print("\n--- FIM DA LISTA ---")
        print("Copie um dos nomes acima (ex: models/gemini-pro) para usar no seu app.py")

except Exception as e:
    print(f"\nERRO GRAVE: {e}")