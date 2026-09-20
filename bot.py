# pyright: reportMissingImports=false
import logging, json, random
from os import listdir
from telegram import Update, InlineQueryResultArticle, InputTextMessageContent, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, InlineQueryHandler, MessageHandler, ConversationHandler, CallbackQueryHandler,  filters
from uuid import uuid4
from scraper import Downloader, DB
import asyncio
import threading
from song_handler import generate_quiz

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

class Song:
    def __init__(self):
        self.id = None
        self.mp3_file = None
        self.animeENName = None
        self.AwaitingAnswer = False
    def set_song(self, mp3_file):
        self.mp3_file = mp3_file
        self.id = int(mp3_file.split(' ')[0])
        self.AwaitingAnswer = True
    def got_answer(self):
        self.__init__()

current_song = Song()

class QuizManager:
    def __init__(self):
        self.active_chats = dict()
        self.active_chats_lock = {}

    def get_lock(self, chat_id):
        if chat_id not in self.active_chats_lock:
            self.active_chats_lock[chat_id] = asyncio.Lock()
        return self.active_chats_lock[chat_id]

    async def add_chat(self, chat_id):
        lock = self.get_lock(chat_id)

        async with lock:
            if not chat_id in self.active_chats:
                self.active_chats[chat_id] = {'members' : set(),
                                  'quiz': ''}
                return True
            return False

    async def add_member(self, chat_id, user_tag):
        lock = self.get_lock(chat_id)
        async with lock:
            if not user_tag in self.active_chats[chat_id]['members']:
                self.active_chats[chat_id]['members'].add(user_tag)
                return True
            return False
        
    async def remove_member(self, chat_id, user_tag):
        lock = self.get_lock(chat_id)
        async with lock:
            self.active_chats[chat_id]['members'].discard(user_tag)

    async def remove_chat(self, chat_id):
        lock = self.get_lock(chat_id)
        async with lock:
            if chat_id in self.active_chats:
                self.active_chats.pop(chat_id)

    def get_members(self, chat_id):
        return self.active_chats[chat_id]['members']


quiz_manager = QuizManager()

async def quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):

    added = await quiz_manager.add_chat(update.effective_chat.id)

    if not added:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="Quiz ancora in corso.\nDigita /end_quiz per annullarlo")
        return
    keyboard = [
        [InlineKeyboardButton("Join", callback_data="join_quiz")],
        [InlineKeyboardButton("Inizia", callback_data="start_quiz")],
        [InlineKeyboardButton("Annulla", callback_data="end_quiz")],
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await context.bot.send_message(chat_id=update.effective_chat.id, text="Eccoci al quizzettone pazzo, pronti?", reply_markup=reply_markup)

    #choices, sampler = generate_quiz('easy', 3)
    #await context.bot.send_audio(chat_id=update.effective_chat.id, audio=open(f'downloaded/{mp3}', 'rb'))

async def join_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    keyboard = [
            [InlineKeyboardButton("Join", callback_data="join_quiz")],
            [InlineKeyboardButton("Inizia", callback_data="start_quiz")],
            [InlineKeyboardButton("Annulla", callback_data="end_quiz")],
        ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    user = update.effective_user
    chat_id = update.effective_chat.id
    user_tag = f"@{user.username}" if user.username else user.first_name+'['+str(user.id)+']'


    added = await quiz_manager.add_member(chat_id, user_tag)

    if added:
        formatted_members_list = '\n'.join(quiz_manager.get_members(chat_id))
        text = "Eccoci al quizzettone pazzo, pronti?\n\nPartecipanti:\n"+formatted_members_list
        await query.answer()
        await query.edit_message_text(text=text, reply_markup=reply_markup)
    else:
        await context.bot.answerCallbackQuery(callback_query_id=query.id, text="Sei già dentro caro", show_alert=True)

async def start_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(text="E mo si inizia")

async def end_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.delete_message()
    elif update.message:
        await update.message.reply_text("Quiz Annullato!")
    await quiz_manager.remove_chat(update.effective_chat.id)

async def catch_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if current_song.AwaitingAnswer:
        answer = update.message.text
        if answer.lower() == current_song.animeENName.lower() or answer.lower() == current_song.animeJPName.lower():
            await context.bot.send_message(chat_id=update.effective_chat.id, text="Risposta corretta!")
            current_song.got_answer()
        else:
            await context.bot.send_message(chat_id=update.effective_chat.id, text="Risposta sbagliata!")
    else:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="Non c'è nessuna domanda in corso. Digita /quiz per iniziare un nuovo quiz.")

db = DB("db.jsonl")

class BOT:
    def __init__(self):
        self.inline_searchers = {}
        self.inline_lock = threading.Lock()

    def register_new_search(self, user_id):
        new_event = threading.Event()

        with self.inline_lock:
            vecchio_evento = self.inline_searchers.get(user_id)
            if vecchio_evento:
                vecchio_evento.set()  # segnala al thread precedente di fermarsi

            self.inline_searchers[user_id] = new_event

        return new_event

    def end_remove(self, user_id, event_lock : threading.Event):
        with self.inline_lock:
            last_active = self.inline_searchers.get(user_id) is event_lock
            if last_active:
                del self.inline_searchers[user_id]
            return last_active

    async def inline_search(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.inline_query.query
        if not query:
            return

        user_id = update.effective_user.id
        lock_event = self.register_new_search(user_id)

        try:                    
            found = await asyncio.to_thread(db.search_by_name_async, lock_event, query)
        finally:
            still_valid = self.end_remove(user_id, lock_event)
        
        if not still_valid or found is None:
            return

        results = []
        
        for entry in found:
            results.append(
                InlineQueryResultArticle(
                    id=str(entry["mal_id"]),
                    title=entry["nameEN"],
                    description=entry["nameJP"],
                    thumbnail_url=entry["coverImg"]["large"],
                    input_message_content=InputTextMessageContent(
                        message_text=f"Hai scelto: {entry['nameEN']}"
                    )
                )
            )

        await context.bot.answer_inline_query(update.inline_query.id, results)

bot = BOT()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(chat_id=update.effective_chat.id, text="Ciao caro, digita /quiz per iniziare")

if __name__ == '__main__':
    application = ApplicationBuilder().token('8423678261:AAGnHWrMf0I3FAYouWPb9P3iDx88uH8tEzE').write_timeout(30).concurrent_updates(True).build()
    
    start_handler = CommandHandler('start', start)
    application.add_handler(start_handler)

    inline_search_handler = InlineQueryHandler(bot.inline_search)
    application.add_handler(inline_search_handler)

    quiz_handler = CommandHandler("quiz", quiz)
    application.add_handler(quiz_handler)

    end_quiz_handler = CommandHandler("end_quiz", end_quiz)
    application.add_handler(end_quiz_handler)

    callback_handlers= [CallbackQueryHandler(join_quiz, pattern="^" + 'join_quiz' + "$"),
                        CallbackQueryHandler(start_quiz, pattern="^" + 'start_quiz' + "$"),
                        CallbackQueryHandler(end_quiz, pattern="^" + 'end_quiz' + "$")]

    for handler in callback_handlers: application.add_handler(handler)

    application.run_polling(allowed_updates=Update.ALL_TYPES)


