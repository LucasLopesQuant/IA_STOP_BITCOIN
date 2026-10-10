"""Hyperliquid: posições REAIS com preço de liquidação (a corretora é on-chain).

Não há histórico de OI na API, então ela não entra no modelo de liq_map.py. Em troca,
cada conta expõe as posições abertas com `liquidationPx`. Não existe lista de todas as
contas: usamos o leaderboard público (o mesmo do site) e consultamos as maiores por
patrimônio. A cobertura é medida contra o OI total e mostrada junto do resultado.
"""
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Lock

import requests

INFO = "https://api.hyperliquid.xyz/info"
LEADERBOARD = "https://stats-data.hyperliquid.xyz/Mainnet/leaderboard"
COIN = "BTC"
TOP = 2000      # contas consultadas, das maiores para as menores
RATE = 8        # chamadas por segundo (limite da API ~10/s para clearinghouseState)


def post(body, tries=4):
    for attempt in range(tries):
        try:
            r = requests.post(INFO, json=body, timeout=15)
            if r.status_code == 429:
                raise requests.HTTPError("429")
            r.raise_for_status()
            return r.json()
        except requests.RequestException:
            if attempt == tries - 1:
                raise
            time.sleep(2 ** attempt)


def market():
    """Preço de marcação, OI (em BTC, um lado) e funding da hora."""
    meta, ctx = post({"type": "metaAndAssetCtxs"})
    c = ctx[[a["name"] for a in meta["universe"]].index(COIN)]
    return float(c["markPx"]), float(c["openInterest"]), float(c["funding"])


def accounts(top=TOP):
    rows = requests.get(LEADERBOARD, timeout=60).json()["leaderboardRows"]
    rows.sort(key=lambda r: -float(r["accountValue"]))
    return [r["ethAddress"] for r in rows[:top]]


def positions(top=TOP, progress=True):
    """Posições de BTC das `top` maiores contas: [(lado, tamanho_btc, entrada, liq, alavancagem)].

    liq é None quando a conta tem colateral de sobra (não liquida). Sem endereço na
    saída: só interessa o agregado por nível de preço.
    """
    users, out, lock = accounts(top), [], Lock()
    gap, nxt = 1 / RATE, [time.time()]

    def fetch(user):
        with lock:  # espaça as chamadas para respeitar o limite
            wait = nxt[0] - time.time()
            nxt[0] = max(nxt[0], time.time()) + gap
        if wait > 0:
            time.sleep(wait)
        try:
            st = post({"type": "clearinghouseState", "user": user})
        except Exception:
            return None
        for ap in st.get("assetPositions", []):
            p = ap["position"]
            if p["coin"] == COIN and float(p["szi"]):
                szi, liq = float(p["szi"]), p.get("liquidationPx")
                return ("long" if szi > 0 else "short", abs(szi), float(p["entryPx"]),
                        float(liq) if liq else None, p["leverage"]["value"])
        return None

    with ThreadPoolExecutor(6) as ex:
        for k, pos in enumerate(ex.map(fetch, users), 1):
            if pos:
                out.append(pos)
            if progress and k % 250 == 0:
                print(f"  hyperliquid: {k}/{len(users)} contas", flush=True)
    return out
