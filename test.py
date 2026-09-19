from scraper import DB





db = DB("db.jsonl")
db_ = db.get_db()

senza_titolo = [e["entry"]["nameEN"] for e in db_ if not e["entry"].get("nameEN")]
print(len(senza_titolo))