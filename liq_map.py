"""Mapa de liquidação aproximado, no estilo do heatmap da CoinGlass."""
from collections import Counter

import numpy as np

# Suposição de como o volume novo se distribui entre alavancagens.
# É o maior chute do modelo: ajuste conforme o que achar mais realista.
LEVERAGES = {10: 0.4, 25: 0.3, 50: 0.2, 100: 0.1}
MM = 0.005  # margem de manutenção (~0,5%): liquida antes da perda total


def liq_price(entry, lev, side):
    # Long liquida abaixo da entrada; short, acima (espelho)
    sign = -1 if side == "long" else 1
    return entry * (1 + sign * (1 / lev - MM))


def hit(zone, high, low):
    # O preço passou pela zona nesta hora? Então já foi liquidada.
    lvl, _, side = zone
    return low <= lvl if side == "long" else high >= lvl


class LiqMap:
    """Mapa incremental em arrays numpy (rápido com anos de histórico).

    Após step() de cada linha, `zones` == build(série até ela). A lógica é a mesma do
    build() original (ver test_liq_map.py, que compara com a versão em listas).
    """

    def __init__(self):
        self.lvl = np.empty(0)
        self.usd = np.empty(0)
        self.short = np.empty(0, bool)  # True = short (liquida acima), False = long
        self.prev_oi = None

    def step(self, row):
        _, high, low, close, oi = row
        prev_oi, self.prev_oi = self.prev_oi, oi
        if prev_oi is None:
            return
        # Remove as zonas que o preço tocou nesta hora
        keep = np.where(self.short, self.lvl > high, self.lvl < low)
        self.lvl, self.usd, self.short = self.lvl[keep], self.usd[keep], self.short[keep]

        if oi < prev_oi:
            # OI caiu: posições fechadas; reduz todas na mesma proporção
            self.usd = self.usd * (oi / prev_oi)
        elif oi > prev_oi:
            # OI subiu: posições novas perto do fechamento da hora.
            # Todo contrato tem comprador e vendedor → cria as duas pontas.
            usd = (oi - prev_oi) * close
            new = [(liq_price(close, lev, side), usd * w, side == "short")
                   for lev, w in LEVERAGES.items() for side in ("long", "short")]
            lvl, u, sh = zip(*new)
            self.lvl = np.concatenate([self.lvl, lvl])
            self.usd = np.concatenate([self.usd, u])
            self.short = np.concatenate([self.short, sh])

    @property
    def zones(self):
        """Zonas vivas no formato antigo: [preço, usd, lado]."""
        return [[float(l), float(u), "short" if s else "long"]
                for l, u, s in zip(self.lvl, self.usd, self.short)]

    def clusters(self, step=500):
        """Igual a clusters(self.zones, step), vetorizado."""
        out = {"long": Counter(), "short": Counter()}
        bands = np.round(self.lvl / step) * step
        for side, mask in (("short", self.short), ("long", ~self.short)):
            b, inv = np.unique(bands[mask], return_inverse=True)
            for lvl, usd in zip(b, np.bincount(inv, weights=self.usd[mask], minlength=len(b))):
                out[side][int(lvl)] += float(usd)
        return out


def build(series):
    """Percorre a série hora a hora e devolve as zonas vivas: [preço, usd, lado]."""
    m = LiqMap()
    for row in series:
        m.step(row)
    return m.zones


def clusters(zones, step=500):
    """Soma o volume em faixas de `step` dólares, separado por lado."""
    out = {"long": Counter(), "short": Counter()}
    for lvl, usd, side in zones:
        out[side][int(round(lvl / step) * step)] += usd
    return out
