"""Histórico longo (desde INICIO) para Binance e Bybit, além dos 30 dias da API da Binance.

- Binance: OI de 5 em 5 min dos arquivos diários públicos (data.binance.vision, "metrics"),
  reduzido a uma foto por hora cheia, e candles 1h da API.
- Bybit: a própria API tem OI horário desde 2021.
- OKX fica de fora: só ~60 dias de OI.

Rodar uma vez (e de novo para estender); depois o store.py mantém os CSVs em dia.
Formato e convenção iguais ao store.py: candle T com o OI do FIM da hora (T+1h).
"""
import csv
import io
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

import requests

from exchanges import BINANCE, SYMBOL, H, bybit, get, merge
from store import DATA, load

INICIO = date(2022, 1, 1)
ARQUIVO = "https://data.binance.vision/data/futures/um/daily/metrics/{s}/{s}-metrics-{d}.zip"
TOL = 10 * 60_000  # usa a foto de OI até 10 min ANTES da hora cheia, nunca depois
CACHE = DATA / "binance_oi_1h.csv"


def ms(d):
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp() * 1000)


def oi_dia(d):
    """Fotos de OI (ms, btc) de um dia do arquivo; [] se o dia ainda não foi publicado."""
    r = requests.get(ARQUIVO.format(s=SYMBOL, d=d.isoformat()), timeout=30)
    if r.status_code == 404:
        return []
    r.raise_for_status()
    z = zipfile.ZipFile(io.BytesIO(r.content))
    rows = csv.DictReader(io.StringIO(z.read(z.namelist()[0]).decode()))
    out = []
    for x in rows:
        t = datetime.strptime(x["create_time"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        oi = float(x["sum_open_interest"] or 0)
        if oi > 0:  # o arquivo tem horas com OI zerado (ex.: 07–08/03/2022): tratar como falta
            out.append((int(t.timestamp() * 1000), oi))
    return out


def por_hora(pontos):
    """Para cada hora cheia B, a última foto em [B − TOL, B]."""
    best = {}
    for t, oi in pontos:
        b = -(-t // H) * H  # arredonda para cima
        if b - t <= TOL and (b not in best or t > best[b][0]):
            best[b] = (t, oi)
    return {b: oi for b, (_, oi) in best.items()}


def binance_oi():
    cache = {}
    if CACHE.exists():
        with CACHE.open() as f:
            cache = {int(r["ts"]): float(r["oi_btc"]) for r in csv.DictReader(f)
                     if float(r["oi_btc"]) > 0}
    ini = INICIO if not cache else \
        datetime.fromtimestamp(max(cache) / 1000, timezone.utc).date() - timedelta(days=1)
    dias = [ini + timedelta(days=k) for k in range((date.today() - ini).days + 1)]
    print(f"Binance: baixando {len(dias)} dias de OI do arquivo público...", flush=True)
    with ThreadPoolExecutor(8) as ex:
        pontos = [p for dia in ex.map(oi_dia, dias) for p in dia]
    cache.update(por_hora(pontos))
    with CACHE.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ts", "oi_btc"])
        w.writerows(sorted(cache.items()))
    return cache


def binance_klines():
    out, start, end = [], ms(INICIO), int(time.time() * 1000)
    while start < end:
        k = get(f"{BINANCE}/fapi/v1/klines", symbol=SYMBOL, interval="1h",
                limit=1500, startTime=start)
        if not k:
            break
        out += k
        start = int(k[-1][0]) + H
    return out


def save(name, rows):
    """Une com o CSV atual (que tem a ponta recente via API) sem duplicar timestamps."""
    atual = {r[0]: r for r in load(name) if r[4] > 0}
    novos = {r[0]: r for r in rows if r[4] > 0}
    comum = [t for t in atual if t in novos]
    if comum:
        diff = max(abs(atual[t][4] / novos[t][4] - 1) for t in comum)
        print(f"  {name}: {len(comum)} horas em comum com a API, maior diferença de OI {diff:.3%}")
    novos.update(atual)  # na sobreposição, fica o valor da API
    rows = sorted(novos.values())
    with (DATA / f"{name.lower()}.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ts", "high", "low", "close", "oi_btc"])
        w.writerows(rows)
    gaps = sum(1 for a, b in zip(rows, rows[1:]) if b[0] - a[0] != H)
    fmt = lambda t: datetime.fromtimestamp(t / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M")
    print(f"  {name}: {len(rows)} horas, {fmt(rows[0][0])} a {fmt(rows[-1][0])} UTC, {gaps} buracos")


def main():
    DATA.mkdir(exist_ok=True)
    save("Binance", merge(binance_klines(), binance_oi(), H))
    hours = (int(time.time() * 1000) - ms(INICIO)) // H + 1
    print(f"Bybit: {hours} horas pela API...", flush=True)
    save("Bybit", bybit(hours))


if __name__ == "__main__":
    main()
