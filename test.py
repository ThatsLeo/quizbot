from scraper import DB, Downloader
from canvas import extract_sample_list
import json
from scraper import cerca_anisongdb
import pickle

db_obj = DB("db.jsonl")
baba = db_obj.get_dup()


choices = db_obj.random_pick([30,60], 10, True)

print(choices)

'''
#print(id_set)
for key, item in baba.items():
    if len(baba[key]) > 1:
        print(f"{key}-{item}")

only_OP = True
if only_OP :
    s = "Kimi no Shiranai Monogatari"
    for key, items in baba.items():
        if s in key:
            for item in items:
                print(item)
'''
"""
{
    (song_name,artist) : [(mal_id,type),],

}
"""