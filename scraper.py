import requests
from requests.exceptions import HTTPError
import time
import json


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
#LA DEVO FINIRE
def check_media_path(code):
    with open("db.jsonl", "r", encoding="utf-8") as f:

        for index in range():
            riga = f[index].strip()
            if riga:
                entry = json.loads(riga)
                print(entry)




def scarica_file(url, percorso_destinazione):
    if not url:
        return False
    try:
        response = requests.get(url, stream=True)
        response.raise_for_status()
        with open(percorso_destinazione, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        return True
    except Exception as err:
        print(f"Errore scaricando {url}: {err}")
        return False
                


#popolate(1, 2, "db.jsonl", 2)
check_media_path(1)