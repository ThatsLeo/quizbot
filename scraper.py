from bs4 import BeautifulSoup
import requests
from requests.exceptions import HTTPError
import time
import json
import asyncio
import yt_dlp


ANI_URL = "https://graphql.anilist.co"
THEME_URL = "https://anisongdb.com/api/mal_ids_request"
DOWNLOAD_URL = "https://naedist.animemusicquiz.com"


#json query verso anilist
#ritorna un {False: errore} in caso di errore
#ritorna un json in caso di successo
#Ogni numero "page" carica una lista di 20 item.
def ani_query(page, type="ANIME", format="TV", ANI_URL = ANI_URL):

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
        return {False: http_err}

    except Exception as err:
        return {False: err}

    else:
        return response.json()


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


def load_db(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None


def add_entry(entry, path):
    with open(path, "a", encoding="utf-8") as f:
        riga = json.dumps(entry, indent=4, ensure_ascii=False)
        f.write(riga + "\n")


def popolate(sleep=None):
    data = ani_query(1)
    data = data["data"]["Page"]["media"]

    for anime in data:
        
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
            add_entry(new, "db.jsonl")



#scarica dal dominio secondo il codice riportato nel database.
def download(code):
    pass


popolate()