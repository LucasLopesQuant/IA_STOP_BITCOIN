"""Mapa histórico sem look-ahead: foto do mapa em cada hora T e quando o preço foi buscar as zonas.

Lê data/*.csv (rode store.py antes). Saída: resumo no terminal + data/backtest.csv.
Regras: ver "Regras para simular o passado" no CLAUDE.md.
"""
import csv
from collections import Counter
from datetime import datetime, timedelta, timezone

import numpy as np

from exchanges import EXCHANGES
from liq_map import LiqMap
from store import DATA, load

HORIZON = 24  # horas olhadas à frente para "qual lado foi tocado primeiro"
WARMUP = 72   # horas de histórico que cada corretora precisa antes de entrar na foto
REF = "Bybit"  # série de preço usada para avaliar toques (a mais longa)
DIAS_TABELA = 90  # dias da foto diária impressa no terminal
BRT = timezone(timedelta(hours=-3))


def snapshots(series, keep_from=None):
    """Para cada hora fechada T da referência, a foto do mapa com dados só até T.

    O mapa completo (clusters) só é guardado a partir de `keep_from` (ms), para a
    página; das outras horas ficam só as 5 maiores faixas de cada lado.
    """
    ref = series[REF]
    by_ts = {n: {r[0]: r for r in s} for n, s in series.items()}
    maps = {n: LiqMap() for n in series}
    seen = dict.fromkeys(series, 0)
    out = []
    for ts, *_ , close, _ in ref:
        live = []
        for n, m in maps.items():
            row = by_ts[n].get(ts)
            if row:
                m.step(row)
                seen[n] += 1
                if seen[n] > WARMUP:  # só entra quem tem dado em T e já aqueceu
                    live.append(n)
        if not live:
            continue
        c = {"long": Counter(), "short": Counter()}
        for n in live:
            for side, cc in maps[n].clusters().items():
                c[side].update(cc)  # soma as faixas das corretoras
        up = [(usd, lvl) for lvl, usd in c["short"].items() if lvl > close]
        dn = [(usd, lvl) for lvl, usd in c["long"].items() if lvl < close]
        if up and dn:
            keep = keep_from is not None and ts >= keep_from
            out.append(dict(ts=ts, close=close, live=live, clusters=c if keep else None,
                            up=sorted(up, reverse=True)[:5], dn=sorted(dn, reverse=True)[:5]))
    return out


class Prices:
    """Máximas e mínimas da referência em numpy, com extremos das próximas HORIZON horas."""

    def __init__(self, ref):
        self.idx = {r[0]: i for i, r in enumerate(ref)}
        self.high = np.array([r[1] for r in ref])
        self.low = np.array([r[2] for r in ref])
        n = len(ref)
        # fut_max[i] = máxima de i+1 até i+HORIZON (NaN se faltar futuro)
        self.fut_max, self.fut_min = np.full(n, np.nan), np.full(n, np.nan)
        if n > HORIZON:
            w = np.lib.stride_tricks.sliding_window_view
            self.fut_max[:n - HORIZON] = w(self.high[1:], HORIZON).max(axis=1)
            self.fut_min[:n - HORIZON] = w(self.low[1:], HORIZON).min(axis=1)

    def hours_to_touch(self, i, level, up):
        """Horas a partir de T (índice i) até o preço tocar `level`; None se não tocou."""
        hit = self.high[i + 1:] >= level if up else self.low[i + 1:] <= level
        if not hit.size:
            return None
        k = int(np.argmax(hit))
        return k + 1 if hit[k] else None


def first_side(hu, hd):
    hu = hu if hu is not None and hu <= HORIZON else None
    hd = hd if hd is not None and hd <= HORIZON else None
    if hu is None and hd is None:
        return "nenhum"
    if hu == hd:
        return "ambiguo"  # tocou os dois no mesmo candle: não dá para saber a ordem
    if hd is None or (hu is not None and hu < hd):
        return "acima"
    return "abaixo"


def evaluate(snaps, ref):
    px = Prices(ref)
    rows = []
    for s in snaps:
        i = px.idx[s["ts"]]
        up_lvl, dn_lvl = s["up"][0][1], s["dn"][0][1]
        hu = px.hours_to_touch(i, up_lvl, True)
        hd = px.hours_to_touch(i, dn_lvl, False)
        complete = i + HORIZON < len(ref)
        rows.append(dict(
            ts=s["ts"], close=s["close"], corretoras="+".join(s["live"]),
            acima=up_lvl, acima_usd=s["up"][0][0], acima_dist=up_lvl / s["close"] - 1,
            abaixo=dn_lvl, abaixo_usd=s["dn"][0][0], abaixo_dist=dn_lvl / s["close"] - 1,
            h_acima=hu, h_abaixo=hd,
            primeiro=first_side(hu, hd) if complete else "incompleto"))
    return rows


def random_baseline(rows, ref, reps=200, seed=7):
    """Taxa de toque em HORIZON de níveis aleatórios com a mesma distribuição de distâncias."""
    rnd = np.random.default_rng(seed)
    px = Prices(ref)
    i = np.array([px.idx[r["ts"]] for r in rows])
    close = np.array([r["close"] for r in rows])[:, None]
    ups = np.array([r["acima_dist"] for r in rows])
    dns = np.array([r["abaixo_dist"] for r in rows])
    lv_up = close * (1 + rnd.choice(ups, (len(rows), reps)))
    lv_dn = close * (1 + rnd.choice(dns, (len(rows), reps)))
    return (float((lv_up <= px.fut_max[i][:, None]).mean()),
            float((lv_dn >= px.fut_min[i][:, None]).mean()))


def metrics(rows, ref):
    """Métricas de um período; ignora as fotos sem HORIZON horas de futuro."""
    rows = [r for r in rows if r["primeiro"] != "incompleto"]
    n = len(rows)
    if not n:
        return None
    within = lambda h: h is not None and h <= HORIZON
    bigger = lambda r: "acima" if r["acima_usd"] > r["abaixo_usd"] else "abaixo"
    nearer = lambda r: "acima" if r["acima_dist"] < -r["abaixo_dist"] else "abaixo"
    count = lambda rs, f: sum(r["primeiro"] == f(r) for r in rs)
    dec = [r for r in rows if r["primeiro"] in ("acima", "abaixo")]
    disagree = [r for r in dec if bigger(r) != nearer(r)]
    r_up, r_dn = random_baseline(rows, ref)
    return dict(
        inicio=rows[0]["ts"], fim=rows[-1]["ts"], n=n,
        dist_acima=sorted(r["acima_dist"] for r in rows)[n // 2],
        dist_abaixo=sorted(r["abaixo_dist"] for r in rows)[n // 2],
        toque_acima=sum(within(r["h_acima"]) for r in rows) / n, aleat_acima=r_up,
        toque_abaixo=sum(within(r["h_abaixo"]) for r in rows) / n, aleat_abaixo=r_dn,
        primeiro={k: sum(r["primeiro"] == k for r in rows) / n
                  for k in ("acima", "abaixo", "nenhum", "ambiguo")},
        decididos=len(dec),
        maior=count(dec, bigger) / len(dec) if dec else None,
        proximo=count(dec, nearer) / len(dec) if dec else None,
        discordam=len(disagree),
        disc_maior=count(disagree, bigger) / len(disagree) if disagree else None,
    )


def pct(x):
    return "   n/a" if x is None else f"{x:6.1%}"


def summary(name, m):
    if not m:
        return
    d0, d1 = (datetime.fromtimestamp(m[k] / 1000, BRT).strftime("%d/%m/%Y") for k in ("inicio", "fim"))
    print(f"\n== {name}: {d0} a {d1}, {m['n']} fotos horárias ==")
    print(f"  distância mediana: acima {m['dist_acima']:+.2%} | abaixo {m['dist_abaixo']:+.2%}")
    print(f"  tocou em {HORIZON}h      maior zona acima {pct(m['toque_acima'])}  (aleatório {pct(m['aleat_acima'])})"
          f" | maior zona abaixo {pct(m['toque_abaixo'])}  (aleatório {pct(m['aleat_abaixo'])})")
    print("  primeiro toque     " + "  ".join(f"{k} {pct(v)}" for k, v in m["primeiro"].items()))
    print(f"  entre os {m['decididos']} decididos: foi primeiro p/ o lado da MAIOR zona {pct(m['maior'])}"
          f" | p/ o lado MAIS PRÓXIMO {pct(m['proximo'])}")
    if m["discordam"]:
        print(f"  quando discordam ({m['discordam']}): maior zona {pct(m['disc_maior'])}"
              f" | mais próximo {pct(1 - m['disc_maior'])}")


def fmt_h(h):
    if h is None:
        return "ainda não"
    return f"{h}h" if h < 48 else f"{h / 24:.1f}d"


def daily_table(rows):
    print("\nFoto diária (00h UTC = 21h BRT do dia anterior): maior zona de cada lado e quando o preço foi buscar")
    print(f"  {'data BRT':<12}{'preço':>9}   {'maior acima':<28}{'buscou em':>10}   {'maior abaixo':<28}{'buscou em':>10}")
    for r in rows:
        if r["ts"] // 3_600_000 % 24:
            continue
        when = datetime.fromtimestamp(r["ts"] / 1000, BRT).strftime("%d/%m %Hh")
        side = lambda k: f"${r[k]:,.0f} ~${r[k + '_usd'] / 1e6:,.0f}M ({r[k + '_dist']:+.1%})"
        print(f"  {when:<12}{r['close']:>9,.0f}   {side('acima'):<28}{fmt_h(r['h_acima']):>10}"
              f"   {side('abaixo'):<28}{fmt_h(r['h_abaixo']):>10}")


def current(snap):
    t = datetime.fromtimestamp(snap["ts"] / 1000, BRT).strftime("%d/%m %Hh BRT")
    print(f"\nFoto mais recente ({t}, candle fechado, {' + '.join(snap['live'])}), preço ${snap['close']:,.0f}")
    for key, label in (("up", "Acima (shorts)"), ("dn", "Abaixo (longs)")):
        print(f"  {label}")
        for usd, lvl in sorted(snap[key], key=lambda x: -x[1]):
            print(f"    ${lvl:,.0f}  ~${usd / 1e6:,.0f}M  ({lvl / snap['close'] - 1:+.1%})")


def main():
    series = {n: s for n in EXCHANGES if (s := load(n))}
    if REF not in series:
        raise SystemExit(f"Sem dados de {REF}. Rode: python store.py")
    ref = series[REF]
    snaps = snapshots(series)
    rows = evaluate(snaps, ref)

    with (DATA / "backtest.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)

    current(snaps[-1])
    daily_table(rows[-DIAS_TABELA * 24:])
    # Calibração (1ª metade) separada do teste (2ª). Nada foi ajustado ainda:
    # os parâmetros são os chutes originais do liq_map.py.
    half = len(rows) // 2
    summary("Calibração", metrics(rows[:half], ref))
    summary("Teste", metrics(rows[half:], ref))
    print(f"\nCSV por hora: {DATA / 'backtest.csv'}")


if __name__ == "__main__":
    main()
