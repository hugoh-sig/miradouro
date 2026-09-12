"""Exceções do MIRADOURO. Todas herdam de :class:`ErroMiradouro`."""


class ErroMiradouro(Exception):
    """Erro genérico do MIRADOURO."""


class ErroProjeto(ErroMiradouro):
    """O ``projeto.yaml`` está ausente, malformado ou inconsistente."""


class ErroPontos(ErroMiradouro):
    """O ``pontos.csv`` está ausente, malformado ou inconsistente."""


class ErroRespostas(ErroMiradouro):
    """Falha ao validar, gravar ou ler respostas."""


class ErroArquivoCorrompido(ErroRespostas):
    """O arquivo de respostas existe mas não pôde ser lido (JSON inválido ou formato desconhecido)."""
