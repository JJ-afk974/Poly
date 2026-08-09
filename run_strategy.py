import requests
import pandas as pd
import json
import os
from datetime import datetime, date, timedelta, timezone

# CONFIGURATION
# ============================================================

INITIAL_CASH = 1000.0

PORTFOLIO_FILE = "portfolio.json"
TRADES_FILE = "trades.csv"

LOCATIONS = {
    "paris": "paris",
    "london": "london",
}

HORIZONS = [0, 1, 2]

GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"

# SLUGS ROULANTS
# ============================================================

def build_slugs():
    """Génère automatiquement les 6 slugs : Paris  J+0 / J+1 / J+2 / Londres J+0 / J+1 / J+2"""

    today = date.today()
    slugs = {}

    for city, slug_city in LOCATIONS.items():
        for j in HORIZONS:
            target_date = today + timedelta(days=j)
            date_str = (
                f"{target_date.strftime('%B').lower()}-"
                f"{target_date.day}-"
                f"{target_date.year}"
            )
            key = f"{city}_j{j}"
            slugs[key] = (
                f"highest-temperature-in-{slug_city}-on-{date_str}"
            )
    return slugs

# API POLYMARKET
# ============================================================

def fetch_event(slug):
    """Récupère un événement Polymarket via son slug."""

    url = f"{GAMMA_API}/events/slug/{slug}"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code != 200:
            print(
                f"[WARNING] Event introuvable : {slug} "
                f"(HTTP {response.status_code})"
            )
            return None
        return response.json()
        
    except requests.RequestException as e:
        print(f"[ERROR] Impossible de récupérer {slug}: {e}")
        return None

def fetch_order_book(token_id):
    """Récupère le carnet CLOB d'un token."""

    url = f"{CLOB_API}/book"

    try:
        response = requests.get(
            url,
            params={"token_id": token_id},
            timeout=10
        )

        if response.status_code != 200:
            return None

        return response.json()

    except requests.RequestException as e:

        print(f"[ERROR] Order book : {e}")

        return None

# EXTRACTION DU PRIX
# ============================================================

def get_best_prices(book):
    """Retourne : best_bid / bid_size / best_ask / ask_size / mid
    Important :
        BUY  -> ASK
        SELL -> BID
    Le MID sert uniquement à valoriser le portefeuille.
    """

    if not book:
        return None, None, None, None, None

    bids = book.get("bids", [])
    asks = book.get("asks", [])

    # Les carnets Polymarket peuvent être renvoyés dans différents ordres : on prend explicitement le maximum du bid et le minimum de l'ask.

    if bids:
        best_bid_entry = max(bids, key=lambda x: float(x["price"]))
        best_bid = float(best_bid_entry["price"])
        bid_size = float(best_bid_entry["size"])
    else:
        best_bid = None
        bid_size = None

    if asks:
        best_ask_entry = min(asks, key=lambda x: float(x["price"]))
        best_ask = float(best_ask_entry["price"])
        ask_size = float(best_ask_entry["size"])
    else:
        best_ask = None
        ask_size = None


    if best_bid is not None and best_ask is not None:
        mid = (best_bid + best_ask) / 2
    else:
        mid = None
    return (best_bid, bid_size, best_ask, ask_size, mid)

# SNAPSHOT DES 6 MARCHÉS
# ============================================================

def fetch_snapshot():
    slugs = build_slugs()
    rows = []

    for market_key, slug in slugs.items():
        print(f"\n[MARKET] {market_key}")
        print(f"         {slug}")

        event = fetch_event(slug)

        if event is None:
            continue

        markets = event.get("markets", [])

        if not markets:
            print("  Aucun market trouvé.")
            continue

        # Métadonnées de l'événement
        event_active = event.get("active", True)
        event_closed = event.get("closed", False)
        event_resolved = event.get("resolved", False)

        # Détermination ville / horizon
        parts = market_key.split("_")

        city = parts[0]
        horizon = int(parts[1].replace("j", ""))

        for market in markets:
            try:
                token_ids = json.loads(market["clobTokenIds"])
                # Premier token = YES
                token_yes = token_ids[0]

            except Exception:
                print("  Token ID invalide.")
                continue

            book = fetch_order_book(token_yes)
            (best_bid, bid_size, best_ask, ask_size, mid) = get_best_prices(book)
            option = market.get("groupItemTitle", market.get("question", "unknown"))

            # Etat du marché individuel
            market_active = market.get("active", event_active)
            market_closed = market.get("closed", event_closed)
            market_resolved = market.get("resolved", event_resolved)

            rows.append({
                "market_key": market_key,
                "city": city,
                "horizon": horizon,
                "slug": slug,
                "event_id": event.get("id"),
                "market_id": market.get("id"),
                "token_id": token_yes,
                "option": option,
                "best_bid": best_bid,
                "bid_size": bid_size,
                "best_ask": best_ask,
                "ask_size": ask_size,
                "mid": mid,
                "active": market_active,
                "closed": market_closed,
                "resolved": market_resolved,
            })

    return pd.DataFrame(rows)

# PORTFOLIO
# ============================================================

def load_portfolio():
    if not os.path.exists(PORTFOLIO_FILE):
        portfolio = {
            "cash": INITIAL_CASH,
            "positions": {},
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        save_portfolio(portfolio)
        return portfolio


    with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_portfolio(portfolio):
    portfolio["updated_at"] = datetime.now(timezone.utc).isoformat()

    with open(PORTFOLIO_FILE, "w", encoding="utf-8") as f:
        json.dump(portfolio, f, indent=2, ensure_ascii=False)

# TRADES
# ============================================================

def log_trade(side, token_id, market_key, option, quantity, price, reason):
    row = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "side": side,
        "market_key": market_key,
        "token_id": token_id,
        "option": option,
        "quantity": quantity,
        "price": price,
        "value": quantity * price,
        "reason": reason,
    }

    df = pd.DataFrame([row])
    file_exists = os.path.exists(TRADES_FILE)
    df.to_csv(
        TRADES_FILE,
        mode="a",
        header=not file_exists,
        index=False
    )

# ACHAT
# ============================================================

def buy(portfolio, row, quantity, reason="strategy"):
    price = row["best_ask"]
    if price is None:
        print("  BUY impossible : pas d'ASK.")
        return False

    cost = quantity * price

    if cost > portfolio["cash"]:
        print(
            f"  BUY impossible : "
            f"cash={portfolio['cash']:.2f}, "
            f"cost={cost:.2f}"
        )
        return False

    token_id = row["token_id"]

    if token_id not in portfolio["positions"]:
        portfolio["positions"][token_id] = {
            "token_id": token_id,
            "market_key": row["market_key"],
            "slug": row["slug"],
            "city": row["city"],
            "horizon": int(row["horizon"]),
            "option": row["option"],
            "quantity": 0.0,
            "total_cost": 0.0,
        }

    position = portfolio["positions"][token_id]
    position["quantity"] += quantity
    position["total_cost"] += cost
    portfolio["cash"] -= cost

    log_trade("BUY", token_id, row["market_key"], row["option"], quantity, price, reason)

    print(
        f"  BUY  {quantity:.2f} "
        f"{row['option']} @ ASK {price:.4f}"
    )
    return True

# VENTE
# ============================================================

def sell(portfolio, row, quantity, reason="strategy"):
    price = row["best_bid"]

    if price is None:
        print("  SELL impossible : pas de BID.")
        return False

    token_id = row["token_id"]

    if token_id not in portfolio["positions"]:
        return False

    position = portfolio["positions"][token_id]
    quantity = min(quantity, position["quantity"])


    if quantity <= 0:
        return False

    revenue = quantity * price
    position["quantity"] -= quantity
    portfolio["cash"] += revenue

    # Réduction proportionnelle du coût
    if position["quantity"] <= 1e-12:
        del portfolio["positions"][token_id]

    else:
        ratio = (position["quantity"] / (position["quantity"] + quantity))
        position["total_cost"] *= ratio

    log_trade("SELL", token_id, row["market_key"], row["option"], quantity, price, reason)

    print(
        f"  SELL {quantity:.2f} "
        f"{row['option']} @ BID {price:.4f}"
    )

    return True

# RESOLUTION DES MARCHÉS
# ============================================================

def resolve_positions(portfolio, snapshot):
    if snapshot.empty:
        return

    rows_by_token = {
        row["token_id"]: row
        for _, row in snapshot.iterrows()
    }

    tokens_to_remove = []

    for token_id, position in portfolio["positions"].items():
        row = rows_by_token.get(token_id)

        if row is None:
            continue

        if not row["resolved"]:
            continue

        quantity = position["quantity"]

        # Détermination du résultat
        winning = False
        outcome = str(row["option"]).lower()


        # Polymarket peut fournir plusieurs champs
        # pour le résultat. On tente d'abord outcomePrices.

        market_id = row["market_id"]
        market = None

        # Dans cette version, on utilise les données présentes dans le snapshot. Si le token est résolu mais qu'on ne connaît pas explicitement le résultat, on évite de solder arbitrairement la position.

        if "outcome_price" in row.index:
            try:
                final_price = float(row["outcome_price"])
                if final_price in (0.0, 1.0):
                    winning = final_price == 1.0

            except Exception:
                pass

        # Si aucune information de résolution explicite n'est disponible, on ne touche pas à la position.
        
        if "outcome_price" not in row.index:
            continue

        payout = quantity if winning else 0.0
        portfolio["cash"] += payout

        log_trade(
            "RESOLUTION",
            token_id,
            position["market_key"],
            position["option"],
            quantity,
            1.0 if winning else 0.0,
            "market_resolution"
        )


        print(
            f"  RESOLUTION "
            f"{position['option']} -> "
            f"{'WIN' if winning else 'LOSS'} "
            f"payout={payout:.2f}"
        )

        tokens_to_remove.append(token_id)

    for token_id in tokens_to_remove:
        del portfolio["positions"][token_id]

# VALORISATION
# ============================================================

def calculate_portfolio_value(portfolio, snapshot):
    cash = portfolio["cash"]
    position_value_mid = 0.0
    liquidation_value = 0.0
    prices = {}
    if not snapshot.empty:
        for _, row in snapshot.iterrows():
            prices[row["token_id"]] = {
                "mid": row["mid"],
                "bid": row["best_bid"]
            }

    for token_id, position in portfolio["positions"].items():
        quantity = position["quantity"]
        price_data = prices.get(token_id)
        if price_data is None:
            continue
        mid = price_data["mid"]
        bid = price_data["bid"]
        if mid is not None:
            position_value_mid += quantity * mid
        if bid is not None:
            liquidation_value += quantity * bid
    nav = cash + liquidation_value
    return {
        "cash": cash,
        "position_value_mid": position_value_mid,
        "liquidation_value": liquidation_value,
        "nav": nav
    }


# STRATEGIE
# ============================================================

def strategy(portfolio, snapshot):
    """
    Acheter si ASK <= 0.10
    Vendre si BID >= 0.70
    Chaque nouvelle position utilise 1.1 USDC maximum.
    """

    if snapshot.empty:
        return

    MAX_POSITION_USD = 1.1
    BUY_THRESHOLD = 0.10
    SELL_THRESHOLD = 0.70

    for _, row in snapshot.iterrows():

        # Marché fermé
        if row["closed"] or not row["active"]:
            continue

        ask = row["best_ask"]
        bid = row["best_bid"]

        # BUY
        if ask is not None:
            token_id = row["token_id"]
            existing_quantity = 0.0
            if token_id in portfolio["positions"]:
                existing_quantity = (portfolio["positions"][token_id]["quantity"])

            current_position_value = (existing_quantity * ask)

            if (ask <= BUY_THRESHOLD and current_position_value < MAX_POSITION_USD):
                remaining_usd = (MAX_POSITION_USD - current_position_value)
                quantity = remaining_usd / ask

                # Ne pas dépenser plus que le cash disponible
                quantity = min(quantity, portfolio["cash"] / ask)
                if quantity > 0:
                    buy(portfolio, row, quantity, reason="buy_threshold")

        # SELL
        if bid is not None:
            token_id = row["token_id"]
            if token_id in portfolio["positions"]:
                quantity = (portfolio["positions"][token_id]["quantity"])
                if (bid >= SELL_THRESHOLD and quantity > 0):
                    sell(portfolio, row, quantity, reason="sell_threshold")

# GRAPH
# ============================================================
HISTORY_FILE = "portfolio_history.csv"
def save_portfolio_history(portfolio, valuation, return_pct):
    row = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "cash": valuation["cash"],
        "position_value_mid": valuation["position_value_mid"],
        "liquidation_value": valuation["liquidation_value"],
        "nav": valuation["nav"],
        "return_pct": return_pct
    }

    df = pd.DataFrame([row])
    file_exists = os.path.exists(HISTORY_FILE)
    df.to_csv(HISTORY_FILE, mode="a", header=not file_exists, index=False)

# MAIN
# ============================================================

def main():

    print("=" * 60)
    print("POLYMARKET LIVE PAPER TRADER")
    print("=" * 60)
    print("Execution :", datetime.now(timezone.utc).isoformat())

    # 1. Charger portefeuille
    # --------------------------------------------------------
    portfolio = load_portfolio()
    print(
        f"\nCash disponible : "
        f"{portfolio['cash']:.2f}"
    )

    print(
        f"Positions : "
        f"{len(portfolio['positions'])}"
    )


    # 2. Récupérer les 6 marchés
    # --------------------------------------------------------
    print("\nRécupération des marchés...")
    snapshot = fetch_snapshot()
    if snapshot.empty:
        print("\nAucun marché récupéré.")
        save_portfolio(portfolio)
        return

    print(f"\n{len(snapshot)} issues récupérées.")

    
    # 3. Résoudre les anciennes positions
    # --------------------------------------------------------
    print("\nVérification des résolutions...")
    resolve_positions(portfolio, snapshot)


    # 4. Exécuter la stratégie
    # --------------------------------------------------------
    print("\nExécution de la stratégie...")
    strategy(portfolio, snapshot)


    # 5. Valorisation
    # --------------------------------------------------------
    valuation = calculate_portfolio_value(portfolio, snapshot)
    nav = valuation["nav"]
    initial_cash = INITIAL_CASH
    return_pct = ((nav / initial_cash) - 1) * 100
    
    print("\n" + "=" * 60)
    print(
        f"Cash       : "
        f"{portfolio['cash']:.2f}"
    )

    print(
        f"Positions  : "
        f"{len(portfolio['positions'])}"
    )

    print(
        f"Valeur     : "
        f"{portfolio_value:.2f}"
    )

    print("=" * 60)


    # 6. Sauvegarder
    # --------------------------------------------------------
    save_portfolio(portfolio)
    save_portfolio_history(portfolio, valuation, return_pct)
    print("\nPortefeuille sauvegardé.")

if __name__ == "__main__":
    main()
