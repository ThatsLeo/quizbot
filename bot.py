import logging
from telegram import Update, InlineQueryResultArticle, InputTextMessageContent, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters, CommandHandler, InlineQueryHandler, CallbackQueryHandler
from telegram.error import BadRequest
from scraper import Downloader, DB
from canvas import extract_sample_list
from queue import Queue
from quizmanager import asyncio, threading, QuizManager, check_answer

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logging.getLogger("apscheduler").setLevel(logging.WARNING)
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

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await context.bot.send_message(chat_id=update.effective_chat.id, text="Ciao caro, digita /quiz per iniziare")

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
                title = entry["nameEN"] or entry["nameJP"] or "Sconosciuto"
                txt = "Risposta corretta!" if right_answer else f"\"{title}\" non era giusto!"

                txt_html = f'<a href="tg://track?id={entry["mal_id"]}">&#8203;</a>{txt}' #mette l'ipertesto in "&#8203" che è un carattere non esistente
                results.append(
                    InlineQueryResultArticle(
                        id=f'answer_{entry["mal_id"]}',
                        title=title,
                        description=entry["nameJP"],
                        thumbnail_url=entry["coverImg"]["large"],
                        input_message_content=InputTextMessageContent(
                            message_text=txt_html,
                            parse_mode='HTML',
                            disable_web_page_preview=True
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
    def _zero2sample(self, config, disc_persistant, queue, stop_event):
        try:
            choices = self.db_obj.random_pick(
                config['diff'], config['n_songs'], only_OP=config['only_OP']
            )
            paths, persistant = self.downloader.download_media_list(
                self.db_obj.get_db(), choices, disc_persistant
            )

            for song_info in extract_sample_list(paths, persistant):
                if stop_event.is_set():
                    return
                queue.put(song_info)
        except Exception as e:
            if not stop_event.is_set():
                queue.put(e)
        finally:
            if not stop_event.is_set():
                queue.put(None)
                            
    #FUNZIONE DI INIZIALIZZAZIONE PIPELINE CHE RITORNA LA CODA DA CUI ESTRARRE I DATI
    def start_quiz_pipeline(self, config, stop_event: threading.Event, disc_persistant=False):
        queue = Queue(maxsize=2)
        threading.Thread(
            target=self._zero2sample,
            args=(config, disc_persistant, queue, stop_event),
            daemon=True
        ).start()
        return queue

    #FUNZIONI HANDLER
    async def quiz(self, update : Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        added = await self.quiz_manager.add_chat(chat_id)

        if not added:
            await context.bot.send_message(chat_id=chat_id, text="Quiz ancora in corso.\nDigita /end_quiz per annullarlo")
            return
        chat_power_list = [admin.user.id for admin in await update.effective_chat.get_administrators()] if update.effective_chat.type != 'PRIVATE' else []
        chat_power_list.append(update.effective_sender.id)
        await self.quiz_manager.config_set_has_power(chat_id, chat_power_list)

        keyboard = [
            [InlineKeyboardButton("Join", callback_data="join_quiz")],
            [InlineKeyboardButton("Settings", callback_data="quiz_settings"), InlineKeyboardButton("Inizia", callback_data="start_quiz")],
            [InlineKeyboardButton("Annulla", callback_data="end_quiz")],
        ]
        
        await context.bot.send_message(
            chat_id=chat_id, text="Eccoci al quizzettone pazzo, pronti?",
            reply_markup=InlineKeyboardMarkup(keyboard))

    async def join_quiz(self, update : Update, context: ContextTypes.DEFAULT_TYPE, from_settings=False):
        query = update.callback_query
        chat_id = update.effective_chat.id
        user = update.effective_user

        added = False
        if not from_settings:
            added = await self.quiz_manager.add_member(chat_id, user)
            if added == "started":
                await query.answer(text="Il quiz è iniziato senza di te\nah ah ah\nscemo", show_alert=True)

        if added or from_settings:
            keyboard = [
                [InlineKeyboardButton("Join", callback_data="join_quiz")],
                [InlineKeyboardButton("Settings", callback_data="quiz_settings"), InlineKeyboardButton("Inizia", callback_data="start_quiz")],
                [InlineKeyboardButton("Annulla", callback_data="end_quiz")],
            ]

            txt = "Eccoci al quizzettone pazzo, pronti?"
            members = self.quiz_manager.get_members_tags(chat_id)
            if members:
                txt+="\n\nPartecipanti:\n"
                txt = txt + '\n'.join(members)

            await update.callback_query.edit_message_text(text=txt,
                    reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await query.answer(text="Sei già dentro caro", show_alert=True)

    async def quiz_settings(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        chat_id = update.effective_chat.id
        if query.from_user.id in await self.quiz_manager.config_get_has_power(chat_id):
            quiz_config = await self.quiz_manager.get_config(chat_id)
            txt = f"*Impostazioni quiz*\n\nDifficoltà: {quiz_config['diff']}\nNumero canzoni [1-20]: {quiz_config['n_songs']}\nIncludi le ending: {not quiz_config['only_OP']}\nCancella i file musicali: {quiz_config['delete_audios']}\nCancella i file video: {quiz_config['delete_videos']}"
            keyboard = [
                [InlineKeyboardButton("Cambia difficoltà", callback_data="settings_change_diff")],
                [InlineKeyboardButton("N. canzoni", callback_data="settings_n_songs"), InlineKeyboardButton("-", callback_data="settings_n_songs_down"), InlineKeyboardButton("+", callback_data="settings_n_songs_up")],
                [InlineKeyboardButton("Includi Ending", callback_data="settings_toggle_endings")],
                [InlineKeyboardButton("File musica", callback_data="settings_toggle_delete_audio"), InlineKeyboardButton("File video", callback_data="settings_toggle_delete_video")],
                [InlineKeyboardButton("Indietro", callback_data="settings_back")]
            ]
            await query.edit_message_text(text=txt,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='markdown'
            )

        else:
            await query.answer(text="Non sei il proprietario del quiz o un amministratore", show_alert=True)

    async def update_quiz_settings(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        chat_id = update.effective_chat.id
        if query.from_user.id in await self.quiz_manager.config_get_has_power(chat_id):
            setting = query.data[9:]
            if setting == 'back':
                await self.join_quiz(update, context, from_settings=True)
            elif setting == 'n_songs':
                await query.answer(text="Usa il + e - testa di", show_alert=True)
            else:
                modified = await self.quiz_manager.update_config_setting(chat_id, setting)
                if modified: await self.quiz_settings(update, context)
                else: await query.answer()
        else:
            await query.answer(text="Non sei il proprietario del quiz o un amministratore", show_alert=True)

    #Ritorna True quando finisce di scaricare e setta la coda nella struttura.
    async def start_quiz(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        chat_id = update.effective_chat.id
        if not self.quiz_manager.get_members(chat_id):
            await query.answer(text="Nessun membro registrato nel quizzettone pazzo", show_alert=True)
            return False

        if query.from_user.id in await self.quiz_manager.config_get_has_power(chat_id):
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
                quiz_config = await self.quiz_manager.get_config(chat_id)
                queue = self.start_quiz_pipeline(config=quiz_config, stop_event=stop_event)
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
        else:
            await query.answer(text="Non sei il proprietario del quiz o un amministratore", show_alert=True)

    async def start_timer(self, chat_id, context: ContextTypes.DEFAULT_TYPE, next_action : str):
        assert next_action in ['post_video', 'to_next_song']
        quiz_msg_id = await self.quiz_manager.get_quiz_msg(chat_id)

        # check aggiuntivo per evitare qualsiasi problema di concorrenza:
        current_jobs = context.job_queue.get_jobs_by_name(f"timer_{chat_id}")
        for job in current_jobs: job.schedule_removal()
        
        job_data = {
            "current": 15, # da dove starta il timer
            "step": 3, # ogni quanti secondi si aggiorna (current deve essere un multiplo)
            "message_id": quiz_msg_id,
            "chat_id": chat_id,
            "next_action" : next_action
        }

        context.job_queue.run_repeating(
            callback=self.timer_callback,
            interval=job_data['step'],
            first=4, #secondi per iniziare il timer (tempo che invia circa e poco più)
            data=job_data,
            name=f"timer_{chat_id}",
            chat_id=chat_id,
            
                )

    async def timer_callback(self, context: ContextTypes.DEFAULT_TYPE):
        job = context.job
        data = job.data

        data["current"] -= data["step"]

        try:
            if data["current"] > 0:
                if data["next_action"] == "post_video": # aggiorna il timer solo se c'è una canzone in corso
                    await context.bot.edit_message_caption(
                        chat_id=data["chat_id"],
                        message_id=data["message_id"],
                        caption=data["current"])
            else:
                job.schedule_removal()
                if data["next_action"] == "post_video":
                    if not await self.quiz_manager.get_delete_audios(data["chat_id"]):
                        await context.bot.edit_message_caption(
                            chat_id=data["chat_id"],
                            message_id=data["message_id"])
                    await self.post_video(data["chat_id"], context)
                else:
                    await self.to_next_song(data["chat_id"], context)

        except BadRequest as e:
            logging.warning(f'errore con il timer: {e}')
            job.schedule_removal()
            
    async def post_video(self, chat_id, context: ContextTypes.DEFAULT_TYPE):

        msg_id = await self.quiz_manager.get_quiz_msg(chat_id)
        if msg_id is not None and await self.quiz_manager.get_delete_audios(chat_id):
            await context.bot.delete_message(chat_id, msg_id)

        song = await self.quiz_manager.get_current_song(chat_id)
        await self.quiz_manager.set_current_song_to_none(chat_id) # non accetta risposte durante il video

        with open(f"{song['media_generic_path']}_sample.mp4", 'rb') as f:

            msg = await context.bot.send_video(
                chat_id, 
                f,
                caption = f"{song['anime_name']} - {song['type'][0]}",
                write_timeout=60, 
                read_timeout=60)
                
            await self.quiz_manager.set_quiz_msg(chat_id, msg.message_id)
            await self.start_timer(chat_id, context, next_action='to_next_song')
        
    #Prende la canzone in struttura e la posta in chat.
    async def post_song(self, chat_id, context: ContextTypes.DEFAULT_TYPE):

        msg_id = await self.quiz_manager.get_quiz_msg(chat_id)
        if msg_id is not None and await self.quiz_manager.get_delete_videos(chat_id):
            await context.bot.delete_message(chat_id, msg_id)

        song = await self.quiz_manager.get_current_song(chat_id)

        with open(f"{song['media_generic_path']}_sample.mp3", 'rb') as f:

            msg = await context.bot.send_audio(
                chat_id, 
                f,
                title='Guess the song',
                performer='@AnimeChatz',
                thumbnail=self.song_img,
                write_timeout=60, 
                read_timeout=60,
                caption='15')
                
            await self.quiz_manager.set_quiz_msg(chat_id, msg.message_id)
            await self.start_timer(chat_id, context, next_action='post_video')

    async def to_next_song(self, chat_id, context: ContextTypes.DEFAULT_TYPE):
        if not await self.quiz_manager.try_advance(chat_id):
            return

        try:
            isSong = await self.quiz_manager.next_song(chat_id)
            if isSong:
                await self.post_song(chat_id, context)
            else:
                msg_id = await self.quiz_manager.get_quiz_msg(chat_id)
                if msg_id is not None and await self.quiz_manager.get_delete_videos(chat_id):
                    await context.bot.delete_message(chat_id, msg_id)
                await context.bot.send_message(chat_id, "Quiz terminato!")
                await self.post_leaderboard(chat_id, context)
                await self.quiz_manager.remove_chat(chat_id)
        finally:
            await self.quiz_manager.done_advancing(chat_id)

    async def end_quiz(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user = query.from_user if query else update.message.from_user
        chat_id = update.effective_chat.id
        if user.id in await self.quiz_manager.config_get_has_power(chat_id):
            # rimozione timer:
            current_jobs = context.job_queue.get_jobs_by_name(f"timer_{chat_id}")
            for job in current_jobs: job.schedule_removal()

            if query:
                await query.delete_message()
            elif update.message:
                await update.message.reply_text("Quiz Annullato!")

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
        else:
            if query:
                await query.answer(text="Non sei il proprietario del quiz", show_alert=True)

    async def post_leaderboard(self, chat_id, context: ContextTypes.DEFAULT_TYPE):
        leaderboard = await self.quiz_manager.get_leaderboard(chat_id)
        txt = ''
        place = 1
        for member, points in leaderboard:
            txt+=f"{place}: {member} - {points} punti\n"
            place+=1

        await context.bot.send_message(chat_id, txt)

    async def react_to_inline_answer(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        message = update.effective_message

        if not message or not message.text:
            return
            
        if message.via_bot and message.via_bot.id == context.bot.id: #risponde solo a messaggi inline inviati con questo bot
            try:
                if "Risposta corretta" in message.text:
                    entities = message.entities or []
                    for ent in entities: # prendo l'id nascosto nell'ipertesto per verificare che sia veramente la risposta giusta
                        if ent.type == 'text_link' and ent.url and ent.url.startswith("tg://track?id="):
                            guessed_anime_id = int(ent.url.split("=")[1])
                            break

                    chat_id = update.effective_chat.id
                    current_song = await self.quiz_manager.get_current_song(chat_id)
                    if current_song:
                        if guessed_anime_id == current_song['anime_id']:
                            await message.set_reaction(reaction="🎉")
                            await self.quiz_manager.add_point(message.from_user, update.effective_chat.id)
                        else:
                            await message.set_reaction(reaction="😐")
                elif "non era giusto" in message.text:
                    await message.set_reaction(reaction="🤡")
            except Exception as e:
                print(f"reaction error: {e}")

bot = BOT(db=DB("db.jsonl"), downloader= Downloader(), qmanager= QuizManager())

if __name__ == '__main__':
    application = ApplicationBuilder().token('8423678261:AAGnHWrMf0I3FAYouWPb9P3iDx88uH8tEzE').write_timeout(30).concurrent_updates(True).build()
    
    start_handler = CommandHandler('start', bot.start)
    application.add_handler(start_handler)

    inline_search_handler = InlineQueryHandler(bot.inline_search)
    application.add_handler(inline_search_handler)

    application.add_handler(MessageHandler(filters.VIA_BOT, bot.react_to_inline_answer))

    quiz_handler = CommandHandler("quiz", bot.quiz)
    application.add_handler(quiz_handler)

    end_quiz_handler = CommandHandler("end_quiz", bot.end_quiz)
    application.add_handler(end_quiz_handler)

    quiz_callback_handlers= [CallbackQueryHandler(bot.join_quiz, pattern="^" + 'join_quiz' + "$"), # per quiz
                        CallbackQueryHandler(bot.start_quiz, pattern="^" + 'start_quiz' + "$"),
                        CallbackQueryHandler(bot.quiz_settings, pattern="^" + 'quiz_settings' + "$"),
                        CallbackQueryHandler(bot.end_quiz, pattern="^" + 'end_quiz' + "$")]

    for handler in quiz_callback_handlers: application.add_handler(handler)

    application.add_handler(CallbackQueryHandler(bot.update_quiz_settings, pattern="^" + 'settings')) # per quiz_settings
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)