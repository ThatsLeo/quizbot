import requests
from requests.exceptions import HTTPError
import time
import json
import random
from pathlib import Path
import threading
import pickle


ANI_URL = "https://graphql.anilist.co"
THEME_URL = "https://anisongdb.com/api/mal_ids_request"
DOWNLOAD_URL = "https://naedist.animemusicquiz.com"

difficulties = {'Facile' : [70,100],
              'Medio' : [40,70],
              'Difficile' : [10,30],
              'Impossibile' : [0,10],
              'Fritto misto' : [0,100]}

#Yield function da usare in un loop, es: for data in ani_query(...):
def ani_query(page_start=1, page_end=None, type="ANIME", format="TV", ANI_URL = ANI_URL):
    """ JSON query verso anilist. Ogni numero "page" carica una lista di 20 item. 
    Ritorna un {False: errore} in caso di errore, JSON in caso di successo """

    query = """
        query($page:Int = 1, $type:MediaType, $format:[MediaFormat], 
        $sort:[MediaSort]=[POPULARITY_DESC,SCORE_DESC] ) { 
            Page(page:$page, perPage:20) {
                pageInfo {
                    currentPage
                    lastPage
                    hasNextPage
            }
            media(type:$type, sort:$sort, format_in:$format) {
                id
                idMal
                title { userPreferred english }
                coverImage { extraLarge large color }
                type
                popularity
                format
                }
            }
        }
        """
    page = page_start

    while True:
        variables = {
            "page": page,
            "type": type,
            "format": [format],
            "sort": "SCORE_DESC"
            }
        
        try:
            response = requests.post(ANI_URL, json={"query":query, "variables":variables})
            response.raise_for_status()

        except HTTPError as http_err:
            yield {False: http_err}
            return

        except Exception as err:
            yield {False: err}
            return

        else:
            res = response.json()
            yield res

        info = res["data"]["Page"]["pageInfo"]

        if not info["hasNextPage"]:
            return
        
        if page_end is not None and page >= page_end:
            return

        page += 1
        time.sleep(0.5)

#La funzione deve essere chiamata con una lista di id, se è solo uno allora [id]
def cerca_anisongdb(mal_ids, filters = None, url = THEME_URL):

    
    body = {
        "mal_ids": mal_ids,  # Lista di interi, es. [154587] o più insieme
        "ignore_duplicate": False,
        "filters": filters or {
            "song_types": ["opening", "ending", "insert"],
            "broadcasts": ["normal", "dub", "rebroadcast"],
            "song_categories": ["standard", "other", "instrumental", "chanting", "character"],
            "anime_types": ["tv", "movie", "ova", "ona", "special", "other"]
        }
    }
    
    try:
        response = requests.post(url, json=body)
        response.raise_for_status()
    except Exception as e:
        return None
    
    risultati = response.json()
    return risultati


def add_entry(entry, path):
    '''Aggiunge una entry nel db.'''
    with open(path, "a", encoding="utf-8") as f:
        riga = json.dumps(entry, ensure_ascii=False)
        f.write(riga + "\n")


def popolate(page_start, page_end, path, sleep=None):
    '''Popola il DB con le informazioni contenute nelle pagine'''
    for data in ani_query(page_start, page_end):
        if False in data:
            print("Errore:", data[False])
            break

        media = data["data"]["Page"]["media"]

        for anime in media:
            
            nameJP = anime["title"]["userPreferred"]
            nameEN = anime["title"]["english"]
            idMal = anime["idMal"]
            idAnilist = anime["id"]
            cover_img = anime["coverImage"]
            print(f"{nameEN}:{idMal}")

            if sleep:
                time.sleep(sleep)

            temi = cerca_anisongdb([idMal])
            if temi == None:
                print(temi)
            else:
                openings = {}
                endings = {}
                for tema in temi:
                    diff = tema["songDifficulty"]
                    type = tema["songType"]
                    song = tema["songName"]
                    songArtist = tema["songArtist"]
                    video_id = tema.get("HQ") or tema.get("MQ")
                    audio_id = tema.get("audio")


                    song_info = {
                    "song": song,
                    "song_artist": songArtist,
                    "difficulty": diff,
                    "video": video_id,
                    "audio": audio_id
                    }

                    if "Opening" in type:
                        openings[type] = song_info
                    elif "Ending" in type:
                        endings[type] = song_info

                new = {
                    "entry": {
                        "anilist_id":idAnilist,
                        "mal_id":idMal,
                        "nameEN":nameEN,
                        "nameJP":nameJP,
                        "coverImg": cover_img,
                        "Openings": openings,
                        "Endings": endings,

                    }
                }
                add_entry(new, path)
    deduplicate_db(path)
    no_video_cleaner(path)
    write_helper(path)

def write_helper(path):
    song_set = dict()

    with open(path, "r", encoding="utf-8") as f:
        for row in f:
            row = row.strip()
            if row:
                complete = json.loads(row)
                entry = complete["entry"]

                OP = entry["Openings"]
                ED = entry["Endings"]
                for type in (OP, ED):
                    for key, op in type.items():
                        to_find = (op["song"], op["song_artist"])
                        if (to_find) not in song_set:
                            song_set[to_find] = []
                        song_set[to_find].append((entry["mal_id"], key))
    path_h = path[:-6] + "_dup.bin"
    with open(path_h, "wb") as file:
        pickle.dump(song_set, file)



def deduplicate_db(path):
    '''Rimuove i record duplicati dal DB'''
    seen = {}
    
    with open(path, "r", encoding="utf-8") as f:
        for row in f:
            row = row.strip()
            if row:
                obj = json.loads(row)
                mal_id = obj["entry"]["mal_id"]
                seen[mal_id] = obj
    
    with open(path, "w", encoding="utf-8") as f:
        for obj in seen.values():
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")

def no_video_cleaner(path):
    null_list = []
    items = []

    with open(path, "r", encoding="utf-8") as db:
        for row in db:
            row = row.strip()
            if row:
                item = json.loads(row)
                entry = item["entry"]

                for sezione in ("Openings", "Endings"):
                    chiavi_da_rimuovere = [
                        key for key, tema in entry[sezione].items()
                        if not tema["video"]
                    ]
                    for key in chiavi_da_rimuovere:
                        null_list.append(entry[sezione][key]["song"])
                        entry[sezione].pop(key)

                if entry["Openings"] or entry["Endings"]:
                    items.append(item)

    with open(path, "w", encoding="utf-8") as f:
        for obj in items:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")



def get_samplepath(dest_path):
    sample_path = Path(dest_path[:-4] + "_sample" + dest_path[-4:])
    return  sample_path

def clean_path(path : Path):
    # pulizia del nome file per evitare problemi su windows:
    win_blacklist = '<>:"/\\|?*~'
    blacklist_table = str.maketrans('', '', win_blacklist)
    nome_pulito = path.name.translate(blacklist_table)
    path = path.with_name(nome_pulito)
    return path
    

class DB:
    def __init__(self, path):
        self.db = self.load_db(path)
        self.dup = self.load_dup(path)

    
    def load_db(self, path):
        '''Carica il db e lo restituisce come file.'''
        with open(path, "r", encoding="utf-8") as f:
            return [json.loads(riga) for riga in f if riga.strip()]

    def load_dup(self, path):
        '''Carica l'oggetto python dal binario ausiliario.
        
        Struttura dell'oggetto:      
        { (song_name,artist) : [(mal_id,type),] ..., ...}


        Esempio di codice di accesso:\n
        baba = db.get_dup()\n
        for key, item in baba.items():\n
            if len(baba[key]) > 1:\n
                print(f"{key}-{item}")
        
        Questo snippet restituisce una cosa del tipo:\n
        ('Kimi no Shiranai Monogatari', 'supercell')-[(17074, 'Ending 2'), (5081, 'Ending 1')]

        '''
        path_h = path[:-6] + "_dup.bin"
        if not Path(path_h).exists():
            write_helper(path)

        with open(path_h, "rb") as file:
            return pickle.load(file)

    def _is_in_(self, a:str, b:str):
        if not a or not b:
            return False
        if a.lower() in b.lower():
            return True
        return False

    def search_by_name(self, query: str):
        '''Cerca nel DB tutti le entry il cui titolo EN o JP contengano la query passata
        Ritorna la lista di queste entry'''
        query = query.lower()
        res = []

        for complete_entry in self.db:
            entry = complete_entry["entry"]

            nameEN = entry["nameEN"]
            nameJP = entry["nameJP"]

            if self._is_in_(query, nameEN) or self._is_in_(query, nameJP):
                res.append(entry) 
        return res

    #Funzione pensata per le implementazioni real-time con un controllo periodico di un evento.
    #La funzione è pensata per essere eseguita in un thread parallelo, se il flag si avvera allora ferma la ricerca.
    def search_by_name_async(self, event_flag: threading.Event, query: str) :
        query = query.lower()
        res = []

        for complete_entry in self.db:

            if event_flag.is_set():
                return None
            
            entry = complete_entry["entry"]

            nameEN = entry["nameEN"]
            nameJP = entry["nameJP"]

            if self._is_in_(query,nameEN) or self._is_in_(query, nameJP):
                res.append(entry)
            if len(res) > 15: break #max 15 risultati

        if event_flag.is_set():
            return None
        return res


    
    def random_pick(self, diff, n_extractions, only_OP=True):
        assert diff in difficulties
        diff_range = difficulties[diff]
        
        all_choices = dict()
        pool_piatto = []  # lista di (indice_entry, song_type, song_id)

        for i, complete_entry in enumerate(self.db):
            entry = complete_entry['entry']

            SONGS = entry["Openings"]
            if not only_OP: SONGS = SONGS | entry["Endings"] # Merge con le ending
            for song_type, opening in SONGS.items():

                diff = opening["difficulty"]
                song_name = opening["song"]
                song_artist = opening["song_artist"]
                if diff and diff_range[0] <= diff <= diff_range[1]:
                    pool_piatto.append((i, song_type, song_name, song_artist))
                    if i not in all_choices:
                        all_choices[i] = {'type': [], 'anime_name': entry['nameEN'], 'anime_id': entry['mal_id']}

        random.shuffle(pool_piatto)

        song_artist_seen = set()
             
        choices = {}
        for i, song_type, song_name, song_artist in pool_piatto:
            key = (song_artist,song_name)
            if key in song_artist_seen:
                continue
            song_artist_seen.add((song_artist,song_name))

            if i not in choices:
                group = self.dup.get(key, [])
                valid_ids = [mal_id for mal_id, _ in group] or [all_choices[i]['anime_id']]

                choices[i] = {
                'type': [],
                'anime_name': all_choices[i]['anime_name'],
                'anime_id': all_choices[i]['anime_id'],
                'valid_ids': valid_ids,
            }            
            choices[i]['type'].append(song_type)

            if len(song_artist_seen) >= n_extractions:
                break

        return choices

    def get_db(self):
        return self.db

    def get_dup(self):
        return self.dup

class Downloader:

    def __init__(self):

        self._download_locks = {}
        self._registry_lock = threading.Lock()
        self.DOWNLOAD_URL = DOWNLOAD_URL
        self.dest_path = 'downloads'

    #La funzione ora si aspetta una copia completa in RAM del DB.
    def download_media_list(self, db_load, choices_list: dict, disc_persistant=False):
        choices_list = {key: choices_list[key] for key in sorted(choices_list.keys())}
        paths = []  # ora: lista di dict, uno per SINGOLA canzone

        for index, complete_entry in enumerate(db_load):
            if index in choices_list:
                entry = complete_entry["entry"]
                info = choices_list[index]

                for target in info['type']:
                    if "Opening" in target:
                        SONG = entry["Openings"][target]
                    elif "Ending" in target:
                        SONG = entry["Endings"][target]

                    media_list = []
                    for format, type_ in (("mp3", "audio"), ("mp4", "video")):
                        new_path = f"{self.dest_path}/{entry['mal_id']}/{SONG['song']}.{format}"
                        sample_path = get_samplepath(new_path)
                        if not sample_path.exists() and type_ != "null":
                            self.download_file_sync(f"{self.DOWNLOAD_URL}/{SONG[type_]}", new_path)
                        media_list.append(new_path)

                    paths.append({
                        'media': tuple(media_list),
                        'anime_name': info['anime_name'],
                        'anime_id': info['anime_id'],
                        'type': [target],
                        'valid_ids': info.get('valid_ids', [info['anime_id']]),
                        'media_generic_path': f"{self.dest_path}/{entry['mal_id']}/{SONG['song']}",
                    })

        return paths, disc_persistant

    #Il parametro forced forza la riscrittura del file nonostante sia già presente.
    def download_file_sync(self, url, dest_path, forced=False):
        """Scarica un file in modo sincrono e thread-safe: evita download concorrenti dello stesso file 
        mettendo in attesa i thread successivi fino al completamento del primo downloader."""

        output_file = Path(dest_path)
        chiave = str(output_file)

        if output_file.exists() and not forced:
            return True

        with self._registry_lock:
            if chiave in self._download_locks:
                event = self._download_locks[chiave]
                sono_io_il_downloader = False
            else:
                event = threading.Event()
                self._download_locks[chiave] = event
                sono_io_il_downloader = True

        if not sono_io_il_downloader:
            event.wait()
            return output_file.exists()

        try:
            risultato = self._esegui_download(url, output_file)
        finally:
            event.set()
            with self._registry_lock:
                del self._download_locks[chiave]

        return risultato

    def _esegui_download(self, url, output_file):
        '''Funzione esecutiva del vero download, viene chiamata unicamente dopo tutti i controlli.'''
        output_file.parent.mkdir(exist_ok=True, parents=True)
        percorso_temp = output_file.with_suffix(output_file.suffix + ".part")
        try:
            response = requests.get(url, stream=True)
            response.raise_for_status()
            with open(percorso_temp, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            percorso_temp.rename(output_file)
            return True
        except Exception as err:
            print(f"Errore scaricando {url}: {err}")
            percorso_temp.unlink(missing_ok=True)
            return False

#Continuare da pagina 66(compresa) in poi
if __name__== '__main__':

    popolate(66,70,"db.jsonl",0.3)


