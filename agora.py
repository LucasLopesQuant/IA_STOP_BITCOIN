"""Zonas de liquidação AGORA: modelo (Binance + Bybit + OKX) + posições reais da Hyperliquid.

Rodar: python agora.py   (atualiza data/*.csv antes; a Hyperliquid leva ~4 min)
"""
import json
import time
from collections import Counter
from datetime import datetime, timezone

import hyperliquid as hl
from exchanges import BINANCE, EXCHANGES, H, SYMBOL, get
from liq_map import build, clusters, hit
from store import DATA, load, main as update_store

STEP = 500
NEAR = 0.05  # escada detalhada: ±5% do preço


def model_zones():
    """Zonas do modelo com todo o histórico salvo, já sem as tocadas desde a última hora salva."""
    update_store()
    zones, last, desde = [], 0, []
    for name in EXCHANGES:
        s = load(name)
        if s:
            zones += build(s)
            last = max(last, s[-1][0])
            desde.append(f"{name} desde {datetime.fromtimestamp(s[0][0] / 1000, timezone.utc):%d/%m/%Y}")
    # Candles depois da última hora salva (inclui a hora em aberto): o preço já passou ali
    k = get("https://api.bybit.com/v5/market/kline", category="linear", symbol=SYMBOL,
            interval="60", start=last + H, limit=10)["result"]["list"]
    if k:
        high, low = max(float(x[2]) for x in k), min(float(x[3]) for x in k)
        zones = [z for z in zones if not hit(z, high, low)]
    return clusters(zones, STEP), desde


def hl_zones(pos):
    out = {"long": Counter(), "short": Counter()}
    for side, size, _, liq, _ in pos:
        if liq:
            out[side][round(liq / STEP) * STEP] += size * liq
    return out


def top(c, side, price, n=5):
    rows = [(usd, lvl) for lvl, usd in c[side].items()
            if (lvl > price if side == "short" else lvl < price)]
    return sorted(sorted(rows, reverse=True)[:n], key=lambda x: -x[1])


def show_top(title, c, price):
    print(f"\n{title}")
    for side, label in (("short", "Acima (shorts)"), ("long", "Abaixo (longs)")):
        print(f"  {label}")
        for usd, lvl in top(c, side, price):
            print(f"    ${lvl:>7,.0f}  ~${usd / 1e6:>6,.1f}M  ({lvl / price - 1:+.1%})")


def ladder(model, real, price):
    """[(nível, usd_modelo, usd_hyperliquid)] de +NEAR a −NEAR do preço, de cima para baixo."""
    lo, hi = price * (1 - NEAR), price * (1 + NEAR)
    val = lambda c, l: c["short" if l > price else "long"].get(l, 0)
    return [(l, val(model, l), val(real, l))
            for l in range(int(hi // STEP * STEP), int(lo // STEP * STEP), -STEP)]


def show_ladder(rows, price):
    print(f"\nEscada ±{NEAR:.0%} (faixas de ${STEP}) — modelo | Hyperliquid real")
    mmax = max([m for _, m, _ in rows] + [1])
    rmax = max([r for *_, r in rows] + [1])
    bar = lambda v, m, w: "█" * round(v / m * w)
    printed = False
    for l, m, r in rows:
        if not printed and l < price:
            print(f"  {'—' * 8} preço ${price:,.0f} {'—' * 40}")
            printed = True
        print(f"  ${l:>7,} {l / price - 1:+5.1%}  {m / 1e6:>6.0f}M {bar(m, mmax, 18):<18} |"
              f" {r / 1e6:>6.1f}M {bar(r, rmax, 18)}")


def main():
    price = float(get(f"{BINANCE}/fapi/v1/ticker/price", symbol=SYMBOL)["price"])
    model, desde = model_zones()
    mark, oi, funding = hl.market()
    print(f"\nHyperliquid: buscando posições das {hl.TOP} maiores contas...")
    pos = hl.positions()
    real = hl_zones(pos)

    print(f"\nPreço agora: ${price:,.0f} (Binance) | ${mark:,.0f} (Hyperliquid)")
    show_top(f"Modelo ({' + '.join(desde)}) — estimativa", model, price)
    show_top("Hyperliquid — posições reais com preço de liquidação", real, price)

    longs = sum(s for side, s, *_ in pos if side == "long")
    shorts = sum(s for side, s, *_ in pos if side == "short")
    no_liq = sum(size for _, size, _, liq, _ in pos if liq is None)
    lev = sorted(p[4] for p in pos)
    lev_med = lev[len(lev) // 2] if lev else None
    print(f"\n  cobertura: {len(pos)} posições de BTC; longs {longs:,.0f} BTC ({longs / oi:.0%} do OI de"
          f" {oi:,.0f} BTC), shorts {shorts:,.0f} BTC ({shorts / oi:.0%})")
    print(f"  sem preço de liquidação (colateral de sobra): {no_liq:,.0f} BTC"
          f" | alavancagem mediana {lev_med}x | funding {funding * 100:+.4f}%/h")

    rows = ladder(model, real, price)
    show_ladder(rows, price)

    # Foto salva para a página do mapa (mapa.py embute se existir)
    foto = dict(ts=int(time.time() * 1000), price=price, mark=mark, step=STEP, near=NEAR,
                desde=desde, ladder=rows,
                model={s: top(model, s, price) for s in ("short", "long")},
                hl={s: top(real, s, price) for s in ("short", "long")},
                hl_info=dict(top=hl.TOP, posicoes=len(pos), longs=longs, shorts=shorts, oi=oi,
                             sem_liq=no_liq, lev_mediana=lev_med, funding_h=funding))
    (DATA / "agora.json").write_text(json.dumps(foto), encoding="utf-8")
    print(f"\nFoto salva em {DATA / 'agora.json'} (rode python mapa.py para pôr na página)")


if __name__ == "__main__":
    main()
