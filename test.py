from scraper import DB, Downloader
from canvas import extract_sample_list
path = [
    ('downloads/9253/Hacking to the Gate_sample.mp3', 'downloads/9253/Hacking to the Gate_sample.mp4'),
    ('downloads/1575/COLORS_sample.mp3', 'downloads/1575/COLORS_sample.mp4'),
    ('downloads/32937/TOMORROW_sample.mp3', 'downloads/32937/TOMORROW_sample.mp4')
]

gen = extract_sample_list(path, disc_persistant=False)
for _ in gen:
    print(_)
#print(choices_info)
#print(paths)

