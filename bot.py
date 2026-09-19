# pyright: reportMissingImports=false
import logging, json, random
from os import listdir
from telegram import Update, InlineQueryResultArticle, InputTextMessageContent
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, InlineQueryHandler, MessageHandler, filters
from uuid import uuid4

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

with open('db.jsonl', 'r', encoding="utf-8") as json_file:
    for i, line in enumerate(json_file):
        entry = json.loads(line)
        data = entry["entry"]

#names = [data[i]['animeENName'] for i in range(len(data))]
#mp3_files = [f for f in listdir('downloaded') if f.endswith('.mp3')]
names = 0
mp3_files = 0
class Song:
    def __init__(self):
        self.id = None
        self.mp3_file = None
        self.animeENName = None
        self.AwaitingAnswer = False
    def set_song(self, mp3_file):
        self.mp3_file = mp3_file
        self.id = int(mp3_file.split(' ')[0])
        self.animeENName = [data[i]['animeENName'] for i in range(len(data)) if data[i]['annId'] == self.id][0]
        self.AwaitingAnswer = True
    def got_answer(self):
        self.__init__()

current_song=Song()

def random_mp3_file():
    return random.choice(mp3_files)

async def quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mp3 = random_mp3_file()
    current_song.set_song(mp3)
    await context.bot.send_audio(chat_id=update.effective_chat.id, audio=open(f'downloaded/{mp3}', 'rb'))
    await context.bot.send_message(chat_id=update.effective_chat.id, text="utilizza l'inline per cercare la risposta")

async def catch_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if current_song.AwaitingAnswer:
        answer = update.message.text
        if answer.lower() == current_song.animeENName.lower():
            await context.bot.send_message(chat_id=update.effective_chat.id, text="Risposta corretta!")
            current_song.got_answer()
        else:
            await context.bot.send_message(chat_id=update.effective_chat.id, text=f"Risposta sbagliata!")
    else:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="Non c'è nessuna domanda in corso. Digita /quiz per iniziare un nuovo quiz.")



def is_in(a:str, b:str):

    if not a or not b:
        return False
    if a.lower() in b.lower():
        return True
    return False

def search_by_name(query: str):
    query = query.lower()
    res = []

    with open("db.jsonl", "r", encoding="utf-8") as f:
        for line in f:
            entry = json.loads(line)["entry"]

            nameEN = entry["nameEN"]
            nameJP = entry["nameJP"]

            if is_in(query,nameEN) or is_in(query, nameJP):
                res.append(entry) 
    return res


async def inline_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.inline_query.query
    if not query:
        return
    results = []
    for entry in search_by_name(query):
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


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(chat_id=update.effective_chat.id, text="Ciao caro, digita /quiz per iniziare")

if __name__ == '__main__':
    application = ApplicationBuilder().token('8423678261:AAGnHWrMf0I3FAYouWPb9P3iDx88uH8tEzE').write_timeout(30).build()
    
    start_handler = CommandHandler('start', start)
    application.add_handler(start_handler)

    inline_search_handler = InlineQueryHandler(inline_search)
    application.add_handler(inline_search_handler)

    quiz_handler = CommandHandler('quiz', quiz)
    application.add_handler(quiz_handler)  

    catch_answer_handler = MessageHandler(filters.TEXT, catch_answer)
    application.add_handler(catch_answer_handler)

    application.run_polling()


