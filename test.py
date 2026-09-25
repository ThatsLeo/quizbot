from scraper import DB, Downloader
from canvas import extract_sample_list
import json
from scraper import cerca_anisongdb


db_obj = DB("db.jsonl")
db = db_obj.get_db()

song_set = dict()
for complete in db:
    entry = complete["entry"]

    OP = entry["Openings"]
    ED = entry["Endings"]
    for type in (OP, ED):
        for key, op in type.items():
            to_find = (op["song"], op["song_artist"])
            if (to_find) not in song_set:
                song_set[to_find] = []
            song_set[to_find].append((entry["mal_id"], key))

#print(id_set)
for entry in song_set:
    if len(song_set[entry]) > 1:
        print(f"{entry}: {len(song_set[entry])}")

#print(paths)



"""
{
    (song_name,artist) : [(mal_id,type),],

}
"""