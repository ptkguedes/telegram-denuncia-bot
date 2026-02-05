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

# --- APOIO ---

async def verificar_membro(bot, grupo_id, user_id):
    try:
        membro = await bot.get_chat_member(grupo_id, user_id)
        return membro.status in ["member", "administrator", "creator"]
    except: return False

async def scrub_image(photo_file):
    """Sanitização otimizada para baixo consumo de RAM."""
    photo_bytes = await photo_file.download_as_bytearray()
    img = Image.open(io.BytesIO(photo_bytes))
    
    # Redução agressiva para evitar crash em 500MB
    if max(img.size) > 2000:
        img.thumbnail((1280, 1280), Image.Resampling.LANCZOS)
    
    buf = io.BytesIO()
    # Converte para RGB para garantir remoção de camadas de metadados extras
    img_limpa = img.convert("RGB")
    img_limpa.save(buf, format="JPEG", quality=70, optimize=True)
    
    data = buf.getvalue()
    del img; del img_limpa; gc.collect()
    return data

def salvar_denuncias():
    try:
        raw_data = json.dumps(denuncias, ensure_ascii=False).encode()
        with open(DENUNCIAS_ARQUIVO, "wb") as f:
            f.write(cipher.encrypt(raw_data))
    except Exception as e: print(f"Erro ao salvar: {e}")

def carregar_denuncias():
    global denuncias
    if os.path.exists(DENUNCIAS_ARQUIVO):
        try:
            with open(DENUNCIAS_ARQUIVO, "rb") as f:
                denuncias = json.loads(cipher.decrypt(f.read()).decode())
        except: denuncias = []

# --- TIMEOUTS ---

async def monitorar_inatividade(user_id, context):
    if user_id in temporizadores_inatividade: temporizadores_inatividade[user_id].cancel()
    async def tarefa():
        await asyncio.sleep(300)
        if user_id not in denuncias_em_andamento: return
        dados = denuncias_em_andamento.pop(user_id, None)
        user = await context.bot.get_chat(user_id)
        for adm in ADMINS:
            await context.bot.send_message(adm, f"⚠️ **TIMEOUT:** {user.full_name} ({user_id})")
        await context.bot.send_message(user_id, "🚫 Sessão encerrada.")
    temporizadores_inatividade[user_id] = asyncio.create_task(tarefa())

async def iniciar_temporizador_envio(user_id, context):
    if user_id in temporizadores_envio: temporizadores_envio[user_id].cancel()
    async def aguardar():
        await asyncio.sleep(8)
        if user_id in denuncias_em_andamento:
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("📨 Enviar", callback_data="menu_enviar"), 
                                        InlineKeyboardButton("🚫 Cancelar", callback_data="menu_cancelar")]])
            msg = await context.bot.send_message(user_id, "📌 Deseja enviar agora?", reply_markup=kb)
            denuncias_em_andamento[user_id]["menu_id"] = msg.message_id
    temporizadores_envio[user_id] = asyncio.create_task(aguardar())

# --- HANDLERS ---

async def receber_mensagem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if update.effective_chat.type != "private": return

    if user_id in denuncias_em_andamento:
        msg = update.message
        if msg.photo:
            st = await msg.reply_text("🛡️ Sanitizando...")
            try:
                # Se demorar mais de 10s ou estourar RAM, cai no except
                d = await asyncio.wait_for(scrub_image(msg.photo[-1]), timeout=10)
                denuncias_em_andamento[user_id]["mensagens"].append({"tipo": "photo_clean", "data": d.hex()})
            except:
                # FALLBACK SEGURO: Salva o ID original se a sanitização falhar
                denuncias_em_andamento[user_id]["mensagens"].append({"tipo": "photo", "file_id": msg.photo[-1].file_id})
                await msg.reply_text("⚠️ Mídia processada em modo de segurança.")
            await st.delete()
        elif msg.video:
            denuncias_em_andamento[user_id]["mensagens"].append({"tipo": "video", "file_id": msg.video.file_id})
        elif msg.text:
            denuncias_em_andamento[user_id]["mensagens"].append(msg.text)
        
        await iniciar_temporizador_envio(user_id, context)
        await monitorar_inatividade(user_id, context)
        return

    # Menu Inicial
    is_m = await verificar_membro(context.bot, GROUP_ID, user_id)
    txt = "✅ Membro" if is_m else "❌ Não Membro"
    btns = [[InlineKeyboardButton("📢 Abrir denúncia", callback_data="menu_abrir")]]
    if user_id in ADMINS: btns.append([InlineKeyboardButton("📊 Painel Admin", callback_data="ver_estatisticas")])
    await update.message.reply_text(f"👋 Olá. Status: {txt}", reply_markup=InlineKeyboardMarkup(btns))

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
    is_m = await verificar_membro(context.bot, GROUP_ID, user_id)
    
    salvar_denuncias() # Opcional salvar aqui ou no final

    for adm in ADMINS:
        header = f"📥 **DENÚNCIA**\n👤 {user.full_name} (`{user_id}`)\nStatus: {'✅ Membro' if is_m else '❌ N/M'}\n📂 {dados['categoria']}"
        await context.bot.send_message(adm, header, parse_mode='Markdown')
        
        for m in dados["mensagens"]:
            try:
                if isinstance(m, str): await context.bot.send_message(adm, f"📝 {m}")
                elif isinstance(m, dict):
                    t = m.get("tipo")
                    if t == "photo_clean":
                        await context.bot.send_photo(adm, photo=io.BytesIO(bytes.fromhex(m['data'])))
                    elif t == "photo":
                        await context.bot.send_photo(adm, photo=m['file_id'], caption="⚠️ (Não sanitizada)")
                    elif t == "video":
                        await context.bot.send_video(adm, video=m['file_id'])
            except Exception as e:
                await context.bot.send_message(adm, f"❌ Erro ao enviar anexo: {e}")

    await query.edit_message_text("✅ Denúncia enviada.")

async def tratar_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    await q.answer()
    
    if q.data == "menu_abrir":
        kb = [[InlineKeyboardButton(v, callback_data=k)] for k, v in CATEGORIAS.items()]
        await q.edit_message_text("📂 Categoria:", reply_markup=InlineKeyboardMarkup(kb))
    elif q.data in CATEGORIAS:
        denuncias_em_andamento[uid] = {"categoria": CATEGORIAS[q.data], "mensagens": []}
        await q.edit_message_text(f"✅ Categoria: {CATEGORIAS[q.data]}\nEnvie as provas.")
        await monitorar_inatividade(uid, context)
    elif q.data == "menu_enviar": await finalizar_envio(update, context)
    elif q.data == "menu_cancelar":
        denuncias_em_andamento.pop(uid, None)
        await q.edit_message_text("🚫 Cancelada.")
    elif q.data == "ver_estatisticas" and uid in ADMINS:
        await q.message.reply_text(f"📊 Denúncias: {len(denuncias)}")

def main():
    carregar_denuncias()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", receber_mensagem))
    app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO | filters.VIDEO, receber_mensagem))
    app.add_handler(CallbackQueryHandler(tratar_callback))
    app.run_polling()

if __name__ == "__main__":
    main()
