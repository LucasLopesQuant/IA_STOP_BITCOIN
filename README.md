# IA que busca stop no Bitcoin

O código do vídeo **"IA que Busca Stop no Bitcoin (Cuidado)"**. Ele estima onde estão as
liquidações de quem opera Bitcoin alavancado (o "mapa de liquidação") e testa a frase que
todo mundo repete: **"o preço vai buscar o stop"**.

Spoiler: em quase 5 anos de dados, a maior faixa do mapa não foi tocada mais vezes que um
nível sorteado à mesma distância. O preço foi para a faixa **mais próxima**, não para a
**maior**. Não foi ímã, foi vizinhança.

> Conteúdo educacional. Nada aqui é recomendação de investimento.

## Como o mapa é montado

1. Pega o open interest e o preço de hora em hora na **Binance, Bybit e OKX** (APIs
   públicas, sem chave).
2. Quando o open interest sobe, alguém abriu posição naquele preço. O modelo espalha essa
   posição em 4 alavancagens (40% em 10x, 30% em 25x, 20% em 50x e 10% em 100x) e calcula
   onde cada uma seria liquidada: `entrada × (1 ∓ (1/alavancagem − 0,5%))`.
3. A faixa some quando o preço passa por ela ou quando o open interest cai.
4. Para conferir com posições reais, `hyperliquid.py` lê as maiores contas da Hyperliquid,
   que são públicas on-chain (o arquivo salvo não guarda endereço nenhum).

## O teste

`backtest.py` tira uma foto do mapa a cada hora, **sem olhar o futuro**, e pergunta: a
maior faixa foi tocada nas 24 horas seguintes? A comparação é com um nível sorteado à mesma
distância do preço. Os dados são divididos em duas metades (calibração e teste), e nada foi
ajustado entre uma e outra.

| quase 5 anos (41.705 fotos) | calibração 2022 a 05/2024 | teste 05/2024 a 10/2026 |
|---|---|---|
| maior faixa de cima tocada em 24h | 6,3% | 5,4% |
| nível sorteado à mesma distância | 6,6% | 6,1% |
| maior faixa de baixo tocada em 24h | 4,3% | 3,6% |
| nível sorteado à mesma distância | 4,2% | 3,1% |
| maior e mais próxima em lados opostos: o preço foi na mais próxima | 96,0% | 98,2% |

## Como rodar

```bash
pip install -r requirements.txt
python historico.py      # uma vez: histórico desde 2022 (Binance por arquivo público, Bybit pela API)
python store.py          # atualiza os dados (pode rodar de hora em hora)
python backtest.py       # o teste acima, com resumo no terminal e data/backtest.csv
python mapa.py           # página data/mapa.html com o mapa de calor dos últimos 90 dias
python agora.py          # foto de agora: modelo + posições reais da Hyperliquid (~4 min)
python test_liq_map.py   # testes do modelo
```

Outros arquivos:

| arquivo | o que faz |
|---|---|
| `exchanges.py` | os adaptadores da Binance, Bybit e OKX, com retry |
| `liq_map.py` | o modelo de liquidação |
| `btc_curto_prazo.py` | painel rápido: funding, open interest, preço |
| `hyper_snapshot.py` | salva as posições da Hyperliquid em CSV, sem endereço |
| `imagens.py` | dataset de imagens candle a candle com as faixas |
| `cenas.py` | as imagens e animações do vídeo, em `cenas/` (precisa de ffmpeg para os mp4) |

Os números exatos mudam conforme a data em que você baixa os dados. A rodada de 90 dias do
vídeo está congelada no `cenas.py` (de 09/07 a 07/10/2026).
