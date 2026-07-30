import React, { useState, useEffect, useRef, useCallback } from 'react'
import axios from 'axios'
import { MapContainer, TileLayer, Marker, Popup, Polyline, useMap } from 'react-leaflet'
import L from 'leaflet'

import markerIcon from 'leaflet/dist/images/marker-icon.png'
import markerShadow from 'leaflet/dist/images/marker-shadow.png'

let DefaultIcon = L.icon({
  iconUrl: markerIcon,
  shadowUrl: markerShadow,
  iconSize: [25, 41],
  iconAnchor: [12, 41]
});
L.Marker.prototype.options.icon = DefaultIcon;

const COORDENADAS_EMPRESA = [-23.6939, -46.5650]

// Componente para corrigir a renderização do Leaflet ao trocar de aba
function RedimensionarMapa() {
  const map = useMap();
  useEffect(() => {
    setTimeout(() => {
      map.invalidateSize();
    }, 100);
  }, [map]);
  return null;
}

function App() {
  const [pedidos, setPedidos] = useState([])
  const [carregando, setCarregando] = useState(true)
  const [abaAtiva, setAbaAtiva] = useState('mapa') 
  const [pedidosSelecionados, setPedidosSelecionados] = useState([]) 
  const [rotaIdaGeometria, setRotaIdaGeometria] = useState([]) 
  const [rotaVoltaGeometria, setRotaVoltaGeometria] = useState([]) 
  const [ordemEntregas, setOrdemEntregas] = useState([]) 

  // ESTADOS PARA OS SUMÁRIOS DAS APIS
  const [resumoPedidos, setResumoPedidos] = useState({
    faturamento_acumulado: 0,
    volume_carga_total_kg: 0,
    pedidos_ativos: 0
  })

  const [resumoMapa, setResumoMapa] = useState({
    faturamento_pronto: 0,
    peso_pronto_kg: 0,
    peso_entregue_mes_kg: 30965
  })

  // ESTADOS DE ORDENAÇÃO E EXIBIÇÃO
  const [ordenarPor, setOrdenarPor] = useState('prazo') 
  const [ordem, setOrdem] = useState('asc') 
  const [modoExibicao, setModoExibicao] = useState('lista') // 'lista' ou 'grade'

  // ESTADOS PARA EXPANSÃO DE PEDIDOS E STATUS INDIVIDUAL DE OFs (EM MEMÓRIA)
  const [pedidosExpandidos, setPedidosExpandidos] = useState([])
  const [statusOfs, setStatusOfs] = useState({})

  const abortControllerOSRM = useRef(null)

  // FUNÇÃO AUXILIAR PARA FORMATAR PESO EM KG (INTEIRO)
  const formatarKg = (valor) => {
    if (!valor || isNaN(valor)) return '0'
    return Math.round(valor).toLocaleString('pt-BR')
  }

  // FUNÇÃO PARA BUSCAR PEDIDOS
  const carregarPedidos = useCallback((silencioso = false) => {
    if (!silencioso) setCarregando(true)
    axios.get(`http://localhost:5000/api/pedidos?ordenar_por=${ordenarPor}&ordem=${ordem}`)
      .then(response => {
        setPedidos(Array.isArray(response.data) ? response.data : [])
        if (!silencioso) setCarregando(false)
      })
      .catch(error => {
        console.error("Erro ao buscar pedidos da API:", error)
        if (!silencioso) setCarregando(false)
      })
  }, [ordenarPor, ordem])

  // FUNÇÃO PARA BUSCAR OS RESUMOS/INDICADORES DAS DUAS TELAS
  const carregarResumos = useCallback(() => {
    Promise.all([
      axios.get('http://localhost:5000/api/resumo/pedidos'),
      axios.get('http://localhost:5000/api/resumo/mapa')
    ]).then(([resPedidos, resMapa]) => {
      const dadosPedidos = resPedidos.data || {}
      const dadosMapa = resMapa.data || {}

      setResumoPedidos({
        ...dadosPedidos,
        volume_carga_total_kg: dadosPedidos.volume_carga_total_kg ?? ((dadosPedidos.volume_carga_total_ton || 0) * 1000)
      })

      setResumoMapa({
        ...dadosMapa,
        peso_pronto_kg: dadosMapa.peso_pronto_kg ?? ((dadosMapa.peso_pronto_ton || 0) * 1000),
        peso_entregue_mes_kg: 30965
      })
    }).catch(error => {
      console.error("Erro ao carregar indicadores de resumo:", error)
    })
  }, [])

  useEffect(() => {
    carregarPedidos()
    carregarResumos()

    const intervalId = setInterval(() => {
      carregarPedidos(true)
      carregarResumos()
    }, 5000)

    return () => clearInterval(intervalId)
  }, [carregarPedidos, carregarResumos])

  const calcularDistancia = (coord1, coord2) => {
    if (!coord1 || !coord2) return 0;
    const R = 6371; 
    const dLat = (coord2[0] - coord1[0]) * Math.PI / 180;
    const dLon = (coord2[1] - coord1[1]) * Math.PI / 180;
    const a = 
      Math.sin(dLat/2) * Math.sin(dLat/2) +
      Math.cos(coord1[0] * Math.PI / 180) * Math.cos(coord2[0] * Math.PI / 180) * Math.sin(dLon/2) * Math.sin(dLon/2);
    const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
    return R * c;
  }

  const calcularRotaOtimizada = useCallback(async (idsSelecionados) => {
    if (!idsSelecionados || idsSelecionados.length === 0) {
      setRotaIdaGeometria([]);
      setRotaVoltaGeometria([]);
      setOrdemEntregas([]);
      return;
    }

    const pedidosParaRota = pedidos.filter(p => p && idsSelecionados.includes(p.id) && p.latitude && p.longitude);

    if (pedidosParaRota.length === 0) {
      setRotaIdaGeometria([]);
      setRotaVoltaGeometria([]);
      setOrdemEntregas([]);
      return;
    }

    if (abortControllerOSRM.current) {
      abortControllerOSRM.current.abort();
    }
    abortControllerOSRM.current = new AbortController();

    try {
      let coordenadasString = `${COORDENADAS_EMPRESA[1]},${COORDENADAS_EMPRESA[0]}`;
      
      pedidosParaRota.forEach(p => {
        coordenadasString += `;${p.longitude},${p.latitude}`;
      });

      const url = `https://router.project-osrm.org/trip/v1/driving/${coordenadasString}?overview=full&geometries=geojson&source=first&destination=any`;
      
      const res = await axios.get(url, { signal: abortControllerOSRM.current.signal });
      
      if (res.data.trips && res.data.trips.length > 0) {
        const coordenadasInvertidas = res.data.trips[0].geometry.coordinates.map(coord => [coord[1], coord[0]]);
        const waypoints = res.data.waypoints;
        
        const waypointsOrdenados = [...waypoints]
          .sort((a, b) => a.waypoint_index - b.waypoint_index)
          .filter(wp => wp.waypoint_index !== 0);

        const ordemCalculada = waypointsOrdenados
          .map(wp => {
            const idxOriginal = wp.trips_index !== undefined ? wp.trips_index : wp.waypoint_index;
            return pedidosParaRota[idxOriginal - 1] ? pedidosParaRota[idxOriginal - 1].id : null;
          })
          .filter(id => id !== null); 

        setOrdemEntregas(ordemCalculada);

        const ultimoPedidoId = ordemCalculada[ordemCalculada.length - 1];
        const ultimoPedido = pedidosParaRota.find(p => p.id === ultimoPedidoId);

        if (ultimoPedido) {
          const coordUltimoCliente = [ultimoPedido.latitude, ultimoPedido.longitude];
          
          let indiceCorte = 0;
          let menorDistancia = Infinity;

          coordenadasInvertidas.forEach((coord, index) => {
            const dist = calcularDistancia(coord, coordUltimoCliente);
            if (dist < menorDistancia) {
              menorDistancia = dist;
              indiceCorte = index;
            }
          });

          setRotaIdaGeometria(coordenadasInvertidas.slice(0, indiceCorte + 1));
          setRotaVoltaGeometria(coordenadasInvertidas.slice(indiceCorte));
        } else {
          setRotaIdaGeometria(coordenadasInvertidas);
          setRotaVoltaGeometria([]);
        }
      }
    } catch (err) {
      if (axios.isCancel(err) || err.name === 'CanceledError' || err.name === 'AbortError') {
        return;
      }
      console.error("Erro ao calcular trajeto otimizado:", err);
    }
  }, [pedidos]);

  const alterarStatusPedido = (id, novoStatus) => {
    setPedidos(prevPedidos => 
      prevPedidos.map(p => p.id === id ? { ...p, status: novoStatus } : p)
    )

    if (novoStatus !== 'Pronto') {
      const novaSelecao = pedidosSelecionados.filter(item => item !== id);
      setPedidosSelecionados(novaSelecao);
      calcularRotaOtimizada(novaSelecao);
    }

    axios.put(`http://localhost:5000/api/pedidos/${id}/status`, { status: novoStatus })
      .then(() => carregarResumos())
      .catch(error => {
        console.error("Erro ao persistir status no banco:", error);
        carregarPedidos(true);
      });
  }

  const toggleSelecaoPedido = (pedido) => {
    if (!pedido) return;
    let novaSelecao;
    if (pedidosSelecionados.includes(pedido.id)) {
      novaSelecao = pedidosSelecionados.filter(item => item !== pedido.id);
    } else {
      novaSelecao = [...pedidosSelecionados, pedido.id];
    }
    setPedidosSelecionados(novaSelecao);
    calcularRotaOtimizada(novaSelecao);
  }

  // --- LÓGICA DE EXPANSÃO DE PEDIDOS E STATUS DE OFs ---
  const toggleExpandirPedido = (idPedido) => {
    setPedidosExpandidos(prev => 
      prev.includes(idPedido) ? prev.filter(id => id !== idPedido) : [...prev, idPedido]
    )
  }

  const alternarStatusOf = (idPedido, indexItem, totalItens) => {
    const chave = `${idPedido}-${indexItem}`
    const novoStatusOf = statusOfs[chave] === 'Concluido' ? 'Pendente' : 'Concluido'

    const novosStatus = {
      ...statusOfs,
      [chave]: novoStatusOf
    }
    setStatusOfs(novosStatus)

    let concluidasCount = 0
    for (let i = 0; i < totalItens; i++) {
      if (novosStatus[`${idPedido}-${i}`] === 'Concluido') {
        concluidasCount++
      }
    }

    if (totalItens > 0 && concluidasCount === totalItens) {
      alterarStatusPedido(idPedido, 'Pronto')
    }
  }

  const obterContadorOfs = (pedido) => {
    if (!pedido || !pedido.itens) return { concluidas: 0, total: 0 }
    const total = pedido.itens.length
    let concluidas = 0
    for (let i = 0; i < total; i++) {
      if (statusOfs[`${pedido.id}-${i}`] === 'Concluido') {
        concluidas++
      }
    }
    return { concluidas, total }
  }

  const pedidosProntos = pedidos.filter(p => p && p.status === 'Pronto')
  const pedidosEmAberto = pedidos.filter(p => p && p.status && p.status !== 'Pronto')

  const renderizarTagPrazo = (dias, dataEntrega) => {
    if (dias === null || dias === undefined || isNaN(dias)) return <span className="text-slate-500">-</span>;
    
    let tag = null;
    if (dias < 0) {
      tag = (
        <span className="inline-flex items-center gap-1.5 px-3 py-1 text-xs font-semibold rounded-full bg-red-500/10 text-red-400 border border-red-500/30 whitespace-nowrap">
          <span className="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse"></span>
          Atrasado ({Math.abs(dias)}d)
        </span>
      )
    } else if (dias === 0 || dias === 1) {
      tag = (
        <span className="inline-flex items-center gap-1.5 px-3 py-1 text-xs font-semibold rounded-full bg-amber-500/10 text-amber-400 border border-amber-500/30 whitespace-nowrap">
          <span className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse"></span>
          Prazo: {dias}d
        </span>
      )
    } else {
      tag = (
        <span className="inline-flex items-center gap-1.5 px-3 py-1 text-xs font-semibold rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 whitespace-nowrap">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>
          Prazo: {dias}d
        </span>
      )
    }

    return (
      <div className="flex flex-col items-end sm:items-center gap-1">
        {tag}
        {dataEntrega && <span className="text-[10px] text-slate-400 whitespace-nowrap">Entrega: {dataEntrega}</span>}
      </div>
    )
  }

  const obterEstiloStatusCompleto = (status) => {
    const estilos = {
      'Pendente': 'bg-amber-500/10 text-amber-400 border-amber-500/30 hover:border-amber-500/50',
      'Compras': 'bg-sky-500/10 text-sky-400 border-sky-500/30 hover:border-sky-500/50',
      'Produção': 'bg-purple-500/10 text-purple-400 border-purple-500/30 hover:border-purple-500/50',
      'Pronto': 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30 hover:border-emerald-500/50'
    }
    return estilos[status] || 'bg-slate-800 text-slate-300 border-slate-700 hover:border-slate-600'
  }

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 p-4 md:p-8 font-sans w-full">
      
      {/* HEADER */}
      <header className="w-full mx-auto mb-6 flex flex-col sm:flex-row justify-between items-start sm:items-center border-b border-slate-800 pb-4 gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white">FIVEL Control</h1>
          <p className="text-slate-400 text-sm">Painel de Controle de Carga e Produção</p>
        </div>
        <div className="flex items-center gap-2 bg-slate-900 px-4 py-2 rounded-lg border border-slate-800 self-stretch sm:self-auto justify-center">
          <span className="w-2.5 h-2.5 rounded-full bg-emerald-500 animate-pulse"></span>
          <span className="text-xs font-medium text-slate-300">Monitor Logístico Ativo (Tempo Real)</span>
        </div>
      </header>

      {/* SELETOR DE ABAS */}
      <div className="w-full mx-auto mb-8 flex gap-2 border-b border-slate-900 pb-px">
        <button
          onClick={() => setAbaAtiva('mapa')}
          className={`pb-3 px-4 font-medium text-sm transition-colors relative ${abaAtiva === 'mapa' ? 'text-indigo-400 border-b-2 border-indigo-400' : 'text-slate-400 hover:text-white'}`}
        >
          Geral e Mapa
        </button>
        <button
          onClick={() => setAbaAtiva('prazos')}
          className={`pb-3 px-4 font-medium text-sm transition-colors relative ${abaAtiva === 'prazos' ? 'text-indigo-400 border-b-2 border-indigo-400' : 'text-slate-400 hover:text-white'}`}
        >
          Controle de Pedidos em Aberto
        </button>
      </div>

      <main className="w-full mx-auto">
        {abaAtiva === 'mapa' ? (
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start w-full">
            
            <div className="lg:col-span-8 space-y-6 w-full">
              {/* CARDS DE SUMÁRIO - GERAL E MAPA */}
              <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                <div className="bg-slate-900 p-6 rounded-xl border border-slate-800 shadow-lg">
                  <p className="text-sm font-medium text-slate-400 mb-1">Faturamento Pronto</p>
                  <p className="text-2xl font-bold text-indigo-400">
                    R$ {(resumoMapa.faturamento_pronto || 0).toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                  </p>
                </div>
                
                <div className="bg-slate-900 p-6 rounded-xl border border-slate-800 shadow-lg">
                  <p className="text-sm font-medium text-slate-400 mb-1">Peso Pronto</p>
                  <p className="text-2xl font-bold text-emerald-400">
                    {formatarKg(resumoMapa.peso_pronto_kg)} <span className="text-sm font-normal text-slate-500">kg</span>
                  </p>
                </div>

                <div className="bg-slate-900 p-6 rounded-xl border border-slate-800 shadow-lg">
                  <p className="text-sm font-medium text-slate-400 mb-1">Peso Entregue Mês (Julho)</p>
                  <p className="text-2xl font-bold text-sky-400">
                    {formatarKg(resumoMapa.peso_entregue_mes_kg)} <span className="text-sm font-normal text-slate-500">kg</span>
                  </p>
                </div>
              </div>

              {/* TABELA DE PEDIDOS PRONTOS */}
              <div className="bg-slate-900 rounded-xl border border-slate-800 shadow-lg overflow-hidden w-full">
                <div className="p-5 border-b border-slate-800 flex justify-between items-center bg-slate-900">
                  <h2 className="text-lg font-semibold text-white">Pedidos Prontos para Expedição</h2>
                  <span className="bg-emerald-500/10 text-emerald-400 text-xs px-2.5 py-1 rounded-full font-semibold border border-emerald-500/20">
                    {pedidosProntos.length} Prontos
                  </span>
                </div>
                <div className="overflow-x-auto w-full">
                  <table className="w-full text-left border-collapse min-w-[600px]">
                    <thead>
                      <tr className="bg-slate-900 text-slate-400 text-xs font-semibold uppercase border-b border-slate-800">
                        <th className="p-4 w-16 text-center">Rota</th>
                        <th className="p-4">Pedido / Cliente</th>
                        <th className="p-4 text-center">Itens</th>
                        <th className="p-4 text-center">Peso</th>
                        <th className="p-4 text-center">Valor (R$)</th>
                        <th className="p-4 text-center">Status</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800/60 text-sm text-slate-300">
                      {pedidosProntos.map((pedido) => {
                        const pesoKg = (pedido.peso_total_kg ?? ((pedido.peso_total_ton || 0) * 1000));
                        return (
                          <tr key={pedido.id} className={`hover:bg-slate-800/30 transition-colors ${pedidosSelecionados.includes(pedido.id) ? 'bg-indigo-500/5' : ''}`}>
                            <td className="p-4 text-center">
                              <label className="relative flex items-center justify-center cursor-pointer select-none group">
                                <input
                                  type="checkbox"
                                  checked={pedidosSelecionados.includes(pedido.id)}
                                  onChange={() => toggleSelecaoPedido(pedido)}
                                  className="sr-only peer"
                                />
                                <div className="w-5 h-5 bg-slate-950 border border-slate-700/80 rounded-md 
                                                flex items-center justify-center text-transparent 
                                                transition-all duration-200 ease-out
                                                peer-checked:bg-indigo-500/20 peer-checked:border-indigo-500 peer-checked:text-indigo-400
                                                group-hover:border-slate-500 peer-checked:group-hover:border-indigo-400
                                                focus-within:ring-2 focus-within:ring-indigo-500/50">
                                  <svg className="w-3.5 h-3.5 stroke-[3] transition-transform duration-200 scale-75 peer-checked:scale-100" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                    <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                                  </svg>
                                </div>
                              </label>
                            </td>
                            <td className="p-4 font-medium text-white">
                              <div className="flex items-center gap-2">
                                <span className="text-xs bg-slate-800 px-2 py-0.5 rounded text-indigo-300 font-mono">
                                  Nº {pedido.id_pedido} {pedido.pedido_cliente ? `PC ${pedido.pedido_cliente}` : ''}
                                </span>
                              </div>
                              <div className="mt-1">{pedido.cliente || 'Sem Nome'}</div>
                              <span className="block text-xs text-slate-500">{pedido.cidade_bloco || ''}</span>
                            </td>
                            <td className="p-4 text-center font-mono">{pedido.total_itens || 0}</td>
                            <td className="p-4 text-center font-mono text-emerald-400">{formatarKg(pesoKg)} kg</td>
                            <td className="p-4 text-center font-medium text-indigo-400">
                              R$ {(pedido.faturamento_total || 0).toLocaleString('pt-BR', { minimumFractionDigits: 2 })}
                            </td>
                            <td className="p-4 text-center">
                              <div className="inline-flex items-center gap-2 pl-3 pr-2 py-1.5 rounded-full border bg-emerald-500/10 text-emerald-400 border-emerald-500/30 text-xs font-semibold">
                                <span>Pronto</span>
                                <button 
                                  onClick={() => alterarStatusPedido(pedido.id, 'Pendente')}
                                  title="Voltar para Em Aberto"
                                  className="w-4 h-4 rounded-full flex items-center justify-center text-emerald-400/60 hover:text-red-400 hover:bg-red-500/20 transition-colors focus:outline-none text-sm font-bold"
                                >
                                  &times;
                                </button>
                              </div>
                            </td>
                          </tr>
                        )
                      })}
                      {pedidosProntos.length === 0 && (
                        <tr>
                          <td colSpan="6" className="p-8 text-center text-slate-500">
                            Nenhum carregamento marcado como "Pronto" no momento.
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>

            {/* COLUNA DO MAPA E LOGÍSTICA */}
            <div className="lg:col-span-4 lg:sticky lg:top-6 w-full space-y-6">
              {/* MAPA */}
              <div className="bg-slate-900 rounded-xl border border-slate-800 shadow-lg overflow-hidden flex flex-col h-[550px] w-full">
                <div className="p-5 border-b border-slate-800 flex justify-between items-center">
                  <h2 className="text-lg font-semibold text-white">Mapa de Fluxo de Entregas</h2>
                  <span className="text-xs text-slate-400">Rota Unificada OSRM Trip</span>
                </div>
                <div className="h-full w-full relative z-10">
                  <MapContainer center={COORDENADAS_EMPRESA} zoom={10} className="h-full w-full">
                    <RedimensionarMapa />
                    <TileLayer
                      attribution='&copy; OpenStreetMap &copy; CARTO'
                      url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
                    />
                    
                    <Marker position={COORDENADAS_EMPRESA}>
                      <Popup>
                        <div className="text-slate-900 p-1">
                          <strong className="text-indigo-600">Minha Empresa</strong><br />
                          <span className="text-xs text-slate-500">SBC - Ponto de Partida</span>
                        </div>
                      </Popup>
                    </Marker>

                    {pedidosProntos.map((pedido) => {
                      const temPosicao = pedido && pedido.latitude && pedido.longitude;
                      const pesoKg = (pedido.peso_total_kg ?? ((pedido.peso_total_ton || 0) * 1000));
                      return temPosicao && (
                        <Marker key={pedido.id} position={[pedido.latitude, pedido.longitude]}>
                          <Popup>
                            <div className="text-slate-900 p-1">
                              <strong className="text-base">{pedido.cliente || 'Sem Nome'}</strong><br />
                              <span className="text-xs text-slate-500">{pedido.cidade_bloco || ''}</span>
                              <hr className="my-1 border-slate-200" />
                              <p className="text-xs m-0"><strong>Ped:</strong> Nº {pedido.id_pedido} {pedido.pedido_cliente ? `PC ${pedido.pedido_cliente}` : ''}</p>
                              <p className="text-xs m-0"><strong>Carga:</strong> {formatarKg(pesoKg)} kg</p>
                            </div>
                          </Popup>
                        </Marker>
                      )
                    })}

                    {rotaIdaGeometria.length > 0 && (
                      <Polyline
                        key={`ida-${pedidosSelecionados.join('-')}`}
                        positions={rotaIdaGeometria}
                        pathOptions={{ color: '#06b6d4', weight: 5, opacity: 0.95 }} 
                      />
                    )}

                    {rotaVoltaGeometria.length > 0 && (
                      <Polyline
                        key={`volta-${pedidosSelecionados.join('-')}`}
                        positions={rotaVoltaGeometria}
                        pathOptions={{ color: '#a855f7', weight: 5, opacity: 0.95 }} 
                      />
                    )}
                  </MapContainer>
                </div>
              </div>

              {/* PAINEL LOGÍSTICA */}
              <div className="bg-slate-900 p-5 rounded-xl border border-slate-800 shadow-lg w-full">
                <div className="border-b border-slate-800 pb-3 mb-5">
                  <h2 className="text-lg font-semibold text-white">Logística LIFO Otimizada</h2>
                  <p className="text-xs text-slate-400">Sequenciamento físico estruturado pela menor distância</p>
                </div>
                
                <div className="space-y-6 text-sm">
                  <div>
                    <span className="block text-xs font-bold text-slate-400 uppercase tracking-wider mb-3">
                      Ordem de Entrega (Menor Rota)
                    </span>
                    <div className="flex flex-col gap-2.5">
                      {ordemEntregas.length > 0 ? (
                        ordemEntregas.map((id, index) => {
                          const pedido = pedidos.find(p => p && p.id === id);
                          const pesoKg = (pedido?.peso_total_kg ?? ((pedido?.peso_total_ton || 0) * 1000));
                          return (
                            <div key={id} className="flex items-center justify-between p-3 bg-slate-800/40 border border-slate-700/50 rounded-lg">
                              <div className="flex items-center gap-3">
                                <span className="w-6 h-6 rounded-full bg-cyan-500/20 text-cyan-400 font-mono text-xs flex items-center justify-center font-bold">
                                  {index + 1}
                                </span>
                                <div>
                                  <div className="font-medium text-white text-sm">{pedido?.cliente || 'Cliente'}</div>
                                  <div className="text-xs text-slate-400 font-mono">
                                    Nº {pedido?.id_pedido} {pedido?.pedido_cliente ? `PC ${pedido.pedido_cliente}` : ''}
                                  </div>
                                </div>
                              </div>
                              <span className="text-xs font-mono text-emerald-400 font-semibold">
                                {formatarKg(pesoKg)} kg
                              </span>
                            </div>
                          )
                        })
                      ) : (
                        <div className="p-4 text-center text-xs text-slate-500 bg-slate-950/40 rounded-lg border border-slate-800/80">
                          Selecione um ou mais pedidos na tabela para calcular a rota otimizada.
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        ) : (
          /* ABA 2: CONTROLE DE PEDIDOS EM ABERTO */
          <div className="space-y-6 w-full">
            {/* CARDS DE SUMÁRIO - CONTROLE DE PEDIDOS */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
              <div className="bg-slate-900 p-6 rounded-xl border border-slate-800 shadow-lg">
                <p className="text-sm font-medium text-slate-400 mb-1">Faturamento Acumulado</p>
                <p className="text-2xl font-bold text-indigo-400">
                  R$ {(resumoPedidos.faturamento_acumulado || 0).toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                </p>
              </div>
              
              <div className="bg-slate-900 p-6 rounded-xl border border-slate-800 shadow-lg">
                <p className="text-sm font-medium text-slate-400 mb-1">Volume de Carga Total</p>
                <p className="text-2xl font-bold text-emerald-400">
                  {formatarKg(resumoPedidos.volume_carga_total_kg)} <span className="text-sm font-normal text-slate-500">kg</span>
                </p>
              </div>

              <div className="bg-slate-900 p-6 rounded-xl border border-slate-800 shadow-lg">
                <p className="text-sm font-medium text-slate-400 mb-1">Pedidos Ativos</p>
                <p className="text-2xl font-bold text-amber-400">{resumoPedidos.pedidos_ativos || 0}</p>
              </div>
            </div>

            <div className="bg-slate-900 rounded-xl border border-slate-800 shadow-lg p-6 w-full">
              <div className="flex flex-col md:flex-row justify-between items-start md:items-center mb-6 gap-4 border-b border-slate-800 pb-4">
                <div>
                  <h2 className="text-xl font-bold text-white">Pedidos em Aberto</h2>
                  <p className="text-xs text-slate-400">Gerencie status, OFs e itens de cada pedido em tempo real</p>
                </div>

                {/* BARRA DE CONTROLES */}
                <div className="flex flex-wrap items-center gap-3 bg-slate-950 p-2 rounded-lg border border-slate-800 w-full md:w-auto justify-between md:justify-end">
                  
                  {/* BOTÕES PARA ALTERNAR MODO DE EXIBIÇÃO */}
                  <div className="flex items-center bg-slate-900 p-1 rounded-md border border-slate-800">
                    <button
                      onClick={() => setModoExibicao('lista')}
                      title="Exibir em Lista"
                      className={`flex items-center gap-1.5 px-3 py-1 text-xs font-medium rounded transition-colors ${modoExibicao === 'lista' ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:text-white'}`}
                    >
                      <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 6h16M4 12h16M4 18h16" />
                      </svg>
                      Lista
                    </button>
                    <button
                      onClick={() => setModoExibicao('grade')}
                      title="Exibir em Grade"
                      className={`flex items-center gap-1.5 px-3 py-1 text-xs font-medium rounded transition-colors ${modoExibicao === 'grade' ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:text-white'}`}
                    >
                      <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2V6zM14 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V6zM4 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2v-2zM14 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z" />
                      </svg>
                      Grade
                    </button>
                  </div>

                  <div className="h-4 w-px bg-slate-800 hidden sm:block"></div>

                  {/* CONTROLES DE ORDENAÇÃO */}
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-slate-400 font-medium hidden sm:inline">Ordenar:</span>
                    <select
                      value={ordenarPor}
                      onChange={(e) => setOrdenarPor(e.target.value)}
                      className="bg-slate-900 text-xs font-medium text-slate-200 border border-slate-700 rounded-md px-2.5 py-1.5 focus:outline-none focus:border-indigo-500"
                    >
                      <option value="prazo">Dias Restantes (Prazo)</option>
                      <option value="id_pedido">Número do Pedido</option>
                      <option value="emissao">Data de Emissão</option>
                      <option value="data_entrega">Data de Entrega</option>
                    </select>

                    <select
                      value={ordem}
                      onChange={(e) => setOrdem(e.target.value)}
                      className="bg-slate-900 text-xs font-medium text-slate-200 border border-slate-700 rounded-md px-2.5 py-1.5 focus:outline-none focus:border-indigo-500"
                    >
                      <option value="asc">Crescente (A-Z / 0-9)</option>
                      <option value="desc">Decrescente (Z-A / 9-0)</option>
                    </select>
                  </div>
                </div>
              </div>

              {carregando ? (
                <div className="p-12 text-center text-slate-400">Carregando dados dos pedidos...</div>
              ) : (
                <div className={modoExibicao === 'lista' ? 'flex flex-col gap-3' : 'grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4'}>
                  {pedidosEmAberto.map((pedido) => {
                    const estaExpandido = pedidosExpandidos.includes(pedido.id)
                    const { concluidas, total } = obterContadorOfs(pedido)
                    const todasConcluidas = total > 0 && concluidas === total
                    const pesoKg = (pedido.peso_total_kg ?? ((pedido.peso_total_ton || 0) * 1000))

                    return modoExibicao === 'lista' ? (
                      /* VISUALIZAÇÃO EM LISTA */
                      <div key={pedido.id} className="bg-slate-950 rounded-xl border border-slate-800/80 hover:border-slate-700 transition-all overflow-hidden">
                        <div className="p-4 flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
                          
                          {/* BOTÃO EXPANDIR + IDENTIFICAÇÃO E CLIENTE */}
                          <div className="flex items-start gap-3 flex-1 min-w-[240px]">
                            <button
                              onClick={() => toggleExpandirPedido(pedido.id)}
                              className="mt-1 p-1 bg-slate-900 hover:bg-slate-800 border border-slate-800 rounded text-slate-400 hover:text-white transition-colors"
                              title="Expandir itens do pedido"
                            >
                              <svg className={`w-4 h-4 transition-transform duration-200 ${estaExpandido ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 9l-7 7-7-7" />
                              </svg>
                            </button>

                            <div>
                              <div className="flex items-center gap-2 mb-1 flex-wrap">
                                <span className="text-xs bg-indigo-500/10 text-indigo-400 px-2 py-0.5 rounded font-mono font-bold border border-indigo-500/20">
                                  Nº {pedido.id_pedido} {pedido.pedido_cliente ? `PC ${pedido.pedido_cliente}` : ''}
                                </span>

                                {/* CONTADOR DE OFs PRONTAS */}
                                <span className={`text-xs px-2 py-0.5 rounded font-mono font-semibold border ${todasConcluidas ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30' : 'bg-slate-800 text-slate-300 border-slate-700'}`}>
                                  OFs Prontas: {concluidas}/{total}
                                </span>
                              </div>
                              <h3 className="font-bold text-white text-base leading-tight">{pedido.cliente}</h3>
                              <p className="text-xs text-slate-400 mt-0.5">{pedido.cidade_bloco} {pedido.endereco_completo ? `• ${pedido.endereco_completo}` : ''}</p>
                            </div>
                          </div>

                          {/* DETALHES DE PESO E DATAS */}
                          <div className="flex items-center gap-6 text-xs text-slate-300 w-full md:w-auto justify-between md:justify-end border-t md:border-t-0 pt-3 md:pt-0 border-slate-800/60">
                            <div className="text-left md:text-center">
                              <span className="block text-[10px] text-slate-500 uppercase">Itens</span>
                              <span className="font-mono font-semibold">{pedido.total_itens || 0}</span>
                            </div>

                            <div className="text-left md:text-center">
                              <span className="block text-[10px] text-slate-500 uppercase">Peso Total</span>
                              <span className="font-mono font-semibold text-emerald-400">{formatarKg(pesoKg)} kg</span>
                            </div>

                            <div className="text-left md:text-center">
                              <span className="block text-[10px] text-slate-500 uppercase">Emissão</span>
                              <span className="font-mono">{pedido.data_emissao || '-'}</span>
                            </div>

                            <div>
                              {renderizarTagPrazo(pedido.dias_restantes, pedido.data_entrega)}
                            </div>
                          </div>

                          {/* ALTERAR STATUS DO PEDIDO */}
                          <div className="flex items-center gap-3 w-full md:w-auto justify-end border-t md:border-t-0 pt-3 md:pt-0 border-slate-800/60">
                            <select
                              value={pedido.status || 'Pendente'}
                              onChange={(e) => alterarStatusPedido(pedido.id, e.target.value)}
                              className={`text-xs font-semibold rounded-lg px-3 py-2 border transition-all cursor-pointer focus:outline-none ${obterEstiloStatusCompleto(pedido.status)}`}
                            >
                              <option value="Pendente" className="bg-slate-900 text-amber-400">Pendente</option>
                              <option value="Compras" className="bg-slate-900 text-sky-400">Compras</option>
                              <option value="Produção" className="bg-slate-900 text-purple-400">Produção</option>
                              <option value="Pronto" className="bg-slate-900 text-emerald-400">Pronto</option>
                            </select>
                          </div>

                        </div>

                        {/* AREA EXPANSÍVEL DA SANFONA (ITENS DA OF) */}
                        {estaExpandido && (
                          <div className="bg-slate-900/90 p-4 border-t border-slate-800/80">
                            <h4 className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-3">
                              Itens do Pedido / Ordens de Fabricação (OFs)
                            </h4>
                            {pedido.itens && pedido.itens.length > 0 ? (
                              <div className="overflow-x-auto">
                                <table className="w-full text-left border-collapse text-xs">
                                  <thead>
                                    <tr className="border-b border-slate-800 text-slate-500 uppercase font-mono">
                                      <th className="py-2 px-3">OF (Nº Serial)</th>
                                      <th className="py-2 px-3">Referência</th>
                                      <th className="py-2 px-3 text-center">Quantidade</th>
                                      <th className="py-2 px-3 text-right">Valor Unit.</th>
                                      <th className="py-2 px-3 text-right">Peso Item</th>
                                      <th className="py-2 px-3 text-center">Fechamento</th>
                                      <th className="py-2 px-3 text-center">Status OF</th>
                                    </tr>
                                  </thead>
                                  <tbody className="divide-y divide-slate-800/50 text-slate-300">
                                    {pedido.itens.map((item, idx) => {
                                      const chaveOf = `${pedido.id}-${idx}`
                                      const estaPronto = statusOfs[chaveOf] === 'Concluido'
                                      const numeroOf = item.id_numof || '-';
                                      const pesoItemKg = item.peso_item || item.peso_tot || 0;

                                      return (
                                        <tr key={idx} className="hover:bg-slate-800/40 transition-colors">
                                          <td className="py-2.5 px-3 font-mono font-bold text-indigo-300">
                                            OF {numeroOf}
                                          </td>
                                          <td className="py-2.5 px-3 font-medium text-white">
                                            {item.referencia || item.id_produto || '-'}
                                          </td>
                                          <td className="py-2.5 px-3 text-center font-mono">
                                            {item.quantidade || item.quant}
                                          </td>
                                          <td className="py-2.5 px-3 text-right font-mono">
                                            R$ {(item.preco_unitario || item.vlunit || 0).toLocaleString('pt-BR', { minimumFractionDigits: 2 })}
                                          </td>
                                          <td className="py-2.5 px-3 text-right font-mono text-emerald-400">
                                            {formatarKg(pesoItemKg)} kg
                                          </td>
                                          <td className="py-2.5 px-3 text-center font-mono text-slate-400">
                                            {item.fecha || '-'}
                                          </td>
                                          <td className="py-2.5 px-3 text-center">
                                            <button
                                              onClick={() => alternarStatusOf(pedido.id, idx, pedido.itens.length)}
                                              className={`px-3 py-1 rounded-full text-[11px] font-semibold border transition-all cursor-pointer ${
                                                estaPronto 
                                                  ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/40 hover:bg-emerald-500/30' 
                                                  : 'bg-amber-500/10 text-amber-400 border-amber-500/30 hover:bg-amber-500/20'
                                              }`}
                                            >
                                              {estaPronto ? '✓ Concluído' : '○ Pendente'}
                                            </button>
                                          </td>
                                        </tr>
                                      )
                                    })}
                                  </tbody>
                                </table>
                              </div>
                            ) : (
                              <div className="text-xs text-slate-500 italic p-2 text-center">
                                Nenhum item detalhado encontrado para este pedido.
                              </div>
                            )}
                          </div>
                        )}                          

                      </div>
                    ) : (
                      /* VISUALIZAÇÃO EM GRADE */
                      <div key={pedido.id} className="bg-slate-950 p-4 rounded-xl border border-slate-800 flex flex-col justify-between hover:border-slate-700 transition-colors">
                        <div>
                          <div className="flex justify-between items-start mb-2 gap-2">
                            <div>
                              <div className="flex items-center gap-2 flex-wrap">
                                <span className="text-xs bg-indigo-500/10 text-indigo-400 px-2 py-0.5 rounded font-mono font-bold border border-indigo-500/20">
                                  Nº {pedido.id_pedido} {pedido.pedido_cliente ? `PC ${pedido.pedido_cliente}` : ''}
                                </span>
                                
                                {/* CONTADOR DE OFs PRONTAS */}
                                <span className={`text-[10px] px-2 py-0.5 rounded font-mono font-semibold border ${todasConcluidas ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30' : 'bg-slate-800 text-slate-300 border-slate-700'}`}>
                                  OFs: {concluidas}/{total}
                                </span>
                              </div>
                              <h3 className="font-bold text-white text-base mt-2 leading-tight">{pedido.cliente}</h3>
                              <p className="text-xs text-slate-400 mt-0.5">{pedido.cidade_bloco}</p>
                            </div>
                            <div>{renderizarTagPrazo(pedido.dias_restantes, pedido.data_entrega)}</div>
                          </div>

                          <div className="my-3 py-2 border-y border-slate-800/80 grid grid-cols-3 gap-2 text-center text-xs">
                            <div>
                              <span className="block text-[10px] text-slate-500 uppercase">Itens</span>
                              <span className="font-mono font-semibold text-slate-200">{pedido.total_itens || 0}</span>
                            </div>
                            <div>
                              <span className="block text-[10px] text-slate-500 uppercase">Peso</span>
                              <span className="font-mono font-semibold text-emerald-400">{formatarKg(pesoKg)} kg</span>
                            </div>
                            <div>
                              <span className="block text-[10px] text-slate-500 uppercase">Emissão</span>
                              <span className="font-mono text-slate-300">{pedido.data_emissao || '-'}</span>
                            </div>
                          </div>
                        </div>

                        {/* BOTÃO EXPANDIR + STATUS NO MODO GRADE */}
                        <div className="space-y-3 pt-2">
                          <button
                            onClick={() => toggleExpandirPedido(pedido.id)}
                            className="w-full py-1.5 px-3 bg-slate-900 hover:bg-slate-800 border border-slate-800 rounded-lg text-xs font-semibold text-indigo-400 flex items-center justify-center gap-2 transition-colors"
                          >
                            <span>{estaExpandido ? 'Ocultar OFs' : 'Ver OFs do Pedido'}</span>
                            <svg className={`w-3.5 h-3.5 transition-transform duration-200 ${estaExpandido ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 9l-7 7-7-7" />
                            </svg>
                          </button>

                          {/* LISTA EXPANDIDA NO MODO GRADE */}
                          {estaExpandido && (
                            <div className="bg-slate-900/90 p-3 rounded-lg border border-slate-800 text-xs space-y-2 max-h-60 overflow-y-auto">
                              {pedido.itens && pedido.itens.length > 0 ? (
                                pedido.itens.map((item, idx) => {
                                  const chaveOf = `${pedido.id}-${idx}`
                                  const estaPronto = statusOfs[chaveOf] === 'Concluido'
                                  const pesoItemKg = item.peso_item || item.peso_tot || 0;
                                  const numeroOf = item.id_numof || '-';

                                  return (
                                    <div key={idx} className="p-2 bg-slate-950/70 border border-slate-800/80 rounded flex flex-col gap-1.5">
                                      <div className="flex justify-between items-center font-mono">
                                        <span className="font-bold text-indigo-300">OF #{numeroOf}</span>
                                        <span className="text-[10px] text-slate-400">Fech: {item.fecha || '-'}</span>
                                      </div>
                                      <div className="font-medium text-white truncate">{item.referencia || item.id_produto}</div>
                                      <div className="flex justify-between items-center text-[11px] text-slate-400">
                                        <span>Qtd: {item.quantidade}</span>
                                        <span className="text-emerald-400 font-mono">{formatarKg(pesoItemKg)} kg</span>
                                      </div>
                                      <button
                                        onClick={() => alternarStatusOf(pedido.id, idx, pedido.itens.length)}
                                        className={`w-full py-1 mt-1 rounded text-[10px] font-semibold border transition-all cursor-pointer ${
                                          estaPronto 
                                            ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/40 hover:bg-emerald-500/30' 
                                            : 'bg-amber-500/10 text-amber-400 border-amber-500/30 hover:bg-amber-500/20'
                                        }`}
                                      >
                                        {estaPronto ? '✓ Concluído' : '○ Pendente'}
                                      </button>
                                    </div>
                                  )
                                })
                              ) : (
                                <div className="text-slate-500 text-center py-2 italic text-[11px]">Nenhum item encontrado.</div>
                              )}
                            </div>
                          )}

                          <div className="flex items-center justify-between pt-2 border-t border-slate-800">
                            <span className="text-xs text-slate-400 font-medium">Status Pedido:</span>
                            <select
                              value={pedido.status || 'Pendente'}
                              onChange={(e) => alterarStatusPedido(pedido.id, e.target.value)}
                              className={`text-xs font-semibold rounded-lg px-2.5 py-1.5 border transition-all cursor-pointer focus:outline-none ${obterEstiloStatusCompleto(pedido.status)}`}
                            >
                              <option value="Pendente" className="bg-slate-900 text-amber-400">Pendente</option>
                              <option value="Compras" className="bg-slate-900 text-sky-400">Compras</option>
                              <option value="Produção" className="bg-slate-900 text-purple-400">Produção</option>
                              <option value="Pronto" className="bg-slate-900 text-emerald-400">Pronto</option>
                            </select>
                          </div>
                        </div>
                      </div>
                    )
                  })}

                  {pedidosEmAberto.length === 0 && (
                    <div className="col-span-full p-8 text-center text-slate-500 bg-slate-950/50 rounded-xl border border-slate-800">
                      Nenhum pedido em aberto encontrado.
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        )}
      </main>
    </div>
  )
}

export default App;