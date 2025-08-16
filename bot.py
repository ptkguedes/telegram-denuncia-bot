from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
import datetime
import json
import os

# Lista de IDs dos administradores
ADMINS = [7477496964, 6439529867]

# Arquivo para salvar denúncias
DENUNCIAS_ARQUIVO = "denuncias.json"

# Lista em memória
denuncias = []

# Carrega denúncias salvas
def carregar_denuncias():
    global denuncias
    if os.path.exists(DENUNCIAS_ARQUIVO):
        with open(DENUNCIAS_ARQUIVO, "r", encoding="utf-8") as f:
            denuncias = json.load(f)

# Salva denúncias no arquivo
def salvar_denuncias():
    with open(DENUNCIAS_ARQUIVO, "w", encoding="utf-8") as f:
        json.dump(denuncias, f, ensure_ascii=False, indent=4)

carregar_denuncias()

# Comando /start — só responde em chat privado
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private":
        return  # Ignora se não for chat privado

    await update.message.reply_text(
        "Bem-vindo ao Canal de Denúncias\n\n"
        "Este espaço é confidencial e destinado a receber denúncias sobre comportamentos, conteúdos ou situações que violem as regras do grupo.\n\n"
        "⚠️ Importante:\n"
        "Todas as informações serão analisadas pela administração.\n"
        "Seu nome será mantido em sigilo absoluto.\n"
        "Utilize este canal apenas para denúncias reais, evitando trotes ou mensagens sem fundamento.\n\n"
        "✍️ Para começar, descreva abaixo a sua denúncia com o máximo de detalhes possíveis (incluindo prints, se necessário)."
    )

# Recebe denúncias — só responde em chat privado
async def receber_denuncia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private":
        return  # Ignora se não for chat privado

    user = update.message.from_user
    user_id = user.id
    username = user.username or "Não disponível"
    timestamp = datetime.datetime.now().isoformat()

    if update.message.text:
        denuncia = {
            "tipo": "texto",
            "conteudo": update.message.text,
            "timestamp": timestamp,
            "user_id": user_id,
            "username": username
        }
        mensagem_admin = (
            f"📥 Nova denúncia recebida\n"
            f"📅 {timestamp}\n"
            f"👤 Denunciante: @{username} (ID: {user_id})\n"
            f"📝 Conteúdo:\n{update.message.text}"
        )
    elif update.message.photo:
        file_id = update.message.photo[-1].file_id
        denuncia = {
            "tipo": "imagem",
            "file_id": file_id,
            "timestamp": timestamp,
            "user_id": user_id,
            "username": username
        }
        mensagem_admin = (
            f"📥 Nova denúncia com imagem recebida\n"
            f"📅 {timestamp}\n"
            f"👤 Denunciante: @{username} (ID: {user_id})"
        )
    else:
        await update.message.reply_text("🚫 Tipo de conteúdo não suportado. Envie texto ou imagem.")
        return

    denuncias.append(denuncia)
    salvar_denuncias()

    await update.message.reply_text("✅ Sua denúncia foi enviada com sucesso. Obrigado por contribuir com a segurança do grupo.")

    for admin_id in ADMINS:
        if denuncia["tipo"] == "texto":
            await context.bot.send_message(chat_id=admin_id, text=mensagem_admin)
        elif denuncia["tipo"] == "imagem":
            await context.bot.send_photo(chat_id=admin_id, photo=file_id, caption=mensagem_admin)

# Comando /ver — só para administradores
async def ver_denuncias(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private":
        return  # Ignora se não for chat privado

    if update.message.from_user.id in ADMINS:
        if not denuncias:
            await update.message.reply_text("Nenhuma denúncia registrada até o momento.")
        else:
            for d in denuncias:
                if d["tipo"] == "texto":
                    msg = (
                        f"📅 {d['timestamp']}\n"
                        f"👤 @{d['username']} (ID: {d['user_id']})\n"
                        f"📝 {d['conteudo']}"
                    )
                    await update.message.reply_text(msg)
                elif d["tipo"] == "imagem":
                    caption = (
                        f"📅 {d['timestamp']}\n"
                        f"👤 @{d['username']} (ID: {d['user_id']})\n"
                        f"🖼️ Denúncia com imagem"
                    )
                    await update.message.reply_photo(photo=d["file_id"], caption=caption)
    else:
        await update.message.reply_text("🚫 Você não tem permissão para visualizar denúncias.")

# Inicializa o bot
app = ApplicationBuilder().token("8278374842:AAG1CuSDCC4bBSlCp5FvDlXlfpMr26lL5uk").build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("ver", ver_denuncias))
app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO, receber_denuncia))

app.run_polling()
