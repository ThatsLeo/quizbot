import requests
from requests.exceptions import HTTPError
import time
import json
import random
from pathlib import Path



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

#carica il db e lo restituisce come file.
#non utilizzata al momento.
def load_db(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None

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
                    "video_path": None,
                    "audio": audio_id,
                    "audio_path": None
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
                        "openings": openings,
                        "Endings": endings,

                    }
                }
                add_entry(new, path)



#scarica dal dominio secondo il codice riportato nel database.
#db_path autoesplicativo
#dest_path è da dichiarare in questo modo es: "downloads"
#choice_list è una lista di dizionari ricavata dalla funzione random_pick strutturata in questo modo:
#[{134 : 'Opening 1'}, ...] in cui la prima chiave è l'indice di riga nel DB, il valore è il target selezionato. 
#disc_persistant dichiara se aggiornare il DB con i path, la gestione dell'eliminazione si dovrà ottenere
#passando questa variabile più avanti nella pipeline.
def check_media_path(db_path, dest_path, choices_list, disc_persistant = False):

    sorted_by_index = sorted(choices_list, key=lambda entry: next(iter(entry)))
    print(sorted_by_index)

    mods = {}

    with open(db_path, "r", encoding="utf-8") as f:

        cur = 0
        key = (list(sorted_by_index[cur].keys()))[0]
        for index, line in enumerate(f):
            if (index == key):

                target = sorted_by_index[cur][key]

                complete_entry = json.loads(line)
                entry = complete_entry["entry"]

                modified = False

                if "Opening" in target:

                    OP = entry["openings"]
                    for opening in OP:
                        if target == opening:
                            if OP[opening]["video_path"] == None:
                                
                                    new_path = f"{dest_path}/{entry["mal_id"]}/{OP[opening]["song"]}.mp4"
                                    download_file(f"{DOWNLOAD_URL}/{OP[opening]["video"]}", new_path)

                                    if disc_persistant : OP[opening]["video_path"] = new_path; modified = True

                                
                            if OP[opening]["audio_path"] == None:

                                new_path = f"{dest_path}/{entry["mal_id"]}/{OP[opening]["song"]}.mp3"
                                download_file(f"{DOWNLOAD_URL}/{OP[opening]["audio"]}", new_path)

                                if disc_persistant : OP[opening]["audio_path"] = new_path; modified = True


                elif "Ending" in target:
                    ED = entry["Endings"]
                    for ending in ED:
                        if target == ending:
                            if ED[ending]["video_path"] == None:

                                new_path = f"{dest_path}/{entry["mal_id"]}/{ED[ending]["song"]}_video.mp4"
                                download_file(f"{DOWNLOAD_URL}/{ED[ending]["video"]}", new_path)

                                if disc_persistant: ED[ending]["video_path"] = new_path; modified = True
                                


                            if ED[ending]["audio_path"] == None:

                                new_path = f"{dest_path}/{entry["mal_id"]}/{ED[ending]["song"]}_audio.mp3"
                                download_file(f"{DOWNLOAD_URL}/{ED[ending]["audio"]}", new_path)

                                if disc_persistant : ED[ending]["audio_path"] = new_path; modified = True

            if disc_persistant and modified:
                mods[index] = complete_entry


                cur += 1
                if cur >= len(sorted_by_index):
                    break
                key = (list(sorted_by_index[cur].keys()))[0]

    if mods:
        with open(db_path, "r", encoding="utf-8") as f:
            righe = f.readlines()
        
        for idx, updates in mods.items():
            righe[idx] = json.dumps(updates, ensure_ascii=False) + "\n"
        
        with open(db_path, "w", encoding="utf-8") as f:
            f.writelines(righe)

    return sorted_by_index, disc_persistant


#il parametro forced forza la riscrittura del file nonostante sia già presente.
def download_file(url, percorso_destinazione, forced = False):
    if not url:
        return False
    
    output_file = Path(percorso_destinazione)

    if output_file.exists() and not forced:
        return True
    
    output_file.parent.mkdir(exist_ok=True, parents=True)
    
    try:
        response = requests.get(url, stream=True)
        response.raise_for_status()
        with open(output_file, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        return True
    except Exception as err:
        print(f"Errore scaricando {url}: {err}")
        return False
                

#diff range deve essere una lista con due valori
#n_extractions è il numero di canzoni che si vogliono estrarre
def random_pick(db_path, diff_range, n_extractions, only_OP = True):

    #converte la difficoltà nel formato del DB anisong
    help_diff = (
        100-diff_range[1],
        100-diff_range[0]
    )

    help_list = []

    with open(db_path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            entry = json.loads(line)
            entry = entry["entry"]


            OP = entry["openings"]
            for key, opening in OP.items():

                diff = opening["difficulty"]

                if diff and diff <= help_diff[1] and diff >= help_diff[0]:

                    info = { i : key }

                    help_list.append(info)

            if not only_OP:
                ED = entry["Endings"]
                for key, ending in ED.items():

                    diff = ending["difficulty"]

                    if diff and diff <= help_diff[1] and diff >= help_diff[0]:
                        info = { i : key }
                        
                        help_list.append(info)
    f.close()

    if n_extractions > len(help_list) : n_extractions = len(help_list)
    choices = random.choices(help_list, k=n_extractions)
    return choices
    


#popolate(3,10,"db.jsonl",1)
choices = random_pick("db.jsonl",[0,10], 3)
check_media_path("db.jsonl","downloads",choices)