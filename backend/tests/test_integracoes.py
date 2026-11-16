"""Geocode (mapa) e otimização de rota: cache, timeouts e alternativas quando o Google falha."""
from simulador import Resp


def test_geocode_cascata_cache_e_posicao_antiga(api, cliente, admin, monkeypatch):
    chamadas = []

    def get_google_lento(url, params=None, headers=None, timeout=None):
        chamadas.append((url, timeout))
        if "googleapis" in url:
            raise api.requests.exceptions.Timeout("simulado")
        if "nominatim" in url:
            assert params.get("countrycodes") == "br"
            return Resp([{"lat": "-23.5", "lon": "-46.6", "place_id": 9}])
        raise AssertionError(url)

    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "chave-falsa")
    monkeypatch.setattr(api.requests, "get", get_google_lento)
    r = cliente.get("/api/geocode", query_string={"id_cliente": "5", "endereco": "Rua A, 10, Santo André"}, headers=admin)
    assert r.status_code == 200 and r.get_json()["lat"] == -23.5, "Google com timeout cai para o Nominatim"
    assert all(timeout for _, timeout in chamadas), "toda chamada externa tem timeout"

    n = len(chamadas)
    r = cliente.get("/api/geocode", query_string={"id_cliente": "5", "endereco": "rua a,  10, SANTO ANDRÉ"}, headers=admin)
    assert r.get_json()["cached"] is True and len(chamadas) == n, "mesmo endereço usa o cache"

    def get_fora_do_ar(url, params=None, headers=None, timeout=None):
        chamadas.append((url, timeout))
        raise api.requests.exceptions.ConnectionError("fora do ar")

    monkeypatch.setattr(api.requests, "get", get_fora_do_ar)
    r = cliente.get("/api/geocode", query_string={"id_cliente": "5", "endereco": "Rua B, 20, 09000-000"}, headers=admin)
    assert r.get_json()["desatualizado"] is True and len(chamadas) > n, "endereço novo consulta; se falhar, usa a posição antiga"


def test_rota_usa_osrm_quando_google_falha(api, cliente, admin, monkeypatch):
    def post_google(*a, **k):
        assert k.get("timeout")
        raise api.requests.exceptions.Timeout("simulado")

    def get_osrm(url, timeout=None, **k):
        assert timeout and url.startswith("https://router.project-osrm.org")
        return Resp({"code": "Ok", "trips": [{"geometry": ""}],
                     "waypoints": [{"waypoint_index": 0}, {"waypoint_index": 2}, {"waypoint_index": 1}]})

    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "chave-falsa")
    monkeypatch.setattr(api.requests, "post", post_google)
    monkeypatch.setattr(api.requests, "get", get_osrm)
    r = cliente.post("/api/optimize_route", headers=admin, json={"pedidos": [
        {"id": "A", "lat": -23.6, "lng": -46.5}, {"id": "B", "lat": -23.7, "lng": -46.4}]})
    d = r.get_json()
    assert r.status_code == 200
    assert d["ordem_entregas"] == ["B", "A"] and d["lifo_entregas"] == ["A", "B"]


def test_rastreamento_foi_removido(api):
    assert "obter_rastreamento" not in api.app.view_functions
