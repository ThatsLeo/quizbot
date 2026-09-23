import logging
from telegram import Update, InlineQueryResultArticle, InputTextMessageContent, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaVideo, InputMediaAudio
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters, CommandHandler, InlineQueryHandler, ChosenInlineResultHandler,  CallbackQueryHandler
from scraper import Downloader, DB
from canvas import extract_sample_list
from queue import Queue
from quizmanager import asyncio, threading, QuizManager, check_answer

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)

class BOT:
    def __init__(self, db: DB, downloader : Downloader, qmanager : QuizManager):

        self.db_obj = db
        self.downloader = downloader
        self.quiz_manager = qmanager

        self.inline_searchers = {}
        self.inline_lock = threading.Lock()

        #non so se mi serve
        self.queue_lock = threading.Lock()

        with open('no_img.png', 'rb') as song_img:
            self.song_img = song_img.read()

        #INLINE FUNCTIONS#
    #SOLO inline_search DEVE ESSERE CHIAMATA#
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
        user = update.effective_user
        chat_id = self.quiz_manager.get_user_chat(user) # chat in cui sta giocando

        if chat_id:
            lock_event = self.register_new_search(user.id)

            current_song = await self.quiz_manager.get_current_song(chat_id)
            if not current_song: # canzone non ancora caricata
                await context.bot.answer_inline_query(update.inline_query.id, [InlineQueryResultArticle(
                                                    id='song_loading',
                                                    title='Aspetta, sto caricando la canzone',
                                                    input_message_content=InputTextMessageContent(
                                                        message_text="Mi piace un sacco il cazzo"
                                                    ))],
                                                    cache_time=0,
                                                    is_personal=True)
                return

            try:                    
                found = await asyncio.to_thread(self.db_obj.search_by_name_async, lock_event, query)
            finally:
                still_valid = self.end_remove(user.id, lock_event)
            
            if not still_valid or not found:
                return

            results = []
            
            for entry in found:
                right_answer = check_answer(entry['mal_id'], current_song)
                txt = "Risposta corretta!" if right_answer else f"\"{entry['nameEN']}\" non era giusto!"
                results.append(
                    InlineQueryResultArticle(
                        id=f'answer_{entry["mal_id"]}',
                        title=entry["nameEN"],
                        description=entry["nameJP"],
                        thumbnail_url=entry["coverImg"]["large"],
                        input_message_content=InputTextMessageContent(
                            message_text=txt
                        )
                        
                    )
                )

            await context.bot.answer_inline_query(update.inline_query.id, results, cache_time=0, is_personal=True)
        else:
            await context.bot.answer_inline_query(update.inline_query.id, [InlineQueryResultArticle(
                                    id='user_not_playing',
                                    title='Non stai giocando a nessuna partita',
                                    input_message_content=InputTextMessageContent(
                                        message_text="Sono un coglione ahah"
                                    ))],
                                    cache_time=0,
                                    is_personal=True)

    #FUNZIONE HELPER DA NON USARE
    def _zero2sample(self, diff, n_songs, only_OP, disc_persistant, queue : Queue, stop_event:threading.Event):
        try:
            choices = self.db_obj.random_pick(diff, n_songs, only_OP=only_OP)
            choices_info, paths, persistant = self.downloader.download_media_list(self.db_obj.get_db(),choices, disc_persistant)

            for song_info in extract_sample_list(paths, choices_info, persistant):
                if stop_event.is_set():
                    return
                queue.put(song_info)
        except Exception as e:
            queue.put(e)
        finally:
            queue.put(None)

    #FUNZIONE DI INIZIALIZZAZIONE PIPELINE CHE RITORNA LA CODA DA CUI ESTRARRE I DATI
    def start_quiz_pipeline(self, diff, n_songs, stop_event: threading.Event, only_OP=True, disc_persistant=False):
        queue = Queue(maxsize=2)
        threading.Thread(
            target=self._zero2sample,
            args=(diff, n_songs, only_OP, disc_persistant, queue, stop_event),
            daemon=True
        ).start()
        return queue

    #FUNZIONI HANDLER
    async def quiz(self, update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        added = await self.quiz_manager.add_chat(chat_id)

        if not added:
            await context.bot.send_message(chat_id=chat_id, text="Quiz ancora in corso.\nDigita /end_quiz per annullarlo")
            return

        keyboard = [
            [InlineKeyboardButton("Join", callback_data="join_quiz")],
            [InlineKeyboardButton("Inizia", callback_data="start_quiz")],
            [InlineKeyboardButton("Annulla", callback_data="end_quiz")],
        ]
        await context.bot.send_message(
            chat_id=chat_id, text="Eccoci al quizzettone pazzo, pronti?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    async def join_quiz(self, update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        chat_id = update.effective_chat.id
        user = update.effective_user

        added = await self.quiz_manager.add_member(chat_id, user)

        if added == "started":
            await query.answer(text="Il quiz è iniziato senza di te\nah ah ah\nscemo", show_alert=True)

        elif added:
            members = self.quiz_manager.get_members_tags(chat_id)
            text = "Eccoci al quizzettone pazzo, pronti?\n\nPartecipanti:\n" + '\n'.join(members)
            keyboard = [
                [InlineKeyboardButton("Join", callback_data="join_quiz")],
                [InlineKeyboardButton("Inizia", callback_data="start_quiz")],
                [InlineKeyboardButton("Annulla", callback_data="end_quiz")],
            ]
            await query.answer()
            await query.edit_message_text(text=text, reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await query.answer(text="Sei già dentro caro", show_alert=True)

    #Ritorna True quando finisce di scaricare e setta la coda nella struttura.
    async def start_quiz(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        chat_id = update.effective_chat.id
        if not self.quiz_manager.get_members(chat_id):
            await query.answer(text="Nessun membro registrato nel quizzettone pazzo", show_alert=True)
            return False

        #prende un lock e controlla lo stato del quiz, se lo stato è ASKING e quindi nessuna funzione
        #di download è stata ancora chiamata allora cambia lo stato e procede a creare la pipeline di download.
        if not await self.quiz_manager.try_quiz(chat_id):
            await query.answer(text="Hai già cliccato il pulsante brutta testa di cazzo", show_alert=True)
            return False

        #manda un messaggio di intermezzo per segnalare la preparazione.
        await query.answer()
        task_anim = asyncio.create_task(self.quiz_manager.spinloading(query))

        try: 
            #inizia il download restituendo la coda, la coda viene immediatamente scritta nello stato della sessione
            stop_event = await self.quiz_manager.get_stop_event(chat_id)
            queue = self.start_quiz_pipeline(diff=[50,100], n_songs=4, stop_event=stop_event, only_OP=True)
            await self.quiz_manager.set_sample_queue(chat_id, queue)
            isSong = await self.quiz_manager.next_song(chat_id)

        finally:
            task_anim.cancel()
            await asyncio.gather(task_anim, return_exceptions=True)

        await query.delete_message()

        if isSong:
            await self.post_song(chat_id, context)
        else:
            await context.bot.send_message(chat_id, "Errore nel caricamento.")
            await self.quiz_manager.remove_chat(chat_id)

    #Prende la canzone in struttura e la posta in chat.
    async def post_song(self, chat_id, context: ContextTypes.DEFAULT_TYPE):

        msg_id = await self.quiz_manager.get_quiz_msg(chat_id)

        song = await self.quiz_manager.get_current_song(chat_id)

        keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton( " ▶️ ", callback_data="next_one")]
                ])
        with open(f"{song['media_generic_path']}_sample.mp3", 'rb') as f:
            if msg_id is None:
                msg = await context.bot.send_audio(
                    chat_id, 
                    f,
                    title='Guess the song',
                    performer='@AnimeChatz',
                    thumbnail=self.song_img,
                    write_timeout=60, 
                    read_timeout=60, 
                    reply_markup=keyboard)
                    
                await self.quiz_manager.set_quiz_msg(chat_id, msg.message_id)

            else:
                await context.bot.edit_message_media(
                    chat_id=chat_id,
                    message_id=msg_id,
                    media=InputMediaAudio(media=f,
                                      title='Guess the song',
                                      performer='@AnimeChatz',
                                      thumbnail=self.song_img),
                    reply_markup=keyboard,
                    write_timeout=60,
                    read_timeout=60
                )

    async def next_one_handler(self, update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        chat_id = update.effective_chat.id

        await query.answer()

        if not await self.quiz_manager.try_advance(chat_id):
            return

        try:
            isSong = await self.quiz_manager.next_song(chat_id)
            if isSong:
                await self.post_song(chat_id, context)
            else:
                msg_id = await self.quiz_manager.get_quiz_msg(chat_id)
        
                await context.bot.delete_message(chat_id, msg_id)
                await context.bot.send_message(chat_id, "Quiz terminato!")
                await self.quiz_manager.remove_chat(chat_id)
        finally:
            await self.quiz_manager.done_advancing(chat_id)

    async def end_quiz(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.delete_message()
        elif update.message:
            await update.message.reply_text("Quiz Annullato!")

        chat_id = update.effective_chat.id

        try: 
            stop_event = await self.quiz_manager.get_stop_event(chat_id)
            if stop_event:
                stop_event.set()
        except:
            pass

        msg_id = await self.quiz_manager.get_quiz_msg(chat_id)
        if msg_id:
            await context.bot.delete_message(chat_id, msg_id)
        await self.quiz_manager.remove_chat(chat_id)

    async def catch_answer(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chosen_id = update.chosen_inline_result.result_id[7:] # leva la parte "answer_"
        user = update.chosen_inline_result.from_user
        chat_id = self.quiz_manager.get_user_chat(user)

        current_song = await self.quiz_manager.get_current_song(chat_id)
        right_answer = check_answer(chosen_id, current_song)

        await context.bot.send_message(chat_id=chat_id, text="Risposta sbagliata")

        if right_answer:
            pass # aggiunge i punti alla leaderboard

    async def react_to_inline_answer(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        message = update.effective_message

        if not message or not message.text:
            return
            
        if message.via_bot and message.via_bot.id == context.bot.id: #risponde solo a messaggi inline inviati con questo bot
            try:
                if "Risposta corretta" in message.text:
                    await message.set_reaction(reaction="🎉") 
                elif "non era giusto" in message.text:
                    await message.set_reaction(reaction="🤡")
            except Exception as e:
                print(f"reaction error: {e}")

    
bot = BOT(db=DB("db.jsonl"), downloader= Downloader(), qmanager= QuizManager())

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(chat_id=update.effective_chat.id, text="Ciao caro, digita /quiz per iniziare")

if __name__ == '__main__':
    application = ApplicationBuilder().token('8423678261:AAGnHWrMf0I3FAYouWPb9P3iDx88uH8tEzE').write_timeout(30).concurrent_updates(True).build()
    
    start_handler = CommandHandler('start', start)
    application.add_handler(start_handler)

    inline_search_handler = InlineQueryHandler(bot.inline_search)
    application.add_handler(inline_search_handler)

    application.add_handler(ChosenInlineResultHandler(bot.catch_answer, pattern="^" + 'join_quiz'))
    application.add_handler(MessageHandler(filters.VIA_BOT, bot.react_to_inline_answer))

    quiz_handler = CommandHandler("quiz", bot.quiz)
    application.add_handler(quiz_handler)

    end_quiz_handler = CommandHandler("end_quiz", bot.end_quiz)
    application.add_handler(end_quiz_handler)

    callback_handlers= [CallbackQueryHandler(bot.join_quiz, pattern="^" + 'join_quiz' + "$"),
                        CallbackQueryHandler(bot.start_quiz, pattern="^" + 'start_quiz' + "$"),
                        CallbackQueryHandler(bot.end_quiz, pattern="^" + 'end_quiz' + "$"),
                        CallbackQueryHandler(bot.next_one_handler, pattern="^" + "next_one" + "$")]

    for handler in callback_handlers: application.add_handler(handler)
    

    application.run_polling(allowed_updates=Update.ALL_TYPES)