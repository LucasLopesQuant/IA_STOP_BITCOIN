"""Histórico próprio: acrescenta as horas fechadas de cada corretora em data/{corretora}.csv.

Rodar de hora em hora (Agendador de Tarefas / cron). Na primeira vez baixa o máximo
que cada API entrega (Binance ~30 dias, OKX ~60, Bybit o que for pedido em BACKFILL_DAYS).
Linha: ts,high,low,close,oi_btc — ts = abertura do candle; oi_btc = OI no FIM da hora.
"""
import csv
import time
from pathlib import Path

from exchanges import EXCHANGES, H

DATA = Path(__file__).parent / "data"
BACKFILL_DAYS = 90
OVERLAP = 3  # horas re-buscadas a cada rodada, cobre atraso de publicação do OI


def load(name):
    path = DATA / f"{name.lower()}.csv"
    if not path.exists():
        return []
    with path.open() as f:
        return [(int(r["ts"]), float(r["high"]), float(r["low"]), float(r["close"]),
                 float(r["oi_btc"])) for r in csv.DictReader(f)]


def update(name, fn):
    path = DATA / f"{name.lower()}.csv"
    rows = load(name)
    last = rows[-1][0] if rows else 0
    hours = BACKFILL_DAYS * 24 if not rows else \
        int((time.time() * 1000 - last) // H) + OVERLAP
    new = [r for r in fn(hours) if r[0] > last]  # nunca reescreve nem duplica
    with path.open("a", newline="") as f:
        w = csv.writer(f)
        if not rows:
            w.writerow(["ts", "high", "low", "close", "oi_btc"])
        w.writerows(new)
    return len(new), len(rows) + len(new)


def main():
    DATA.mkdir(exist_ok=True)
    for name, fn in EXCHANGES.items():
        try:
            added, total = update(name, fn)
            print(f"{name}: +{added} horas (total {total})")
        except Exception as e:
            print(f"[aviso] {name} falhou: {e}")


if __name__ == "__main__":
    main()
