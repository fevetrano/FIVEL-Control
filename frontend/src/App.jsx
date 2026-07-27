import React, { useState, useEffect } from 'react'
import axios from 'axios'
import { MapContainer, TileLayer, Marker, Popup, Polyline } from 'react-leaflet'
import L from 'leaflet'

// Correção para o ícone do pino do Leaflet aparecer corretamente no React
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

function App() {
  const [pedidos, setPedidos] = useState([])
  const [carregando, setCarregando] = useState(true)
  const [abaAtiva, setAbaAtiva] = useState('mapa') 
  const [pedidosSelecionados, setPedidosSelecionados] = useState([]) 
  const [rotaIdaGeometria, setRotaIdaGeometria] = useState([]) 
  const [rotaVoltaGeometria, setRotaVoltaGeometria] = useState([]) 
  const [ordemEntregas, setOrdemEntregas] = useState([]) 

  useEffect(() => {
    axios.get('http://localhost:5000/api/pedidos')
      .then(response => {
        setPedidos(Array.isArray(response.data) ? response.data : [])
        setCarregando(false)
      })
      .catch(error => {
        console.error("Erro ao buscar pedidos da API:", error)
        setCarregando(false)
      })
  }, [])

  // Função auxiliar para calcular a distância entre duas coordenadas (Fórmula de Haversine)
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

  const calcularRotaOtimizada = async (idsSelecionados) => {
    if (idsSelecionados.length === 0) {
      setRotaIdaGeometria([]);
      setRotaVoltaGeometria([]);
      setOrdemEntregas([]);
      return;
    }

    const pedidosParaRota = pedidos.filter(p => p && idsSelecionados.includes(p.id) && p.latitude && p.longitude);

    if (pedidosParaRota.length === 0) return;

    try {
      let coordenadasString = `${COORDENADAS_EMPRESA[1]},${COORDENADAS_EMPRESA[0]}`;
      
      pedidosParaRota.forEach(p => {
        coordenadasString += `;${p.longitude},${p.latitude}`;
      });

      const url = `https://router.project-osrm.org/trip/v1/driving/${coordenadasString}?overview=full&geometries=geojson&source=first&destination=any`;
      
      const res = await axios.get(url);
      
      if (res.data.trips && res.data.trips.length > 0) {
        const coordenadasInvertidas = res.data.trips[0].geometry.coordinates.map(coord => [coord[1], coord[0]]);
        const waypoints = res.data.waypoints;
        
        const ordemCalculada = waypoints
          .map(wp => wp.waypoint_index)
          .filter(index => index !== 0)
          .map(index => pedidosParaRota[index - 1] ? pedidosParaRota[index - 1].id : null)
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
      console.error("Erro ao calcular trajeto otimizado:", err);
    }
  }

  const alterarStatusPedido = (id, novoStatus) => {
    setPedidos(prevPedidos => 
      prevPedidos.map(p => p.id === id ? { ...p, status: novoStatus } : p)
    )
    if (novoStatus !== 'Pronto') {
      const novaSelecao = pedidosSelecionados.filter(item => item !== id);
      setPedidosSelecionados(novaSelecao);
      calcularRotaOtimizada(novaSelecao);
    }
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

  const pedidosProntos = pedidos.filter(p => p && p.status === 'Pronto')
  const pedidosEmAberto = pedidos.filter(p => p && p.status && p.status !== 'Pronto')

  const faturamentoTotal = pedidos.reduce((acc, p) => acc + ((p && p.faturamento_total) || 0), 0)
  const pesoTotalTon = pedidos.reduce((acc, p) => acc + ((p && p.peso_total_ton) || 0), 0)
  const totalPedidos = pedidos.length

  const renderizarTagPrazo = (dias) => {
    if (dias === null || dias === undefined || isNaN(dias)) return <span className="text-slate-500">-</span>;
    if (dias < 0) {
      return (
        <span className="inline-flex items-center gap-1.5 px-3 py-1 text-xs font-semibold rounded-full bg-red-500/10 text-red-400 border border-red-500/30">
          <span className="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse"></span>
          Atrasado {Math.abs(dias)}d
        </span>
      )
    } else if (dias === 0 || dias === 1) {
      return (
        <span className="inline-flex items-center gap-1.5 px-3 py-1 text-xs font-semibold rounded-full bg-amber-500/10 text-amber-400 border border-amber-500/30">
          <span className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse"></span>
          Prazo: {dias}d
        </span>
      )
    } else {
      return (
        <span className="inline-flex items-center gap-1.5 px-3 py-1 text-xs font-semibold rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>
          Prazo: {dias}d
        </span>
      )
    }
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
          <span className="text-xs font-medium text-slate-300">Monitor Logístico Ativo</span>
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
              {/* CARDS DE SUMÁRIO */}
              <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                <div className="bg-slate-900 p-6 rounded-xl border border-slate-800 shadow-lg">
                  <p className="text-sm font-medium text-slate-400 mb-1">Faturamento Acumulado</p>
                  <p className="text-2xl font-bold text-indigo-400">
                    R$ {faturamentoTotal.toLocaleString('pt-BR', { minimumFractionDigits: 2 })}
                  </p>
                </div>
                
                <div className="bg-slate-900 p-6 rounded-xl border border-slate-800 shadow-lg">
                  <p className="text-sm font-medium text-slate-400 mb-1">Volume de Carga Total</p>
                  <p className="text-2xl font-bold text-emerald-400">
                    {pesoTotalTon.toFixed(2)} <span className="text-sm font-normal text-slate-500">Ton</span>
                  </p>
                </div>

                <div className="bg-slate-900 p-6 rounded-xl border border-slate-800 shadow-lg">
                  <p className="text-sm font-medium text-slate-400 mb-1">Pedidos Ativos</p>
                  <p className="text-2xl font-bold text-amber-400">{totalPedidos}</p>
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
                        <th className="p-4">Cliente</th>
                        <th className="p-4 text-center">Qtd</th>
                        <th className="p-4 text-center">Peso</th>
                        <th className="p-4 text-center">Valor (R$)</th>
                        <th className="p-4 text-center">Status</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800/60 text-sm text-slate-300">
                      {pedidosProntos.map((pedido) => (
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
                            {pedido.cliente || 'Sem Nome'}
                            <span className="block text-xs text-slate-500">{pedido.cidade_bloco || ''}</span>
                          </td>
                          <td className="p-4 text-center">{(pedido.quantidade || 0).toLocaleString('pt-BR')}</td>
                          <td className="p-4 text-center font-mono text-emerald-400">{(pedido.peso_total_ton || 0).toFixed(2)} t</td>
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
                      ))}
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
                      return temPosicao && (
                        <Marker key={pedido.id} position={[pedido.latitude, pedido.longitude]}>
                          <Popup>
                            <div className="text-slate-900 p-1">
                              <strong className="text-base">{pedido.cliente || 'Sem Nome'}</strong><br />
                              <span className="text-xs text-slate-500">{pedido.cidade_bloco || ''}</span>
                              <hr className="my-1 border-slate-200" />
                              <p className="text-xs m-0"><strong>Carga:</strong> {(pedido.peso_total_ton || 0).toFixed(2)} Ton</p>
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

              {/* PAINEL LOGÍSTICA ATUALIZADO (GRID/LISTA PADRONIZADO E EXPANDIDO) */}
              <div className="bg-slate-900 p-5 rounded-xl border border-slate-800 shadow-lg w-full">
                <div className="border-b border-slate-800 pb-3 mb-5">
                  <h2 className="text-lg font-semibold text-white">Logística LIFO Otimizada</h2>
                  <p className="text-xs text-slate-400">Sequenciamento físico estruturado pela menor distância</p>
                </div>
                
                <div className="space-y-6 text-sm">
                  {/* Bloco 1: Ordem de Entrega */}
                  <div>
                    <span className="block text-xs font-bold text-slate-400 uppercase tracking-wider mb-3">
                      Ordem de Entrega (Menor Rota)
                    </span>
                    <div className="flex flex-col gap-2.5">
                      {ordemEntregas.length > 0 ? (
                        ordemEntregas.map((id, index) => {
                          const pedido = pedidos.find(p => p && p.id === id);
                          if (!pedido) return null;
                          return (
                            <div key={`del-${id}`} className="flex items-center gap-4 bg-slate-950 border border-slate-800 p-3.5 rounded-xl transition-colors hover:border-slate-700">
                              <span className="bg-emerald-500/10 text-emerald-400 px-2.5 py-1 rounded-lg border border-emerald-500/30 font-bold text-xs shrink-0">
                                {index + 1}º Destino
                              </span>
                              <div className="min-w-0 flex-1">
                                <p className="text-sm font-bold text-white truncate">{pedido.cliente || 'Sem nome'}</p>
                                <p className="text-xs text-slate-400 truncate mt-0.5">{pedido.cidade_bloco || ''}</p>
                              </div>
                            </div>
                          );
                        })
                      ) : (
                        <span className="text-xs text-slate-500 bg-slate-950/40 p-3 rounded-lg border border-dashed border-slate-800 block text-center">
                          Selecione os pedidos para montar o itinerário estruturado.
                        </span>
                      )}
                    </div>
                  </div>
                  
                  {/* Bloco 2: Ordem de Carregamento (LIFO) -> Idêntico em estrutura, variando cor */}
                  {ordemEntregas.length > 0 && (
                    <div>
                      <span className="block text-xs font-bold text-slate-400 uppercase tracking-wider mb-3">
                        Ordem de Carregamento no Caminhão (LIFO)
                      </span>
                      <div className="flex flex-col gap-2.5">
                        {[...ordemEntregas].reverse().map((id, index) => {
                          const pedido = pedidos.find(p => p && p.id === id);
                          if (!pedido) return null;
                          return (
                            <div key={`load-${id}`} className="flex items-center gap-4 bg-slate-950 border border-slate-800 p-3.5 rounded-xl transition-colors hover:border-slate-700">
                              <span className="bg-purple-500/10 text-purple-400 px-2.5 py-1 rounded-lg border border-purple-500/30 font-bold text-xs shrink-0">
                                {index + 1}º Colocar
                              </span>
                              <div className="min-w-0 flex-1">
                                <p className="text-sm font-bold text-white truncate">{pedido.cliente || 'Sem nome'}</p>
                                <p className="text-xs text-slate-400 truncate mt-0.5">{pedido.cidade_bloco || ''}</p>
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
        ) : (
          /* ================= ABA 2: MONITOR E EDIÇÃO DE STATUS ================= */
          <div className="space-y-6 w-full">
            <div className="bg-slate-900 p-5 rounded-xl border border-slate-800 flex flex-col sm:flex-row justify-between items-start sm:items-center shadow-md gap-4 w-full">
              <div>
                <h2 className="text-xl font-bold text-white">Pedidos em Aberto sob Monitoramento</h2>
                <p className="text-sm text-slate-400">Modifique o status dos cards para gerenciar o fluxo interno.</p>
              </div>
              <div className="bg-amber-500/10 text-amber-400 px-4 py-2 rounded-lg border border-amber-500/20 font-semibold text-sm">
                Total em Aberto: {pedidosEmAberto.length}
              </div>
            </div>

            <div className="bg-slate-900 rounded-xl border border-slate-800 shadow-lg overflow-hidden w-full">
              <div className="overflow-x-auto w-full">
                <table className="w-full text-left border-collapse min-w-[700px]">
                  <thead>
                    <tr className="bg-slate-950 text-slate-400 text-xs font-semibold uppercase border-b border-slate-800">
                      <th className="p-4">Cliente | Região</th>
                      <th className="p-4 text-center">Volume (Ton)</th>
                      <th className="p-4 text-center">Prazo</th>
                      <th className="p-4 text-center w-64">Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/60 text-sm text-slate-300">
                    {pedidosEmAberto
                      .map((pedido) => {
                        if (!pedido) return null;
                        return (
                          <tr key={pedido.id} className="hover:bg-slate-800/20 transition-colors">
                            <td className="p-4 font-medium text-white">
                              {pedido.cliente || 'Sem Nome'}
                              <span className="block text-xs text-slate-400">{pedido.cidade_bloco || ''}</span>
                            </td>
                            <td className="p-4 text-center font-mono text-emerald-400">{(pedido.peso_total_ton || 0).toFixed(2)} t</td>
                            <td className="p-4 text-center">
                              {renderizarTagPrazo(pedido.dias_restantes)}
                            </td>
                            <td className="p-4 text-center">
                              <div className="relative inline-block w-48 text-left group">
                                <select
                                  value={pedido.status || 'Pendente'}
                                  onChange={(e) => alterarStatusPedido(pedido.id, e.target.value)}
                                  className={`w-full appearance-none px-4 py-2 rounded-full text-xs font-bold border cursor-pointer transition-all focus:outline-none pr-8 text-center ${obterEstiloStatusCompleto(pedido.status)}`}
                                >
                                  <option value="Pendente" className="bg-slate-950 text-amber-400 font-semibold">Pendente</option>
                                  <option value="Compras" className="bg-slate-950 text-sky-400 font-semibold">Compras</option>
                                  <option value="Produção" className="bg-slate-950 text-purple-400 font-semibold">Produção</option>
                                  <option value="Pronto" className="bg-slate-950 text-emerald-400 font-semibold">Pronto</option>
                                </select>
                                <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-4 text-slate-400/80 group-hover:text-slate-300">
                                  <svg className="h-3 w-3 transition-transform duration-200" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="3" d="M19 9l-7 7-7-7" />
                                  </svg>
                                </div>
                              </div>
                            </td>
                          </tr>
                        );
                      })}
                    {pedidosEmAberto.length === 0 && (
                      <tr>
                        <td colSpan="4" className="p-8 text-center text-slate-500">
                          Nenhum pedido em aberto no momento. Todos estão "Prontos" para expedição!
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  )
}

export default App