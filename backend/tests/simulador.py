"""Cartmaster (Firebird) simulado para os testes. Nada aqui conecta no banco real."""
from datetime import date


class FakeCursor:
    def __init__(self, fb):
        self.fb = fb
        self._rows = []
        self.description = []

    def execute(self, sql, params=()):
        self.fb.log.append((" ".join(sql.split()), tuple(params)))
        for trecho, resposta in self.fb.respostas:
            if trecho in sql:
                self._rows = list(resposta(params) if callable(resposta) else resposta)
                return
        raise AssertionError(f"Consulta sem resposta simulada: {' '.join(sql.split())[:120]}")

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows


class FakeFirebird:
    """respostas: lista de (trecho do SQL, linhas | função(params) -> linhas)."""

    def __init__(self, respostas):
        self.respostas = respostas
        self.log = []
        self.commits = 0
        self.closed = False

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass

    def close(self):
        self.closed = True

    def sqls(self, trecho=""):
        return [sql for sql, _ in self.log if trecho in sql]


class Resp:
    """Resposta HTTP simulada (requests)."""

    def __init__(self, dados, status=200):
        self._dados, self.status_code = dados, status

    def json(self):
        return self._dados


def data_fixa(monkeypatch, api, dia):
    """Faz date.today() devolver `dia` dentro do api.py."""
    class Hoje(date):
        @classmethod
        def today(cls):
            return dia
    monkeypatch.setattr(api, "date", Hoje)


def usar_firebird(monkeypatch, api, fb):
    monkeypatch.setattr(api, "get_db_connection", lambda: fb)
    return fb
