import os
import json
import asyncio
import datetime
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes
)

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
GROUP_ID = int(os.getenv("GROUP_ID"))

ADMINS = [7477496964, 6439529867]

DENUNCIAS_ARQUIVO = "denuncias.json"
BLOQUEADOS_ARQUIVO = "bloqueados.json"

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

async def verificar_membro(bot, grupo_id, user_id):
    try:
        membro = await bot.get_chat_member(grupo_id, user_id)
        return membro.status in ["member", "administrator", "creator"]
    except:
        return False

async def iniciar_temporizador_envio(user_id, context):
    try:
        if temporizadores_envio.get(user_id):
            temporizadores_envio[user_id].cancel()
    except Exception:
        pass

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
      temporizadores_inatividade = {}

async def monitorar_inatividade(user_id, context):
    # Cancela monitoramento anterior, se existir
    if user_id in temporizadores_inatividade:
        temporizadores_inatividade[user_id].cancel()

    async def tarefa():
        await asyncio.sleep(180)
        ultimo = tempo_inatividade.get(user_id)
        if not ultimo or user_id not in denuncias_em_andamento:
            return

        # Envia aviso de inatividade
        await context.bot.send_message(
            chat_id=user_id,
            text="👀 Ei, ainda está aí? Se não continuar sua denúncia, ela será encerrada por inatividade."
        )

        await asyncio.sleep(120)
        ultimo = tempo_inatividade.get(user_id)
        if not ultimo or user_id not in denuncias_em_andamento:
            return

        if (datetime.datetime.now() - ultimo).total_seconds() >= 300:
            dados = denuncias_em_andamento.pop(user_id, None)
            tempo_inatividade.pop(user_id, None)

            await context.bot.send_message(
                chat_id=user_id,
                text="🚫 Denúncia encerrada automaticamente por inatividade. Se desejar, você pode iniciar novamente."
            )

            categoria = dados.get("categoria", "Não especificada") if dados else "Não especificada"
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            is_member = await verificar_membro(context.bot, GROUP_ID, user_id)
            membro_status = "Membro ✅" if is_member else "Membro ❌"

            for admin_id in ADMINS:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=(
                        f"⚠️ Denúncia encerrada por inatividade:\n"
                        f"👤 Usuário: {user_id}\n"
                        f"{membro_status}\n"
                        f"📂 Categoria: {categoria}\n"
                        f"🕒 Horário: {timestamp}"
                    )
                )

    temporizadores_inatividade[user_id] = asyncio.create_task(tarefa())

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

    is_member = await verificar_membro(context.bot, GROUP_ID, user_id)
    membro_status = "Membro ✅" if is_member else "Membro ❌"

    for admin_id in ADMINS:
        await context.bot.send_message(
            chat_id=admin_id,
            text=(
                f"👤 Novo usuário iniciou uma denúncia:\n"
                f"ID: {user_id}\n"
                f"Username: @{username}\n"
                f"{membro_status}"
            )
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
        await monitorar_inatividade(user_id, context)
        return

    is_member = await verificar_membro(context.bot, GROUP_ID, user_id)
    membro_status = "Membro ✅" if is_member else "Membro ❌"

    if user_id in ADMINS:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 Abrir denúncia", callback_data="menu_abrir")],
            [InlineKeyboardButton("📂 Denúncias recentes", callback_data="menu_recentes")],
            [InlineKeyboardButton("📊 Painel de moderação", callback_data="ver_estatisticas")],
            [InlineKeyboardButton("🚫 Usuários bloqueados", callback_data="ver_bloqueados")]
        ])
        await context.bot.send_message(chat_id=user_id, text="👋 Painel administrativo:", reply_markup=keyboard)
    else:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 Abrir denúncia", callback_data="menu_abrir")]
        ])
        await context.bot.send_message(
            chat_id=user_id,
            text=f"👋 Olá! Bem-vindo ao sistema de denúncias.\n{membro_status}\nEscolha uma opção abaixo:",
            reply_markup=keyboard
        )

async def enviar_denuncia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or "Não disponível"

    if user_id not in denuncias_em_andamento:
        await context.bot.send_message(chat_id=user_id, text="⚠️ Você não possui nenhuma denúncia em andamento.")
        return

    dados = denuncias_em_andamento.pop(user_id)
    tempo_inatividade.pop(user_id, None)
    dados["user_id"] = user_id
    dados["timestamp"] = datetime.datetime.now().isoformat()
    denuncias.append(dados)
    salvar_denuncias()

    is_member = await verificar_membro(context.bot, GROUP_ID, user_id)
    membro_status = "Membro ✅" if is_member else "Membro ❌"

    for admin_id in ADMINS:
        cabecalho = (
            f"📥 Nova denúncia recebida:\n"
            f"👤 Usuário: {user_id} (@{username})\n"
            f"{membro_status}\n"
            f"📂 Categoria: {dados['categoria']}\n"
            f"🕒 Horário: {dados['timestamp']}\n"
            f"📎 Total de mensagens: {len(dados['mensagens'])}"
        )
        await context.bot.send_message(chat_id=admin_id, text=cabecalho)

        for item in dados["mensagens"]:
            if isinstance(item, str):
                await context.bot.send_message(chat_id=admin_id, text=f"📝 {item}")
            elif isinstance(item, dict):
                tipo = item.get("tipo")
                file_id = item.get("file_id")
                if tipo == "photo":
                    await context.bot.send_photo(chat_id=admin_id, photo=file_id)
                elif tipo == "video":
                    await context.bot.send_video(chat_id=admin_id, video=file_id)

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📩 Notificar denunciante", callback_data=f"notificar_{user_id}")]
        ])
        await context.bot.send_message(chat_id=admin_id, text="Ações disponíveis:", reply_markup=keyboard)

    await context.bot.send_message(chat_id=user_id, text="✅ Denúncia enviada com sucesso. Obrigado por colaborar!")
    context.bot_data[f"denuncia_enviada_{user_id}"] = True

async def tratar_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    if query.data in CATEGORIAS:
        denuncias_em_andamento[user_id] = {
            "categoria": CATEGORIAS[query.data],
            "mensagens": []
        }
        tempo_inatividade[user_id] = datetime.datetime.now()
        await query.edit_message_text(f"✅ Categoria selecionada: {CATEGORIAS[query.data]}\nAgora envie sua denúncia com detalhes.")
        await monitorar_inatividade(user_id, context)

    elif query.data == "menu_enviar":
        await enviar_denuncia(update, context)

    elif query.data == "menu_cancelar":
        denuncias_em_andamento.pop(user_id, None)
        tempo_inatividade.pop(user_id, None)
        await query.edit_message_text("🚫 Denúncia cancelada.")

    elif query.data == "menu_continuar":
        await query.edit_message_text("✏️ Continue enviando mensagens para complementar sua denúncia.")

    elif query.data == "menu_abrir":
        await abrir_denuncia(update, context)

    elif query.data == "menu_recentes":
        if denuncias:
            for d in denuncias[-5:]:
                resumo = (
                    f"📅 {d['timestamp']}\n"
                    f"👤 Usuário: {d['user_id']}\n"
                    f"📂 Categoria: {d['categoria']}\n"
                    f"📎 Total de mensagens: {len(d['mensagens'])}"
                )
                await query.message.reply_text(resumo)
        else:
            await query.message.reply_text("⚠️ Nenhuma denúncia registrada.")

    elif query.data == "ver_estatisticas":
        total = len(denuncias)
        bloqueados_count = len(bloqueados)
        await query.message.reply_text(
            f"📊 Estatísticas:\n"
            f"📁 Total de denúncias: {total}\n"
            f"🚫 Usuários bloqueados: {bloqueados_count}"
        )

    elif query.data == "ver_bloqueados":
        if bloqueados:
            lista = "\n".join(str(uid) for uid in bloqueados)
            await query.message.reply_text(f"🚫 Usuários bloqueados:\n{lista}")
        else:
            await query.message.reply_text("✅ Nenhum usuário bloqueado.")

    elif query.data.startswith("notificar_"):
        alvo_id = int(query.data.split("_")[1])
        await context.bot.send_message(
            chat_id=alvo_id,
            text="📢 Sua denúncia foi recebida com sucesso. Entraremos em contato caso precisemos de mais detalhes."
        )
        await query.message.reply_text("✅ Denunciante notificado com sucesso.")

# ✅ Inicialização do bot
def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", abrir_denuncia))
    app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO | filters.VIDEO, receber_mensagem))
    app.add_handler(CallbackQueryHandler(tratar_callback))
    app.run_polling()

if __name__ == "__main__":
    main()
