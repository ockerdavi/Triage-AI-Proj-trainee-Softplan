"""Script de diagnóstico para medir o tempo de resposta e latência dos modelos do Gemini."""
import time
from triagem import triar, MODELOS_TRIAGEM

def medir_latencia():
    print("Iniciando teste de conexão e latência da API do Gemini...\n")
    relato_teste = "Meu mouse parou de funcionar, a luz não liga e preciso de um novo urgente."
    
    for modelo in MODELOS_TRIAGEM:
        print(f"Testando modelo: {modelo}")
        inicio = time.time()
        
        # Faz a chamada à API
        resposta = triar(relato_teste)
        
        fim = time.time()
        tempo_total = fim - inicio
        
        status = "OK" if resposta.ok else f"FALHA ({resposta.mensagem})"
        
        print(f" -> Status: {status}")
        print(f" -> Tempo de resposta: {tempo_total:.2f} segundos\n")

if __name__ == "__main__":
    medir_latencia()