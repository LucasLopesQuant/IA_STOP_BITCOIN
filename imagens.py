"""Dataset de imagens candle a candle com as zonas de liquidação (mesmo método do Robo Fibo).

Para cada candle de 1h FECHADO (instante t = fechamento) desenha os últimos 120 candles até t:
- mapa de calor das zonas de liquidação do modelo (Binance + Bybit) atrás dos candles.
  Cada coluna mostra o mapa como estava no fechamento DAQUELE candle, então a imagem
  inteira só usa dados até t;
- candles (verde = fechou >= abertura) e volume negociado embaixo, como no Robo Fibo;
- à direita, o perfil do mapa em t (volume de liquidação por nível de preço).

Escala: máxima/mínima da janela com folga de PAD do preço para cima e para baixo, para
mostrar as zonas logo além do range. A cor de cada imagem é normalizada pelo percentil 99
das células do próprio mapa (como a escala de preço, que também é da própria janela).

Saída: dataset/1h/BTCUSDT_AAAAMMDD_HHMM.png (hora de t em UTC) e dataset/rotulos.csv.
Uso: python imagens.py [--passo N] [--ultimos N]
"""
import csv
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image

from exchanges import BINANCE, SYMBOL, H, get
from historico import INICIO, ms
from liq_map import LiqMap
from store import DATA, load

SAIDA = Path(__file__).parent / "dataset"
CANDLES = DATA / "candles_1h.csv"
FONTES = ("Binance", "Bybit")  # as duas com histórico desde 2022 (OKX só tem ~60 dias)
JANELA = 120
WARMUP = 30 * 24  # horas de mapa acumulado antes da primeira imagem
PAD = 0.03        # folga da escala: 3% do preço acima e abaixo do range da janela
GAMA = 1.0       # contraste do calor (1 = linear: só as zonas grandes ficam claras)
HORIZONTES = (24, 36)
SPLITS = [("treino", datetime(2024, 1, 1, tzinfo=timezone.utc)),
          ("validacao", datetime(2025, 1, 1, tzinfo=timezone.utc)),
          ("teste", None)]

# densidade do mapa por hora: faixas de 0,05% em log-preço, até ±20% do fechamento
W = 0.0005
SPAN = 0.2
L = int(2 * SPAN / W)

# geometria (igual ao Robo Fibo + perfil à direita)
PX_CANDLE = 4
ALT_PRECO, ALT_SEP, ALT_VOL = 200, 8, 48
LARG_GRAF, LARG_PERFIL = JANELA * PX_CANDLE, 48
LARG, ALT = LARG_GRAF + LARG_PERFIL, ALT_PRECO + ALT_SEP + ALT_VOL
VERDE, VERMELHO, CINZA = (38, 166, 154), (239, 83, 80), (110, 110, 110)
# preto → índigo → violeta → amarelo (sem verde/vermelho, para não confundir com os candles)
PARADAS = [(0.0, (0, 0, 0)), (0.3, (45, 20, 105)), (0.65, (140, 60, 190)), (1.0, (255, 220, 70))]


def lut():
    x = np.linspace(0, 1, 256)
    pos = [p for p, _ in PARADAS]
    return np.stack([np.interp(x, pos, [c[k] for _, c in PARADAS]) for k in range(3)], 1).astype(np.uint8)


LUT = lut()


# ---------- Dados ----------

def candles():
    """Candles 1h da Binance (OHLCV) desde INICIO, com cache incremental em data/candles_1h.csv."""
    rows = []
    if CANDLES.exists():
        with CANDLES.open() as f:
            rows = [tuple(float(x) if k else int(x) for k, x in enumerate(r))
                    for r in list(csv.reader(f))[1:]]
    start = rows[-1][0] + H if rows else ms(INICIO)
    now = time.time() * 1000
    while start + H <= now:
        k = get(f"{BINANCE}/fapi/v1/klines", symbol=SYMBOL, interval="1h", limit=1500, startTime=start)
        new = [(int(x[0]), *map(float, x[1:6])) for x in k if int(x[0]) + H <= now]  # só fechados
        if not new:
            break
        rows += new
        start = new[-1][0] + H
    with CANDLES.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ts", "open", "high", "low", "close", "volume"])
        w.writerows(rows)
    return np.array(rows)


def preparar(c, series):
    """Densidade do mapa no fechamento de cada candle: (off, dens).

    off[h] = índice log da primeira faixa; dens[h] = USD por faixa (L faixas).
    Só usa as linhas das corretoras com ts <= ts do candle h.
    """
    ts = c[:, 0].astype(np.int64)
    maps = {n: LiqMap() for n in series}
    pos = dict.fromkeys(series, 0)
    off = np.zeros(len(c), np.int64)
    dens = np.zeros((len(c), L), np.float32)
    for h, t in enumerate(ts):
        lvl, usd = [], []
        for n, s in series.items():
            while pos[n] < len(s) and s[pos[n]][0] <= t:
                maps[n].step(s[pos[n]])
                pos[n] += 1
            lvl.append(maps[n].lvl)
            usd.append(maps[n].usd)
        lvl, usd = np.concatenate(lvl), np.concatenate(usd)
        off[h] = int(np.floor((np.log(c[h, 4]) - SPAN) / W))
        b = np.floor(np.log(lvl) / W).astype(np.int64) - off[h]
        ok = (b >= 0) & (b < L)
        dens[h] = np.bincount(b[ok], weights=usd[ok], minlength=L)
    return off, dens


# ---------- Desenho ----------

def desenhar(c, off, dens, i):
    a = slice(i - JANELA + 1, i + 1)
    o, h, l, cl, v = (c[a, k] for k in range(1, 6))
    pad = PAD * cl[-1]
    pmax, pmin = h.max() + pad, l.min() - pad
    esc = (ALT_PRECO - 1) / (pmax - pmin)

    def linha(p):
        return int(round((pmax - p) * esc))

    # Calor: cada faixa de cada coluna vai para a linha de pixel do seu preço
    precos = np.exp((off[a][:, None] + np.arange(L)[None, :] + 0.5) * W)
    rows = np.round((pmax - precos) * esc).astype(np.int64)
    cols = np.broadcast_to(np.arange(JANELA)[:, None], rows.shape)
    ok = (rows >= 0) & (rows < ALT_PRECO)
    calor = np.bincount((rows * JANELA + cols)[ok], weights=dens[a][ok],
                        minlength=ALT_PRECO * JANELA).reshape(ALT_PRECO, JANELA)
    nz = calor[calor > 0]
    vmax = np.percentile(nz, 99) if nz.size else 1.0
    nivel = (np.clip(calor / vmax, 0, 1) ** GAMA * 255).astype(np.uint8)

    img = np.zeros((ALT, LARG, 3), np.uint8)
    img[:ALT_PRECO, :LARG_GRAF] = np.repeat(LUT[nivel], PX_CANDLE, axis=1)

    vol_max = v.max() if v.max() > 0 else 1.0
    for k in range(JANELA):
        x = k * PX_CANDLE
        cor = VERDE if cl[k] >= o[k] else VERMELHO
        img[linha(h[k]):linha(l[k]) + 1, x + 1] = cor
        img[linha(max(o[k], cl[k])):linha(min(o[k], cl[k])) + 1, x:x + 3] = cor
        alt_v = int(round(v[k] / vol_max * ALT_VOL))
        if alt_v:
            img[ALT - alt_v:, x:x + 3] = tuple(int(q * 0.6) for q in cor)

    # Perfil em t: barra por linha de preço, comprimento proporcional ao volume do mapa
    perfil = calor[:, -1]
    pm = perfil.max() if perfil.max() > 0 else 1.0
    x0 = LARG_GRAF + 4
    for r in np.nonzero(perfil)[0]:
        n = int(round(perfil[r] / pm * (LARG_PERFIL - 6)))
        if n:
            img[r, x0:x0 + n] = LUT[nivel[r, -1]] if nivel[r, -1] > 40 else LUT[40]
    img[linha(cl[-1]), LARG_GRAF:LARG_GRAF + 3] = CINZA  # marca do preço em t
    return img


# ---------- Rótulos ----------

def rotulos(c, idx):
    t = c[:, 0].astype(np.int64) + H  # fechamento
    out = []
    for i in idx:
        ti = datetime.fromtimestamp(t[i] / 1000, timezone.utc)
        split = next(n for n, fim in SPLITS if fim is None or ti < fim)
        fim = dict(SPLITS)[split]
        r = dict(arquivo=nome(t[i]), ativo=SYMBOL, t=ti.isoformat(), preco=c[i, 4], split=split)
        for hz in HORIZONTES:
            j = i + hz
            r[f"y_{hz}h"] = c[j, 4] / c[i, 4] - 1 if j < len(c) else ""
            fim_hz = datetime.fromtimestamp(t[j] / 1000, timezone.utc) if j < len(c) else None
            r[f"ok_{hz}h"] = bool(fim_hz and (fim is None or fim_hz <= fim))
        out.append(r)
    return out


def nome(t_ms):
    return f"{SYMBOL}_{datetime.fromtimestamp(t_ms / 1000, timezone.utc):%Y%m%d_%H%M}.png"


def main():
    args = sys.argv[1:]
    passo = int(args[args.index("--passo") + 1]) if "--passo" in args else 1
    ultimos = int(args[args.index("--ultimos") + 1]) if "--ultimos" in args else None

    c = candles()
    series = {n: load(n) for n in FONTES}
    print(f"{len(c)} candles; preparando o mapa hora a hora...", flush=True)
    off, dens = preparar(c, series)
    primeiro = max(JANELA - 1, WARMUP)
    idx = list(range(primeiro, len(c), passo))
    if ultimos:
        idx = idx[-ultimos:]

    (SAIDA / "1h").mkdir(parents=True, exist_ok=True)
    t = c[:, 0].astype(np.int64) + H
    for n, i in enumerate(idx):
        Image.fromarray(desenhar(c, off, dens, i)).save(SAIDA / "1h" / nome(t[i]), optimize=False)
        if n % 2000 == 0:
            print(f"  {datetime.fromtimestamp(t[i] / 1000, timezone.utc):%Y-%m-%d} ({n}/{len(idx)})", flush=True)
    if not ultimos:
        rot = rotulos(c, idx)
        with (SAIDA / "rotulos.csv").open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=rot[0].keys())
            w.writeheader()
            w.writerows(rot)
        print(f"{len(rot)} imagens + dataset/rotulos.csv")
    else:
        print(f"{len(idx)} imagens")


if __name__ == "__main__":
    main()
