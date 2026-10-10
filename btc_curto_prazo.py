"""Painel rápido de sentimento de curto prazo do BTC (APIs públicas, sem chave)."""
from exchanges import get, fetch_all, BINANCE, SYMBOL
from liq_map import LEVERAGES, liq_price, build, clusters


# ---------- Coleta (Binance) ----------

def price():
    d = get(f"{BINANCE}/fapi/v1/ticker/24hr", symbol=SYMBOL)
    return float(d["lastPrice"]), float(d["priceChangePercent"])


def funding():
    # Vem em fração (0.0001 = 0,01%) e vale por período de 8h
    d = get(f"{BINANCE}/fapi/v1/premiumIndex", symbol=SYMBOL)
    return float(d["lastFundingRate"]) * 100


def open_interest(hours=24):
    # Histórico horário de OI em USD; compara agora com N horas atrás
    d = get(f"{BINANCE}/futures/data/openInterestHist",
            symbol=SYMBOL, period="1h", limit=hours + 1)
    first, last = (float(x["sumOpenInterestValue"]) for x in (d[0], d[-1]))
    return last, (last / first - 1) * 100


def long_short():
    # Razão de contas compradas/vendidas (>1 = mais gente comprada)
    d = get(f"{BINANCE}/futures/data/globalLongShortAccountRatio",
            symbol=SYMBOL, period="1h", limit=1)
    return float(d[0]["longShortRatio"])


def fear_greed():
    d = get("https://api.alternative.me/fng/", limit=1)["data"][0]
    return int(d["value"]), d["value_classification"]


# ---------- Interpretação ----------

def read_funding(f):
    # Referência: +0,01%/8h é o "normal" do mercado
    if f > 0.03:
        return "longs pagando caro (risco de flush p/ baixo)"
    if f < -0.01:
        return "shorts pagando (risco de short squeeze)"
    return "neutro"


def read_oi(price_chg, oi_chg):
    # Leitura clássica preço x OI: quem está empurrando o movimento
    return {
        (True, True): "alta com posições novas (longs entrando)",
        (True, False): "alta por fechamento de shorts",
        (False, True): "queda com posições novas (shorts entrando)",
        (False, False): "queda por saída/liquidação de longs",
    }[(price_chg > 0, oi_chg > 0)]


def read_ls(ls):
    # Extremos costumam ser contrários: multidão de um lado vira combustível
    if ls > 2:
        return "multidão comprada (contrário: cautela)"
    if ls < 0.8:
        return "multidão vendida (contrário: squeeze possível)"
    return "equilibrado"


# ---------- Saída ----------

def print_heatmap(top=5):
    series = fetch_all()
    c = clusters([z for s in series.values() for z in build(s)])
    print(f"\nMaiores zonas de liquidação acumuladas ({' + '.join(series)}):")
    for side, label in (("short", "Acima (shorts)"), ("long", "Abaixo (longs)")):
        print(f"  {label}")
        for lvl, usd in sorted(c[side].most_common(top), reverse=True):
            print(f"    ${lvl:,.0f}  ~${usd / 1e6:,.0f}M")


def main():
    p, chg = price()
    f = funding()
    oi, oi_chg = open_interest()
    ls = long_short()
    fg, fg_txt = fear_greed()

    print(f"Preço       ${p:,.0f} ({chg:+.2f}% 24h)")
    print(f"Funding     {f:+.4f}%  → {read_funding(f)}")
    print(f"Open Int.   ${oi / 1e9:.2f}B ({oi_chg:+.2f}% 24h) → {read_oi(chg, oi_chg)}")
    print(f"Long/Short  {ls:.2f}  → {read_ls(ls)}")
    print(f"Medo/Gan.   {fg} ({fg_txt})")

    print("\nLiquidação de quem entrar agora:")
    for lev in LEVERAGES:
        print(f"  {lev:>3}x  longs ${liq_price(p, lev, 'long'):,.0f}"
              f"  |  shorts ${liq_price(p, lev, 'short'):,.0f}")

    print_heatmap()


if __name__ == "__main__":
    main()
