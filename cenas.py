# -*- coding: utf-8 -*-
"""
As imagens e animações do vídeo "IA que busca stop no Bitcoin", uma por cena, em
`cenas/`.

    python cenas.py            # tudo
    python cenas.py 00 11b     # só essas cenas

Lê os CSV de `data/` (congelados em 07/10/2026) e o modelo do `liq_map.py`; nada é
redesenhado à mão, cada número sai do código. O cálculo pesado (o mapa hora a hora em
quase cinco anos) fica em cache em `data/cache_cenas.pkl`: apague para refazer.

Identidade do canal (a mesma das cenas da série de IA): fundo quase preto, verde de
terminal, fonte de código, 1920x1080 a 30 fps, e nada importante abaixo de 900 px, onde o
editor queima a legenda.
"""
from __future__ import annotations

import csv
import pickle
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager
from matplotlib.animation import FFMpegWriter, FuncAnimation
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.patches import FancyBboxPatch

import backtest as bt
from exchanges import EXCHANGES, H
from liq_map import LEVERAGES, MM, liq_price
from store import DATA, load

AQUI = Path(__file__).resolve().parent
SAIDA = AQUI / "cenas"
CACHE = DATA / "cache_cenas.pkl"
FONTES = AQUI / "fonts"   # opcional: JetBrains Mono aqui; sem ela, cai na DejaVu
BRT = timezone(timedelta(hours=-3))

FUNDO, PAINEL = "#05060a", "#0d1017"
VERDE, VERMELHO, AMBAR, NEUTRO = "#20E37B", "#FF4D5E", "#FFB020", "#9AA4B2"
BRANCO, CINZA, LINHA = "#e6e6e6", "#4b5260", "#1a1e27"
FPS = 30

for f in FONTES.glob("*.ttf"):
    font_manager.fontManager.addfont(str(f))
plt.rcParams.update({
    "font.family": ["JetBrains Mono", "DejaVu Sans"], "font.size": 20,
    "figure.facecolor": FUNDO, "axes.facecolor": FUNDO, "savefig.facecolor": FUNDO,
    "axes.edgecolor": "#2a2d36", "axes.labelcolor": BRANCO, "text.color": BRANCO,
    "xtick.color": NEUTRO, "ytick.color": NEUTRO, "xtick.labelsize": 18,
    "ytick.labelsize": 18, "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": LINHA, "lines.solid_capstyle": "round",
})
plt.rcParams["animation.ffmpeg_path"] = shutil.which("ffmpeg") or "ffmpeg"

# calor: preto, índigo, violeta, âmbar (sem verde e vermelho, que são do preço e dos lados)
CALOR = LinearSegmentedColormap.from_list("calor", [FUNDO, "#2a1659", "#7b2d8e", "#d9456b", AMBAR, "#fff1c2"])
AREA = [0.08, 0.22, 0.76, 0.62]

# A primeira rodada (90 dias) é a que o projeto tinha em 07/10 de manhã: Bybit desde o início
# da coleta própria, Binance só os 30 dias da API e a OKX inteira (~60 dias).
INICIO_90D = 1783602000000          # 09/07/2026 13h UTC, a primeira hora da Bybit naquela coleta
BINANCE_90D_HORAS = 720
FIM_90D = 1791381600000             # 07/10/2026 14h UTC, a última hora daquela rodada


# ---------------------------------------------------------------- utilidades

def br(x: float, casas: int = 0) -> str:
    inteiro, _, decimal = f"{x:,.{casas}f}".partition(".")
    return inteiro.replace(",", ".") + ("," + decimal if decimal else "")


def pct(x: float, casas: int = 1) -> str:
    return br(100 * x, casas) + "%"


def dia(ts: int, fmt: str = "%d/%m") -> str:
    return datetime.fromtimestamp(ts / 1000, BRT).strftime(fmt)


def quadro(titulo: str | None = None, sub: str | None = None):
    fig = plt.figure(figsize=(19.2, 10.8), dpi=100)
    if titulo:
        fig.text(0.08, 0.915, titulo, fontsize=38, fontweight="bold", color=BRANCO)
    if sub:
        fig.text(0.08, 0.87, sub, fontsize=21, color=NEUTRO)
    return fig


def fonte(fig, texto: str) -> None:
    fig.text(0.08, 0.175, texto, fontsize=15, color=CINZA)


def salvar(fig, nome: str) -> None:
    SAIDA.mkdir(parents=True, exist_ok=True)
    fig.savefig(SAIDA / f"{nome}.png", dpi=100)
    plt.close(fig)
    print(f"  {nome}.png")


def animar(fig, passo, quadros: int, nome: str, segura: float = 1.5) -> None:
    """Grava o mp4 (1920x1080, 30 fps) e o último quadro como png."""
    SAIDA.mkdir(parents=True, exist_ok=True)
    total = quadros + int(segura * FPS)
    anim = FuncAnimation(fig, lambda i: passo(min(i, quadros - 1)), frames=total, blit=False)
    anim.save(SAIDA / f"{nome}.mp4", writer=FFMpegWriter(
        fps=FPS, codec="libx264", bitrate=8000, extra_args=["-pix_fmt", "yuv420p"]))
    fig.savefig(SAIDA / f"{nome}.png", dpi=100)
    plt.close(fig)
    print(f"  {nome}.mp4 + png")


def digitar(nome: str, texto: str, tamanho: int = 60, cor: str = VERDE, cps: int = 26) -> None:
    """Frase-chave digitando, em verde de terminal, com cursor."""
    fig = quadro()
    t = fig.text(0.08, 0.56, "", fontsize=tamanho, color=cor, va="center",
                 fontweight="bold", linespacing=1.5)
    completo = "> " + texto
    n = max(1, int(len(completo) / cps * FPS))

    def passo(i):
        k = int(len(completo) * (i + 1) / n)
        cursor = "▌" if (i // 12) % 2 == 0 or k < len(completo) else " "
        t.set_text(completo[:k] + cursor)
    animar(fig, passo, n, nome, segura=2.0)


def caixa(fig, ret, texto, cor=BRANCO, tam=24, fundo=PAINEL, borda=None):
    ax = fig.add_axes(ret)
    ax.axis("off")
    ax.add_patch(FancyBboxPatch((0, 0), 1, 1, boxstyle="round,pad=0,rounding_size=0.06",
                                transform=ax.transAxes, facecolor=fundo,
                                edgecolor=borda or cor, linewidth=2))
    ax.text(0.5, 0.5, texto, ha="center", va="center", fontsize=tam, color=cor,
            fontweight="bold", linespacing=1.4)
    return ax


# ---------------------------------------------------------------- dados

def series(corte: bool = False) -> dict:
    s = {n: load(n) for n in EXCHANGES}
    s = {n: v for n, v in s.items() if v}
    if corte:   # a primeira rodada, de 90 dias, congelada em 07/10 (dado novo não entra)
        s = {n: [r for r in v if r[0] <= FIM_90D] for n, v in s.items()}
        s["Bybit"] = [r for r in s["Bybit"] if r[0] >= INICIO_90D]
        s["Binance"] = s["Binance"][-BINANCE_90D_HORAS:]
    return s


def calcular() -> dict:
    """Roda o backtest do projeto nas duas rodadas e guarda só o que as cenas usam."""
    out = {}
    for nome, corte in (("90d", True), ("longo", False)):
        print(f"  calculando a rodada {nome} (pode levar alguns minutos)...", flush=True)
        s = series(corte)
        ref = s[bt.REF]
        guarda = ref[-1][0] - 21 * 24 * H if nome == "longo" else None
        fotos = bt.snapshots(s, keep_from=guarda)
        linhas = bt.evaluate(fotos, ref)
        metade = len(linhas) // 2
        out[nome] = {
            "linhas": linhas,
            "calib": bt.metrics(linhas[:metade], ref),
            "teste": bt.metrics(linhas[metade:], ref),
            "mapa": [(f["ts"], f["close"], f["clusters"]) for f in fotos if f["clusters"]],
            "ultima": {k: fotos[-1][k] for k in ("ts", "close", "up", "dn", "live")},
        }
    with CACHE.open("wb") as f:
        pickle.dump(out, f)
    return out


_R = None


def R() -> dict:
    global _R
    if _R is None:
        _R = pickle.loads(CACHE.read_bytes()) if CACHE.exists() else calcular()
    return _R


def hyperliquid() -> tuple[list[dict], str]:
    arqs = sorted(DATA.glob("hyperliquid_*.csv"))
    if not arqs:
        raise SystemExit("rode antes: python hyper_snapshot.py")
    with arqs[-1].open() as f:
        return list(csv.DictReader(f)), arqs[-1].stem.split("_")[1]


# ---------------------------------------------------------------- abertura

def c00_mapa_calor() -> None:
    mapa = R()["longo"]["mapa"]
    ts = [m[0] for m in mapa]
    close = np.array([m[1] for m in mapa])
    lo, hi = close.min() * 0.86, close.max() * 1.14
    faixas = np.arange(np.floor(lo / 500) * 500, hi + 500, 500)
    M = np.zeros((len(faixas), len(mapa)))
    for j, (_, _, cl) in enumerate(mapa):
        for lado in ("long", "short"):
            for nivel, usd in cl[lado].items():
                i = int(round((nivel - faixas[0]) / 500))
                if 0 <= i < len(faixas):
                    M[i, j] += usd
    escala = np.percentile(M[M > 0], 99)
    fig = quadro("o mapa de liquidação do Bitcoin", "Binance + Bybit + OKX, foto de hora em hora")
    ax = fig.add_axes([0.08, 0.26, 0.72, 0.58])
    ax.grid(False)
    vazio = np.full_like(M, np.nan)
    im = ax.imshow(vazio, aspect="auto", origin="lower", cmap=CALOR, vmin=0, vmax=escala,
                   extent=[0, len(mapa), faixas[0] - 250, faixas[-1] + 250], interpolation="nearest")
    linha, = ax.plot([], [], color=BRANCO, lw=2.2)
    ax.set_xlim(0, len(mapa))
    ax.set_ylim(faixas[0], faixas[-1])
    ax.yaxis.set_major_formatter(lambda v, _: "$" + br(v / 1000) + " mil")
    marcas = [j for j, t in enumerate(ts) if (t // H) % 24 == 3][::4]
    ax.set_xticks(marcas, [dia(ts[j]) for j in marcas])
    u = R()["longo"]["ultima"]
    (usd_a, lvl_a), (usd_b, lvl_b) = u["up"][0], u["dn"][0]
    rotulos = [ax.annotate(f"US$ {br(lvl)}\n~US$ {br(usd / 1e6)} mi", (len(mapa), lvl), xytext=(14, 0),
                           textcoords="offset points", va="center", fontsize=19, color=cor,
                           fontweight="bold", annotation_clip=False, alpha=0)
               for lvl, usd, cor in ((lvl_a, usd_a, VERDE), (lvl_b, usd_b, VERMELHO))]
    n = 180

    def passo(i):
        k = max(1, int(len(mapa) * (i + 1) / n))
        A = vazio.copy()
        A[:, :k] = M[:, :k]
        im.set_data(np.where(A > 0, A, np.nan))
        linha.set_data(np.arange(k) + 0.5, close[:k])
        for r in rotulos:
            r.set_alpha(1.0 if k >= len(mapa) else 0)
    fig.text(0.08, 0.175, "faixas claras = muito dinheiro alavancado que seria liquidado ali   |   linha branca = o preço",
             fontsize=15, color=CINZA)
    animar(fig, passo, n, "00_mapa_calor", segura=3.0)


def c01_tres_perguntas() -> None:
    fig = quadro("três perguntas para o robô")
    for i, p in enumerate(["onde estão os stops?", "quem está do outro lado?", "o preço vai mesmo buscar?"]):
        y = 0.68 - i * 0.16
        fig.text(0.1, y, f"{i + 1}", fontsize=70, color=VERDE, fontweight="bold", va="center")
        fig.text(0.18, y, p, fontsize=48, color=BRANCO, va="center")
    salvar(fig, "01_tres_perguntas")


def c02_ia_corretora() -> None:
    fig = quadro("o que a IA de uma corretora concluiu", "os três números estavam certos")
    itens = [("saída de 1.059 BTC\ndos ETFs", "um dia de ETF\né barulho"),
             ("funding\n-0,0007%", "praticamente\nzero"),
             ("Medo e Ganância\nem 70", "fundo costuma vir\ncom medo extremo")]
    for i, (dado, leitura) in enumerate(itens):
        x = 0.08 + i * 0.29
        caixa(fig, [x, 0.52, 0.25, 0.22], dado, BRANCO, tam=27)
        fig.text(x + 0.125, 0.47, "↓", ha="center", fontsize=34, color=CINZA)
        caixa(fig, [x, 0.27, 0.25, 0.16], leitura, VERMELHO, tam=24)
    fig.text(0.08, 0.2, 'conclusão dela: "acumule na fraqueza"', fontsize=30, color=AMBAR, fontweight="bold")
    salvar(fig, "02_ia_corretora")


def c03_dois_lados() -> None:
    fig = quadro("todo contrato tem dois lados", "o funding diz quem está mais afoito, não quem é maioria")
    caixa(fig, [0.1, 0.42, 0.28, 0.26], "quem comprou\n(long)", VERDE, tam=34)
    caixa(fig, [0.62, 0.42, 0.28, 0.26], "quem vendeu\n(short)", VERMELHO, tam=34)
    fig.text(0.5, 0.58, "1 contrato", ha="center", fontsize=30, color=BRANCO, fontweight="bold")
    fig.text(0.5, 0.5, "⟵──────⟶", ha="center", fontsize=40, color=NEUTRO)
    fig.text(0.5, 0.3, "os dois lados têm sempre o mesmo tamanho", ha="center", fontsize=30, color=AMBAR)
    salvar(fig, "03_dois_lados")


# ---------------------------------------------------------------- onde estão os stops

def c04_escada_alavancagem() -> None:
    fig = quadro("quanto precisa cair para liquidar quem comprou", "Bitcoin, com margem de manutenção de 0,5%")
    ax = fig.add_axes([0.1, 0.22, 0.62, 0.6])
    ax.set_xlim(0, 1)
    ax.set_ylim(-11, 1.2)
    ax.set_xticks([])
    ax.yaxis.set_major_formatter(lambda v, _: br(v) + "%")
    ax.axhline(0, color=BRANCO, lw=3)
    ax.text(0.02, 0.35, "você entrou aqui", color=BRANCO, fontsize=20)
    degraus = [(100, VERMELHO), (50, "#ff7a59"), (25, AMBAR), (10, "#d9d26a")]
    objs = []
    for lev, cor in degraus:
        q = -(1 / lev - MM) * 100
        l = ax.axhline(q, color=cor, lw=3, alpha=0)
        t = ax.text(1.02, q, f"{lev}x  liquida em {br(q, 1)}%", color=cor, fontsize=24,
                    fontweight="bold", va="center", transform=ax.get_yaxis_transform(), alpha=0)
        objs.append((l, t))
    n = 4 * FPS

    def passo(i):
        k = int(len(objs) * (i + 1) / n + 0.999)
        for j, (l, t) in enumerate(objs):
            a = 1.0 if j < k else 0.0
            l.set_alpha(a)
            t.set_alpha(a)
    animar(fig, passo, n, "04_escada_alavancagem", segura=2.5)


def c05_mapa_montando() -> None:
    """72 horas da Bybit: cada alta do open interest cria as 8 faixas (4 alavancagens x 2 lados)."""
    s = load("Bybit")
    fim = len(s) - 24 * 12
    j0 = fim - 72
    zonas = []                       # [nível, usd, short, nasce, morre]
    for k in range(j0, fim):
        _, high, low, close, oi = s[k]
        prev = s[k - 1][4]
        for z in zonas:
            if z[4] is None and ((z[2] and high >= z[0]) or (not z[2] and low <= z[0])):
                z[4] = k
        if oi > prev:
            usd = (oi - prev) * close
            for lev, w in LEVERAGES.items():
                for lado in ("long", "short"):
                    zonas.append([liq_price(close, lev, lado), usd * w, lado == "short", k, None])
    fig = quadro("como o robô monta o mapa", "Bybit, 72 horas: o open interest subiu, nasceu posição nova")
    ax = fig.add_axes([0.08, 0.42, 0.76, 0.42])
    ax2 = fig.add_axes([0.08, 0.22, 0.76, 0.16], sharex=ax)
    x = np.arange(j0, fim)
    preco = np.array([s[k][3] for k in x])
    doi = np.array([s[k][4] - s[k - 1][4] for k in x])
    ax.set_ylim(preco.min() * 0.88, preco.max() * 1.12)
    ax.set_xlim(j0, fim)
    ax.yaxis.set_major_formatter(lambda v, _: "$" + br(v / 1000) + " mil")
    ax2.yaxis.set_major_formatter(lambda v, _: br(v) + " BTC")
    ax2.tick_params(labelsize=14)
    ax.tick_params(labelbottom=False)
    marcas = [k for k in x if (s[k][0] // H) % 24 == 3]
    ax2.set_xticks(marcas, [dia(s[k][0]) for k in marcas])
    usd_max = max(z[1] for z in zonas)
    linha, = ax.plot([], [], color=BRANCO, lw=2.5, zorder=5)
    barras = ax2.bar(x, doi, color=[VERDE if d > 0 else VERMELHO for d in doi], width=0.8)
    for b in barras:
        b.set_visible(False)
    segs = []
    for z in zonas:
        cor = VERDE if z[2] else VERMELHO
        seg, = ax.plot([], [], color=cor, lw=2, alpha=min(1, 0.15 + 0.85 * z[1] / usd_max))
        segs.append((z, seg))
    fig.text(0.86, 0.75, "acima: vendidos\nseriam liquidados", color=VERDE, fontsize=17)
    fig.text(0.86, 0.5, "abaixo: comprados\nseriam liquidados", color=VERMELHO, fontsize=17)
    fig.text(0.86, 0.27, "variação do\nopen interest", color=NEUTRO, fontsize=15)
    n = 8 * FPS

    def passo(i):
        k = j0 + max(1, int(72 * (i + 1) / n))
        linha.set_data(x[:k - j0], preco[:k - j0])
        for b, xx in zip(barras, x):
            b.set_visible(xx < k)
        for z, seg in segs:
            if z[3] < k:
                fim_z = min(k, z[4]) if z[4] else k
                seg.set_data([z[3], fim_z], [z[0], z[0]])
            else:
                seg.set_data([], [])
    animar(fig, passo, n, "05_mapa_montando", segura=2.5)


def c06_chute_alavancagem() -> None:
    fig = quadro("a alavancagem de cada um: ninguém sabe", "então o robô chuta como o dinheiro novo se divide")
    ax = fig.add_axes([0.16, 0.24, 0.6, 0.56])
    levs = list(LEVERAGES)[::-1]
    pesos = [LEVERAGES[l] for l in levs]
    ax.barh([f"{l}x" for l in levs], pesos, color=[VERMELHO, "#ff7a59", AMBAR, "#d9d26a"], height=0.6)
    ax.set_xlim(0, 0.5)
    ax.grid(axis="y", visible=False)
    ax.xaxis.set_major_formatter(lambda v, _: pct(v, 0))
    ax.tick_params(axis="y", labelsize=30)
    for i, p in enumerate(pesos):
        ax.text(p + 0.01, i, pct(p, 0), va="center", fontsize=30, fontweight="bold")
    fig.text(0.8, 0.62, "CHUTE", fontsize=60, color=AMBAR, fontweight="bold", rotation=-12)
    salvar(fig, "06_chute_alavancagem")


def c07_tres_corretoras() -> None:
    fig = quadro("três corretoras, de hora em hora", "só a porta pública, sem chave e sem pagar")
    for i, nome in enumerate(["Binance", "Bybit", "OKX"]):
        caixa(fig, [0.08, 0.64 - i * 0.18, 0.24, 0.13], nome, BRANCO, tam=32)
        fig.text(0.34, 0.705 - i * 0.18, "open interest + preço  ─────▶", fontsize=20, color=NEUTRO, va="center")
    caixa(fig, [0.68, 0.36, 0.24, 0.4], "o mapa\nsomado", AMBAR, tam=40)
    salvar(fig, "07_tres_corretoras")


# ---------------------------------------------------------------- quem está do outro lado

def c08_hyperliquid() -> None:
    pos, quando = hyperliquid()
    px, oi = float(pos[0]["preco_agora"]), float(pos[0]["oi_btc_um_lado"])
    longs = sum(float(p["tamanho_btc"]) for p in pos if p["lado"] == "long")
    shorts = sum(float(p["tamanho_btc"]) for p in pos if p["lado"] == "short")
    bins = np.arange(-100, 105, 5)
    vol = {"long": np.zeros(len(bins) - 1), "short": np.zeros(len(bins) - 1)}
    for p in pos:
        if not p["liquidacao"]:
            continue
        d = np.clip((float(p["liquidacao"]) / px - 1) * 100, -99.9, 99.9)
        vol[p["lado"]][np.searchsorted(bins, d) - 1] += float(p["tamanho_btc"]) * px
    fig = quadro("posições reais de Bitcoin na Hyperliquid",
                 f"as 2.000 maiores contas, {quando[8:10]}/{quando[5:7]}: onde cada uma seria liquidada")
    ax = fig.add_axes([0.13, 0.24, 0.8, 0.56])
    c = (bins[:-1] + bins[1:]) / 2
    ax.bar(c, vol["long"] / 1e6, width=4.6, color=VERMELHO, label="comprados")
    ax.bar(c, vol["short"] / 1e6, width=4.6, color=VERDE, bottom=vol["long"] / 1e6, label="vendidos")
    ax.axvspan(-5, 5, color=AMBAR, alpha=0.12)
    ax.axvline(0, color=BRANCO, lw=2)
    ax.text(0, ax.get_ylim()[1] * 0.95, "preço agora", ha="center", fontsize=18, color=BRANCO)
    ax.xaxis.set_major_formatter(lambda v, _: ("+" if v > 0 else "") + br(v) + "%")
    ax.yaxis.set_major_formatter(lambda v, _: "US$ " + br(v) + " mi")
    ax.legend(loc="upper left", frameon=False, fontsize=18)
    ax.set_xticks([-100, -75, -50, -25, 0, 25, 50, 75, 100],
                  ["-100%", "-75%", "-50%", "-25%", "0%", "+25%", "+50%", "+75%", "+100%\nou mais"])
    com = [p for p in pos if p["liquidacao"]]
    perto = sum(abs(float(p["liquidacao"]) / px - 1) <= 0.05 for p in com)
    fig.text(0.14, 0.62, f"a menos de 5% do preço:\n{perto} de {len(com)} posições", fontsize=24,
             color=AMBAR, fontweight="bold")
    fonte(fig, f"{len(pos)} posições de BTC ({len(pos) - len(com)} sem preço de liquidação)   |   cobrem "
               f"{pct(longs / oi, 0)} dos comprados e {pct(shorts / oi, 0)} dos vendidos de lá")
    salvar(fig, "08_hyperliquid")


# ---------------------------------------------------------------- o preço vai buscar?

def _linha_tempo(nome: str, rodada: str, titulo: str) -> None:
    m = R()[rodada]
    fig = quadro(titulo, "a primeira metade ajusta, a segunda só testa, sem mexer depois de olhar")
    ax = fig.add_axes([0.08, 0.45, 0.84, 0.16])
    ax.axis("off")
    ax.set_xlim(0, 1)
    ax.add_patch(FancyBboxPatch((0, 0), 0.495, 1, boxstyle="round,pad=0,rounding_size=0.08", color="#203a2c"))
    ax.add_patch(FancyBboxPatch((0.505, 0), 0.495, 1, boxstyle="round,pad=0,rounding_size=0.08", color="#3a2a14"))
    ax.text(0.25, 0.5, "calibração", ha="center", va="center", fontsize=34, color=VERDE, fontweight="bold")
    ax.text(0.75, 0.5, "teste", ha="center", va="center", fontsize=34, color=AMBAR, fontweight="bold")
    fmt = "%d/%m/%Y" if rodada == "longo" else "%d/%m"
    for x, k, met in ((0.0, "inicio", "calib"), (0.5, "inicio", "teste"), (1.0, "fim", "teste")):
        fig.text(0.08 + 0.84 * x, 0.38, dia(m[met][k], fmt), ha="center", fontsize=22, color=NEUTRO)
    fig.text(0.29, 0.3, f"{br(m['calib']['n'])} fotos de hora em hora", ha="center", fontsize=20, color=CINZA)
    fig.text(0.71, 0.3, f"{br(m['teste']['n'])} fotos de hora em hora", ha="center", fontsize=20, color=CINZA)
    salvar(fig, nome)


def c09_linha_tempo_90d() -> None:
    _linha_tempo("09_linha_tempo_90d", "90d", "os últimos 90 dias, divididos em dois")


def c10_sorteio_niveis() -> None:
    """Uma foto real: a maior faixa e níveis sorteados à mesma distância, contra as 24h seguintes."""
    linhas = [l for l in R()["90d"]["linhas"] if l["primeiro"] != "incompleto"]
    l = linhas[len(linhas) // 3]
    s = {r[0]: r for r in load("Bybit")}
    hs = [s[l["ts"] + k * H] for k in range(0, 25) if l["ts"] + k * H in s]
    rnd = np.random.default_rng(3)
    dists = rnd.choice([x["acima_dist"] for x in linhas], 14)
    fig = quadro("a régua: o sorteio", "níveis sorteados à mesma distância do preço")
    ax = fig.add_axes([0.08, 0.22, 0.7, 0.6])
    ax.plot(range(len(hs)), [h[3] for h in hs], color=BRANCO, lw=3)
    ax.fill_between(range(len(hs)), [h[2] for h in hs], [h[1] for h in hs], color=BRANCO, alpha=0.12)
    for d in dists:
        ax.axhline(l["close"] * (1 + d), color=CINZA, lw=1.5, ls="--")
    ax.axhline(l["acima"], color=AMBAR, lw=4)
    ax.text(len(hs) - 0.5, l["acima"], f" maior faixa\n US$ {br(l['acima'])}", color=AMBAR, fontsize=20,
            fontweight="bold", va="center")
    ax.set_xlabel("horas depois da foto", fontsize=18, color=NEUTRO)
    ax.yaxis.set_major_formatter(lambda v, _: "$" + br(v / 1000) + " mil")
    fig.text(0.8, 0.5, "tracejado:\nlinhas\nsorteadas", color=NEUTRO, fontsize=20)
    salvar(fig, "10_sorteio_niveis")


def _barras(nome: str, grupos: list[tuple[str, float, float]], titulo: str, sub: str, apagar: int = 0) -> None:
    """Barras mapa contra sorteio, crescendo. grupos: (rótulo, mapa, sorteio); os `apagar`
    primeiros ficam apagados (são a rodada anterior)."""
    fig = quadro(titulo, sub)
    ax = fig.add_axes([0.1, 0.24, 0.8, 0.56])
    ax.grid(axis="x", visible=False)
    topo = max(max(g[1], g[2]) for g in grupos) * 1.3
    ax.set_ylim(0, topo)
    ax.yaxis.set_major_formatter(lambda v, _: pct(v, 0))
    xs = np.arange(len(grupos)) * 3
    ax.set_xticks(xs + 0.5, [g[0] for g in grupos], fontsize=22)
    objs = []
    for i, (x, (_, mapa, sorteio)) in enumerate(zip(xs, grupos)):
        a = 0.3 if i < apagar else 1
        b1 = ax.bar(x, 0, width=0.9, color=AMBAR, alpha=a)[0]
        b2 = ax.bar(x + 1, 0, width=0.9, color=CINZA, alpha=a)[0]
        t1 = ax.text(x, 0, "", ha="center", fontsize=30, fontweight="bold", color=AMBAR, alpha=a)
        t2 = ax.text(x + 1, 0, "", ha="center", fontsize=30, fontweight="bold", color=NEUTRO, alpha=a)
        objs.append((b1, b2, t1, t2, mapa, sorteio, i < apagar))
    fig.text(0.1, 0.83, "■ maior faixa do mapa", color=AMBAR, fontsize=20)
    fig.text(0.36, 0.83, "■ nível sorteado à mesma distância", color=NEUTRO, fontsize=20)
    n = int(2.2 * FPS)

    def passo(i):
        f = min(1, (i + 1) / n)
        for b1, b2, t1, t2, mapa, sorteio, velho in objs:
            g = 1 if velho else f
            b1.set_height(mapa * g)
            b2.set_height(sorteio * g)
            if g >= 1:
                t1.set_text(pct(mapa))
                t1.set_y(mapa + topo * 0.02)
                t2.set_text(pct(sorteio))
                t2.set_y(sorteio + topo * 0.02)
    animar(fig, passo, n, nome, segura=2.5)


def c11a_calibracao_90d() -> None:
    c = R()["90d"]["calib"]
    _barras("11a_calibracao_90d", [("calibração", c["toque_acima"], c["aleat_acima"])],
            "o preço foi buscar a maior faixa de cima em 24h?", f"primeira metade: {dia(c['inicio'])} a {dia(c['fim'])}")


def c11b_teste_90d() -> None:
    c, t = R()["90d"]["calib"], R()["90d"]["teste"]
    _barras("11b_teste_90d", [("calibração", c["toque_acima"], c["aleat_acima"]),
                              ("teste", t["toque_acima"], t["aleat_acima"])],
            "e na segunda metade?", f"teste: {dia(t['inicio'])} a {dia(t['fim'])}", apagar=1)


def c12_print_perfeito() -> None:
    linhas = R()["90d"]["linhas"]
    alvo = int(datetime(2026, 9, 20, 0, tzinfo=timezone.utc).timestamp() * 1000)   # 19/09, 21h BRT
    l = next(x for x in linhas if x["ts"] == alvo)
    s = {r[0]: r for r in load("Bybit")}
    hs = [s[l["ts"] + k * H] for k in range(-12, 48) if l["ts"] + k * H in s]
    x = np.array([(h[0] - l["ts"]) / H for h in hs])
    fig = quadro("o print perfeito", f"foto de {dia(l['ts'], '%d/%m, %Hh')}: a maior faixa de cima a "
                                     f"+{br(100 * l['acima_dist'], 1)}% do preço")
    ax = fig.add_axes([0.08, 0.22, 0.72, 0.6])
    ax.axhline(l["acima"], color=AMBAR, lw=4)
    ax.text(x[-1] + 1, l["acima"], f"US$ {br(l['acima'])}", color=AMBAR, fontsize=22, fontweight="bold", va="center")
    ax.axvline(0, color=CINZA, lw=1.5, ls="--")
    ax.set_xlim(x[0], x[-1])
    lo, hi = min(h[2] for h in hs), max(h[1] for h in hs)
    ax.set_ylim(lo * 0.995, max(hi, l["acima"]) * 1.004)
    ax.yaxis.set_major_formatter(lambda v, _: "$" + br(v / 1000, 1) + " mil")
    ax.set_xlabel("horas desde a foto", fontsize=18, color=NEUTRO)
    linha, = ax.plot([], [], color=BRANCO, lw=3)
    toque = ax.annotate(f"tocou em {l['h_acima']}h", (l["h_acima"], l["acima"]), xytext=(-40, -70),
                        textcoords="offset points", fontsize=26, color=VERDE, fontweight="bold",
                        arrowprops=dict(arrowstyle="->", color=VERDE, lw=2), alpha=0)
    closes = np.array([h[3] for h in hs])
    n = 6 * FPS

    def passo(i):
        k = max(1, int(len(hs) * (i + 1) / n))
        linha.set_data(x[:k], closes[:k])
        toque.set_alpha(1 if x[k - 1] >= l["h_acima"] else 0)
    animar(fig, passo, n, "12_print_perfeito", segura=2.5)


def c13_linha_tempo_longo() -> None:
    _linha_tempo("13_linha_tempo_longo", "longo", "quase cinco anos de Bitcoin, divididos em dois")


def c14_barras_longo() -> None:
    c, t = R()["longo"]["calib"], R()["longo"]["teste"]
    _barras("14_barras_longo", [("calibração\nacima", c["toque_acima"], c["aleat_acima"]),
                                ("calibração\nabaixo", c["toque_abaixo"], c["aleat_abaixo"]),
                                ("teste\nacima", t["toque_acima"], t["aleat_acima"]),
                                ("teste\nabaixo", t["toque_abaixo"], t["aleat_abaixo"])],
            "e com quase cinco anos?", f"{dia(c['inicio'], '%m/%Y')} a {dia(t['fim'], '%m/%Y')}, "
                                       f"{br(c['n'] + t['n'])} fotos de hora em hora")


def c15_mais_proximo() -> None:
    fig = quadro("a maior faixa de um lado, a mais próxima do outro",
                 "para qual lado o preço foi primeiro?")
    for i, (rod, rot) in enumerate((("90d", "90 dias"), ("longo", "quase 5 anos"))):
        for j, met in enumerate(("calib", "teste")):
            m = R()[rod][met]
            x = 0.1 + j * 0.42
            y = 0.62 - i * 0.24
            ganhou = round(m["discordam"] * (1 - m["disc_maior"]))
            texto = f"{ganhou} de {m['discordam']}" if m["discordam"] < 200 else pct(1 - m["disc_maior"], 0)
            fig.text(x, y, texto, fontsize=64, color=VERDE, fontweight="bold", va="center")
            fig.text(x, y - 0.075, f"{rot}, {'calibração' if met == 'calib' else 'teste'}: foi para a MAIS PRÓXIMA",
                     fontsize=18, color=NEUTRO, va="center")
    salvar(fig, "15_mais_proximo")


def c16_vizinhanca() -> None:
    digitar("16_frase_vizinhanca", "não foi ímã.\n  foi vizinhança.")


def c17_chute_cobra() -> None:
    linhas = [l for l in R()["longo"]["linhas"]]
    d = np.array([100 * l["acima_dist"] for l in linhas] + [100 * l["abaixo_dist"] for l in linhas])
    fig = quadro("o chute cobrou o preço", "a que distância do preço estava a maior faixa, em cada foto")
    ax = fig.add_axes([0.08, 0.24, 0.84, 0.56])
    ax.hist(d[np.abs(d) < 25], bins=np.arange(-25, 25.5, 0.5), color=AMBAR)
    q = (1 / 10 - MM) * 100
    for v in (-q, q):
        ax.axvline(v, color=BRANCO, lw=2, ls="--")
    ax.text(q + 0.4, ax.get_ylim()[1] * 0.85, f"liquidação\ndo 10x: ±{br(q, 1)}%", color=BRANCO, fontsize=20)
    ax.xaxis.set_major_formatter(lambda v, _: ("+" if v > 0 else "") + br(v) + "%")
    ax.set_yticks([])
    fonte(fig, "o 10x leva 40% do peso no chute, então a faixa dele é quase sempre a maior")
    salvar(fig, "17_chute_cobra")


# ---------------------------------------------------------------- fecho

def c18_faixa() -> None:
    digitar("18_frase_faixa", "você é a faixa\n  no mapa de alguém.")


def c19_proximo_video() -> None:
    fig = quadro("o próximo vídeo")
    ax = fig.add_axes([0.08, 0.26, 0.5, 0.56])
    ax.axis("off")
    ax.add_patch(FancyBboxPatch((0, 0), 1, 1, boxstyle="round,pad=0,rounding_size=0.03",
                                transform=ax.transAxes, facecolor=PAINEL, edgecolor=VERDE, lw=3))
    ax.text(0.5, 0.5, "(capa do episódio 1)", ha="center", va="center", fontsize=24, color=CINZA)
    fig.text(0.62, 0.66, "A IA Consegue\nPrever o Preço\nde uma Ação\nAmanhã?", fontsize=40,
             color=BRANCO, fontweight="bold", va="top", linespacing=1.3)
    salvar(fig, "19_proximo_video")


CENAS = {
    "00": c00_mapa_calor, "01": c01_tres_perguntas, "02": c02_ia_corretora, "03": c03_dois_lados,
    "04": c04_escada_alavancagem, "05": c05_mapa_montando, "06": c06_chute_alavancagem,
    "07": c07_tres_corretoras, "08": c08_hyperliquid, "09": c09_linha_tempo_90d,
    "10": c10_sorteio_niveis, "11a": c11a_calibracao_90d, "11b": c11b_teste_90d,
    "12": c12_print_perfeito, "13": c13_linha_tempo_longo, "14": c14_barras_longo,
    "15": c15_mais_proximo, "16": c16_vizinhanca, "17": c17_chute_cobra, "18": c18_faixa,
    "19": c19_proximo_video,
}


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    pedidas = sys.argv[1:] or list(CENAS)
    for k in pedidas:
        CENAS[k]()
    print(f"\n{len(pedidas)} cena(s) em {SAIDA}")


if __name__ == "__main__":
    main()
