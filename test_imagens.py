"""A imagem de t tem que ser a mesma com os dados cortados em t e com o histórico completo.

Rodar: python test_imagens.py   (~1 min; usa data/*.csv e data/candles_1h.csv)
"""
import numpy as np

import imagens as im
from store import load


def test_sem_futuro():
    c = im.candles()
    series = {n: load(n) for n in im.FONTES}
    off, dens = im.preparar(c, series)
    n = len(c)
    for i in (im.WARMUP + 1000, n // 2, n - 500):
        t = c[i, 0]
        c_cut = c[:i + 1]
        s_cut = {k: [r for r in s if r[0] <= t] for k, s in series.items()}
        off_cut, dens_cut = im.preparar(c_cut, s_cut)
        assert np.array_equal(im.desenhar(c, off, dens, i), im.desenhar(c_cut, off_cut, dens_cut, i)), i


def test_rotulos():
    c = im.candles()
    i = len(c) - 100
    r = im.rotulos(c, [i])[0]
    assert abs(r["y_24h"] - (c[i + 24, 4] / c[i, 4] - 1)) < 1e-12
    assert r["ok_24h"] and r["split"] == "teste"
    assert im.rotulos(c, [len(c) - 10])[0]["ok_36h"] is False  # horizonte além dos dados


if __name__ == "__main__":
    test_sem_futuro()
    test_rotulos()
    print("ok: imagens sem futuro (3 instantes) e rótulos conferidos")
