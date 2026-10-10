"""Foto das posições reais de BTC na Hyperliquid, sem endereço: data/hyperliquid_<data>.csv."""
import csv
from datetime import date

import hyperliquid as hl
from store import DATA

if __name__ == "__main__":
    px, oi, funding = hl.market()
    pos = hl.positions()
    nome = DATA / f"hyperliquid_{date.today()}.csv"
    with nome.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["lado", "tamanho_btc", "entrada", "liquidacao", "alavancagem", "preco_agora", "oi_btc_um_lado"])
        for lado, tam, ent, liq, lev in pos:
            w.writerow([lado, tam, ent, liq if liq else "", lev, px, oi])
    longs = sum(p[1] for p in pos if p[0] == "long"); shorts = sum(p[1] for p in pos if p[0] == "short")
    print(f"{len(pos)} posições | preço {px:,.0f} | OI {oi:,.0f} BTC | cobertura longs {longs/oi:.1%} shorts {shorts/oi:.1%}")
    print(f"salvo em {nome}")
