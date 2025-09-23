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
    chat = update.effective_chat
    user = update.effective_user
    user_id = user.id
    username = user.username or "Não disponível"

    if chat.type != "private":
        return

    if user_id in bloqueados:
        await context.bot.send_message(chat_id=user_id, text="🚫 Você está bloqueado e não pode enviar denúncias.")
        return

    categorias = [[InlineKeyboardButton(nome, callback_data=key)] for key, nome in CATEGORIAS.items()]
    markup = InlineKeyboardMarkup(categorias)

    await context.bot.send_message(chat_id=user_id, text="Escolha a categoria da denúncia:", reply_markup=markup)

    for admin_id in ADMINS:
        await context.bot.send_message(
            chat_id=admin_id,
            text=f"👤 Novo usuário iniciou uma denúncia:\nID: {user_id}\nUsername: @{username}"
        )
async def receber_mensagem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    user_id = user.id

    if chat.type != "private":
        return

    texto = update.effective_message.text or ""
    if user_id in conversas_ativas:
        admin_id = conversas_ativas[user_id]
        await context.bot.send_message(chat_id=admin_id, text=f"📨 Resposta de {user_id}:\n{texto}")
        return

    if user_id in context.user_data and "resposta_alvo" in context.user_data:
        alvo_id = context.user_data.pop("resposta_alvo")
        await context.bot.send_message(chat_id=alvo_id, text=f"💬 Mensagem da moderação:\n{texto}")
        await context.bot.send_message(chat_id=user_id, text="✅ Mensagem enviada ao denunciante.")
        return

    if user_id in denuncias_em_andamento:
        erro = verificar_mensagem(user_id, texto)
        if erro:
            await context.bot.send_message(chat_id=user_id, text=erro)
            return

        denuncias_em_andamento[user_id]["mensagens"].append(texto)
        tempo_inatividade[user_id] = datetime.datetime.now()

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📨 Enviar denúncia", callback_data="menu_enviar")],
            [InlineKeyboardButton("🚫 Cancelar denúncia", callback_data="menu_cancelar")]
        ])
        await context.bot.send_message(chat_id=user_id, text="📌 Mensagem registrada. Quando terminar, escolha uma opção abaixo:", reply_markup=keyboard)
        return

    if user_id in ADMINS:
        await menu_admin(update, context)
    else:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 Abrir denúncia", callback_data="menu_abrir")]
        ])
        await context.bot.send_message(chat_id=user_id, text="👋 Olá! Bem-vindo ao sistema de denúncias.\nEscolha uma opção abaixo:", reply_markup=keyboard)

async def enviar_denuncia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in denuncias_em_andamento:
        await context.bot.send_message(chat_id=user_id, text="⚠️ Você não possui nenhuma denúncia em andamento.")
        return

    dados = denuncias_em_andamento.pop(user_id)
    tempo_inatividade.pop(user_id, None)
    dados["user_id"] = user_id
    dados["timestamp"] = datetime.datetime.now().isoformat()
    denuncias.append(dados)
    salvar_denuncias()

    await context.bot.send_message(chat_id=user_id, text="✅ Denúncia enviada com sucesso. Obrigado por colaborar!")

    for admin_id in ADMINS:
        await context.bot.send_message(
            chat_id=admin_id,
            text=f"📥 Nova denúncia recebida de {user_id}:\nCategoria: {dados['categoria']}\nMensagens: {len(dados['mensagens'])}"
        )

async def menu_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMINS:
        await context.bot.send_message(chat_id=user_id, text="🚫 Menu exclusivo para administradores.")
        return

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Ver estatísticas", callback_data="ver_estatisticas")],
        [InlineKeyboardButton("📥 Ver denúncias recentes", callback_data="ver_denuncias")],
        [InlineKeyboardButton("✅ Lista de desbloqueados", callback_data="ver_desbloqueados")]
    ])
    await context.bot.send_message(chat_id=user_id, text="👮 Painel administrativo:", reply_markup=keyboard)
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
app.add_handler(CommandHandler("menu", menu_admin))
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


