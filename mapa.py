"""Gera data/mapa.html: foto atual (escada + Hyperliquid), mapa de calor histórico e backtest.

Rodar depois de store.py (e de agora.py, para a foto atual): python mapa.py
O mapa é montado com todo o histórico salvo; a página mostra só os últimos DIAS.
"""
import json
from datetime import datetime
from pathlib import Path

from backtest import BRT, HORIZON, REF, evaluate, metrics, snapshots
from exchanges import EXCHANGES, H
from store import DATA, load

DIAS = 90      # janela mostrada no mapa de calor e na tabela diária
STEP = 500
MARGIN = 0.15  # faixa de preço mostrada: mín/máx do período ± 15%


def main():
    series = {n: s for n in EXCHANGES if (s := load(n))}
    ref = series[REF]
    keep_from = ref[-1][0] - DIAS * 24 * H
    snaps = snapshots(series, keep_from)
    rows = evaluate(snaps, ref)
    shown = [s for s in snaps if s["clusters"] is not None]
    i0 = next(i for i, r in enumerate(ref) if r[0] == shown[0]["ts"])
    hist = ref[i0:]  # snapshots são horas consecutivas da referência a partir daqui
    assert [r[0] for r in hist] == [s["ts"] for s in shown]

    lo = min(r[2] for r in hist) * (1 - MARGIN) // STEP * STEP
    hi = max(r[1] for r in hist) * (1 + MARGIN) // STEP * STEP
    nb = int((hi - lo) // STEP) + 1
    grid = []
    for s in shown:
        col = [0] * nb
        for side in ("long", "short"):
            for lvl, usd in s["clusters"][side].items():
                b = int((lvl - lo) // STEP)
                if 0 <= b < nb:
                    col[b] += round(usd / 1e5)  # em décimos de milhão
        grid += col

    events, prev = [], None
    for i, s in enumerate(shown):
        live = " + ".join(s["live"])
        if live != prev:
            events.append([i, live])
            prev = live
    half = len(rows) // 2
    split_ts = rows[half]["ts"]
    cur = snaps[-1]
    agora = DATA / "agora.json"
    data = dict(
        gen=datetime.now(BRT).strftime("%d/%m/%Y %Hh%M BRT"), horizon=HORIZON, dias=DIAS,
        hist0=snaps[0]["ts"],
        t0=shown[0]["ts"], n=len(shown), ymin=lo, step=STEP, nb=nb, grid=grid,
        h=[r[1] for r in hist], l=[r[2] for r in hist], c=[r[3] for r in hist],
        events=events,
        split=(split_ts - shown[0]["ts"]) // H if split_ts >= shown[0]["ts"] else None,
        cur=dict(ts=cur["ts"], close=cur["close"], live=cur["live"], up=cur["up"], dn=cur["dn"]),
        cal=metrics(rows[:half], ref), tst=metrics(rows[half:], ref),
        daily=[r for r in rows if not r["ts"] // H % 24 and r["ts"] >= keep_from],
        agora=json.loads(agora.read_text(encoding="utf-8")) if agora.exists() else None,
    )
    tpl = (Path(__file__).parent / "mapa_template.html").read_text(encoding="utf-8")
    out = DATA / "mapa.html"
    out.write_text(tpl.replace("/*DATA*/null", json.dumps(data, separators=(",", ":"))),
                   encoding="utf-8")
    print(f"{out} ({out.stat().st_size / 1e6:.1f} MB, {len(shown)} fotos x {nb} faixas)")


if __name__ == "__main__":
    main()
