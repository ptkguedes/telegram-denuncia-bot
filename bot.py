import os
import json
import asyncio
import datetime
import secrets
import hashlib
import io
import gc
from dotenv import load_dotenv
from PIL import Image
from cryptography.fernet import Fernet
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes
)

# --- CONFIGURAÇÃO E CRIPTOGRAFIA ---
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
GROUP_ID = int(os.getenv("GROUP_ID"))
FERNET_KEY = os.getenv("FERNET_KEY").encode()
cipher = Fernet(FERNET_KEY)

ADMINS = [8154662660, 6439529867]
DENUNCIAS_ARQUIVO = "denuncias.enc"
BLOQUEADOS_ARQUIVO = "bloqueados.json"
ULTIMA_LIMPEZA_ARQUIVO = "last_clean.txt"

# Variáveis globais
denuncias = []
bloqueados = []
denuncias_em_andamento = {}
tempo_inatividade = {}
temporizadores_envio = {}
temporizadores_inatividade = {}
conversas_ativas = {}

CATEGORIAS = {
    "cat_pornografia": "Pornografia / CP",
    "cat_venda": "Venda não autorizada",
    "cat_privacidade": "Violação de privacidade",
    "cat_bullying": "Bullying / Ofensas",
    "cat_violencia": "Conteúdo violento",
    "cat_outro": "Outro"
}

# --- NÚCLEO DE SEGURANÇA (GHOST PROTOCOL) ---

def secure_shred(file_path, passes=3):
    """Obliteração física do arquivo antes da deleção."""
    if os.path.exists(file_path):
        size = os.path.getsize(file_path)
        with open(file_path, "ba+", buffering=0) as f:
            for _ in range(passes):
                f.seek(0)
                f.write(secrets.token_bytes(size))
                os.fsync(f.fileno())
        os.remove(file_path)

async def scrub_image(photo_file):
    """Lava metadados EXIF/GPS reconstruindo a imagem em RAM."""
    photo_bytes = await photo_file.download_as_bytearray()
    img = Image.open(io.BytesIO(photo_bytes))
    buffer_limpo = io.BytesIO()
    img_limpa = Image.new(img.mode, img.size)
    img_limpa.putdata(list(img.getdata()))
    img_limpa.save(buffer_limpo, format="JPEG", quality=85)
    data = buffer_limpo.getvalue()
    del img; del img_limpa; gc.collect()
    return data

def salvar_denuncias():
    raw_data = json.dumps(denuncias, ensure_ascii=False).encode()
    with open(DENUNCIAS_ARQUIVO, "wb") as f:
        f.write(cipher.encrypt(raw_data))

def carregar_denuncias():
    global denuncias
    if os.path.exists(DENUNCIAS_ARQUIVO):
        try:
            with open(DENUNCIAS_ARQUIVO, "rb") as f:
                denuncias = json.loads(cipher.decrypt(f.read()).decode())
        except: denuncias = []

def carregar_bloqueados():
    global bloqueados
    if os.path.exists(BLOQUEADOS_ARQUIVO):
        with open(BLOQUEADOS_ARQUIVO, "r", encoding="utf-8") as f:
            bloqueados = json.load(f)

def salvar_bloqueados():
    with open(BLOQUEADOS_ARQUIVO, "w", encoding="utf-8") as f:
        json.dump(bloqueados, f, ensure_ascii=False, indent=4)

# --- POLÍTICA DE RETENÇÃO E INATIVIDADE ---

async def verificar_auto_destruicao(context):
    global denuncias
    ultima = datetime.datetime.now()
    if os.path.exists(ULTIMA_LIMPEZA_ARQUIVO):
        with open(ULTIMA_LIMPEZA_ARQUIVO, "r") as f:
            ultima = datetime.datetime.fromisoformat(f.read().strip())

    if len(denuncias) >= 100 or (datetime.datetime.now() - ultima) >= datetime.timedelta(weeks=2):
        secure_shred(DENUNCIAS_ARQUIVO)
        denuncias = []
        salvar_denuncias()
        with open(ULTIMA_LIMPEZA_ARQUIVO, "w") as f:
            f.write(datetime.datetime.now().isoformat())
        for adm in ADMINS:
            await context.bot.send_message(adm, "☣️ **SISTEMA:** Limpeza quinzenal concluída. Dados obliterados.")

async def monitorar_inatividade(user_id, context):
    if user_id in temporizadores_inatividade:
        temporizadores_inatividade[user_id].cancel()

    async def tarefa():
        await asyncio.sleep(180)
        if user_id not in denuncias_em_andamento: return
        await context.bot.send_message(user_id, "👀 Ei, sua denúncia ainda não foi enviada. Sessão expira em 2 min.")

        await asyncio.sleep(120)
        if user_id not in denuncias_em_andamento: return

        dados = denuncias_em_andamento.pop(user_id, None)
        user = await context.bot.get_chat(user_id)
        tem_conteudo = len(dados.get("mensagens", [])) > 0

        for admin_id in ADMINS:
            status = "⚠️ INTERROMPIDA (Com Dados)" if tem_conteudo else "🗑️ SESSÃO EXPIRADA (Vazia)"
            header = (f"{status}\n👤 **User:** {user.full_name}\n🆔 `{user_id}`\n📂 **Cat:** {dados.get('categoria')}")
            await context.bot.send_message(admin_id, header, parse_mode='Markdown')
            
            if tem_conteudo:
                for item in dados["mensagens"]:
                    if isinstance(item, str): await context.bot.send_message(admin_id, f"📝 {item}")
                    elif isinstance(item, dict) and item.get("tipo") == "video":
                        await context.bot.send_video(admin_id, item['file_id'])

        await context.bot.send_message(user_id, "🚫 Sessão encerrada.")

    temporizadores_inatividade[user_id] = asyncio.create_task(tarefa())

# --- HANDLERS DE COMUNICAÇÃO ---

async def abrir_denuncia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in bloqueados:
        return await update.message.reply_text("🚫 Você está bloqueado.")
    
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(n, callback_data=k)] for k, n in CATEGORIAS.items()])
    await update.message.reply_text("Escolha a categoria da denúncia:", reply_markup=keyboard)

async def receber_mensagem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if update.effective_chat.type != "private": return

    if user_id in denuncias_em_andamento:
        msg = update.message
        if msg.photo:
            status = await msg.reply_text("🛡️ Sanitizando metadados...")
            photo_data = await scrub_image(msg.photo[-1])
            denuncias_em_andamento[user_id]["mensagens"].append({"tipo": "photo_clean", "data": photo_data.hex()})
            await status.delete()
        elif msg.video:
            denuncias_em_andamento[user_id]["mensagens"].append({"tipo": "video", "file_id": msg.video.file_id})
        elif msg.text:
            denuncias_em_andamento[user_id]["mensagens"].append(msg.text)
        
        await monitorar_inatividade(user_id, context)
        return

    # Painel Admin ou Usuário Inicial
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("📢 Abrir denúncia", callback_data="menu_abrir")]])
    await update.message.reply_text(f"👋 Olá! Deseja iniciar uma denúncia?", reply_markup=keyboard)

async def enviar_denuncia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in denuncias_em_andamento: return

    dados = denuncias_em_andamento.pop(user_id)
    user = update.effective_user
    dados.update({"user_real": user.full_name, "user_id": user_id, "timestamp": datetime.datetime.now().isoformat()})
    
    denuncias.append(dados)
    salvar_denuncias()
    await verificar_auto_destruicao(context)

    for admin_id in ADMINS:
        await context.bot.send_message(admin_id, f"📥 **NOVA DENÚNCIA**\n👤 {user.full_name} (`{user_id}`)\n📂 {dados['categoria']}", parse_mode='Markdown')
        for item in dados["mensagens"]:
            if isinstance(item, str): await context.bot.send_message(admin_id, f"📝 {item}")
            elif isinstance(item, dict):
                if item['tipo'] == 'photo_clean':
                    await context.bot.send_photo(admin_id, photo=io.BytesIO(bytes.fromhex(item['data'])), caption="🛡️ Sanitizada")
                else: await context.bot.send_video(admin_id, item['file_id'])

    await update.message.reply_text("✅ Enviada com sucesso.")

async def protocolo_zero(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMINS: return
    await update.message.reply_text("☣️ **EXECUTANDO PROTOCOLO ZERO...**")
    for f in [DENUNCIAS_ARQUIVO, BLOQUEADOS_ARQUIVO, ".env"]: secure_shred(f)
    os._exit(0)

# --- INICIALIZAÇÃO ---

def main():
    carregar_denuncias()
    carregar_bloqueados()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", abrir_denuncia))
    app.add_handler(CommandHandler("kill", protocolo_zero))
    app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO | filters.VIDEO, receber_mensagem))
    app.add_handler(CallbackQueryHandler(tratar_callback)) # Implementar tratar_callback com as lógicas de menu
    app.run_polling()

if __name__ == "__main__":
    main()
