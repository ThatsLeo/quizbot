from scraper import DB, Downloader
from canvas import extract_sample_list
import time

difficulty = {'easy' : [70,100],
              'medium' : [40,70],
              'hard' : [10,30],
              'impossible' : [0,10]}

db_obj = DB("db.jsonl")
db = db_obj.get_db()

dl = Downloader()

def generate_quiz(diff : str, number_of_songs: int, only_openings : bool = True):
    a = time.process_time()
    choices = db_obj.random_pick(difficulty[diff], number_of_songs, only_OP=only_openings)
    choices_info, paths, persistant = dl.download_media_list(db,choices)
    gen = extract_sample_list(paths)
    print(choices_info)
    print(paths)
    return choices_info, gen