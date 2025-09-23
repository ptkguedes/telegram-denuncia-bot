import os
import datetime
import json
import asyncio
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes
)
from moderacao import verificar_mensagem

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")

ADMINS = [7477496964, 6439529867]  # Jake e Maria

DENUNCIAS_ARQUIVO = "denuncias.json"
BLOQUEADOS_ARQUIVO = "bloqueados.json"
denuncias = []
bloqueados = []
denuncias_em_andamento = {}
tempo_inatividade = {}
conversas_ativas = {}

def carregar_denuncias():
    global denuncias
    if os.path.exists(DENUNCIAS_ARQUIVO):
        with open(DENUNCIAS_ARQUIVO, "r", encoding="utf-8") as f:
            denuncias = json.load(f)

def salvar_denuncias():
    with open(DENUNCIAS_ARQUIVO, "w", encoding="utf-8") as f:
        json.dump(denuncias, f, ensure_ascii=False, indent=4)

def carregar_bloqueados():
    global bloqueados
    if os.path.exists(BLOQUEADOS_ARQUIVO):
        with open(BLOQUEADOS_ARQUIVO, "r", encoding="utf-8") as f:
            bloqueados = json.load(f)

def salvar_bloqueados():
    with open(BLOQUEADOS_ARQUIVO, "w", encoding="utf-8") as f:
        json.dump(bloqueados, f, ensure_ascii=False, indent=4)

carregar_denuncias()
carregar_bloqueados()

CATEGORIAS = {
    "cat_pornografia": "Pornografia / CP",
    "cat_venda": "Venda não autorizada",
    "cat_privacidade": "Violação de privacidade",
    "cat_bullying": "Bullying / Ofensas",
    "cat_violencia": "Conteúdo violento",
    "cat_outro": "Outro"
}

async def monitorar_inatividade(user_id, context):
    await asyncio.sleep(180)
    ultimo = tempo_inatividade.get(user_id)
    if not ultimo or user_id not in denuncias_em_andamento:
        return
    if (datetime.datetime.now() - ultimo).total_seconds() >= 180:
        await context.bot.send_message(
            chat_id=user_id,
            text="👋 Ei, ainda está aí?\nSe não for continuar com a denúncia, ela será fechada automaticamente por inatividade."
        )
        await asyncio.sleep(30)
        ultimo = tempo_inatividade.get(user_id)
        if (datetime.datetime.now() - ultimo).total_seconds() >= 210:
            denuncias_em_andamento.pop(user_id, None)
            tempo_inatividade.pop(user_id, None)
            await context.bot.send_message(
                chat_id=user_id,
                text="🚫 Denúncia encerrada automaticamente por inatividade. Se desejar, você pode iniciar novamente."
            )

async def abrir_denuncia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private":
        return
    user = update.message.from_user
    user_id = user.id
    username = user.username or "Não disponível"
    if user_id in bloqueados:
        await update.message.reply_text("🚫 Você está bloqueado e não pode enviar denúncias.")
        return
    categorias = [[InlineKeyboardButton(nome, callback_data=key)] for key, nome in CATEGORIAS.items()]
    markup = InlineKeyboardMarkup(categorias)
    await update.message.reply_text("Escolha a categoria da denúncia:", reply_markup=markup)
    for admin_id in ADMINS:
        await context.bot.send_message(
            chat_id=admin_id,
            text=f"👤 Novo usuário iniciou uma denúncia:\nID: {user_id}\nUsername: @{username}"
        )
async def receber_mensagem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private":
        return

    user_id = update.message.from_user.id

    if user_id in conversas_ativas:
        admin_id = conversas_ativas[user_id]
        texto = update.message.text.strip() if update.message.text else "[imagem]"
        if update.message.photo:
            foto = update.message.photo[-1]
            file_id = foto.file_id
            texto = f"[imagem] file_id: {file_id}"
        await context.bot.send_message(
            chat_id=admin_id,
            text=f"📨 Resposta de @{update.message.from_user.username or user_id}:\n{texto}"
        )
        return

    if user_id not in denuncias_em_andamento:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 Abrir denúncia", callback_data="menu_abrir")]
        ])
        await update.message.reply_text("👋 Olá! Bem-vindo ao sistema de denúncias.\nEscolha uma opção abaixo:", reply_markup=keyboard)
        return

    if update.message.photo:
        foto = update.message.photo[-1]
        file_id = foto.file_id
        texto = f"[imagem] file_id: {file_id}"
    else:
        texto = update.message.text.strip() if update.message.text else "[imagem]"

    erro = verificar_mensagem(user_id, texto)
    if erro:
        await update.message.reply_text(erro)
        return

    timestamp = datetime.datetime.now().isoformat()
    denuncias_em_andamento[user_id]["mensagens"].append({"texto": texto, "timestamp": timestamp})
    tempo_inatividade[user_id] = datetime.datetime.now()

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📨 Enviar denúncia", callback_data="menu_enviar")],
        [InlineKeyboardButton("🚫 Cancelar denúncia", callback_data="menu_cancelar")]
    ])
    await update.message.reply_text("📌 Mensagem registrada. Quando terminar, escolha uma opção abaixo:", reply_markup=keyboard)

async def enviar_denuncia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private":
        return

    user = update.message.from_user
    user_id = user.id
    username = user.username or "Não disponível"
    dados = denuncias_em_andamento.get(user_id)

    if not dados or not dados["mensagens"]:
        await update.message.reply_text("⚠️ Nenhuma denúncia em andamento.")
        return

    texto_completo = ""
    imagens = []

    for m in dados["mensagens"]:
        texto_completo += f"{m['texto']}\n"
        if m["texto"].startswith("[imagem] file_id:"):
            file_id = m["texto"].split("file_id:")[1].strip()
            imagens.append(file_id)

    timestamp = datetime.datetime.now().isoformat()
    denuncia = {
        "tipo": "texto",
        "conteudo": texto_completo,
        "categoria": dados["categoria"],
        "timestamp": timestamp,
        "user_id": user_id,
        "username": username
    }

    denuncias.append(denuncia)
    salvar_denuncias()
    denuncias_em_andamento.pop(user_id, None)
    tempo_inatividade.pop(user_id, None)

    await update.message.reply_text("✅ Sua denúncia foi enviada com sucesso. Obrigado por contribuir com a segurança do grupo.")

    botoes_admin = []

    if user_id in bloqueados:
        botoes_admin.append([InlineKeyboardButton("✅ Desbloquear usuário", callback_data=f"desbloquear_{user_id}")])
    else:
        botoes_admin.append([InlineKeyboardButton("🚫 Bloquear usuário", callback_data=f"bloquear_{user_id}")])

    if user_id in conversas_ativas:
        botoes_admin.append([InlineKeyboardButton("💬 Responder ao denunciante", callback_data=f"responder_{user_id}")])
    else:
        botoes_admin.append([InlineKeyboardButton("💬 Interagir com denunciante", callback_data=f"interagir_{user_id}")])

    keyboard = InlineKeyboardMarkup(botoes_admin)

    mensagem_admin = (
        f"📥 Nova denúncia recebida\n"
        f"📅 {timestamp}\n"
        f"👤 @{username} (ID: {user_id})\n"
        f"📂 Categoria: {dados['categoria']}\n"
        f"📝 Conteúdo:\n{texto_completo}"
    )

    for admin_id in ADMINS:
        await context.bot.send_message(chat_id=admin_id, text=mensagem_admin, reply_markup=keyboard)
        for file_id in imagens:
            await context.bot.send_photo(chat_id=admin_id, photo=file_id)
            # 🔧 Comandos administrativos

async def interagir(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id not in ADMINS:
        await update.message.reply_text("🚫 Comando restrito aos administradores.")
        return
    try:
        partes = update.message.text.split(maxsplit=2)
        alvo_id = int(partes[1])
        mensagem = partes[2]
        conversas_ativas[alvo_id] = update.message.from_user.id
        await context.bot.send_message(chat_id=alvo_id, text=f"📣 Mensagem da moderação:\n{mensagem}")
        await update.message.reply_text("✅ Mensagem enviada e canal de conversa ativado.")
    except Exception:
        await update.message.reply_text("⚠️ Uso correto: /interagir <user_id> <mensagem>")

async def responder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id not in ADMINS:
        await update.message.reply_text("🚫 Comando restrito aos administradores.")
        return
    try:
        partes = update.message.text.split(maxsplit=2)
        alvo_id = int(partes[1])
        mensagem = partes[2]
        await context.bot.send_message(chat_id=alvo_id, text=f"💬 Resposta da moderação:\n{mensagem}")
        await update.message.reply_text("✅ Resposta enviada ao denunciante.")
    except Exception:
        await update.message.reply_text("⚠️ Uso: /responder <user_id> <mensagem>")

async def encerrar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id not in ADMINS:
        await update.message.reply_text("🚫 Comando restrito aos administradores.")
        return
    try:
        alvo_id = int(context.args[0])
        if alvo_id in conversas_ativas:
            conversas_ativas.pop(alvo_id)
            await update.message.reply_text("✅ Conversa encerrada com sucesso.")
        else:
            await update.message.reply_text("⚠️ Esse usuário não está em conversa ativa.")
    except:
        await update.message.reply_text("⚠️ Uso: /encerrar <user_id>")

async def cancelar_denuncia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private":
        return
    user_id = update.message.from_user.id
    if user_id in denuncias_em_andamento:
        denuncias_em_andamento.pop(user_id)
        tempo_inatividade
        # 🔧 Comandos administrativos

async def interagir(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id not in ADMINS:
        await update.message.reply_text("🚫 Comando restrito aos administradores.")
        return
    try:
        partes = update.message.text.split(maxsplit=2)
        alvo_id = int(partes[1])
        mensagem = partes[2]
        conversas_ativas[alvo_id] = update.message.from_user.id
        await context.bot.send_message(chat_id=alvo_id, text=f"📣 Mensagem da moderação:\n{mensagem}")
        await update.message.reply_text("✅ Mensagem enviada e canal de conversa ativado.")
    except Exception:
        await update.message.reply_text("⚠️ Uso correto: /interagir <user_id> <mensagem>")

async def responder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id not in ADMINS:
        await update.message.reply_text("🚫 Comando restrito aos administradores.")
        return
    try:
        partes = update.message.text.split(maxsplit=2)
        alvo_id = int(partes[1])
        mensagem = partes[2]
        await context.bot.send_message(chat_id=alvo_id, text=f"💬 Resposta da moderação:\n{mensagem}")
        await update.message.reply_text("✅ Resposta enviada ao denunciante.")
    except Exception:
        await update.message.reply_text("⚠️ Uso: /responder <user_id> <mensagem>")

async def encerrar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id not in ADMINS:
        await update.message.reply_text("🚫 Comando restrito aos administradores.")
        return
    try:
        alvo_id = int(context.args[0])
        if alvo_id in conversas_ativas:
            conversas_ativas.pop(alvo_id)
            await update.message.reply_text("✅ Conversa encerrada com sucesso.")
        else:
            await update.message.reply_text("⚠️ Esse usuário não está em conversa ativa.")
    except:
        await update.message.reply_text("⚠️ Uso: /encerrar <user_id>")

async def cancelar_denuncia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private":
        return
    user_id = update.message.from_user.id
    if user_id in denuncias_em_andamento:
        denuncias_em_andamento.pop(user_id)
        tempo_inatividade.pop(user_id, None)
        await update.message.reply_text("🚫 Sua denúncia foi cancelada. Nenhum dado foi enviado.")
    else:
        await update.message.reply_text("⚠️ Você não possui nenhuma denúncia em andamento.")

async def estatisticas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private":
        return
    if update.message.from_user.id not in ADMINS:
        await update.message.reply_text("🚫 Você não tem permissão para visualizar estatísticas.")
        return
    contagem = {nome: 0 for nome in CATEGORIAS.values()}
    for d in denuncias:
        cat = d.get("categoria")
        if cat in contagem:
            contagem[cat] += 1
    texto = "📊 Estatísticas de denúncias:\n"
    for nome, qtd in contagem.items():
        texto += f"• {nome}: {qtd}\n"
    await update.message.reply_text(texto)

async def unblock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id not in ADMINS:
        await update.message.reply_text("🚫 Comando restrito aos administradores.")
        return
    try:
        if context.args:
            alvo_id = int(context.args[0])
        elif update.message.reply_to_message:
            alvo_id = update.message.reply_to_message.from_user.id
        else:
            await update.message.reply_text("⚠️ Uso: /unblock <user_id> ou responda à mensagem do usuário bloqueado.")
            return

        if alvo_id in bloqueados:
            bloqueados.remove(alvo_id)
            salvar_bloqueados()
            await update.message.reply_text(f"✅ Usuário {alvo_id} foi desbloqueado com sucesso.")
        else:
            await update.message.reply_text("⚠️ Esse usuário não está bloqueado.")
    except Exception:
        await update.message.reply_text("⚠️ Erro ao tentar desbloquear. Verifique o ID ou a mensagem marcada.")

# 🎮 Callback geral para botões inline
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    data = query.data

    if data == "menu_abrir":
        await abrir_denuncia(update, context)
        return

    if data == "menu_enviar":
        await enviar_denuncia(update, context)
        return

    if data == "menu_cancelar":
        await cancelar_denuncia(update, context)
        return

    if data in CATEGORIAS:
        denuncias_em_andamento[user_id] = {
            "categoria": CATEGORIAS[data],
            "mensagens": []
        }
        tempo_inatividade[user_id] = datetime.datetime.now()
        await query.edit_message_text(f"✅ Categoria selecionada: {CATEGORIAS[data]}\nAgora envie as mensagens com evidências.")
        asyncio.create_task(monitorar_inatividade(user_id, context))
        return

    if data.startswith("bloquear_") and user_id in ADMINS:
        alvo_id = int(data.split("_")[1])
        if alvo_id not in bloqueados:
            bloqueados.append(alvo_id)
            salvar_bloqueados()
            await query.edit_message_text("🚫 Usuário bloqueado com sucesso.")
        else:
            await query.edit_message_text("⚠️ Usuário já está bloqueado.")

    elif data.startswith("desbloquear_") and user_id in ADMINS:
        alvo_id = int(data.split("_")[1])
        if alvo_id in bloqueados:
            bloqueados.remove(alvo_id)
            salvar_bloqueados()
            await query.edit_message_text("✅ Usuário desbloqueado com sucesso.")
        else:
            await query.edit_message_text("⚠️ Usuário não está bloqueado.")

    elif data.startswith("interagir_") and user_id in ADMINS:
        alvo_id = int(data.split("_")[1])
        conversas_ativas[alvo_id] = user_id
        await context.bot.send_message(
            chat_id=alvo_id,
            text="📣 Um administrador entrou em contato com você sobre sua denúncia. Por favor, responda aqui se desejar continuar."
        )
        await query.edit_message_text("✅ Mensagem enviada ao denunciante e canal de conversa ativado.")

    elif data.startswith("responder_") and user_id in ADMINS:
        alvo_id = int(data.split("_")[1])
        context.user_data["resposta_alvo"] = alvo_id
        await context.bot.send_message(chat_id=user_id, text="✏️ Digite a mensagem que deseja enviar ao denunciante.")

    elif data == "ver_estatisticas" and user_id in ADMINS:
        await estatisticas(update, context)

# 🚀 Inicialização do bot
app = ApplicationBuilder().token(TOKEN).build()

# 📌 Registro de handlers
app.add_handler(CommandHandler("abrirdenuncia", abrir_denuncia))
app.add_handler(CommandHandler("enviar_denuncia", enviar_denuncia))
app.add_handler(CommandHandler("cancelardenuncia", cancelar_denuncia))
app.add_handler(CommandHandler("estatisticas", estatisticas))
app.add_handler(CommandHandler("interagir", interagir))
app.add_handler(CommandHandler("responder", responder))
app.add_handler(CommandHandler("encerrar", encerrar))
app.add_handler(CommandHandler("unblock", unblock))
app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO, receber_mensagem))
app.add_handler(CallbackQueryHandler(callback_handler))
app.add_handler(MessageHandler(~filters.ChatType.PRIVATE, lambda update, context: None))  # Ignora grupos

app.run_polling()


