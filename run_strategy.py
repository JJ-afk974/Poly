import json
import os
import pandas as pd
from datetime import datetime

FEE = 0.002
PORTFOLIO_FILE = "portfolio.json"
TRADES_FILE = "trades.csv"

# fetch_snapshot() = ta fonction actuelle

def load_portfolio():
    if os.path.exists(PORTFOLIO_FILE):
        with open(PORTFOLIO_FILE, "r") as f:
            return json.load(f)
    return {"cash": 1000.0, "positions": {}}

def save_portfolio(p):
    with open(PORTFOLIO_FILE, "w") as f:
        json.dump(p, f, indent=2)

def log_trade(side, asset, price, qty):
    row = pd.DataFrame([{
        "time": datetime.utcnow().isoformat(),
        "side": side,
        "asset": asset,
        "price": price,
        "qty": qty
    }])
    row.to_csv(
        TRADES_FILE,
        mode="a",
        header=not os.path.exists(TRADES_FILE),
        index=False
    )

portfolio = load_portfolio()
snapshot = fetch_snapshot()   # DataFrame index = option

BUY = 0.20
SELL = 0.80
QTY = 10

for asset, row in snapshot.iterrows():

    ask = row["ask"]
    bid = row["bid"]

    # achat
    if ask is not None and ask < BUY:
        cost = ask * QTY * (1 + FEE)
        if portfolio["cash"] >= cost:
            portfolio["cash"] -= cost
            portfolio["positions"][asset] = portfolio["positions"].get(asset, 0) + QTY
            log_trade("BUY", asset, ask, QTY)

    # vente
    if bid is not None and bid > SELL:
        held = portfolio["positions"].get(asset, 0)
        if held >= QTY:
            portfolio["cash"] += bid * QTY * (1 - FEE)
            portfolio["positions"][asset] -= QTY
            if portfolio["positions"][asset] == 0:
                del portfolio["positions"][asset]
            log_trade("SELL", asset, bid, QTY)

# valorisation
value = portfolio["cash"]
for asset, qty in portfolio["positions"].items():
    if asset in snapshot.index:
        value += qty * snapshot.loc[asset, "mid"]

print(f"{datetime.utcnow()}  Cash={portfolio['cash']:.2f}  Value={value:.2f}")
print("Positions:", portfolio["positions"])

save_portfolio(portfolio)
