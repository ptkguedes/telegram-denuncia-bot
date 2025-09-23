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

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")

ADMINS = [7477496964, 6439529867]  # Jake e Maria

DENUNCIAS_ARQUIVO = "denuncias.json"
BLOQUEADOS_ARQUIVO = "bloqueados.json"
denuncias = []
bloqueados = []
denuncias_em_andamento = {}
tempo_inatividade = {}
temporizadores_envio = {}
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

async def iniciar_temporizador_envio(user_id, context):
    if temporizadores_envio.get(user_id):
        temporizadores_envio[user_id].cancel()

    async def aguardar_e_sugerir_envio():
        await asyncio.sleep(8)
        if user_id in denuncias_em_andamento:
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("📨 Enviar denúncia", callback_data="menu_enviar")],
                [InlineKeyboardButton("🚫 Cancelar denúncia", callback_data="menu_cancelar")],
                [InlineKeyboardButton("✏️ Continuar denúncia", callback_data="menu_continuar")]
            ])
            await context.bot.send_message(
                chat_id=user_id,
                text="📌 Mensagem registrada. Quando terminar, escolha uma opção abaixo:",
                reply_markup=keyboard
            )

    temporizadores_envio[user_id] = asyncio.create_task(aguardar_e_sugerir_envio())

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

    if user_id in denuncias_em_andamento:
        await context.bot.send_message(
            chat_id=user_id,
            text="⚠️ Você já possui uma denúncia em andamento.\nFinalize ou cancele antes de iniciar outra."
        )
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
        tempo_inatividade[user_id] = datetime.datetime.now()

        if update.message.photo:
            file_id = update.message.photo[-1].file_id
            denuncias_em_andamento[user_id]["mensagens"].append({"tipo": "photo", "file_id": file_id})
        elif update.message.video:
            file_id = update.message.video.file_id
            denuncias_em_andamento[user_id]["mensagens"].append({"tipo": "video", "file_id": file_id})
        elif texto:
            denuncias_em_andamento[user_id]["mensagens"].append(texto)

        await iniciar_temporizador_envio(user_id, context)
        return

    if user_id in ADMINS:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 Abrir denúncia", callback_data="menu_abrir")],
            [InlineKeyboardButton("📂 Denúncias recentes", callback_data="menu_recentes")],
            [InlineKeyboardButton("📊 Painel de moderação", callback_data="menu_painel")]
        ])
        await context.bot.send_message(chat_id=user_id, text="👋 Painel administrativo:", reply_markup=keyboard)
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
    context.bot_data[f"denuncia_enviada_{user_id}"] = True

    for admin_id in ADMINS:
        cabecalho = (
            f"📥 Nova denúncia recebida:\n"
            f"👤 Usuário: {user_id}\n"
            f"📂 Categoria: {dados['categoria']}\n"
            f"🕒 Horário: {dados['timestamp']}\n"
            f"📎 Total de mensagens: {len(dados['mensagens'])}"
        )

        botoes = []
        if user_id not in bloqueados:
            botoes.append(InlineKeyboardButton("🚫 Bloquear usuário", callback_data=f"bloquear_{user_id}"))
        botoes.append(InlineKeyboardButton("💬 Interagir com denunciante", callback_data=f"interagir_{user_id}"))
        markup = InlineKeyboardMarkup([botoes])

        await context.bot.send_message(chat_id=admin_id, text=cabecalho, reply_markup=markup)

        for item in dados["mensagens"]:
            if isinstance(item, str):
                await context.bot.send_message(chat_id=admin_id, text=f"📝 {item}")
            elif isinstance(item, dict):
                tipo = item.get("tipo")
                arquivo_id = item.get("file_id")
                if tipo == "photo":
                    await context.bot.send_photo(chat_id=admin_id, photo=arquivo_id)
                elif tipo == "video":
                    await context.bot.send_video(chat_id=admin_id, video=arquivo_id)
async def cancelar_denuncia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in denuncias_em_andamento:
        denuncias_em_andamento.pop(user_id)
        tempo_inatividade.pop(user_id, None)
        await context.bot.send_message(chat_id=user_id, text="🚫 Sua denúncia foi cancelada. Nenhum dado foi enviado.")
    else:
        await context.bot.send_message(chat_id=user_id, text="⚠️ Você não possui nenhuma denúncia em andamento.")

async def estatisticas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMINS:
        await context.bot.send_message(chat_id=user_id, text="🚫 Você não tem permissão para visualizar estatísticas.")
        return
    contagem = {nome: 0 for nome in CATEGORIAS.values()}
    for d in denuncias:
        cat = d.get("categoria")
        if cat in contagem:
            contagem[cat] += 1
    texto = "📊 Estatísticas de denúncias:\n"
    for nome, qtd in contagem.items():
        texto += f"• {nome}: {qtd}\n"
    await context.bot.send_message(chat_id=user_id, text=texto)

async def menu_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMINS:
        await context.bot.send_message(chat_id=user_id, text="🚫 Menu exclusivo para administradores.")
        return

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Abrir denúncia", callback_data="menu_abrir")],
        [InlineKeyboardButton("📂 Ver denúncias recentes", callback_data="menu_recentes")],
        [InlineKeyboardButton("📊 Ver estatísticas", callback_data="ver_estatisticas")],
        [InlineKeyboardButton("✅ Lista de desbloqueados", callback_data="ver_desbloqueados")]
    ])
    await context.bot.send_message(chat_id=user_id, text="👮 Painel administrativo:", reply_markup=keyboard)

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    data = query.data

    if data == "menu_abrir":
        await abrir_denuncia(update, context)
    elif data == "menu_enviar":
        await enviar_denuncia(update, context)
    elif data == "menu_cancelar":
        await cancelar_denuncia(update, context)
    elif data == "menu_continuar":
        await context.bot.send_message(chat_id=user_id, text="✏️ Continue enviando mensagens com evidências.")
    elif data in CATEGORIAS:
        denuncias_em_andamento[user_id] = {
            "categoria": CATEGORIAS[data],
            "mensagens": []
        }
        tempo_inatividade[user_id] = datetime.datetime.now()
        await query.edit_message_text(f"✅ Categoria selecionada: {CATEGORIAS[data]}\nAgora envie as mensagens com evidências.")
        asyncio.create_task(monitorar_inatividade(user_id, context))
    elif data.startswith("bloquear_") and user_id in ADMINS:
        alvo_id = int(data.split("_")[1])
        if alvo_id not in bloqueados:
            bloqueados.append(alvo_id)
            salvar_bloqueados()
            await query.edit_message_text("🚫 Usuário bloqueado com sucesso.")
        else:
            await query.edit_message_text("⚠️ Usuário já está bloqueado.")
    elif data.startswith("interagir_") and user_id in ADMINS:
        alvo_id = int(data.split("_")[1])
        mensagem = (
            "📣 Recebemos a sua denúncia, a tratativa será aplicada conforme grau de severidade. "
            "Você está recebendo esta mensagem caso os administradores precisem entrar em contato. Obrigado!"
        )
        await context.bot.send_message(chat_id=alvo_id, text=mensagem)
        await query.edit_message_text("✅ Confirmação de recebimento enviada ao denunciante.")
    elif data.startswith("responder_") and user_id in ADMINS:
        alvo_id = int(data.split("_")[1])
        context.user_data["resposta_alvo"] = alvo_id
        await context.bot.send_message(chat_id=user_id, text="✏️ Digite a mensagem que deseja enviar ao denunciante.")
    elif data == "ver_estatisticas" and user_id in ADMINS:
        await estatisticas(update, context)
    elif data == "menu_recentes" and user_id in ADMINS:
        ultimas = list(enumerate(denuncias))[-10:]
        if not ultimas:
            await context.bot.send_message(chat_id=user_id, text="📭 Nenhuma denúncia registrada.")
            return

        for i, dados in reversed(ultimas):
            resumo = dados.get("mensagens", ["(sem conteúdo)"])[0]
            autor_id = dados.get("user_id", "desconhecido")
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🗑️ Deletar denúncia", callback_data=f"deletar_{i}")],
                [InlineKeyboardButton("💬 Interagir com denunciante", callback_data=f"interagir_{autor_id}")]
            ])
            await context.bot.send_message(
                chat_id=user_id,
                text=f"📝 Denúncia #{i}\n👤 Autor: {autor_id}\n📄 Conteúdo: {str(resumo)[:100]}...",
                reply_markup=keyboard
            )
    elif data.startswith("deletar_") and user_id in ADMINS:
        denuncia_id = int(data.split("_")[1])
        if 0 <= denuncia_id < len(denuncias):
            denuncias.pop(denuncia_id)
            salvar_denuncias()
            await query.edit_message_text("🗑️ Denúncia deletada com sucesso.")
        else:
            await query.edit_message_text("⚠️ Denúncia não encontrada.")

# 🚀 Inicialização do bot
app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("menu", menu_admin))
app.add_handler(CommandHandler("abrirdenuncia", abrir_denuncia))
app.add_handler(CommandHandler("enviar_denuncia", enviar_denuncia))
app.add_handler(CommandHandler("cancelardenuncia", cancelar_denuncia))
app.add_handler(CommandHandler("estatisticas", estatisticas))
app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO | filters.VIDEO, receber_mensagem))
app.add_handler(CallbackQueryHandler(callback_handler))
app.add_handler(MessageHandler(~filters.ChatType.PRIVATE, lambda update, context: None))

app.run_polling() 
