import requests
from requests.exceptions import HTTPError
import time
import json
import random
from pathlib import Path
from canvas import extract_sample_list
import threading



ANI_URL = "https://graphql.anilist.co"
THEME_URL = "https://anisongdb.com/api/mal_ids_request"
DOWNLOAD_URL = "https://naedist.animemusicquiz.com"


#json query verso anilist
#ritorna un {False: errore} in caso di errore
#ritorna un json in caso di successo
#Ogni numero "page" carica una lista di 20 item.
#Yield function da usare in un loop, es: for data in ani_query(...):
def ani_query(page_start=1, page_end=None, type="ANIME", format="TV", ANI_URL = ANI_URL):

    
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
        time.sleep(1)

#la funzione deve essere chiamata con una lista di id, se è solo uno allora [id]
def cerca_anisongdb(mal_ids, filters = None, url = THEME_URL):

    
    body = {
        "mal_ids": mal_ids,  # lista di interi, es. [154587] o più insieme
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
    except Exception as err:
        return None
    
    risultati = response.json()
    return risultati

#aggiunge una entry nel db.
def add_entry(entry, path):
    with open(path, "a", encoding="utf-8") as f:
        riga = json.dumps(entry, ensure_ascii=False)
        f.write(riga + "\n")

#god function che prende una pagina start e una target, scarica tutte le pagine di mezzo
#e le scrive nel db.
#Page_end è COMPRESA nelle pagine scaricate.
#Se page_end è None la funzione continua fin quando trova pagine da anilist.
#sleep attende secondi per evitare timeout dai server.
def popolate(page_start, page_end, path, sleep=None):

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
                    video_id = tema.get("HQ") or tema.get("MQ")
                    audio_id = tema.get("audio")


                    song_info = {
                    "song": song,
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


class DB:
    def __init__(self, path):
        self.db = self.load_db(path)

    #carica il db e lo restituisce come file.
    def load_db(self, path):
        with open(path, "r", encoding="utf-8") as f:
            return [json.loads(riga) for riga in f if riga.strip()]

    def _is_in_(self, a:str, b:str):
        if not a or not b:
            return False
        if a.lower() in b.lower():
            return True
        return False

    def search_by_name(self,query: str):
        query = query.lower()
        res = []

        for complete_entry in self.db:
            entry = complete_entry["entry"]

            nameEN = entry["nameEN"]
            nameJP = entry["nameJP"]

            if self._is_in_(query,nameEN) or self._is_in_(query, nameJP):
                res.append(entry) 
        return res

    #funzione pensata per le implementazioni real-time con un controllo periodico di un evento.
    #La funzione è pensata per essere eseguita in un thread parallelo, se il flag si avvera allora ferma la ricerca.
    def search_by_name_async(self, event_flag:threading.Event, query:str):
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

        if event_flag.is_set():
            return None
        return res


    # difficoltà corrisponde a quella nel db
    def random_pick(self, diff_range, n_extractions, only_OP = True):

        all_choices = dict()

        for i, complete_entry in enumerate(self.db):
            entry = complete_entry['entry']

            SONGS = entry["Openings"]
            if not only_OP: SONGS = SONGS | entry["Endings"] # faccio un merge con le ending
            for song_type, opening in SONGS.items():

                diff = opening["difficulty"]

                if diff and diff <= diff_range[1] and diff >= diff_range[0]:

                    all_choices[i] = {'type' : song_type, 'anime_name': entry['nameEN'], 'anime_id' : entry['mal_id']}

        if n_extractions > len(all_choices) : n_extractions = len(all_choices)
        choices = dict(random.choices(list(all_choices.items()), k=n_extractions))
        return choices

    def get_db(self):
        return self.db

class Downloader:

    def __init__(self, dl_url, dest_path):

        self._download_locks = {}
        self._registry_lock = threading.Lock()
        self.DOWNLOAD_URL = dl_url
        self.dest_path = dest_path

    #La funzione ora si aspetta una copia completa in RAM del DB.
    def download_media_list(self, db_load, choices_list:dict, disc_persistant = False):

        choices_list = {key:choices_list[key] for key in sorted(choices_list.keys())} # sort per index
        paths = []

        for index, complete_entry in enumerate(db_load):
            if index in choices_list:

                target = choices_list[index]['type']
                entry = complete_entry["entry"]
                
                if "Opening" in target: SONG = entry["Openings"][target]
                elif "Ending" in target: SONG = entry["Endings"][target]

                #video download sincrono                                            
                new_path = f"{self.dest_path}/{entry['mal_id']}/{SONG['song']}.mp4"
                self.download_file_sync(f"{self.DOWNLOAD_URL}/{SONG['video']}", new_path)
                paths.append(new_path)

                #audio download sincrono
                new_path = f"{self.dest_path}/{entry['mal_id']}/{SONG['song']}.mp3"
                self.download_file_sync(f"{self.DOWNLOAD_URL}/{SONG['audio']}", new_path)
                paths.append(new_path)
                choices_list[index]['media_path'] = f"{self.dest_path}/{entry['mal_id']}"


        return choices_list, paths, disc_persistant


    #il parametro forced forza la riscrittura del file nonostante sia già presente.
    #Pensata per gestire download concorrenti sullo stesso file.
    #Se due thread provano a scaricare lo stesso file, il primo che arriva prende il lock e mette in attesa
    #tutti gli altri fino al completamento.
    def download_file_sync(self, url, dest_path, forced=False):
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

    #funzione esecutiva del vero download, viene chiamata unicamente dopo tutti i controlli.
    def _esegui_download(self, url, output_file):
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


if __name__== '__main__':
    db_obj = DB("db.jsonl")
    db = db_obj.get_db()

    dl = Downloader()

    choices = db.random_pick(db,[60,100], 5)
    sorted, paths, persistant = dl.download_media_list(db,choices)
    for song in extract_sample_list(paths):
        print(song)



