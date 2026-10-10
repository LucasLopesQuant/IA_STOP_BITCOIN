"""Teste de equivalência: o mapa incremental tem que bater com o recálculo do zero.

Rodar: python test_liq_map.py
"""
import random
from liq_map import LEVERAGES, LiqMap, build, clusters, hit, liq_price


def build_ref(series):
    # Cópia literal do build() original (não incremental), usada como referência
    zones = []
    for prev, (_, high, low, close, oi) in zip(series, series[1:]):
        prev_oi = prev[4]
        zones = [z for z in zones if not hit(z, high, low)]
        if oi < prev_oi:
            for z in zones:
                z[1] *= oi / prev_oi
        elif oi > prev_oi:
            usd = (oi - prev_oi) * close
            for lev, w in LEVERAGES.items():
                for side in ("long", "short"):
                    zones.append([liq_price(close, lev, side), usd * w, side])
    return zones


def synthetic(n, seed):
    rnd = random.Random(seed)
    price, oi, rows = 80_000.0, 50_000.0, []
    for t in range(n):
        close = price * (1 + rnd.gauss(0, 0.006))
        high = max(price, close) * (1 + abs(rnd.gauss(0, 0.003)))
        low = min(price, close) * (1 - abs(rnd.gauss(0, 0.003)))
        oi = max(1.0, oi * (1 + rnd.gauss(0, 0.01)) if rnd.random() > 0.1 else oi)
        rows.append((t * 3_600_000, high, low, close, oi))
        price = close
    return rows


def same(a, b):
    return len(a) == len(b) and all(
        x[2] == y[2] and abs(x[0] - y[0]) < 1e-6 and abs(x[1] - y[1]) < 1e-6 * max(1, y[1])
        for x, y in zip(a, b))


def same_clusters(a, b):
    return all(a[s].keys() == b[s].keys() and
               all(abs(a[s][k] - b[s][k]) <= 1e-6 * max(1, b[s][k]) for k in b[s])
               for s in ("long", "short"))


def test_equivalence():
    for seed in range(20):
        series = synthetic(300, seed)
        m = LiqMap()
        for i, row in enumerate(series):
            m.step(row)
            ref = build_ref(series[:i + 1])
            assert same(m.zones, ref), (seed, i)
            assert same_clusters(m.clusters(), clusters(ref)), (seed, i)
        assert same(build(series), build_ref(series)), seed


def test_sides():
    # Zonas vivas de long ficam abaixo do último close; de short, acima
    series = synthetic(500, 99)
    close = series[-1][3]
    for lvl, _, side in build(series):
        assert (lvl < close) if side == "long" else (lvl > close)


if __name__ == "__main__":
    test_equivalence()
    test_sides()
    print("ok: incremental == recálculo do zero (20 séries x 300 horas)")
