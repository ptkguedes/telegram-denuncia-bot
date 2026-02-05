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
    """Sanitiza metadados em RAM para proteger o denunciante."""
    photo_bytes = await photo_file.download_as_bytearray()
    img = Image.open(io.BytesIO(photo_bytes))
    if max(img.size) > 3000: img.thumbnail((2048, 2048))
    buf = io.BytesIO()
    img_limpa = Image.new(img.mode, img.size)
    img_limpa.putdata(list(img.getdata()))
    img_limpa.save(buf, format="JPEG", quality=80)
    data = buf.getvalue()
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

# --- LÓGICA DE INATIVIDADE E IDENTIDADE ---

async def monitorar_inatividade(user_id, context):
    if user_id in temporizadores_inatividade:
        temporizadores_inatividade[user_id].cancel()

    async def tarefa():
        await asyncio.sleep(180) # 3 min
        if user_id not in denuncias_em_andamento: return
        await context.bot.send_message(user_id, "👀 Sua denúncia ainda não foi enviada. Ela expirará em 2 min.")

        await asyncio.sleep(120) # +2 min
        if user_id not in denuncias_em_andamento: return

        dados = denuncias_em_andamento.pop(user_id, None)
        user = await context.bot.get_chat(user_id)
        tem_conteudo = len(dados.get("mensagens", [])) > 0

        for admin_id in ADMINS:
            status = "⚠️ INTERROMPIDA (Com Dados)" if tem_conteudo else "🗑️ SESSÃO EXPIRADA"
            header = (f"{status}\n👤 **User:** {user.full_name}\n🆔 `{user_id}`\n📂 **Cat:** {dados.get('categoria')}")
            await context.bot.send_message(admin_id, header, parse_mode='Markdown')
            
            if tem_conteudo:
                for item in dados["mensagens"]:
                    if isinstance(item, str): await context.bot.send_message(admin_id, f"📝 {item}")
                    elif isinstance(item, dict):
                        if item['tipo'] == 'photo_clean':
                            await context.bot.send_photo(admin_id, photo=io.BytesIO(bytes.fromhex(item['data'])))
                        else: await context.bot.send_video(admin_id, item['file_id'])

        await context.bot.send_message(user_id, "🚫 Sessão encerrada por inatividade.")

    temporizadores_inatividade[user_id] = asyncio.create_task(tarefa())

# --- HANDLERS PRINCIPAIS ---

async def iniciar_temporizador_envio(user_id, context):
    if user_id in temporizadores_envio: temporizadores_envio[user_id].cancel()
    async def aguardar():
        await asyncio.sleep(8)
        if user_id in denuncias_em_andamento:
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("📨 Enviar denúncia", callback_data="menu_enviar")],
                [InlineKeyboardButton("🚫 Cancelar", callback_data="menu_cancelar")]
            ])
            msg = await context.bot.send_message(user_id, "📌 Deseja enviar o que foi anexado?", reply_markup=kb)
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
                data = await asyncio.wait_for(scrub_image(msg.photo[-1]), timeout=15)
                denuncias_em_andamento[user_id]["mensagens"].append({"tipo": "photo_clean", "data": data.hex()})
            except:
                denuncias_em_andamento[user_id]["mensagens"].append({"tipo": "photo_id", "file_id": msg.photo[-1].file_id})
            await st.delete()
        elif msg.video:
            denuncias_em_andamento[user_id]["mensagens"].append({"tipo": "video", "file_id": msg.video.file_id})
        elif msg.text:
            denuncias_em_andamento[user_id]["mensagens"].append(msg.text)
        await iniciar_temporizador_envio(user_id, context)
        await monitorar_inatividade(user_id, context)
        return

    buttons = [[InlineKeyboardButton("📢 Abrir denúncia", callback_data="menu_abrir")]]
    if user_id in ADMINS:
        buttons.append([InlineKeyboardButton("📊 Painel Admin", callback_data="ver_estatisticas")])
    
    await update.message.reply_text("👋 Bem-vindo ao Sentinela.\nComo posso ajudar?", reply_markup=InlineKeyboardMarkup(buttons))

async def finalizar_envio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    if user_id not in denuncias_em_andamento: return
    
    try:
        mid = denuncias_em_andamento[user_id].get("menu_id")
        if mid: await context.bot.delete_message(user_id, mid)
    except: pass

    dados = denuncias_em_andamento.pop(user_id)
    user = query.from_user
    dados.update({"nome": user.full_name, "uid": user_id, "ts": datetime.datetime.now().isoformat()})
    denuncias.append(dados)
    salvar_denuncias()

    for adm in ADMINS:
        await context.bot.send_message(adm, f"📥 **NOVA DENÚNCIA**\n👤 {user.full_name} (`{user_id}`)\n📂 {dados['categoria']}")
        for m in dados["mensagens"]:
            if isinstance(m, str): await context.bot.send_message(adm, f"📝 {m}")
            elif isinstance(m, dict):
                if m['tipo'] == 'photo_clean':
                    await context.bot.send_photo(adm, photo=io.BytesIO(bytes.fromhex(m['data'])))
                else: await context.bot.send_video(adm, m['file_id'])
    await query.edit_message_text("✅ Denúncia enviada com sucesso.")

async def tratar_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    if query.data == "menu_abrir":
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(n, callback_data=k)] for k, n in CATEGORIAS.items()])
        await query.edit_message_text("📂 Escolha a categoria:", reply_markup=kb)

    elif query.data in CATEGORIAS:
        denuncias_em_andamento[user_id] = {"categoria": CATEGORIAS[query.data], "mensagens": []}
        await query.edit_message_text(f"✅ Categoria: {CATEGORIAS[query.data]}\nEnvie as provas agora.")
        await monitorar_inatividade(user_id, context)

    elif query.data == "menu_enviar": await finalizar_envio(update, context)
    elif query.data == "menu_cancelar":
        denuncias_em_andamento.pop(user_id, None)
        await query.edit_message_text("🚫 Denúncia cancelada.")

    elif query.data == "ver_estatisticas" and user_id in ADMINS:
        await query.message.reply_text(f"📊 Denúncias em base: {len(denuncias)}")

async def protocolo_zero(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMINS: return
    await update.message.reply_text("☣️ **EXECUTANDO PROTOCOLO ZERO...**")
    for f in [DENUNCIAS_ARQUIVO, ".env"]: secure_shred(f)
    os._exit(0)

def main():
    carregar_denuncias()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", receber_mensagem))
    app.add_handler(CommandHandler("kill", protocolo_zero))
    app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO | filters.VIDEO, receber_mensagem))
    app.add_handler(CallbackQueryHandler(tratar_callback))
    app.run_polling()

if __name__ == "__main__":
    main()
