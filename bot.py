import os
import json
import asyncio
import datetime
import secrets
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

# --- CONFIGURAÇÃO ---
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
GROUP_ID = int(os.getenv("GROUP_ID"))
FERNET_KEY = os.getenv("FERNET_KEY").encode()
cipher = Fernet(FERNET_KEY)

ADMINS = [8154662660, 6439529867]
DENUNCIAS_ARQUIVO = "denuncias.enc"
ULTIMA_LIMPEZA_ARQUIVO = "last_clean.txt"

denuncias = []
denuncias_em_andamento = {}
temporizadores_envio = {}
temporizadores_inatividade = {}

CATEGORIAS = {
    "cat_pornografia": "Pornografia / CP",
    "cat_venda": "Venda não autorizada",
    "cat_privacidade": "Violação de privacidade",
    "cat_bullying": "Bullying / Ofensas",
    "cat_violencia": "Conteúdo violento",
    "cat_outro": "Outro"
}

# --- FUNÇÕES DE APOIO E SEGURANÇA ---

async def verificar_membro(bot, grupo_id, user_id):
    """Verifica se o usuário pertence ao grupo principal."""
    try:
        membro = await bot.get_chat_member(grupo_id, user_id)
        return membro.status in ["member", "administrator", "creator"]
    except:
        return False

def secure_shred(file_path):
    if os.path.exists(file_path):
        size = os.path.getsize(file_path)
        with open(file_path, "ba+", buffering=0) as f:
            f.write(secrets.token_bytes(size))
            os.fsync(f.fileno())
        os.remove(file_path)

async def scrub_image(photo_file):
    photo_bytes = await photo_file.download_as_bytearray()
    img = Image.open(io.BytesIO(photo_bytes))
    if max(img.size) > 3000: img.thumbnail((2048, 2048))
    buf = io.BytesIO()
    img_limpa = Image.new(img.mode, img.size)
    img_limpa.putdata(list(img.getdata()))
    img_limpa.save(buf, format="JPEG", quality=80)
    data = buf.getvalue()
    del img; gc.collect()
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

# --- FLUXO DE MENSAGENS E TIMEOUTS ---

async def monitorar_inatividade(user_id, context):
    if user_id in temporizadores_inatividade: temporizadores_inatividade[user_id].cancel()
    async def tarefa():
        await asyncio.sleep(300) # 5 min total
        if user_id not in denuncias_em_andamento: return
        dados = denuncias_em_andamento.pop(user_id)
        is_m = await verificar_membro(context.bot, GROUP_ID, user_id)
        m_status = "✅ Membro" if is_m else "❌ Não é Membro"
        for adm in ADMINS:
            await context.bot.send_message(adm, f"⚠️ **TIMEOUT:** {user_id}\n{m_status}\nCat: {dados['categoria']}")
        await context.bot.send_message(user_id, "🚫 Sessão encerrada.")
    temporizadores_inatividade[user_id] = asyncio.create_task(tarefa())

async def iniciar_temporizador_envio(user_id, context):
    if user_id in temporizadores_envio: temporizadores_envio[user_id].cancel()
    async def aguardar():
        await asyncio.sleep(8)
        if user_id in denuncias_em_andamento:
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("📨 Enviar", callback_data="menu_enviar"), 
                                        InlineKeyboardButton("🚫 Cancelar", callback_data="menu_cancelar")]])
            msg = await context.bot.send_message(user_id, "📌 Pronto para enviar?", reply_markup=kb)
            denuncias_em_andamento[user_id]["menu_id"] = msg.message_id
    temporizadores_envio[user_id] = asyncio.create_task(aguardar())

async def receber_mensagem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if update.effective_chat.type != "private": return

    if user_id in denuncias_em_andamento:
        msg = update.message
        if msg.photo:
            st = await msg.reply_text("🛡️ Sanitizando...")
            try:
                d = await asyncio.wait_for(scrub_image(msg.photo[-1]), timeout=15)
                denuncias_em_andamento[user_id]["mensagens"].append({"tipo": "photo_clean", "data": d.hex()})
            except:
                denuncias_em_andamento[user_id]["mensagens"].append({"tipo": "vid", "file_id": msg.photo[-1].file_id})
            await st.delete()
        elif msg.video: denuncias_em_andamento[user_id]["mensagens"].append({"tipo": "vid", "file_id": msg.video.file_id})
        elif msg.text: denuncias_em_andamento[user_id]["mensagens"].append(msg.text)
        await iniciar_temporizador_envio(user_id, context)
        return

    is_m = await verificar_membro(context.bot, GROUP_ID, user_id)
    m_status = "✅ Membro do Grupo" if is_m else "❌ Não é Membro"
    btns = [[InlineKeyboardButton("📢 Abrir denúncia", callback_data="menu_abrir")]]
    if user_id in ADMINS: btns.append([InlineKeyboardButton("📊 Painel Admin", callback_data="ver_estatisticas")])
    await update.message.reply_text(f"👋 Bem-vindo.\nStatus: {m_status}", reply_markup=InlineKeyboardMarkup(btns))

async def finalizar_envio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.callback_query.from_user.id
    if user_id not in denuncias_em_andamento: return
    try:
        mid = denuncias_em_andamento[user_id].get("menu_id")
        if mid: await context.bot.delete_message(user_id, mid)
    except: pass
    dados = denuncias_em_andamento.pop(user_id)
    is_m = await verificar_membro(context.bot, GROUP_ID, user_id)
    m_status = "✅ Membro" if is_m else "❌ Estrangeiro"
    denuncias.append(dados)
    salvar_denuncias()
    for adm in ADMINS:
        await context.bot.send_message(adm, f"📥 **DENÚNCIA**\n👤 {update.callback_query.from_user.full_name}\nStatus: {m_status}\n📂 {dados['categoria']}")
        for m in dados["mensagens"]:
            if isinstance(m, str): await context.bot.send_message(adm, f"📝 {m}")
            elif isinstance(m, dict):
                if m['tipo'] == 'photo_clean': await context.bot.send_photo(adm, photo=io.BytesIO(bytes.fromhex(m['data'])))
                else: await context.bot.send_video(adm, m['file_id'])
    await update.callback_query.edit_message_text("✅ Enviada.")

async def tratar_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "menu_abrir":
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(n, callback_data=k)] for k, n in CATEGORIAS.items()])
        await q.edit_message_text("📂 Escolha a categoria:", reply_markup=kb)
    elif q.data in CATEGORIAS:
        denuncias_em_andamento[q.from_user.id] = {"categoria": CATEGORIAS[q.data], "mensagens": []}
        await q.edit_message_text(f"✅ Categoria: {CATEGORIAS[q.data]}\nEnvie as provas.")
    elif q.data == "menu_enviar": await finalizar_envio(update, context)
    elif q.data == "ver_estatisticas" and q.from_user.id in ADMINS:
        await q.message.reply_text(f"📊 Total na base: {len(denuncias)}")

def main():
    carregar_denuncias()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", receber_mensagem))
    app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO | filters.VIDEO, receber_mensagem))
    app.add_handler(CallbackQueryHandler(tratar_callback))
    app.run_polling()

if __name__ == "__main__":
    main()
