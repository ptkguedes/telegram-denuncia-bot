import os
import datetime
import json
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes
)
from moderacao import verificar_mensagem

ADMINS = [7477496964, 6439529867]

DENUNCIAS_ARQUIVO = "denuncias.json"
BLOQUEADOS_ARQUIVO = "bloqueados.json"
denuncias = []
bloqueados = []
denuncias_em_andamento = {}  # user_id: {"categoria": ..., "mensagens": [...]}
tempo_inatividade = {}       # user_id: datetime

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
                text="🚫 Denúncia encerrada automaticamente por inatividade. Se desejar, você pode iniciar novamente com /abrirdenuncia."
            )

async def abrir_denuncia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private":
        return
    user_id = update.message.from_user.id
    if user_id in bloqueados:
        await update.message.reply_text("🚫 Você está bloqueado e não pode enviar denúncias.")
        return
    categorias = [[InlineKeyboardButton(nome, callback_data=key)] for key, nome in CATEGORIAS.items()]
    markup = InlineKeyboardMarkup(categorias)
    await update.message.reply_text("Escolha a categoria da denúncia:", reply_markup=markup)

async def receber_mensagem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private":
        return
    user_id = update.message.from_user.id
    if user_id not in denuncias_em_andamento:
        await update.message.reply_text("🚫 Para fazer uma denúncia, você deve começar com /abrirdenuncia.")
        return
    texto = update.message.text.strip() if update.message.text else "[imagem]"
    erro = verificar_mensagem(user_id, texto)
    if erro:
        await update.message.reply_text(erro)
        return
    timestamp = datetime.datetime.now().isoformat()
    denuncias_em_andamento[user_id]["mensagens"].append({"texto": texto, "timestamp": timestamp})
    tempo_inatividade[user_id] = datetime.datetime.now()
    await update.message.reply_text("📌 Mensagem registrada. Quando terminar, digite /enviar_denuncia.")

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
    texto_completo = "\n".join([m["texto"] for m in dados["mensagens"]])
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
    mensagem_admin = (
        f"📥 Nova denúncia recebida\n"
        f"📅 {timestamp}\n"
        f"👤 @{username} (ID: {user_id})\n"
        f"📂 Categoria: {dados['categoria']}\n"
        f"📝 Conteúdo:\n{texto_completo}"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚫 Bloquear usuário", callback_data=f"bloquear_{user_id}")]
    ])
    for admin_id in ADMINS:
        await context.bot.send_message(chat_id=admin_id, text=mensagem_admin, reply_markup=keyboard)

async def cancelar_denuncia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private":
        return
    user_id = update.message.from_user.id
    if user_id in denuncias_em_andamento:
        denuncias_em_andamento.pop(user_id)
        tempo_inatividade.pop(user_id, None)
        await update.message.reply_text(
            "🚫 Sua denúncia foi cancelada. Nenhum dado foi enviado.\n"
            "Se desejar iniciar uma nova denúncia, digite /abrirdenuncia."
        )
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

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.message.chat.type != "private":
        return
    user_id = query.from_user.id
    if query.data.startswith("cat_"):
        categoria = CATEGORIAS.get(query.data, "Outro")
        denuncias_em_andamento[user_id] = {"categoria": categoria, "mensagens": []}
        tempo_inatividade[user_id] = datetime.datetime.now()
        context.application.create_task(monitorar_inatividade(user_id, context))
        await query.message.reply_text(
            f"✅ Categoria selecionada: {categoria}\nAgora descreva os detalhes da denúncia."
        )
        await query.message.reply_text(
            "📌 Por Favor, lembre-se de adicionar evidências referentes à denúncia que está sendo feita.\n"
            "Mantenha uma boa política no uso deste canal, evitando spam e perda de credibilidade em suas denúncias.\n\n"
            "Obrigado.\nAtt: Amizades"
        )
    elif query.data.startswith("bloquear_") and user_id in ADMINS:
        alvo_id = int(query.data.split("_")[1])
        if alvo_id not in bloqueados:
            bloqueados.append(alvo_id)
            salvar_bloqueados()
            await query.message.reply_text(f"✅ Usuário {alvo_id} bloqueado com sucesso.")
        else:
            await query.message.reply_text(f"⚠️ O usuário {alvo_id} já está bloqueado.")
        await query.edit_message_reply_markup(None)

TOKEN = os.getenv("BOT_TOKEN")
app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("abrirdenuncia", abrir_denuncia))
app.add_handler(CommandHandler("enviar_denuncia", enviar_denuncia))
app.add_handler(CommandHandler("cancelardenuncia", cancelar_denuncia))
app.add_handler(CommandHandler("estatisticas", estatisticas))
app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO, receber_mensagem))
app.add_handler(CallbackQueryHandler(callback_handler))
app.add_handler(MessageHandler(~filters.ChatType.PRIVATE, lambda update, context: None))
app.run_polling()
