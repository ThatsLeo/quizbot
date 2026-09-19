from scraper import download_media_list, random_pick, extract_sample_list

difficulty = {'easy' : [70,100],
              'medium' : [40,70],
              'hard' : [10,30],
              'impossible' : [0,10]}


def generate_quiz(diff : str, song_number):
    choices = random_pick("db.jsonl", difficulty[diff], song_number)
    choices_info, paths, persistant = download_media_list("db.jsonl","downloads",choices)

    gen = extract_sample_list(paths)
    return 'aspeeee'