import time
from collections import defaultdict

# ⏱️ Configurações de controle
INTERVALO_MINIMO = 30  # segundos entre denúncias
TAMANHO_MAXIMO = 1000  # caracteres
PALAVRAS_PROIBIDAS = [
    "trote", "zoeira", "fake", "brincadeira",
    "idiota", "burro", "palhaçada", "mentira"
]

# 🧠 Histórico por usuário
ULTIMA_MENSAGEM = defaultdict(lambda: 0)
ULTIMO_TEXTO = defaultdict(lambda: "")

def verificar_mensagem(user_id, texto):
    agora = time.time()

    # ⏳ Verifica intervalo mínimo entre mensagens
    if agora - ULTIMA_MENSAGEM[user_id] < INTERVALO_MINIMO:
        return "⏳ Aguarde um pouco antes de enviar outra denúncia."

    # 📏 Verifica tamanho da mensagem
    if len(texto) > TAMANHO_MAXIMO:
        return "🚫 Sua denúncia é muito longa. Tente resumir em até 1000 caracteres."

    # 🔁 Verifica repetição de conteúdo
    if texto.strip() == ULTIMO_TEXTO[user_id]:
        return "🚫 Denúncia repetida detectada. Tente reformular."

    # 🚫 Verifica palavras proibidas
    if any(p in texto.lower() for p in PALAVRAS_PROIBIDAS):
        return "🚫 Conteúdo inadequado detectado. Denúncias falsas ou ofensivas não serão toleradas."

    # ✅ Atualiza histórico
    ULTIMA_MENSAGEM[user_id] = agora
    ULTIMO_TEXTO[user_id] = texto.strip()

    return None  # Tudo certo
