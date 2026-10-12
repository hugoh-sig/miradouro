"""Composição de painéis PNG: grades de imagens, marcação do pixel alvo, textos."""

from __future__ import annotations

import io
from collections.abc import Sequence
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

FUNDO = (252, 252, 251)
TINTA = (11, 11, 11)
TINTA_SECUNDARIA = (82, 81, 78)
COR_ALVO = (255, 230, 0)  # pixel alvo
COR_JANELA = (255, 255, 255)  # janela 3×3
MARGEM = 12


@lru_cache(maxsize=8)
def fonte(tamanho: int = 14, negrito: bool = False) -> ImageFont.ImageFont:
    """DejaVu Sans (vem com o matplotlib); recua para a fonte padrão do PIL."""
    try:
        from matplotlib import font_manager

        nome = "DejaVu Sans:bold" if negrito else "DejaVu Sans"
        caminho = font_manager.findfont(font_manager.FontProperties(family=nome.split(":")[0], weight="bold" if negrito else "normal"), fallback_to_default=True)
        return ImageFont.truetype(caminho, tamanho)
    except Exception:  # pragma: no cover — ambiente sem matplotlib/fontes
        return ImageFont.load_default()


def para_png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def ampliar(img: Image.Image, fator: int) -> Image.Image:
    """Amplia por vizinho mais próximo (mantém os pixels como blocos)."""
    if fator <= 1:
        return img
    return img.resize((img.width * fator, img.height * fator), Image.Resampling.NEAREST)


def marcar_pixel_alvo(
    img: Image.Image,
    centro_px: tuple[float, float],
    lado_px: float,
    janela: int = 3,
    cor_alvo: tuple[int, int, int] = COR_ALVO,
    cor_janela: tuple[int, int, int] = COR_JANELA,
) -> Image.Image:
    """Desenha o contorno do pixel alvo (``lado_px``) e da janela ``janela``×``janela`` ao redor.

    Não preenche nada: o intérprete precisa ver o conteúdo do pixel.
    """
    d = ImageDraw.Draw(img)
    cx, cy = centro_px
    meio = lado_px / 2
    if janela and janela > 1:
        mj = lado_px * janela / 2
        d.rectangle([cx - mj, cy - mj, cx + mj, cy + mj], outline=cor_janela, width=2)
    d.rectangle([cx - meio, cy - meio, cx + meio, cy + meio], outline=cor_alvo, width=2)
    return img


def marcar_poligono(img: Image.Image, pontos: Sequence[tuple[float, float]], cor=COR_ALVO, largura: int = 2) -> Image.Image:
    d = ImageDraw.Draw(img)
    pts = [tuple(p) for p in pontos]
    d.polygon(pts, outline=cor, width=largura)
    return img


def barra_escala(img: Image.Image, metros_por_px: float, metros: float | None = None) -> Image.Image:
    """Barra de escala no canto inferior esquerdo."""
    if metros is None:
        alvo = img.width * metros_por_px / 4
        for m in (10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000):
            if m >= alvo:
                metros = m
                break
        else:
            metros = 5000
    px = metros / metros_por_px
    d = ImageDraw.Draw(img)
    x0, y0 = 10, img.height - 14
    d.rectangle([x0 - 4, y0 - 18, x0 + px + 4, y0 + 6], fill=(0, 0, 0, 140))
    d.line([x0, y0, x0 + px, y0], fill=(255, 255, 255), width=3)
    d.text((x0, y0 - 17), f"{int(metros)} m", fill=(255, 255, 255), font=fonte(12))
    return img


def rotular(img: Image.Image, texto: str | Sequence[str], fonte_tamanho: int = 13) -> Image.Image:
    """Faixa de rótulo no topo da imagem (fundo escuro semitransparente); aceita várias linhas."""
    linhas = [texto] if isinstance(texto, str) else list(texto)
    base = img.convert("RGBA")
    camada = Image.new("RGBA", base.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(camada)
    f = fonte(fonte_tamanho)
    passo = fonte_tamanho + 4
    altura = passo * len(linhas) + 6
    d.rectangle([0, 0, base.width, altura], fill=(0, 0, 0, 150))
    for i, linha in enumerate(linhas):
        d.text((6, 4 + i * passo), linha, fill=(255, 255, 255), font=f)
    return Image.alpha_composite(base, camada).convert("RGB")


def compor_grade(
    tiles: Sequence[Image.Image],
    colunas: int,
    titulo: str,
    subtitulo: str = "",
    rodape: Sequence[str] = (),
    espaco: int = 8,
) -> Image.Image:
    """Monta os tiles numa grade com título, subtítulo e linhas de rodapé."""
    if not tiles:
        raise ValueError("compor_grade precisa de pelo menos um tile")
    colunas = max(1, min(colunas, len(tiles)))
    linhas = -(-len(tiles) // colunas)
    lw = max(t.width for t in tiles)
    lh = max(t.height for t in tiles)
    f_titulo, f_sub, f_rodape = fonte(18, negrito=True), fonte(13), fonte(11)
    cabecalho = 30 + (20 if subtitulo else 0)
    alt_rodape = 16 * len(rodape) + (6 if rodape else 0)
    largura = MARGEM * 2 + colunas * lw + (colunas - 1) * espaco
    altura = MARGEM * 2 + cabecalho + linhas * lh + (linhas - 1) * espaco + alt_rodape
    painel = Image.new("RGB", (largura, altura), FUNDO)
    d = ImageDraw.Draw(painel)
    d.text((MARGEM, MARGEM), titulo, fill=TINTA, font=f_titulo)
    if subtitulo:
        d.text((MARGEM, MARGEM + 26), subtitulo, fill=TINTA_SECUNDARIA, font=f_sub)
    y0 = MARGEM + cabecalho
    for i, t in enumerate(tiles):
        c, r = i % colunas, i // colunas
        painel.paste(t, (MARGEM + c * (lw + espaco), y0 + r * (lh + espaco)))
    y = y0 + linhas * lh + (linhas - 1) * espaco + 6
    for linha in rodape:
        d.text((MARGEM, y), linha, fill=TINTA_SECUNDARIA, font=f_rodape)
        y += 16
    return painel


def tile_de_erro(largura: int, altura: int, mensagem: str) -> Image.Image:
    """Tile cinza com mensagem (ex.: estação sem cenas). Mantém o painel legível."""
    img = Image.new("RGB", (largura, altura), (200, 200, 200))
    d = ImageDraw.Draw(img)
    d.text((10, altura // 2 - 8), mensagem, fill=TINTA, font=fonte(13))
    return img
