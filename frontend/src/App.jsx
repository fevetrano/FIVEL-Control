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
      <header className="max-w-7xl mx-auto mb-8 flex justify-between items-center border-b border-slate-800 pb-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white">FIVEL Control</h1>
          <p className="text-slate-400 text-sm">Painel de Controle de Carga e Produção</p>
        </div>
        <div className="flex items-center gap-2 bg-slate-900 px-4 py-2 rounded-lg border border-slate-800">
          <span className="w-2.5 h-2.5 rounded-full bg-emerald-500 animate-pulse"></span>
          <span className="text-xs font-medium text-slate-300">Monitor Logístico Ativo</span>
        </div>
      </header>

      <main className="max-w-7xl mx-auto space-y-8">
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

        {/* SEÇÃO DO MAPA LOGÍSTICO */}
        <div className="bg-slate-900 rounded-xl border border-slate-800 shadow-lg overflow-hidden">
          <div className="p-5 border-b border-slate-800 flex justify-between items-center">
            <h2 className="text-lg font-semibold text-white">Mapa de Fluxo de Entregas</h2>
            <span className="text-xs text-slate-400">Diadema & Sorocaba</span>
          </div>
          <div className="h-[400px] w-full relative z-10">
            {/* Centralizado próximo a SP/Diadema/Sorocaba */}
            <MapContainer center={[-23.5505, -46.6333]} zoom={9} className="h-full w-full">
              {/* Estilo Dark Mode para o Mapa */}
              <TileLayer
                attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>'
                url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
              />
              
              {/* Renderiza um pino para cada pedido que tiver coordenadas válidas */}
              {pedidos.map((pedido) => {
                if (pedido.latitude && pedido.longitude) {
                  return (
                    <Marker key={pedido.id} position={[pedido.latitude, pedido.longitude]}>
                      <Popup>
                        <div className="text-slate-900 p-1">
                          <strong className="text-base">{pedido.cliente}</strong><br />
                          <span className="text-xs text-slate-500">{pedido.cidade_bloco}</span>
                          <hr className="my-1 border-slate-200" />
                          <p className="text-xs m-0"><strong>Qtd:</strong> {pedido.quantidade}</p>
                          <p className="text-xs m-0"><strong>Carga:</strong> {pedido.peso_total_ton.toFixed(2)} Ton</p>
                          <p className="text-xs m-0 text-indigo-600"><strong>Valor:</strong> R$ {pedido.faturamento_total.toFixed(2)}</p>
                          <span className={`inline-block mt-1 px-2 py-0.5 text-[10px] font-bold rounded ${pedido.status === 'Pronto' ? 'bg-emerald-100 text-emerald-800' : 'bg-amber-100 text-amber-800'}`}>
                            {pedido.status}
                          </span>
                        </div>
                      </Popup>
                    </Marker>
                  )
                }
                return null
              })}
            </MapContainer>
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
                  <th className="p-4 text-right">Qtd</th>
                  <th className="p-4 text-right">Preço Un.</th>
                  <th className="p-4 text-right">Peso Total (Ton)</th>
                  <th className="p-4 text-right">Faturamento</th>
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
                    <td className="p-4 text-right">{pedido.quantidade.toLocaleString('pt-BR')}</td>
                    <td className="p-4 text-right">R$ {pedido.preco_unitario.toFixed(2)}</td>
                    <td className="p-4 text-right font-mono text-emerald-400">{pedido.peso_total_ton.toFixed(2)} t</td>
                    <td className="p-4 text-right font-medium text-indigo-400">
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
      </main>
    </div>
  )
}

export default App