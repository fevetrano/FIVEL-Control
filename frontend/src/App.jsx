import React, { useState, useEffect } from 'react'
import axios from 'axios'

function App() {
  const [pedidos, setPedidos] = useState([])
  const [carregando, setCarregando] = useState(true)

  // Função que vai no Python buscar os dados reais
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

  // Cálculos automáticos do Painel (Soma tudo o que vem do banco)
  const faturamentoTotal = pedidos.reduce((acc, p) => acc + p.faturamento_total, 0)
  const pesoTotalTon = pedidos.reduce((acc, p) => acc + p.peso_total_ton, 0)
  const totalPedidos = pedidos.length

  if (carregando) {
    return (
      <div className="min-h-screen bg-slate-900 text-slate-100 flex items-center justify-center">
        <p className="text-lg font-medium animate-pulse text-indigo-400">Carregando dados do FIVEL Control...</p>
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
          <span className="text-xs font-medium text-slate-300">API Python Ativa</span>
        </div>
      </header>

      <main className="max-w-7xl mx-auto">
        {/* CARDS DE SUMÁRIO */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
          <div className="bg-slate-900 p-6 rounded-xl border border-slate-800 shadow-lg">
            <p className="text-sm font-medium text-slate-400 mb-1">Faturamento Acumulado</p>
            <p className="text-2xl font-bold text-indigo-400">
              R$ {faturamentoTotal.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </p>
          </div>
          
          <div className="bg-slate-900 p-6 rounded-xl border border-slate-800 shadow-lg">
            <p className="text-sm font-medium text-slate-400 mb-1">Volume de Carga Total</p>
            <p className="text-2xl font-bold text-emerald-400">
              {pesoTotalTon.toFixed(2)} <span className="text-sm font-normal text-slate-500">Ton</span>
            </p>
          </div>

          <div className="bg-slate-900 p-6 rounded-xl border border-slate-800 shadow-lg">
            <p className="text-sm font-medium text-slate-400 mb-1">Pedidos em Aberto</p>
            <p className="text-2xl font-bold text-amber-400">{totalPedidos}</p>
          </div>
        </div>

        {/* TABELA DE PEDIDOS */}
        <div className="bg-slate-900 rounded-xl border border-slate-800 shadow-lg overflow-hidden">
          <div className="p-5 border-b border-slate-800">
            <h2 className="text-lg font-semibold text-white">Lista de Pedidos em Aberto</h2>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="bg-slate-900 text-slate-400 text-xs font-semibold uppercase border-b border-slate-800">
                  <th className="p-4">Cliente</th>
                  <th className="p-4 text-center">Quantidade</th>
                  <th className="p-4 text-center">Preço Un. (R$)</th>
                  <th className="p-4 text-center">Peso Un. (kg)</th>
                  <th className="p-4 text-center">Peso Total (Ton)</th>
                  <th className="p-4 text-center">Faturamento</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60 text-sm text-slate-300">
                {pedidos.map((pedido) => (
                  <tr key={pedido.id} className="hover:bg-slate-800/30 transition-colors">
                    <td className="p-4 font-medium text-white">{pedido.cliente}</td>
                    <td className="p-4 text-center">{pedido.quantidade.toLocaleString('pt-BR')}</td>
                    <td className="p-4 text-center">R$ {pedido.preco_unitario.toFixed(2)}</td>
                    <td className="p-4 text-center">{pedido.peso_unitario.toFixed(3)}</td>
                    <td className="p-4 text-center font-mono text-emerald-400">{pedido.peso_total_ton.toFixed(2)} t</td>
                    <td className="p-4 text-center font-medium text-indigo-400">
                      R$ {pedido.faturamento_total.toLocaleString('pt-BR', { minimumFractionDigits: 2 })}
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