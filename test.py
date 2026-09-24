from scraper import DB, Downloader
from canvas import extract_sample_list
import json
from scraper import cerca_anisongdb


res = cerca_anisongdb([9253])
with open("test.json", "w", encoding="utf-8") as f:
    f.write(json.dumps(res, indent=4))
#print(paths)

