import requests
import pandas as pd
import time
import os
import json
from datetime import datetime

SLUG = "highest-temperature-in-paris-on-june-30-2026"

FICHIER = "poly_live.csv"

def fetch_poly():
    url = f"https://gamma-api.polymarket.com/events/slug/{SLUG}"
    r = requests.get(url, timeout=10)
    if r.status_code != 200:
        print(f"Erreur {r.status_code} -> {r.text}")
        return None
    return r.json()

event = fetch_poly()

rows = []

for market in event["markets"]:
    token_yes = json.loads(market["clobTokenIds"])[0]

    book = requests.get(
        "https://clob.polymarket.com/book",
        params={"token_id": token_yes},
        timeout=10
    ).json()

    best_bid = book["bids"][-1] if book["bids"] else {"price": None, "size": None}
    best_ask = book["asks"][-1] if book["asks"] else {"price": None, "size": None}

    rows.append({
        "option": market["groupItemTitle"],
        "bestBid": best_bid["price"],
        "bidVolume": best_bid["size"],
        "bestAsk": best_ask["price"],
        "askVolume": best_ask["size"],
    })

data = pd.DataFrame(rows)

if not data.empty:
    data["_collecte_le"] = datetime.now().isoformat()
    data.to_csv(FICHIER, mode="a", header=not os.path.exists(FICHIER), index=False)
    print("Donnée enregistrée")
