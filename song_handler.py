from scraper import DB, Downloader
from canvas import extract_sample_list

difficulty = {'easy' : [70,100],
              'medium' : [40,70],
              'hard' : [10,30],
              'impossible' : [0,10]}

db_obj = DB("db.jsonl")
db = db_obj.get_db()

dl = Downloader()

def generate_quiz(diff : str, number_of_songs: int, only_openings : bool = True):
    choices = db_obj.random_pick(difficulty[diff], number_of_songs, only_OP=only_openings)
    choices_info, paths, persistant = dl.download_media_list(db,choices)
    return choices_info

print(generate_quiz('easy', 3))
