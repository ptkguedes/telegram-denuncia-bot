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
    if os.path.exists(file_path):
        size = os.path.getsize(file_path)
        with open(file_path, "ba+", buffering=0) as f:
            for _ in range(passes):
                f.seek(0)
                f.write(secrets.token_bytes(size))
                os.fsync(f.fileno())
        os.remove(file_path)

async def scrub_image(photo_file):
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

async def verificar_membro(bot, grupo_id, user_id):
    try:
        membro = await bot.get_chat_member(grupo_id, user_id)
        return membro.status in ["member", "administrator", "creator"]
    except: return False

# --- LOGICA DE TEMPORIZADORES E INATIVIDADE ---

async def iniciar_temporizador_envio(user_id, context):
    if user_id in temporizadores_envio:
        temporizadores_envio[user_id].cancel()

    async def aguardar_e_sugerir_envio():
        await asyncio.sleep(8)
        if user_id in denuncias_em_andamento:
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("📨 Enviar denúncia", callback_data="menu_enviar")],
                [InlineKeyboardButton("🚫 Cancelar", callback_data="menu_cancelar")],
                [InlineKeyboardButton("✏️ Continuar", callback_data="menu_continuar")]
            ])
            await context.bot.send_message(chat_id=user_id, text="📌 Mensagens registradas. O que deseja fazer?", reply_markup=keyboard)

    temporizadores_envio[user_id] = asyncio.create_task(aguardar_e_sugerir_envio())

async def monitorar_inatividade(user_id, context):
    if user_id in temporizadores_inatividade:
        temporizadores_inatividade[user_id].cancel()

    async def tarefa():
        await asyncio.sleep(180)
        if user_id not in denuncias_em_andamento: return
        await context.bot.send_message(user_id, "👀 Sua denúncia ainda não foi enviada. Ela expirará em 2 min.")

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
        await context.bot.send_message(user_id, "🚫 Sessão encerrada por inatividade.")

    temporizadores_inatividade[user_id] = asyncio.create_task(tarefa())

# --- HANDLERS PRINCIPAIS ---

async def abrir_denuncia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in bloqueados:
        return await update.effective_chat.send_message("🚫 Você está bloqueado.")
    
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(n, callback_data=k)] for k, n in CATEGORIAS.items()])
    await context.bot.send_message(chat_id=user_id, text="Escolha a categoria da denúncia:", reply_markup=keyboard)

async def receber_mensagem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user_id = update.effective_user.id
    if chat.type != "private": return

    texto = update.effective_message.text or ""
    
    # Lógica de conversa ativa com Admin
    if user_id in conversas_ativas:
        admin_id = conversas_ativas[user_id]
        await context.bot.send_message(chat_id=admin_id, text=f"📨 Resposta de {user_id}:\n{texto}")
        return

    # Lógica de denúncia em andamento
    if user_id in denuncias_em_andamento:
        msg = update.message
        if msg.photo:
            st = await msg.reply_text("🛡️ Sanitizando metadados...")
            photo_data = await scrub_image(msg.photo[-1])
            denuncias_em_andamento[user_id]["mensagens"].append({"tipo": "photo_clean", "data": photo_data.hex()})
            await st.delete()
        elif msg.video:
            denuncias_em_andamento[user_id]["mensagens"].append({"tipo": "video", "file_id": msg.video.file_id})
        elif texto:
            denuncias_em_andamento[user_id]["mensagens"].append(texto)
        
        await iniciar_temporizador_envio(user_id, context)
        await monitorar_inatividade(user_id, context)
        return

    # Painel Inicial
    is_member = await verificar_membro(context.bot, GROUP_ID, user_id)
    membro_status = "Membro ✅" if is_member else "Membro ❌"
    
    keyboard_list = [[InlineKeyboardButton("📢 Abrir denúncia", callback_data="menu_abrir")]]
    if user_id in ADMINS:
        keyboard_list.append([InlineKeyboardButton("📊 Painel Admin", callback_data="ver_estatisticas")])
    
    await update.message.reply_text(f"👋 Olá! Bem-vindo.\n{membro_status}", reply_markup=InlineKeyboardMarkup(keyboard_list))

async def enviar_denuncia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in denuncias_em_andamento: return

    dados = denuncias_em_andamento.pop(user_id)
    user = update.effective_user
    dados.update({"user_real": user.full_name, "user_id": user_id, "timestamp": datetime.datetime.now().isoformat()})
    
    denuncias.append(dados)
    salvar_denuncias()
    
    for admin_id in ADMINS:
        await context.bot.send_message(admin_id, f"📥 **NOVA DENÚNCIA**\n👤 {user.full_name} (`{user_id}`)\n📂 {dados['categoria']}", parse_mode='Markdown')
        for item in dados["mensagens"]:
            if isinstance(item, str): await context.bot.send_message(admin_id, f"📝 {item}")
            elif isinstance(item, dict):
                if item['tipo'] == 'photo_clean':
                    await context.bot.send_photo(admin_id, photo=io.BytesIO(bytes.fromhex(item['data'])), caption="🛡️ Sanitizada")
                else: await context.bot.send_video(admin_id, item['file_id'])

    await context.bot.send_message(chat_id=user_id, text="✅ Denúncia enviada com sucesso.")

async def tratar_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    if query.data in CATEGORIAS:
        denuncias_em_andamento[user_id] = {"categoria": CATEGORIAS[query.data], "mensagens": []}
        await query.edit_message_text(f"✅ Categoria: {CATEGORIAS[query.data]}\nEnvie os detalhes agora.")
        await monitorar_inatividade(user_id, context)

    elif query.data == "menu_enviar": await enviar_denuncia(update, context)
    elif query.data == "menu_cancelar":
        denuncias_em_andamento.pop(user_id, None)
        await query.edit_message_text("🚫 Cancelada.")
    elif query.data == "menu_abrir": await abrir_denuncia(update, context)
    elif query.data == "ver_estatisticas":
        await query.message.reply_text(f"📊 Total: {len(denuncias)}\n🚫 Bloqueados: {len(bloqueados)}")

async def protocolo_zero(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMINS: return
    await update.message.reply_text("☣️ **PROTOCOLO ZERO ATIVADO...**")
    for f in [DENUNCIAS_ARQUIVO, BLOQUEADOS_ARQUIVO, ".env"]: secure_shred(f)
    os._exit(0)

def main():
    carregar_denuncias()
    carregar_bloqueados()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", abrir_denuncia))
    app.add_handler(CommandHandler("kill", protocolo_zero))
    app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO | filters.VIDEO, receber_mensagem))
    app.add_handler(CallbackQueryHandler(tratar_callback))
    app.run_polling()

if __name__ == "__main__":
    main()
