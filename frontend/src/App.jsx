import React, { useState, useEffect } from 'react'
import axios from 'axios'
import { MapContainer, TileLayer, Marker, Popup } from 'react-leaflet'
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

function App() {
  const [pedidos, setPedidos] = useState([])
  const [carregando, setCarregando] = useState(true)
  const [abaAtiva, setAbaAtiva] = useState('mapa') // 'mapa' ou 'prazos'

  useEffect(() => {
    axios.get('http://localhost:5000/api/pedidos')
      .then(response => {
        setPedidos(response.data)
        setCarregando(false)
      })
      .catch(error => {
        console.error("Erro ao buscar pedidos da API:", error)
        setCarregando(false)
      })
  }, [])

  const faturamentoTotal = pedidos.reduce((acc, p) => acc + p.faturamento_total, 0)
  const pesoTotalTon = pedidos.reduce((acc, p) => acc + p.peso_total_ton, 0)
  const totalPedidos = pedidos.length

  // Função interna para renderizar as bolinhas e as tags de prazos sem nenhum emoji
  const renderizarTagPrazo = (dias) => {
    if (dias === null || dias === undefined) return <span className="text-slate-500">-</span>;
    
    if (dias < 0) {
      return (
        <span className="inline-flex items-center gap-2 px-2.5 py-1 text-xs font-semibold rounded-full bg-red-500/10 text-red-400 border border-red-500/20">
          <span className="w-2 h-2 rounded-full bg-red-500 animate-pulse"></span>
          Atrasado ({Math.abs(dias)} {Math.abs(dias) === 1 ? 'dia' : 'dias'})
        </span>
      )
    } else if (dias === 0 || dias === 1) {
      return (
        <span className="inline-flex items-center gap-2 px-2.5 py-1 text-xs font-semibold rounded-full bg-amber-500/10 text-amber-400 border border-amber-500/20">
          <span className="w-2 h-2 rounded-full bg-amber-500 animate-pulse"></span>
          Crítico ({dias === 0 ? 'Hoje' : 'Amanhã'})
        </span>
      )
    } else {
      return (
        <span className="inline-flex items-center gap-2 px-2.5 py-1 text-xs font-semibold rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
          <span className="w-2 h-2 rounded-full bg-emerald-500"></span>
          No Prazo ({dias} dias)
        </span>
      )
    }
  }

  if (carregando) {
    return (
      <div className="min-h-screen bg-slate-900 text-slate-100 flex items-center justify-center">
        <p className="text-lg font-medium animate-pulse text-indigo-400">Carregando dados logísticos...</p>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 p-6 font-sans">
      {/* HEADER */}
      <header className="max-w-[1600px] mx-auto mb-6 flex justify-between items-center border-b border-slate-800 pb-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white">FIVEL Control</h1>
          <p className="text-slate-400 text-sm">Painel de Controle de Carga e Produção</p>
        </div>
        <div className="flex items-center gap-2 bg-slate-900 px-4 py-2 rounded-lg border border-slate-800">
          <span className="w-2.5 h-2.5 rounded-full bg-emerald-500 animate-pulse"></span>
          <span className="text-xs font-medium text-slate-300">Monitor Logístico Ativo</span>
        </div>
      </header>

      {/* SELETOR DE ABAS (MINIMALISTA) */}
      <div className="max-w-[1600px] mx-auto mb-8 flex gap-2 border-b border-slate-900 pb-px">
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
          Monitor de Prazos
        </button>
      </div>

      <main className="max-w-[1600px] mx-auto">
        {abaAtiva === 'mapa' ? (
          /* ================= ABA 1: GERAL E MAPA ================= */
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
            
            {/* COLUNA DA ESQUERDA (Cards + Tabela) */}
            <div className="lg:col-span-8 space-y-6">
              
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

              {/* TABELA DE PEDIDOS */}
              <div className="bg-slate-900 rounded-xl border border-slate-800 shadow-lg overflow-hidden">
                <div className="p-5 border-b border-slate-800">
                  <h2 className="text-lg font-semibold text-white">Lista de Pedidos da Cartonagem</h2>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-left border-collapse">
                    <thead>
                      <tr className="bg-slate-900 text-slate-400 text-xs font-semibold uppercase border-b border-slate-800">
                        <th className="p-4">Cliente</th>
                        <th className="p-4 text-center">Qtd</th>
                        <th className="p-4 text-center">Preço Un.</th>
                        <th className="p-4 text-center">Peso Total (Ton)</th>
                        <th className="p-4 text-center">Faturamento</th>
                        <th className="p-4 text-center">Status</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800/60 text-sm text-slate-300">
                      {pedidos.map((pedido) => (
                        <tr key={pedido.id} className="hover:bg-slate-800/30 transition-colors">
                          <td className="p-4 font-medium text-white">
                            {pedido.cliente}
                            <span className="block text-xs text-slate-500">{pedido.cidade_bloco}</span>
                          </td>
                          <td className="p-4 text-center">{pedido.quantidade.toLocaleString('pt-BR')}</td>
                          <td className="p-4 text-center">R$ {pedido.preco_unitario.toFixed(2)}</td>
                          <td className="p-4 text-center font-mono text-emerald-400">{pedido.peso_total_ton.toFixed(2)} t</td>
                          <td className="p-4 text-center font-medium text-indigo-400">
                            R$ {pedido.faturamento_total.toLocaleString('pt-BR', { minimumFractionDigits: 2 })}
                          </td>
                          <td className="p-4 text-center">
                            <span className={`px-2.5 py-1 text-xs font-semibold rounded-full ${pedido.status === 'Pronto' ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-amber-500/10 text-amber-400 border border-amber-500/20'}`}>
                              {pedido.status}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>

            {/* COLUNA DA DIREITA (Mapa) */}
            <div className="lg:col-span-4 bg-slate-900 rounded-xl border border-slate-800 shadow-lg overflow-hidden flex flex-col h-[580px] sticky top-6">
              <div className="p-5 border-b border-slate-800 flex justify-between items-center">
                <h2 className="text-lg font-semibold text-white">Mapa de Fluxo de Entregas</h2>
                <span className="text-xs text-slate-400">Diadema & Sorocaba</span>
              </div>
              <div className="h-full w-full relative z-10">
                <MapContainer center={[-23.5505, -46.6333]} zoom={9} className="h-full w-full">
                  <TileLayer
                    attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>'
                    url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
                  />
                  {pedidos.map((pedido) => (
                    pedido.latitude && pedido.longitude && (
                      <Marker key={pedido.id} position={[pedido.latitude, pedido.longitude]}>
                        <Popup>
                          <div className="text-slate-900 p-1">
                            <strong className="text-base">{pedido.cliente}</strong><br />
                            <span className="text-xs text-slate-500">{pedido.cidade_bloco}</span>
                            <hr className="my-1 border-slate-200" />
                            <p className="text-xs m-0"><strong>Qtd:</strong> {pedido.quantidade}</p>
                            <p className="text-xs m-0"><strong>Carga:</strong> {pedido.peso_total_ton.toFixed(2)} Ton</p>
                            <p className="text-xs m-0 text-indigo-600"><strong>Valor:</strong> R$ {pedido.faturamento_total.toFixed(2)}</p>
                            <p className="text-xs m-0 mt-1"><strong>Prazo:</strong> {pedido.data_entrega || 'Não definida'}</p>
                          </div>
                        </Popup>
                      </Marker>
                    )
                  ))}
                </MapContainer>
              </div>
            </div>
          </div>
        ) : (
          /* ================= ABA 2: MONITOR DE PRAZOS ================= */
          <div className="space-y-6">
            <div className="bg-slate-900 p-5 rounded-xl border border-slate-800 flex justify-between items-center shadow-md">
              <div>
                <h2 className="text-xl font-bold text-white">Pedidos em Aberto sob Monitoramento</h2>
                <p className="text-sm text-slate-400">Exibindo cargas pendentes ordenadas por criticidade de prazo para o transporte.</p>
              </div>
              <div className="bg-amber-500/10 text-amber-400 px-4 py-2 rounded-lg border border-amber-500/20 font-semibold text-sm flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-amber-500 animate-pulse"></span>
                Total Pendentes: {pedidos.filter(p => p.status === 'Pendente').length}
              </div>
            </div>

            <div className="bg-slate-900 rounded-xl border border-slate-800 shadow-lg overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full text-left border-collapse">
                  <thead>
                    <tr className="bg-slate-950 text-slate-400 text-xs font-semibold uppercase border-b border-slate-800">
                      <th className="p-4">Cliente / Região</th>
                      <th className="p-4 text-center">Volume (Ton)</th>
                      <th className="p-4 text-center">Data Prometida</th>
                      <th className="p-4 text-center">Status de Criticidade</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/60 text-sm text-slate-300">
                    {pedidos
                      .filter(p => p.status === 'Pendente') 
                      .sort((a, b) => a.dias_restantes - b.dias_restantes) 
                      .map((pedido) => (
                        <tr key={pedido.id} className="hover:bg-slate-800/20 transition-colors">
                          <td className="p-4 font-medium text-white">
                            {pedido.cliente}
                            <span className="block text-xs text-slate-400">{pedido.cidade_bloco}</span>
                          </td>
                          <td className="p-4 text-center font-mono text-emerald-400">{pedido.peso_total_ton.toFixed(2)} t</td>
                          <td className="p-4 text-center font-medium text-slate-200">{pedido.data_entrega || 'Não definida'}</td>
                          <td className="p-4 flex justify-center items-center pt-5">
                            {renderizarTagPrazo(pedido.dias_restantes)}
                          </td>
                        </tr>
                      ))}
                    {pedidos.filter(p => p.status === 'Pendente').length === 0 && (
                      <tr>
                        <td colSpan="4" className="p-8 text-center text-slate-500">
                          Nenhum pedido pendente em aberto no momento.
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