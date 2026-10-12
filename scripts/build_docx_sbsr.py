"""Monta docs/artigo/rascunho.docx a partir de docs/artigo/texto.md, na estrutura do template SBSR.

Cópia adaptada de ~/paraopeba_r3_quintais/scripts/build_docx_sbsr.py (12/10/2026) para o artigo do MIRADOURO;
só os caminhos padrão mudaram. O original não foi alterado.

Script de apoio à escrita, fora do pipeline numerado. Uso: python scripts/build_docx_sbsr.py
Modo de diagramação final (template SBSR à risca): python scripts/build_docx_sbsr.py entrada.md saida.docx --final
  → título a 35 mm da borda superior (10 mm de espaço antes), autores 10,5 pt itálico, afiliações 10 pt,
    uma linha em branco (11 pt) antes e depois de cada título de seção, subseções (**n.n. …**) sem recuo
    na margem esquerda, Fig. 1 a 68 mm e figura tripla (fig3_) a 144 mm. O restante é igual ao modo normal.
Entrada: docs/artigo/texto.md (prosa final em markdown restrito — ver convenções abaixo) e as figuras
         referenciadas nele (data/outputs/*.png).
Saída:   docs/artigo/rascunho.docx (Letter, margens do template, título em coluna única,
         corpo em duas colunas de 86 mm com 6 mm entre elas, Times New Roman 10 pt).

Convenções do texto.md:
  '# TÍTULO'                      → título (14 pt, negrito, caixa alta, centrado)
  1ª e 2ª linhas após o título     → autores (centrado) e afiliações (centrado, 9 pt)
  '## Resumo' / '## Abstract'      → cabeçalhos centrados em negrito; o Abstract inteiro em itálico
  '## 1. SEÇÃO'                    → título de seção (negrito, caixa alta, centrado, linha em branco antes/depois)
  parágrafos                       → justificados; 1º parágrafo da seção sem recuo, demais com 0,63 cm
  '**2.1. Subtítulo.** texto'      → subseção embutida (negrito no início do parágrafo)
  '> [SEÇÃO DA COAUTORA: ...]'     → caixa destacada (sombreado + borda)
  '![Figura N. legenda](caminho)'  → imagem na largura da coluna + legenda 9 pt negrito abaixo
  'Tabela N. legenda' + tabela '|' → legenda 9 pt negrito acima + tabela real do Word
  '[n] referência'                 → item de referência com recuo deslocado
  '[quebra de coluna]'             → (só --final) quebra de coluna no início do parágrafo seguinte: equilíbrio da última página
"""
import re
import sys
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Emu, Mm, Pt, Twips

REPO = Path(__file__).resolve().parents[1]
MD = REPO / "docs/artigo/texto.md"
OUT = REPO / "docs/artigo/rascunho.docx"
FONTE = "Times New Roman"
LARGURA_COLUNA = Mm(86)
TAM_CORPO, TAM_LEGENDA, TAM_TABELA, TAM_AFILIACAO = Pt(10), Pt(9), Pt(7), Pt(9)
RECUO = Cm(0.63)
FINAL = False            # ligado por --final (ver docstring)
LINHA_BRANCA = Pt(11.5)   # uma linha em branco (passo de linha do corpo 10 pt ≈ 11,5 pt) antes/depois dos títulos, como no template
RESPIRO = Pt(6)           # respiro uniforme entre texto e figuras/tabelas (modo final)

# ── utilitários de formatação ──────────────────────────────────────────────────────────────
def _fonte(run, tam=TAM_CORPO, negrito=None, italico=None):
    run.font.name = FONTE
    run._element.rPr.rFonts.set(qn("w:eastAsia"), FONTE)
    run.font.size = tam
    if negrito is not None:
        run.font.bold = negrito
    if italico is not None:
        run.font.italic = italico


def _runs(par, texto, tam=TAM_CORPO, italico_base=False, negrito_base=False):
    """Converte ***x***, **x**, *x* em runs."""
    for tok in re.split(r"(\*\*\*.+?\*\*\*|\*\*.+?\*\*|\*.+?\*)", texto):
        if not tok:
            continue
        if tok.startswith("***"):
            r = par.add_run(tok[3:-3]); _fonte(r, tam, True, True)
        elif tok.startswith("**"):
            r = par.add_run(tok[2:-2]); _fonte(r, tam, True, italico_base)
        elif tok.startswith("*"):
            r = par.add_run(tok[1:-1]); _fonte(r, tam, negrito_base, True)
        else:
            r = par.add_run(tok); _fonte(r, tam, negrito_base, italico_base)


def _paragrafo(doc, texto="", alinh=WD_ALIGN_PARAGRAPH.JUSTIFY, tam=TAM_CORPO, recuo=None,
               antes=0, depois=0, italico=False, negrito=False, keep_next=False):
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.alignment = alinh
    pf.space_before, pf.space_after = Pt(antes), Pt(depois)
    pf.line_spacing = 1.0
    if recuo is not None:
        pf.first_line_indent = recuo
    pf.keep_with_next = keep_next
    if texto:
        _runs(p, texto, tam, italico, negrito)
    return p


def _sombrear(p, cor="FFF2CC", borda="BF9000"):
    pPr = p._p.get_or_add_pPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear"); shd.set(qn("w:color"), "auto"); shd.set(qn("w:fill"), cor)
    pPr.append(shd)
    bdr = OxmlElement("w:pBdr")
    for lado in ("top", "left", "bottom", "right"):
        el = OxmlElement(f"w:{lado}")
        el.set(qn("w:val"), "single"); el.set(qn("w:sz"), "6"); el.set(qn("w:space"), "3"); el.set(qn("w:color"), borda)
        bdr.append(el)
    pPr.append(bdr)


def _colunas(section, n, espaco_twips=346):
    sectPr = section._sectPr
    for c in sectPr.findall(qn("w:cols")):
        sectPr.remove(c)
    cols = OxmlElement("w:cols")
    cols.set(qn("w:num"), str(n)); cols.set(qn("w:space"), str(espaco_twips)); cols.set(qn("w:equalWidth"), "1")
    # w:cols deve vir antes de w:docGrid / w:titlePg na ordem do esquema; inserir após pgMar
    pgMar = sectPr.find(qn("w:pgMar"))
    pgMar.addnext(cols)


def _pagina(section):
    section.page_width, section.page_height = Twips(12240), Twips(15840)      # Letter, como o template
    section.left_margin = section.right_margin = Twips(1080)                 # 19 mm
    section.top_margin = section.bottom_margin = Twips(1411)                 # 24,9 mm
    section.header_distance = section.footer_distance = Twips(0)


def _celula(cell, texto, tam=TAM_TABELA, negrito=False, alinh=WD_ALIGN_PARAGRAPH.CENTER):
    cell.text = ""
    p = cell.paragraphs[0]
    p.paragraph_format.alignment = alinh
    p.paragraph_format.space_before = p.paragraph_format.space_after = Pt(0)
    _runs(p, texto, tam, negrito_base=negrito)
    tcPr = cell._tc.get_or_add_tcPr()
    mar = OxmlElement("w:tcMar")
    for lado, v in (("top", 5), ("bottom", 5), ("left", 40), ("right", 40)):
        el = OxmlElement(f"w:{lado}"); el.set(qn("w:w"), str(v)); el.set(qn("w:type"), "dxa"); mar.append(el)
    tcPr.append(mar)


def _tabela(doc, legenda, linhas):
    _paragrafo(doc, legenda, WD_ALIGN_PARAGRAPH.CENTER, TAM_LEGENDA, antes=(RESPIRO.pt if FINAL else 4), depois=2,
               negrito=True, keep_next=True)
    cab = [c.strip() for c in linhas[0].strip("|").split("|")]
    corpo = [[c.strip() for c in l.strip("|").split("|")] for l in linhas[2:]]
    t = doc.add_table(rows=1 + len(corpo), cols=len(cab))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.autofit = False
    # larguras fixas somando a largura da coluna de texto: colunas numéricas pela célula mais longa do
    # corpo (≈1,45 mm por caractere a 7,5 pt + margens; o cabeçalho pode quebrar linha), e a primeira
    # coluna (nomes) fica com o restante
    # ≈1,25 mm por caractere a 7 pt + 2,5 mm de margens, piso 8,5 mm: sobra para nomes longos na 1ª coluna
    mm_num = [max(8.5, max(len(re.sub(r"\*", "", l[j])) for l in corpo) * 1.25 + 2.5) for j in range(1, len(cab))]
    primeira = max(14.0, LARGURA_COLUNA.mm - sum(mm_num))
    larguras = [Mm(primeira)] + [Mm(w) for w in mm_num]
    if sum(w.mm for w in larguras) > LARGURA_COLUNA.mm + 0.01:      # colunas de texto: redistribui e deixa quebrar linha
        tot = sum(len(re.sub(r"\*", "", l[j])) for l in tudo for j in range(len(cab))) if (tudo := [cab] + corpo) else 1
        peso = [max(8.0, sum(len(re.sub(r"\*", "", l[j])) for l in tudo) ** 0.7) for j in range(len(cab))]
        larguras = [Mm(LARGURA_COLUNA.mm * w / sum(peso)) for w in peso]
    tblPr = t._tbl.tblPr
    lay = OxmlElement("w:tblLayout"); lay.set(qn("w:type"), "fixed"); tblPr.append(lay)
    # python-docx cria a grade com a largura da página inteira; a grade e a largura total precisam
    # refletir a coluna de texto, senão o LibreOffice/Word desenham a tabela larga demais
    for gc, w in zip(t._tbl.tblGrid.findall(qn("w:gridCol")), larguras):
        gc.set(qn("w:w"), str(int(w.twips)))
    tblW = tblPr.find(qn("w:tblW"))
    if tblW is None:
        tblW = OxmlElement("w:tblW"); tblPr.append(tblW)
    tblW.set(qn("w:type"), "dxa"); tblW.set(qn("w:w"), str(int(sum(w.twips for w in larguras))))
    for j, c in enumerate(cab):
        _celula(t.rows[0].cells[j], c, negrito=True)
    for i, linha in enumerate(corpo, start=1):
        for j, c in enumerate(linha):
            _celula(t.rows[i].cells[j], c, alinh=WD_ALIGN_PARAGRAPH.LEFT if j == 0 else WD_ALIGN_PARAGRAPH.CENTER)
    for i, row in enumerate(t.rows):
        trPr = row._tr.get_or_add_trPr()
        cs = OxmlElement("w:cantSplit"); trPr.append(cs)           # linha nunca quebra entre páginas/colunas
        for j, cell in enumerate(row.cells):
            cell.width = larguras[j]
            if i < len(t.rows) - 1:                                  # tabela inteira numa só coluna
                cell.paragraphs[0].paragraph_format.keep_with_next = True
    if FINAL:                                       # respiro após a tabela igual ao das figuras: parágrafo de 1 pt + 6 pt
        p = doc.add_paragraph(); pf = p.paragraph_format
        pf.space_before, pf.space_after, pf.line_spacing = Pt(0), RESPIRO, Pt(1)
        _fonte(p.add_run(" "), Pt(1))
    else:
        _paragrafo(doc, "", depois=2)


LARGURA_DUPLA = Mm(120)


def _figura_dupla(doc, legenda, caminho):
    """Figura atravessando as duas colunas: seção contínua de 1 coluna só para a figura e a legenda."""
    s1 = doc.add_section(WD_SECTION.CONTINUOUS); _pagina(s1); _colunas(s1, 1)
    p = doc.add_paragraph()
    p.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before, p.paragraph_format.space_after = (RESPIRO if FINAL else Pt(2)), Pt(2)
    p.paragraph_format.keep_with_next = True
    # figuras marcadas "_dupla" foram desenhadas a 178 mm com fontes ≥ 7 pt: entram quase no tamanho real
    p.add_run().add_picture(str(caminho), width=Mm(170) if "_dupla" in Path(caminho).name else (Mm(144) if FINAL else LARGURA_DUPLA))
    _paragrafo(doc, legenda, WD_ALIGN_PARAGRAPH.CENTER, TAM_LEGENDA, depois=(RESPIRO.pt if FINAL else 2), negrito=True)
    s2 = doc.add_section(WD_SECTION.CONTINUOUS); _pagina(s2); _colunas(s2, 2)


def _figura(doc, legenda, caminho):
    if "fig3_" in Path(caminho).name or "_dupla" in Path(caminho).name:   # largura dupla (painel triplo / figuras marcadas)
        return _figura_dupla(doc, legenda, caminho)
    p = doc.add_paragraph()
    p.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before, p.paragraph_format.space_after = (RESPIRO if FINAL else Pt(4)), Pt(2)
    p.paragraph_format.keep_with_next = True
    # a Fig. 1 (mapa, formato retrato) entra um pouco mais estreita para não dominar a coluna
    largura = Mm(56) if "fig1_" in Path(caminho).name else Mm(70)   # Fig. 1 desenhada para a coluna; 78 mm mantém ≥ 6,5 pt
    if FINAL and "fig1_" in Path(caminho).name:
        largura = Mm(68)
    p.add_run().add_picture(str(caminho), width=largura)
    _paragrafo(doc, legenda, WD_ALIGN_PARAGRAPH.CENTER, TAM_LEGENDA, depois=(RESPIRO.pt if FINAL else 2), negrito=True)


# ── leitura do markdown restrito ───────────────────────────────────────────────────────────
def blocos(md: str):
    """Gera (tipo, conteúdo) a partir do texto.md."""
    linhas = md.splitlines()
    i = 0
    while i < len(linhas):
        l = linhas[i]
        if not l.strip():
            i += 1; continue
        if l.startswith("# "):
            yield "titulo", l[2:].strip()
        elif l.startswith("## "):
            yield "secao", l[3:].strip()
        elif l.startswith("> "):
            yield "caixa", l[2:].strip()
        elif l.strip() == "[quebra de coluna]":
            yield "quebra_coluna", None
        elif l.startswith("!["):
            m = re.match(r"!\[(.+?)\]\((.+?)\)", l)
            yield "figura", (m.group(1), m.group(2))
        elif re.match(r"^Tabela \d+\.", l):
            k = i + 1                                  # a tabela pode vir após linha(s) em branco
            while k < len(linhas) and not linhas[k].strip():
                k += 1
            if k < len(linhas) and linhas[k].startswith("|"):
                j = k
                while j < len(linhas) and linhas[j].startswith("|"):
                    j += 1
                yield "tabela", (l.strip(), linhas[k:j])
                i = j; continue
            yield "paragrafo", l.strip()
        elif re.match(r"^\[\d+\] ", l):
            yield "referencia", l.strip()
        else:
            yield "paragrafo", l.strip()
        i += 1


def main() -> None:
    global MD, OUT, FINAL
    args = [a for a in sys.argv[1:] if a != "--final"]
    FINAL = "--final" in sys.argv
    if args:                         # uso alternativo: build_docx_sbsr.py entrada.md saida.docx [--final]
        MD = Path(args[0]); OUT = Path(args[1]) if len(args) > 1 else OUT
    md = MD.read_text(encoding="utf-8")
    doc = Document()
    est = doc.styles["Normal"]
    est.font.name = FONTE; est.font.size = TAM_CORPO
    est.element.rPr.rFonts.set(qn("w:eastAsia"), FONTE)
    _pagina(doc.sections[0])
    _colunas(doc.sections[0], 1)

    cabecalho = 0            # 0 = título ainda não lido, 1 = autores, 2 = afiliações, 3 = corpo
    em_abstract = False
    primeiro_da_secao = True
    duas_colunas = False
    quebra_pendente = False
    for tipo, cont in blocos(md):
        if tipo == "titulo":
            # modo final: 10 mm (28 pt) de espaço antes → topo do título a 35 mm da borda (margem de 25 mm)
            p = _paragrafo(doc, cont, WD_ALIGN_PARAGRAPH.CENTER, Pt(14), antes=28 if FINAL else 0, depois=10 if FINAL else 4,
                           negrito=True)
            cabecalho = 1
        elif tipo == "paragrafo" and cabecalho == 1:
            _paragrafo(doc, cont, WD_ALIGN_PARAGRAPH.CENTER, Pt(10.5) if FINAL else TAM_CORPO, depois=6 if FINAL else 4,
                       italico=FINAL); cabecalho = 2
        elif tipo == "paragrafo" and cabecalho == 2:
            _paragrafo(doc, cont, WD_ALIGN_PARAGRAPH.CENTER, TAM_CORPO if FINAL else TAM_AFILIACAO,
                       depois=LINHA_BRANCA.pt if FINAL else 4); cabecalho = 3
        elif tipo == "secao":
            if not duas_colunas:                       # o corpo (a partir do Resumo) vai em duas colunas
                s = doc.add_section(WD_SECTION.CONTINUOUS); _pagina(s); _colunas(s, 2); duas_colunas = True
            em_abstract = cont.lower().startswith("abstract")
            texto = cont if cont[0].isdigit() or cont.isupper() else cont
            if FINAL:                                  # linha em branco antes e depois (o Resumo já está no topo da coluna)
                antes, depois = (0 if cont.lower().startswith("resumo") else LINHA_BRANCA.pt), LINHA_BRANCA.pt
            else:
                antes, depois = 2, 1
            _paragrafo(doc, texto, WD_ALIGN_PARAGRAPH.CENTER, TAM_CORPO, antes=antes, depois=depois, negrito=True,
                       italico=em_abstract, keep_next=True)
            primeiro_da_secao = True
        elif tipo == "paragrafo":
            recuo = None if primeiro_da_secao else RECUO
            if FINAL and re.match(r"^\*\*\d+\.\d+\.", cont):   # subseção embutida: negrito na margem esquerda
                recuo = None
            p = _paragrafo(doc, cont, WD_ALIGN_PARAGRAPH.JUSTIFY, TAM_CORPO, recuo=recuo, italico=em_abstract)
            if quebra_pendente:                    # quebra no INÍCIO deste parágrafo: sem linha vazia no topo da coluna
                r = p.add_run(); r.add_break(WD_BREAK.COLUMN)
                p._p.get_or_add_pPr().addnext(r._r)
                quebra_pendente = False
            primeiro_da_secao = False
        elif tipo == "quebra_coluna":              # equilíbrio manual da última página (o LibreOffice não
            quebra_pendente = FINAL                # equilibra colunas de seção final); ignorado fora do modo final
        elif tipo == "caixa":
            p = _paragrafo(doc, cont, WD_ALIGN_PARAGRAPH.JUSTIFY, TAM_CORPO, antes=4, depois=4, italico=True)
            _sombrear(p); primeiro_da_secao = False
        elif tipo == "figura":
            legenda, caminho = cont
            _figura(doc, legenda, REPO / caminho)
        elif tipo == "tabela":
            legenda, linhas = cont
            _tabela(doc, legenda, linhas)
        elif tipo == "referencia":
            p = _paragrafo(doc, cont, WD_ALIGN_PARAGRAPH.JUSTIFY, TAM_CORPO, depois=1)
            p.paragraph_format.left_indent = Cm(0.6); p.paragraph_format.first_line_indent = Cm(-0.6)
    doc.save(OUT)
    print(f"OK → {OUT}")


if __name__ == "__main__":
    sys.exit(main())
