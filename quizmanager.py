import asyncio, threading

class Leaderboard:
    def __init__(self):
        self._leaderboard = dict()
    def add(self, user):
        if user.id not in self._leaderboard:
            self._leaderboard[user.id] = {'user_obj': user, 'turn': False, 'overall': 0} # turn se il giocatore ha trovato la risposta nel turno, overall punti totali
    def discard(self, user):
        self._leaderboard.pop(user.id, None)
    def get_members(self):
        return list(self._leaderboard.keys())
    def get_turn(self, user):
        return self._leaderboard[user.id]['turn']
    def get_overall(self, user):
        return self._leaderboard[user.id]['overall']
    def __contains__(self, user): # abilita: if i in members 
        return user.id in self._leaderboard
    def __iter__(self): # abilita: for i in members 
        return (data['user_obj'] for data in self._leaderboard.values())
    def __len__(self):
        return len(self._leaderboard)

def _get_user_tag(user):
    return f"@{user.username}" if user.username else f"{user.first_name}[{user.id}]"

def check_answer(answer_id, current_song):
    if current_song:
        if int(answer_id) == current_song['anime_id']:
            return True
    else:
        return False

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

        #dentro quiz possono trovarsi:
        #ASKING ovvero stato iniziale in attesa
        #PREPARING ovvero random_pick con download
        async with lock:
            if not chat_id in self.active_chats:
                self.active_chats[chat_id] = {
                    'members': Leaderboard(),
                    'quiz': 'ASKING',
                    'current_song': None,
                    'sample_queue': None,
                    'advancing' : False,
                    'quiz_msg_id': None,
                    'stop_event' : threading.Event(),
                    'config': {
                        'diff_range': [0, 100],
                        'n_songs': None,
                        'only_OP': True
                    },
                }
                return True
            return False

    async def try_advance(self, chat_id):
        lock = self.get_lock(chat_id)
        async with lock:
            if self.active_chats[chat_id].get('advancing', False):
                return False
            self.active_chats[chat_id]['advancing'] = True
            return True

    async def done_advancing(self, chat_id):
        lock = self.get_lock(chat_id)
        async with lock:
            if chat_id in self.active_chats:
                self.active_chats[chat_id]['advancing'] = False

    async def try_quiz(self, chat_id):
        lock = self.get_lock(chat_id)
        async with lock:
            if self.active_chats[chat_id]["quiz"] == "ASKING":
                self.active_chats[chat_id]["quiz"] = "PREPARING"
                return True
            return False

    async def spinloading(self, query):
        frames = ["", ".", "..", "..."]
        i = 0
        try:
            while True:
                await query.edit_message_text(text=f"Sto preparando le canzoni{frames[i % len(frames)]}")
                i += 1
                await asyncio.sleep(3)
        except asyncio.CancelledError:
            pass 

    async def add_member(self, chat_id, user):
        lock = self.get_lock(chat_id)
        async with lock:

            if self.active_chats[chat_id]["quiz"] == "started":
                return "started"

            #if not any(member.id == user.id for member in self.active_chats[chat_id]['members']):
            if not self.get_user_chat(user):
                self.active_chats[chat_id]['members'].add(user)
                return True
            return False
        
    async def remove_member(self, chat_id, user):
        lock = self.get_lock(chat_id)
        async with lock:
            for member in self.active_chats[chat_id]['members']:
                if member.id == user.id:
                    self.active_chats[chat_id]['members'].discard(member)

    async def remove_chat(self, chat_id):
        lock = self.get_lock(chat_id)
        async with lock:
            if chat_id in self.active_chats:
                self.active_chats.pop(chat_id)

    def get_members(self, chat_id):
        return self.active_chats[chat_id]['members']

    def get_members_tags(self, chat_id):
        return [_get_user_tag(user) for user in self.get_members(chat_id)]
    
    def get_user_chat(self, user):
        for chat, chat_data in self.active_chats.items():
            if any(member.id == user.id for member in chat_data['members']):
                return chat                 
        return None # se non sta in nessuna chat
    
    async def set_current_song(self, chat_id, song):
        lock = self.get_lock(chat_id)
        async with lock:
            self.active_chats[chat_id]['current_song'] = song

    async def get_current_song(self, chat_id):
        lock = self.get_lock(chat_id)
        async with lock:
            return self.active_chats[chat_id]['current_song']

    async def set_sample_queue(self, chat_id, queue):
        lock = self.get_lock(chat_id)
        async with lock:
            if self.active_chats[chat_id]["sample_queue"] is None:
                self.active_chats[chat_id]["sample_queue"] = queue
                return True
        return False

    async def get_sample_queue(self, chat_id):
        lock = self.get_lock(chat_id)
        async with lock:
            return self.active_chats[chat_id]['sample_queue']

    #FUNZIONE GET DELLA CODA PER CONSUMARE IL PROSSIMO ITEM
    async def get_next_sample(self, queue):
        res = await asyncio.to_thread(queue.get)
        if isinstance(res, Exception):
            raise res
        return res

    async def get_quiz_msg(self, chat_id):
        lock = self.get_lock(chat_id)
        async with lock:
            return self.active_chats[chat_id]["quiz_msg_id"] 

    async def set_quiz_msg(self, chat_id, msg_id):
        lock = self.get_lock(chat_id)
        async with lock:
            if self.active_chats[chat_id]["quiz_msg_id"] is None:
                self.active_chats[chat_id]["quiz_msg_id"] = msg_id
                return True
            return False

    async def get_stop_event(self, chat_id):
        lock = self.get_lock(chat_id)
        async with lock:
            if chat_id in self.active_chats:
                return self.active_chats[chat_id]['stop_event']
            return None

    #Scrive la prossima canzone estratta nella coda direttamente nella struttura della sessione.
    #Ritorna True se la prossima canzone esiste, false se la coda è finita.
    async def next_song(self, chat_id):
        #Viene estratta la coda relativa alla propria sessione e viene estratta la canzone dalla coda.
        queue = await self.get_sample_queue(chat_id)
        song = await self.get_next_sample(queue)
        if song:
            await self.set_current_song(chat_id, song)
            return True
        return False
