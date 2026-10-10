"""Coleta de preço e open interest horários em várias corretoras (APIs públicas)."""
import time
import requests

SYMBOL = "BTCUSDT"
BINANCE = "https://fapi.binance.com"
TIMEOUT = 10
HOURS = 100  # janela padrão do painel
H = 3_600_000  # 1 hora em ms


def get(url, **params):
    """GET simples com 3 tentativas: devolve o JSON ou levanta o último erro."""
    for attempt in range(3):
        try:
            r = requests.get(url, params=params, timeout=TIMEOUT)
            r.raise_for_status()
            return r.json()
        except requests.RequestException:
            if attempt == 2:
                raise
            time.sleep(1 + attempt)


def windows(hours, size):
    """Divide as últimas `hours` horas em janelas [início, fim] de `size` horas (ms)."""
    end = int(time.time() * 1000) // H * H
    start = end - hours * H
    while start < end:
        yield start, min(start + (size - 1) * H, end)
        start += size * H


def merge(candles, oi_map, oi_shift):
    """Junta cada candle FECHADO (ts, high, low, close) com o OI em BTC do FIM da hora.

    oi_shift: quanto somar ao ts do candle para achar o OI do fim da hora.
    Binance e Bybit marcam o OI no instante do ts (= início do candle), então o fim
    do candle T é o OI de T+1h. A OKX já marca no fim da hora (shift 0).
    Tudo isso é conhecido no fechamento de T, então não há look-ahead.
    """
    now = time.time() * 1000
    rows = {}
    for t, _, h, l, c, *_ in candles:
        t = int(t)
        if t + H <= now and t + oi_shift in oi_map:  # descarta o candle em aberto
            rows[t] = (t, float(h), float(l), float(c), oi_map[t + oi_shift])
    return sorted(rows.values())


# Cada adaptador devolve [(ts, high, low, close, oi_em_btc), ...] em ordem crescente.
# OI em BTC (não em USD) para que a variação reflita posições, não o preço.

def binance(hours=HOURS):
    hours = min(hours, 30 * 24 - 2)  # a Binance só guarda 30 dias de OI
    oi, k = {}, []
    for s, e in windows(hours + 1, 500):
        for x in get(f"{BINANCE}/futures/data/openInterestHist", symbol=SYMBOL,
                     period="1h", limit=500, startTime=s, endTime=e + H):
            oi[int(x["timestamp"])] = float(x["sumOpenInterest"])
        k += get(f"{BINANCE}/fapi/v1/klines", symbol=SYMBOL, interval="1h",
                 limit=500, startTime=s, endTime=e)
    return merge(k, oi, H)


def bybit_get(url, **params):
    # A Bybit responde 200 com retCode != 0 quando limita a taxa; espera e tenta de novo
    for attempt in range(5):
        d = get(url, **params)
        if d.get("retCode") == 0:
            return d["result"]["list"]
        time.sleep(2 ** attempt)
    raise RuntimeError(f"Bybit: {d.get('retCode')} {d.get('retMsg')}")


def bybit(hours=HOURS):
    base = "https://api.bybit.com/v5/market"
    p = dict(category="linear", symbol=SYMBOL)
    oi, k = {}, []
    for s, e in windows(hours + 1, 200):
        for x in bybit_get(f"{base}/open-interest", intervalTime="1h", limit=200,
                           startTime=s, endTime=e + H, **p):
            oi[int(x["timestamp"])] = float(x["openInterest"])
        k += bybit_get(f"{base}/kline", interval="60", limit=200, start=s, end=e, **p)
        if hours > 1000:
            time.sleep(0.1)  # paginação longa: não estourar o limite
    return merge(k, oi, H)


def okx(hours=HOURS):
    base, inst = "https://www.okx.com/api/v5", "BTC-USDT-SWAP"
    oi, k = {}, []
    for s, e in windows(hours, 100):
        # x = [ts, oi, oiCcy, oiUsd]; o ts marca o fim da hora; begin/end são exclusivos
        for x in get(f"{base}/rubik/stat/contracts/open-interest-history", instId=inst,
                     period="1H", limit=100, begin=s - 1, end=e + 1)["data"]:
            oi[int(x[0])] = float(x[2])
        # history-candles: `after` = mais antigos que, `before` = mais novos que
        k += get(f"{base}/market/history-candles", instId=inst, bar="1H",
                 limit=100, after=e + 1, before=s - 1)["data"]
        time.sleep(0.3)  # rubik tem limite de 5 chamadas a cada 2s
    return merge(k, oi, 0)


EXCHANGES = {"Binance": binance, "Bybit": bybit, "OKX": okx}


def fetch_all(hours=HOURS):
    """Busca todas; se uma falhar (bloqueio, mudança de API), segue com as outras."""
    data = {}
    for name, fn in EXCHANGES.items():
        try:
            data[name] = fn(hours)
        except Exception as e:
            print(f"[aviso] {name} falhou: {e}")
    return data
