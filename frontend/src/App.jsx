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
  const [isDarkMode, setIsDarkMode] = useState(true); 
  
  const [pedidos, setPedidos] = useState([])
  const [compras, setCompras] = useState([])
  const [carregando, setCarregando] = useState(true)
  const [abaAtiva, setAbaAtiva] = useState('prazos') 
  
  const [pedidosSelecionados, setPedidosSelecionados] = useState([]) 
  const [rotaIdaGeometria, setRotaIdaGeometria] = useState([]) 
  const [rotaVoltaGeometria, setRotaVoltaGeometria] = useState([]) 
  const [ordemEntregas, setOrdemEntregas] = useState([]) 

  const [resumoPedidos, setResumoPedidos] = useState({
    faturamento_acumulado: 0,
    volume_carga_total_kg: 0,
    pedidos_ativos: 0
  })

  const [resumoMapa, setResumoMapa] = useState({
    faturamento_pronto: 0,
    peso_pronto_kg: 0,
    peso_entregue_mes_kg: 0
  })

  const [dadosDashboard, setDadosDashboard] = useState({
    faturamento_mes: 0,
    peso_mes_kg: 0,
    total_nfs_mes: 0,
    faturamento_carteira: 0,
    peso_carteira_kg: 0,
    total_pedidos_carteira: 0,
    distribuicao_kanban: { Pendente: 0, Compras: 0, Produção: 0, Pronto: 0 },
    mes_referencia: ''
  })

  const [ordenarPor, setOrdenarPor] = useState('prazo') 
  const [ordem, setOrdem] = useState('asc') 
  const [modoExibicao, setModoExibicao] = useState('lista') 

  const [termoPesquisa, setTermoPesquisa] = useState("");
  const [modalBipadorAberto, setModalBipadorAberto] = useState(false);
  const [statusBipador, setStatusBipador] = useState('Produção');
  const [ofBipador, setOfBipador] = useState("");
  const [msgBipador, setMsgBipador] = useState({ texto: "", tipo: "" });
  const inputBipadorRef = useRef(null);

  const [pedidosExpandidos, setPedidosExpandidos] = useState([])
  const [comprasExpandidas, setComprasExpandidas] = useState([])

  const abortControllerOSRM = useRef(null)
  
  // --- PROTEÇÃO CONTRA CONDIÇÃO DE CORRIDA (RACE CONDITION) ---
  const isUpdatingRef = useRef(false);
  const fallbackTimerRef = useRef(null);

  const iniciarAtualizacao = () => {
    isUpdatingRef.current = true;
    if (fallbackTimerRef.current) clearTimeout(fallbackTimerRef.current);
    fallbackTimerRef.current = setTimeout(() => {
      isUpdatingRef.current = false;
    }, 8000); 
  };

  const finalizarAtualizacao = () => {
    isUpdatingRef.current = false;
    if (fallbackTimerRef.current) clearTimeout(fallbackTimerRef.current);
  };

  const t = {
    bg: isDarkMode ? 'bg-[#0F0F0F]' : 'bg-gray-100',
    card: isDarkMode ? 'bg-[#202020]' : 'bg-white',
    inner: isDarkMode ? 'bg-[#151515]' : 'bg-gray-50',
    innerAlt: isDarkMode ? 'bg-[#1A1A1A]' : 'bg-gray-100',
    border: isDarkMode ? 'border-[#333333]' : 'border-gray-200',
    textPrimary: isDarkMode ? 'text-[#F8F8F8]' : 'text-gray-900',
    textSecondary: isDarkMode ? 'text-[#A0A0A0]' : 'text-gray-500',
    textAccent: isDarkMode ? 'text-[#5DD62C]' : 'text-[#337418]',
    borderAccent: isDarkMode ? 'border-[#5DD62C]' : 'border-[#337418]',
    borderAccentSoft: isDarkMode ? 'border-[#5DD62C]/20' : 'border-[#337418]/30',
    bgAccentSoft: isDarkMode ? 'bg-[#5DD62C]/10' : 'bg-[#5DD62C]/20',
    hoverCard: isDarkMode ? 'hover:bg-[#2A2A2A]' : 'hover:bg-gray-50',
    hoverInner: isDarkMode ? 'hover:bg-[#202020]' : 'hover:bg-gray-100',
    hoverBorderAccent: isDarkMode ? 'hover:border-[#5DD62C]/50' : 'hover:border-[#337418]/50',
    divider: isDarkMode ? 'divide-[#333333]' : 'divide-gray-200',
    inputBg: isDarkMode ? 'bg-[#202020]' : 'bg-white',
    ring: isDarkMode ? 'hover:ring-[#333333]' : 'hover:ring-gray-300'
  };

  const formatarKg = (valor) => {
    if (!valor || isNaN(valor)) return '0'
    return Math.round(valor).toLocaleString('pt-BR')
  }

  const carregarPedidos = useCallback((silencioso = false) => {
    if (silencioso && isUpdatingRef.current) return;

    if (!silencioso) setCarregando(true)
    axios.get(`http://localhost:5000/api/pedidos?ordenar_por=${ordenarPor}&ordem=${ordem}`)
      .then(response => {
        if (isUpdatingRef.current) return; 
        setPedidos(Array.isArray(response.data) ? response.data : [])
        if (!silencioso) setCarregando(false)
      })
      .catch(error => {
        console.error("Erro ao buscar pedidos da API:", error)
        if (!silencioso) setCarregando(false)
      })
  }, [ordenarPor, ordem])

  const carregarCompras = useCallback((silencioso = false) => {
    if (silencioso && isUpdatingRef.current) return;

    axios.get(`http://localhost:5000/api/compras`)
      .then(response => {
        if (isUpdatingRef.current) return;
        setCompras(Array.isArray(response.data) ? response.data : [])
      })
      .catch(error => {
        console.error("Erro ao buscar compras da API:", error)
      })
  }, [])

  const carregarResumos = useCallback(() => {
    Promise.all([
      axios.get('http://localhost:5000/api/resumo/pedidos'),
      axios.get('http://localhost:5000/api/resumo/mapa'),
      axios.get('http://localhost:5000/api/resumo/dashboard')
    ]).then(([resPedidos, resMapa, resDash]) => {
      const dadosPedidos = resPedidos.data || {}
      const dadosMapa = resMapa.data || {}

      setResumoPedidos({
        ...dadosPedidos,
        volume_carga_total_kg: dadosPedidos.volume_carga_total_kg ?? ((dadosPedidos.volume_carga_total_ton || 0) * 1000)
      })

      setResumoMapa(prev => ({
        ...prev,
        peso_entregue_mes_kg: dadosMapa.peso_entregue_mes_kg ?? ((dadosMapa.peso_entregue_mes_ton || 0) * 1000)
      }))

      if (resDash.data) {
        setDadosDashboard(resDash.data)
      }
    }).catch(error => {
      console.error("Erro ao carregar indicadores de resumo:", error)
    })
  }, [])

  useEffect(() => {
    carregarPedidos()
    carregarCompras()
    carregarResumos()

    const intervalId = setInterval(() => {
      carregarPedidos(true)
      carregarCompras(true)
      carregarResumos()
    }, 5000)

    return () => clearInterval(intervalId)
  }, [carregarPedidos, carregarCompras, carregarResumos])

  useEffect(() => {
    const calcularProntos = () => {
      let fat = 0;
      let peso = 0;
      pedidos.forEach(p => {
        if (p.status === 'Pronto') {
          fat += (p.faturamento_total || 0);
          peso += (p.peso_total_kg || 0);
        }
      });
      setResumoMapa(prev => ({
        ...prev,
        faturamento_pronto: fat,
        peso_pronto_kg: peso
      }));
    };
    calcularProntos();
  }, [pedidos]);

  useEffect(() => {
    if (modalBipadorAberto && inputBipadorRef.current) {
      inputBipadorRef.current.focus();
    }
  }, [modalBipadorAberto]);

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

  const calcularRotaOtimizada = useCallback(async (idsSelecionados, listaPedidos) => {
    if (!idsSelecionados || idsSelecionados.length === 0) {
      setRotaIdaGeometria([]);
      setRotaVoltaGeometria([]);
      setOrdemEntregas([]);
      return;
    }

    const pedidosParaRota = (listaPedidos || pedidos).filter(p => p && idsSelecionados.includes(p.id) && p.latitude && p.longitude);

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

  useEffect(() => {
    calcularRotaOtimizada(pedidosSelecionados, pedidos);
  }, [pedidosSelecionados, pedidos, calcularRotaOtimizada]);

  const darBaixaCompra = (idCompra) => {
    iniciarAtualizacao();
    
    setCompras(prev => prev.map(c => c.idCompra === idCompra ? { ...c, status: 'RECEBIDA', dataRecebida: new Date().toLocaleDateString('pt-BR') } : c));

    axios.put(`http://localhost:5000/api/compras/${idCompra}/baixa`)
      .then(() => {
        finalizarAtualizacao();
        carregarCompras(true);
        carregarPedidos(true); 
        carregarResumos();
      })
      .catch(error => {
        finalizarAtualizacao();
        console.error("Erro ao dar baixa na compra:", error);
        carregarCompras(true);
      });
  }

  const toggleSelecaoPedido = (pedido) => {
    if (!pedido) return;
    setPedidosSelecionados(prev => 
      prev.includes(pedido.id) ? prev.filter(id => id !== pedido.id) : [...prev, pedido.id]
    );
  }

  const toggleExpandirPedido = (idPedido) => {
    setPedidosExpandidos(prev => 
      prev.includes(idPedido) ? prev.filter(id => id !== idPedido) : [...prev, idPedido]
    )
  }

  const toggleExpandirCompra = (idCompra) => {
    setComprasExpandidas(prev => 
      prev.includes(idCompra) ? prev.filter(id => id !== idCompra) : [...prev, idCompra]
    )
  }

  const alternarStatusOf = (idPedido, idOf, novoStatus) => {
    iniciarAtualizacao();

    setPedidos(prevPedidos => {
      return prevPedidos.map(p => {
        if (p.id === idPedido) {
          const novosItens = p.itens.map(item => {
            if(item.id_numof === idOf) {
               return { ...item, statusOF: novoStatus, concluido: novoStatus === "Pronto" }
            }
            return item;
          });
          const todasConcluidas = novosItens.every(i => i.concluido)
          return { ...p, itens: novosItens, status: todasConcluidas ? 'Pronto' : 'Pendente' }
        }
        return p
      })
    })

    axios.put(`http://localhost:5000/api/pedidos/${idPedido}/itens/${idOf}/status`, { status: novoStatus })
    .then(() => {
      finalizarAtualizacao();
      carregarResumos()
    })
    .catch(error => {
      finalizarAtualizacao();
      console.error("Erro ao persistir status da OF no banco:", error)
      carregarPedidos(true)
    })
  }

  const handleBiparOF = async (e) => {
    if (e.key !== 'Enter') return;
    if (!ofBipador.trim()) return;

    iniciarAtualizacao();
    const numeroOF = ofBipador.trim();
    
    setOfBipador(""); 
    
    setPedidos(prevPedidos => {
      return prevPedidos.map(p => {
        let encontrouOF = false;
        const novosItens = p.itens.map(item => {
          if(String(item.id_numof) === numeroOF) {
             encontrouOF = true;
             return { ...item, statusOF: statusBipador, concluido: statusBipador === "Pronto" }
          }
          return item;
        });

        if (encontrouOF) {
          const todasConcluidas = novosItens.every(i => i.concluido)
          return { ...p, itens: novosItens, status: todasConcluidas ? 'Pronto' : 'Pendente' }
        }
        return p;
      })
    });

    try {
      await axios.put(`http://localhost:5000/api/ofs/status-rapido`, { 
        id_of: numeroOF, 
        status: statusBipador 
      });
      finalizarAtualizacao();
      setMsgBipador({ texto: `OF ${numeroOF} salva!`, tipo: 'success' });
      carregarResumos();
    } catch (error) {
      finalizarAtualizacao();
      console.error("Erro no Bipador:", error);
      setMsgBipador({ texto: `Erro na OF ${numeroOF}`, tipo: 'error' });
      carregarPedidos(true); 
    }

    setTimeout(() => setMsgBipador({texto: "", tipo: ""}), 3000); 
  }

  const alterarStatusPedido = (id, novoStatus) => {
    iniciarAtualizacao();

    setPedidos(prevPedidos => 
      prevPedidos.map(p => p.id === id ? { ...p, status: novoStatus } : p)
    );

    axios.put(`http://localhost:5000/api/pedidos/${id}/status`, { status: novoStatus })
      .then(() => {
        finalizarAtualizacao();
        carregarResumos()
      })
      .catch(error => {
        finalizarAtualizacao();
        console.error("Erro ao persistir status no banco:", error);
        carregarPedidos(true);
      });
  }

  const alterarAba = (novaAba) => {
    iniciarAtualizacao();
    setAbaAtiva(novaAba);
    finalizarAtualizacao();
  };

  const obterContadorOfs = (pedido) => {
    if (!pedido || !pedido.itens) return { concluidas: 0, total: 0 }
    const total = pedido.itens.length
    const concluidas = pedido.itens.filter(i => i.concluido).length
    return { concluidas, total }
  }

  const pedidosFiltrados = pedidos.filter(p => {
    if (!p) return false;
    const termo = termoPesquisa.toLowerCase();
    if (!termo) return true;

    const matchPedido = String(p.id_pedido || '').toLowerCase().includes(termo);
    const matchCliente = String(p.cliente || '').toLowerCase().includes(termo);
    const matchPC = String(p.pedido_cliente || '').toLowerCase().includes(termo);

    return matchPedido || matchCliente || matchPC;
  });

  const pedidosProntos = pedidosFiltrados.filter(p => p.status === 'Pronto')
  const pedidosEmAberto = pedidosFiltrados.filter(p => p.status !== 'Pronto')

  const renderizarTagPrazo = (dias, dataEntrega) => {
    if (dias === null || dias === undefined || isNaN(dias)) return <span className={t.textSecondary}>-</span>;
    
    let tag = null;
    if (dias < 0) {
      tag = (
        <span className={`inline-flex items-center gap-1.5 px-3 py-1 text-[11px] font-semibold rounded-full ${isDarkMode ? 'bg-red-500/10 text-red-400 border-red-500/20' : 'bg-red-100 text-red-700 border-red-300'} whitespace-nowrap`}>
          <span className="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse"></span>
          Atrasado ({Math.abs(dias)}d)
        </span>
      )
    } else if (dias === 0 || dias === 1) {
      tag = (
        <span className={`inline-flex items-center gap-1.5 px-3 py-1 text-[11px] font-semibold rounded-full ${isDarkMode ? 'bg-amber-500/10 text-amber-400 border-amber-500/20' : 'bg-amber-100 text-amber-700 border-amber-300'} whitespace-nowrap`}>
          <span className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse"></span>
          Prazo: {dias}d
        </span>
      )
    } else {
      tag = (
        <span className={`inline-flex items-center gap-1.5 px-3 py-1 text-[11px] font-semibold rounded-full ${t.bgAccentSoft} ${t.textAccent} border ${t.borderAccentSoft} whitespace-nowrap`}>
          <span className="w-1.5 h-1.5 rounded-full bg-[#5DD62C]"></span>
          Prazo: {dias}d
        </span>
      )
    }

    return (
      <div className="flex flex-col items-end sm:items-center gap-1">
        {tag}
        {dataEntrega && <span className={`text-[10px] ${t.textSecondary} whitespace-nowrap`}>Entrega: {dataEntrega}</span>}
      </div>
    )
  }

  const obterEstiloStatusCompleto = (status) => {
    const estilos = {
      'Pendente': isDarkMode ? 'bg-amber-500/10 text-amber-400 border-amber-500/20' : 'bg-amber-100 text-amber-700 border-amber-300',
      'Compras': isDarkMode ? 'bg-sky-500/10 text-sky-400 border-sky-500/20' : 'bg-sky-100 text-sky-700 border-sky-300',
      'Produção': isDarkMode ? 'bg-purple-500/10 text-purple-400 border-purple-500/20' : 'bg-purple-100 text-purple-700 border-purple-300',
      'Pronto': isDarkMode ? 'bg-[#5DD62C]/10 text-[#5DD62C] border-[#5DD62C]/20' : 'bg-[#5DD62C]/20 text-[#337418] border-[#337418]/30'
    }
    return estilos[status] || (isDarkMode ? 'bg-[#202020] text-[#A0A0A0] border-[#333333]' : 'bg-gray-100 text-gray-500 border-gray-200')
  }

  const renderCartaoCompra = (compra) => {
    const isExpanded = comprasExpandidas.includes(compra.idCompra);
    
    let todosClientes = [];
    if(compra.itens) {
      compra.itens.forEach(item => {
         if(item.ofs) {
           item.ofs.forEach(of => {
               if(of.cliente) todosClientes.push(of.cliente);
           });
         }
      });
    }
    const clientesUnicos = [...new Set(todosClientes)].join(", ");
    const isRecebida = compra.dataRecebida || compra.status === 'RECEBIDA';

    return (
      <div key={compra.idCompra} className={`${t.card} rounded-xl overflow-hidden shadow-lg transition-all ${t.ring}`}>
        <div 
           className={`p-5 flex flex-col md:flex-row justify-between items-start md:items-center gap-4 cursor-pointer ${t.hoverCard} transition-colors`} 
           onClick={() => toggleExpandirCompra(compra.idCompra)}
        >
          <div className="flex-1 min-w-[250px]">
            <div className="flex items-center gap-2 mb-1.5">
               <span className={`text-xs font-mono font-bold ${t.bgAccentSoft} ${t.textAccent} px-2 py-0.5 rounded border ${t.borderAccentSoft}`}>
                 OC: {compra.idCompra}
               </span>
               <span className={`text-[10px] px-2 py-0.5 rounded font-bold uppercase border ${!isRecebida ? (isDarkMode ? 'bg-amber-500/10 text-amber-400 border-amber-500/20' : 'bg-amber-100 text-amber-700 border-amber-300') : `${t.bgAccentSoft} ${t.textAccent} ${t.borderAccentSoft}`}`}>
                 {!isRecebida ? 'Em Compras' : 'Recebida'}
               </span>
            </div>
            <h3 className={`font-bold ${t.textPrimary} text-base leading-tight mt-1`}>{compra.fornecedor || 'Fornecedor Não Informado'}</h3>
          </div>
          
          <div className={`flex flex-wrap items-center gap-6 text-xs ${t.textSecondary} w-full md:w-auto justify-between md:justify-end border-t ${t.border} md:border-t-0 pt-3 md:pt-0`}>
            <div className="text-left md:text-center">
              <span className={`block text-[10px] ${t.textSecondary} uppercase mb-0.5`}>Emissão</span>
              <span className={`font-mono ${t.textPrimary}`}>{compra.dataEmissao || '-'}</span>
            </div>
            <div className="text-left md:text-center">
              <span className={`block text-[10px] ${t.textSecondary} uppercase mb-0.5`}>Previsão</span>
              <span className={`font-mono ${t.textPrimary}`}>{compra.dataPrevisao || '-'}</span>
            </div>
            <div className="text-left md:text-center">
              <span className={`block text-[10px] ${t.textSecondary} uppercase mb-0.5`}>Peso Total</span>
              <span className={`font-mono font-semibold ${t.textPrimary}`}>{formatarKg(compra.pesoTotalKg)} <span className={t.textAccent}>kg</span></span>
            </div>
            <div className="text-left md:text-center">
              <span className={`block text-[10px] ${t.textSecondary} uppercase mb-0.5`}>Valor Total</span>
              <span className={`font-mono font-semibold ${t.textPrimary}`}>R$ {(compra.valorTotal || 0).toLocaleString('pt-BR', {minimumFractionDigits: 2})}</span>
            </div>
            
            <div className={`pl-4 border-l ${t.border} flex items-center justify-end min-w-[140px]`}>
               {!isRecebida ? (
                 <button 
                   onClick={(e) => { e.stopPropagation(); darBaixaCompra(compra.idCompra); }} 
                   className="bg-[#5DD62C] hover:bg-[#337418] text-[#0F0F0F] hover:text-[#F8F8F8] text-xs font-bold px-4 py-2.5 rounded-lg shadow-lg transition-all transform hover:scale-105 w-full"
                 >
                   Dar Baixa (Receber NF)
                 </button>
               ) : (
                 <div className={`text-[11px] ${t.textSecondary} font-semibold flex flex-col items-end w-full`}>
                   <span className={`${t.textAccent} flex items-center gap-1`}>
                     <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M5 13l4 4L19 7" /></svg>
                     Baixa Realizada
                   </span>
                   <span className={t.textPrimary}>{compra.dataRecebida}</span>
                 </div>
               )}
            </div>
          </div>
        </div>
        
        <div className={`px-5 py-2.5 ${t.innerAlt} border-t ${t.border} text-xs flex justify-between items-center ${t.textSecondary}`}>
           <span className="truncate pr-4"><strong>Cliente(s):</strong> <span className={t.textPrimary}>{clientesUnicos || '-'}</span></span>
        </div>
        
        {isExpanded && (
          <div className={`${t.inner} p-5 border-t ${t.border}`}>
            <h4 className={`text-xs font-bold ${t.textSecondary} uppercase tracking-wider mb-4`}>
              Itens da Compra e OFs Vinculadas
            </h4>
            {compra.itens && compra.itens.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full text-left border-collapse text-xs">
                  <thead>
                    <tr className={`border-b ${t.border} ${t.textSecondary} uppercase font-mono ${isDarkMode ? 'bg-slate-950/50' : 'bg-gray-200/50'}`}>
                      <th className="py-3 px-3 rounded-tl-lg">OF (Nº Serial)</th>
                      <th className="py-3 px-3">Cliente</th>
                      <th className="py-3 px-3">Referência</th>
                      <th className="py-3 px-3 text-center">Qtd OF (Cx)</th>
                      <th className="py-3 px-3 text-center">Qtd Chapas</th>
                      <th className="py-3 px-3 text-right">Valor Total Item</th>
                      <th className="py-3 px-3 text-right">Peso Item</th>
                      <th className="py-3 px-3 text-center rounded-tr-lg">Status OF</th>
                    </tr>
                  </thead>
                  <tbody className={`divide-y ${t.divider} ${t.textPrimary}`}>
                    {compra.itens.map((itemGroup, idxGroup) => {
                      
                      if (!itemGroup.ofs || itemGroup.ofs.length === 0) {
                        return (
                          <tr key={`item-${idxGroup}`} className={`${t.hoverCard} transition-colors`}>
                             <td className={`py-3 px-3 font-mono font-bold ${t.textSecondary}`}>-</td>
                             <td className={`py-3 px-3 font-medium ${t.textSecondary}`}>-</td>
                             <td className={`py-3 px-3 font-medium ${t.textSecondary}`}>Item sem OF: {itemGroup.item}</td>
                             <td className="py-3 px-3 text-center font-mono">-</td>
                             <td className="py-3 px-3 text-center font-mono">{itemGroup.quantidadeChapa}</td>
                             <td className="py-3 px-3 text-right font-mono">R$ {itemGroup.vltot.toLocaleString('pt-BR', { minimumFractionDigits: 2 })}</td>
                             <td className={`py-3 px-3 text-right font-mono ${t.textAccent}`}>{formatarKg(itemGroup.pesoChapa)} kg</td>
                             <td className="py-3 px-3 text-center">-</td>
                          </tr>
                        )
                      }

                      return itemGroup.ofs.map((of, idxOf) => (
                        <tr key={`of-${idxGroup}-${idxOf}`} className={`${t.hoverCard} transition-colors`}>
                          <td className={`py-3 px-3 font-mono font-bold ${t.textAccent}`}>
                            OF {of.idOF}
                          </td>
                          <td className="py-3 px-3 font-medium">
                            {of.cliente || '-'}
                          </td>
                          <td className="py-3 px-3 font-medium">
                            {of.referencia || itemGroup.item}
                          </td>
                          <td className="py-3 px-3 text-center font-mono">
                            {of.quantOF}
                          </td>
                          <td className={`py-3 px-3 text-center font-mono ${t.textSecondary}`}>
                            {idxOf === 0 ? itemGroup.quantidadeChapa : '—'}
                          </td>
                          <td className="py-3 px-3 text-right font-mono">
                            {idxOf === 0 ? `R$ ${itemGroup.vltot.toLocaleString('pt-BR', { minimumFractionDigits: 2 })}` : '—'}
                          </td>
                          <td className={`py-3 px-3 text-right font-mono ${t.textAccent}`}>
                            {idxOf === 0 ? `${formatarKg(itemGroup.pesoChapa)} kg` : '—'}
                          </td>
                          <td className="py-3 px-3 text-center">
                             <span className={`px-2.5 py-1 rounded-full text-[11px] font-semibold border ${obterEstiloStatusCompleto(of.statusOF).replace('hover:', '')}`}>
                               {of.statusOF}
                             </span>
                          </td>
                        </tr>
                      ))
                    })}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className={`text-xs ${t.textSecondary} italic p-4 text-center`}>
                Nenhum item detalhado encontrado para esta compra.
              </div>
            )}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className={`min-h-screen ${t.bg} p-4 md:p-8 font-sans w-full transition-colors duration-300`}>
      
      {/* HEADER */}
      <header className={`w-full mx-auto mb-8 flex flex-col sm:flex-row justify-between items-start sm:items-center border-b ${t.border} pb-5 gap-4 relative z-10`}>
        <div>
          <h1 className={`text-2xl font-bold tracking-tight ${t.textPrimary}`}>FIVEL Control</h1>
          <p className={`${t.textSecondary} text-sm`}>Painel de Controle de Carga e Produção</p>
        </div>
        <div className="flex items-center gap-3">
          
          <button 
            onClick={() => setModalBipadorAberto(true)}
            className={`flex items-center gap-2 bg-[#5DD62C] hover:bg-[#337418] text-[#0F0F0F] hover:text-[#F8F8F8] px-4 py-2 rounded-xl border border-transparent shadow-sm hover:scale-105 transition-all text-xs font-bold`}
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 4v16m8-8H4" /></svg>
            Lançamento Rápido OF
          </button>

          <button 
            onClick={() => setIsDarkMode(!isDarkMode)}
            className={`flex items-center gap-2 ${t.card} px-4 py-2 rounded-xl border ${t.border} shadow-sm hover:scale-105 transition-all text-xs font-bold ${t.textSecondary} hover:${t.textPrimary}`}
          >
            {isDarkMode ? 'Modo Claro' : 'Modo Escuro'}
          </button>

          <div className={`flex items-center gap-2 ${t.card} px-4 py-2 rounded-xl border ${t.border} self-stretch sm:self-auto justify-center shadow-md`}>
            <span className="w-2.5 h-2.5 rounded-full bg-[#5DD62C] animate-pulse"></span>
            <span className={`text-xs font-medium ${t.textPrimary}`}>Monitor Logístico Ativo</span>
          </div>
        </div>
      </header>

      {/* MODAL BIPADOR */}
      {modalBipadorAberto && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className={`${t.card} border ${t.border} rounded-2xl shadow-2xl p-6 w-full max-w-md transform scale-100 transition-all`}>
            <div className="flex justify-between items-center mb-5">
              <h2 className={`text-lg font-bold ${t.textPrimary}`}>Lançamento Rápido de OF</h2>
              <button 
                onClick={() => setModalBipadorAberto(false)}
                className={`text-[#A0A0A0] hover:text-red-500 transition-colors`}
              >
                <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" /></svg>
              </button>
            </div>

            <div className="space-y-5">
              <div>
                <label className={`block text-xs font-bold ${t.textSecondary} uppercase tracking-wider mb-2`}>1. Escolha o Status</label>
                <div className="grid grid-cols-3 gap-2">
                  <button 
                    onClick={() => { setStatusBipador('Pendente'); inputBipadorRef.current.focus(); }}
                    className={`py-2 rounded-lg text-xs font-bold border transition-all ${statusBipador === 'Pendente' ? 'bg-amber-500/20 text-amber-500 border-amber-500/50' : `${t.inner} ${t.textSecondary} ${t.border}`}`}
                  >
                    PENDENTE
                  </button>
                  <button 
                    onClick={() => { setStatusBipador('Produção'); inputBipadorRef.current.focus(); }}
                    className={`py-2 rounded-lg text-xs font-bold border transition-all ${statusBipador === 'Produção' ? 'bg-purple-500/20 text-purple-500 border-purple-500/50' : `${t.inner} ${t.textSecondary} ${t.border}`}`}
                  >
                    PRODUÇÃO
                  </button>
                  <button 
                    onClick={() => { setStatusBipador('Pronto'); inputBipadorRef.current.focus(); }}
                    className={`py-2 rounded-lg text-xs font-bold border transition-all ${statusBipador === 'Pronto' ? 'bg-[#5DD62C]/20 text-[#5DD62C] border-[#5DD62C]/50' : `${t.inner} ${t.textSecondary} ${t.border}`}`}
                  >
                    PRONTO
                  </button>
                </div>
              </div>

              <div>
                <label className={`block text-xs font-bold ${t.textSecondary} uppercase tracking-wider mb-2`}>2. Digite ou Bipe a OF e tecle Enter</label>
                <input 
                  ref={inputBipadorRef}
                  type="text" 
                  value={ofBipador}
                  onChange={(e) => setOfBipador(e.target.value)}
                  onKeyDown={handleBiparOF}
                  placeholder="Nº da OF..."
                  className={`w-full ${t.inner} ${t.textPrimary} border ${t.border} rounded-xl px-4 py-3 text-lg font-mono font-bold focus:outline-none focus:border-[#5DD62C] focus:ring-1 focus:ring-[#5DD62C] transition-all`}
                />
                <p className={`text-[10px] mt-1.5 ${t.textSecondary}`}>O status será salvo instantaneamente.</p>
              </div>

              {msgBipador.texto && (
                <div className={`p-3 rounded-lg text-xs font-bold text-center animate-pulse ${msgBipador.tipo === 'success' ? 'bg-[#5DD62C]/10 text-[#5DD62C] border border-[#5DD62C]/20' : 'bg-red-500/10 text-red-500 border border-red-500/20'}`}>
                  {msgBipador.texto}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* SELETOR DE ABAS */}
      <div className={`w-full mx-auto mb-8 flex gap-2 border-b ${t.border} pb-px overflow-x-auto relative z-0`}>
        <button
          onClick={() => alterarAba('mapa')}
          className={`pb-3 px-4 font-medium text-sm transition-colors relative whitespace-nowrap ${abaAtiva === 'mapa' ? `${t.textAccent} border-b-2 ${t.borderAccent}` : `${t.textSecondary} hover:${t.textPrimary}`}`}
        >
          Geral e Mapa
        </button>
        <button
          onClick={() => alterarAba('prazos')}
          className={`pb-3 px-4 font-medium text-sm transition-colors relative whitespace-nowrap ${abaAtiva === 'prazos' ? `${t.textAccent} border-b-2 ${t.borderAccent}` : `${t.textSecondary} hover:${t.textPrimary}`}`}
        >
          Controle de Pedidos em Aberto
        </button>
        <button
          onClick={() => alterarAba('compras')}
          className={`pb-3 px-4 font-medium text-sm transition-colors relative whitespace-nowrap ${abaAtiva === 'compras' ? `${t.textAccent} border-b-2 ${t.borderAccent}` : `${t.textSecondary} hover:${t.textPrimary}`}`}
        >
          Gestão de Compras
        </button>
        <button
          onClick={() => alterarAba('dashboard')}
          className={`pb-3 px-4 font-medium text-sm transition-colors relative whitespace-nowrap ${abaAtiva === 'dashboard' ? `${t.textAccent} border-b-2 ${t.borderAccent}` : `${t.textSecondary} hover:${t.textPrimary}`}`}
        >
          Dashboard
        </button>
      </div>

      <main className="w-full mx-auto relative z-0">

        {/* ABA: COMPRAS */}
        {abaAtiva === 'compras' && (() => {
          const comprasEmAberto = compras.filter(c => !(c.dataRecebida || c.status === 'RECEBIDA'));
          const comprasRecebidas = compras.filter(c => c.dataRecebida || c.status === 'RECEBIDA');

          const valorTotalComprasAberto = comprasEmAberto.reduce((acc, c) => acc + (c.valorTotal || 0), 0);
          const pesoTotalComprasAberto = comprasEmAberto.reduce((acc, c) => acc + (c.pesoTotalKg || 0), 0);

          return (
            <div className="space-y-8 w-full">
              
              {/* BLOCOS DE DADOS NUMÉRICOS DE COMPRAS */}
              <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
                <div className={`${t.card} p-6 rounded-2xl shadow-md flex flex-col justify-center`}>
                  <p className={`text-[13px] font-medium ${t.textSecondary} mb-1.5 tracking-wide`}>Valor Total em Compras (Aberto)</p>
                  <p className={`text-3xl font-bold ${t.textPrimary} tracking-tight`}>
                    R$ {valorTotalComprasAberto.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                  </p>
                </div>
                
                <div className={`${t.card} p-6 rounded-2xl shadow-md flex flex-col justify-center`}>
                  <p className={`text-[13px] font-medium ${t.textSecondary} mb-1.5 tracking-wide`}>Volume de Chapas Total</p>
                  <p className={`text-3xl font-bold ${t.textPrimary} tracking-tight`}>
                    {formatarKg(pesoTotalComprasAberto)} <span className={`text-base font-medium ${t.textAccent} ml-1`}>kg</span>
                  </p>
                </div>

                <div className={`${t.card} p-6 rounded-2xl shadow-md flex flex-col justify-center`}>
                  <p className={`text-[13px] font-medium ${t.textSecondary} mb-1.5 tracking-wide`}>Compras em Aberto</p>
                  <p className={`text-3xl font-bold ${t.textPrimary} tracking-tight`}>{comprasEmAberto.length}</p>
                </div>
              </div>

              <div className={`flex justify-between items-center border-b ${t.border} pb-3`}>
                <div>
                   <h2 className={`text-xl font-bold ${t.textPrimary}`}>Gestão de Compras (Chapas)</h2>
                   <p className={`text-xs ${t.textSecondary}`}>Controle de recebimento de matéria-prima e vínculo de OFs</p>
                </div>
                <button 
                  onClick={() => carregarCompras(false)} 
                  className={`${t.card} border ${t.border} ${t.textPrimary} hover:${t.borderAccent} hover:${t.textAccent} px-4 py-2 rounded-lg text-xs font-semibold transition-colors shadow-sm`}
                >
                  Atualizar Compras
                </button>
              </div>
              
              {/* COMPRAS EM ABERTO */}
              <div className="space-y-4">
                <h3 className={`text-lg font-bold ${isDarkMode ? 'text-amber-400' : 'text-amber-600'} flex items-center gap-2`}>
                   <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
                   Compras em Aberto ({comprasEmAberto.length})
                </h3>
                <div className="grid grid-cols-1 gap-4">
                  {comprasEmAberto.map(compra => renderCartaoCompra(compra))}
                  {comprasEmAberto.length === 0 && !carregando && (
                    <div className={`p-8 text-center ${t.textSecondary} ${t.card} rounded-2xl border ${t.border}`}>
                      Nenhuma ordem de compra em aberto encontrada a partir do ID 1863.
                    </div>
                  )}
                </div>
              </div>

              {/* COMPRAS RECEBIDAS */}
              <div className={`space-y-4 pt-6 border-t ${t.border}`}>
                <h3 className={`text-lg font-bold ${t.textAccent} flex items-center gap-2`}>
                   <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
                   Compras Recebidas ({comprasRecebidas.length})
                </h3>
                <div className="grid grid-cols-1 gap-4 opacity-80 hover:opacity-100 transition-opacity">
                  {comprasRecebidas.map(compra => renderCartaoCompra(compra))}
                  {comprasRecebidas.length === 0 && !carregando && (
                    <div className={`p-8 text-center ${t.textSecondary} ${t.card} rounded-2xl border ${t.border}`}>
                      Nenhuma ordem de compra concluída encontrada a partir do ID 1863.
                    </div>
                  )}
                </div>
              </div>

            </div>
          );
        })()}

        {/* ABA: DASHBOARD & ANALYTICS */}
        {abaAtiva === 'dashboard' && (
          <div className="space-y-8 w-full">
            <div className={`flex justify-between items-center border-b ${t.border} pb-3`}>
              <h2 className={`text-xl font-bold ${t.textPrimary}`}>Indicadores Operacionais e Faturamento</h2>
              <span className={`text-xs ${t.textAccent} ${t.bgAccentSoft} border ${t.borderAccentSoft} px-3 py-1 rounded-full font-mono`}>
                Mês de Referência: {dadosDashboard.mes_referencia}
              </span>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
              <div className={`${t.card} p-6 rounded-2xl shadow-md flex flex-col justify-center relative overflow-hidden`}>
                <div className={`absolute top-0 right-0 w-2 h-full bg-[#5DD62C]`}></div>
                <p className={`text-[13px] font-medium ${t.textSecondary} mb-1.5 tracking-wide`}>Faturamento Faturado (Mês)</p>
                <p className={`text-3xl font-bold ${t.textPrimary} tracking-tight`}>
                  R$ {(dadosDashboard.faturamento_mes || 0).toLocaleString('pt-BR', { minimumFractionDigits: 2 })}
                </p>
              </div>

              <div className={`${t.card} p-6 rounded-2xl shadow-md flex flex-col justify-center relative overflow-hidden`}>
                <div className={`absolute top-0 right-0 w-2 h-full bg-sky-500`}></div>
                <p className={`text-[13px] font-medium ${t.textSecondary} mb-1.5 tracking-wide`}>Peso Expedido (Mês)</p>
                <p className={`text-3xl font-bold ${t.textPrimary} tracking-tight`}>
                  {formatarKg(dadosDashboard.peso_mes_kg)} <span className={`text-base font-medium ${t.textAccent} ml-1`}>kg</span>
                </p>
              </div>

              <div className={`${t.card} p-6 rounded-2xl shadow-md flex flex-col justify-center relative overflow-hidden`}>
                <div className={`absolute top-0 right-0 w-2 h-full bg-indigo-500`}></div>
                <p className={`text-[13px] font-medium ${t.textSecondary} mb-1.5 tracking-wide`}>Total de NFs Emitidas</p>
                <p className={`text-3xl font-bold ${t.textPrimary} tracking-tight`}>
                  {dadosDashboard.total_nfs_mes || 0}
                </p>
              </div>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              
              <div className={`${t.card} p-6 rounded-2xl shadow-md flex flex-col justify-between`}>
                <div>
                  <h3 className={`text-lg font-bold ${t.textPrimary} mb-5 border-b ${t.border} pb-2`}>Resumo da Carteira em Aberto</h3>
                  <div className="space-y-4">
                    <div className={`flex justify-between items-center ${t.inner} p-4 rounded-xl border ${t.border}`}>
                      <span className={`text-sm ${t.textSecondary}`}>Faturamento da Carteira</span>
                      <span className={`text-lg font-bold ${t.textPrimary} font-mono`}>
                        R$ {(dadosDashboard.faturamento_carteira || 0).toLocaleString('pt-BR', { minimumFractionDigits: 2 })}
                      </span>
                    </div>

                    <div className={`flex justify-between items-center ${t.inner} p-4 rounded-xl border ${t.border}`}>
                      <span className={`text-sm ${t.textSecondary}`}>Volume Total em Carga</span>
                      <span className={`text-lg font-bold ${t.textAccent} font-mono`}>
                        {formatarKg(dadosDashboard.peso_carteira_kg)} kg
                      </span>
                    </div>

                    <div className={`flex justify-between items-center ${t.inner} p-4 rounded-xl border ${t.border}`}>
                      <span className={`text-sm ${t.textSecondary}`}>Total de Pedidos Ativos</span>
                      <span className={`text-lg font-bold ${t.textPrimary} font-mono`}>
                        {dadosDashboard.total_pedidos_carteira || 0} pedidos
                      </span>
                    </div>
                  </div>
                </div>
              </div>

              <div className={`${t.card} p-6 rounded-2xl shadow-md`}>
                <h3 className={`text-lg font-bold ${t.textPrimary} mb-5 border-b ${t.border} pb-2`}>Distribuição Por Estágio (Kanban)</h3>
                
                <div className="space-y-5">
                  <div>
                    <div className="flex justify-between text-xs font-semibold mb-2">
                      <span className={t.textPrimary}>Pendente ({dadosDashboard.distribuicao_kanban.Pendente || 0})</span>
                      <span className={t.textSecondary}>
                        {dadosDashboard.total_pedidos_carteira ? Math.round(((dadosDashboard.distribuicao_kanban.Pendente || 0) / dadosDashboard.total_pedidos_carteira) * 100) : 0}%
                      </span>
                    </div>
                    <div className={`w-full ${t.inner} h-3 rounded-full overflow-hidden border ${t.border}`}>
                      <div 
                        className="bg-amber-500 h-full transition-all duration-500" 
                        style={{ width: `${dadosDashboard.total_pedidos_carteira ? ((dadosDashboard.distribuicao_kanban.Pendente || 0) / dadosDashboard.total_pedidos_carteira) * 100 : 0}%` }}
                      ></div>
                    </div>
                  </div>

                  <div>
                    <div className="flex justify-between text-xs font-semibold mb-2">
                      <span className={t.textPrimary}>Compras ({dadosDashboard.distribuicao_kanban.Compras || 0})</span>
                      <span className={t.textSecondary}>
                        {dadosDashboard.total_pedidos_carteira ? Math.round(((dadosDashboard.distribuicao_kanban.Compras || 0) / dadosDashboard.total_pedidos_carteira) * 100) : 0}%
                      </span>
                    </div>
                    <div className={`w-full ${t.inner} h-3 rounded-full overflow-hidden border ${t.border}`}>
                      <div 
                        className="bg-sky-500 h-full transition-all duration-500" 
                        style={{ width: `${dadosDashboard.total_pedidos_carteira ? ((dadosDashboard.distribuicao_kanban.Compras || 0) / dadosDashboard.total_pedidos_carteira) * 100 : 0}%` }}
                      ></div>
                    </div>
                  </div>

                  <div>
                    <div className="flex justify-between text-xs font-semibold mb-2">
                      <span className={t.textPrimary}>Produção ({dadosDashboard.distribuicao_kanban.Produção || 0})</span>
                      <span className={t.textSecondary}>
                        {dadosDashboard.total_pedidos_carteira ? Math.round(((dadosDashboard.distribuicao_kanban.Produção || 0) / dadosDashboard.total_pedidos_carteira) * 100) : 0}%
                      </span>
                    </div>
                    <div className={`w-full ${t.inner} h-3 rounded-full overflow-hidden border ${t.border}`}>
                      <div 
                        className="bg-purple-500 h-full transition-all duration-500" 
                        style={{ width: `${dadosDashboard.total_pedidos_carteira ? ((dadosDashboard.distribuicao_kanban.Produção || 0) / dadosDashboard.total_pedidos_carteira) * 100 : 0}%` }}
                      ></div>
                    </div>
                  </div>

                  <div>
                    <div className="flex justify-between text-xs font-semibold mb-2">
                      <span className={t.textPrimary}>Pronto ({dadosDashboard.distribuicao_kanban.Pronto || 0})</span>
                      <span className={t.textSecondary}>
                        {dadosDashboard.total_pedidos_carteira ? Math.round(((dadosDashboard.distribuicao_kanban.Pronto || 0) / dadosDashboard.total_pedidos_carteira) * 100) : 0}%
                      </span>
                    </div>
                    <div className={`w-full ${t.inner} h-3 rounded-full overflow-hidden border ${t.border}`}>
                      <div 
                        className="bg-[#5DD62C] h-full transition-all duration-500" 
                        style={{ width: `${dadosDashboard.total_pedidos_carteira ? ((dadosDashboard.distribuicao_kanban.Pronto || 0) / dadosDashboard.total_pedidos_carteira) * 100 : 0}%` }}
                      ></div>
                    </div>
                  </div>

                </div>
              </div>

            </div>
          </div>
        )}

        {/* ABA: MAPA E GERAL */}
        {abaAtiva === 'mapa' && (
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start w-full">
            
            <div className="lg:col-span-8 space-y-6 w-full">
              
              {/* BLOCOS DE DADOS NUMÉRICOS GERAIS */}
              <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
                <div className={`${t.card} p-6 rounded-2xl shadow-md flex flex-col justify-center`}>
                  <p className={`text-[13px] font-medium ${t.textSecondary} mb-1.5 tracking-wide`}>Faturamento Pronto</p>
                  <p className={`text-3xl font-bold ${t.textPrimary} tracking-tight`}>
                    R$ {(resumoMapa.faturamento_pronto || 0).toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                  </p>
                </div>
                
                <div className={`${t.card} p-6 rounded-2xl shadow-md flex flex-col justify-center`}>
                  <p className={`text-[13px] font-medium ${t.textSecondary} mb-1.5 tracking-wide`}>Peso Pronto</p>
                  <p className={`text-3xl font-bold ${t.textPrimary} tracking-tight`}>
                    {formatarKg(resumoMapa.peso_pronto_kg)} <span className={`text-base font-medium ${t.textAccent} ml-1`}>kg</span>
                  </p>
                </div>

                <div className={`${t.card} p-6 rounded-2xl shadow-md flex flex-col justify-center`}>
                  <p className={`text-[13px] font-medium ${t.textSecondary} mb-1.5 tracking-wide`}>Peso Entregue Mês</p>
                  <p className={`text-3xl font-bold ${t.textPrimary} tracking-tight`}>
                    {formatarKg(resumoMapa.peso_entregue_mes_kg)} <span className={`text-base font-medium ${t.textAccent} ml-1`}>kg</span>
                  </p>
                </div>
              </div>

              <div className={`${t.card} rounded-2xl shadow-md overflow-hidden w-full border ${t.border}`}>
                <div className={`p-5 border-b ${t.border} flex justify-between items-center ${t.card}`}>
                  <h2 className={`text-lg font-bold ${t.textPrimary}`}>Pedidos Prontos para Expedição</h2>
                  <span className={`${t.bgAccentSoft} ${t.textAccent} text-xs px-3 py-1.5 rounded-full font-bold border ${t.borderAccentSoft}`}>
                    {pedidosProntos.length} Prontos
                  </span>
                </div>
                <div className="overflow-x-auto w-full">
                  <table className="w-full text-left border-collapse min-w-[600px]">
                    <thead>
                      <tr className={`${t.inner} ${t.textSecondary} text-[11px] font-bold uppercase tracking-wider border-b ${t.border}`}>
                        <th className="p-4 w-16 text-center">Rota</th>
                        <th className="p-4">Pedido / Cliente</th>
                        <th className="p-4 text-center">Itens</th>
                        <th className="p-4 text-center">Peso</th>
                        <th className="p-4 text-center">Valor (R$)</th>
                        <th className="p-4 text-center">Status</th>
                      </tr>
                    </thead>
                    <tbody className={`divide-y ${t.divider} text-sm ${t.textPrimary}`}>
                      {pedidosProntos.map((pedido) => {
                        const pesoKg = (pedido.peso_total_kg ?? ((pedido.peso_total_ton || 0) * 1000));
                        return (
                          <tr key={pedido.id} className={`${t.hoverCard} transition-colors ${pedidosSelecionados.includes(pedido.id) ? (isDarkMode ? 'bg-[#5DD62C]/5' : 'bg-[#5DD62C]/10') : ''}`}>
                            <td className="p-4 text-center">
                              <label className="relative flex items-center justify-center cursor-pointer select-none group">
                                <input
                                  type="checkbox"
                                  checked={pedidosSelecionados.includes(pedido.id)}
                                  onChange={() => toggleSelecaoPedido(pedido)}
                                  className="sr-only peer"
                                />
                                <div className={`w-5 h-5 ${isDarkMode ? 'bg-[#0F0F0F]' : 'bg-white'} border ${t.border} rounded-md 
                                                flex items-center justify-center text-transparent 
                                                transition-all duration-200 ease-out
                                                peer-checked:bg-[#5DD62C] peer-checked:border-[#5DD62C] peer-checked:text-[#0F0F0F]
                                                group-hover:border-gray-500 peer-checked:group-hover:border-[#5DD62C]
                                                focus-within:ring-2 focus-within:ring-[#5DD62C]/50`}>
                                  <svg className="w-3.5 h-3.5 stroke-[3] transition-transform duration-200 scale-75 peer-checked:scale-100" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                    <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                                  </svg>
                                </div>
                              </label>
                            </td>
                            <td className="p-4 font-medium">
                              <div className="flex items-center gap-2">
                                <span className={`text-xs ${t.inner} px-2 py-0.5 rounded ${t.textSecondary} font-mono border ${t.border}`}>
                                  Nº {pedido.id_pedido} {pedido.pedido_cliente ? `PC ${pedido.pedido_cliente}` : ''}
                                </span>
                              </div>
                              <div className="mt-1 font-bold">{pedido.cliente || 'Sem Nome'}</div>
                              <span className={`block text-[11px] ${t.textSecondary}`}>{pedido.cidade_bloco || ''}</span>
                            </td>
                            <td className="p-4 text-center font-mono">{pedido.total_itens || 0}</td>
                            <td className={`p-4 text-center font-mono ${t.textAccent}`}>{formatarKg(pesoKg)} kg</td>
                            <td className="p-4 text-center font-mono font-medium">
                              R$ {(pedido.faturamento_total || 0).toLocaleString('pt-BR', { minimumFractionDigits: 2 })}
                            </td>
                            <td className="p-4 text-center">
                              <div className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-full border ${t.bgAccentSoft} ${t.textAccent} ${t.borderAccentSoft} text-[11px] font-bold`}>
                                <span>Pronto</span>
                              </div>
                            </td>
                          </tr>
                        )
                      })}
                      {pedidosProntos.length === 0 && (
                        <tr>
                          <td colSpan="6" className={`p-8 text-center ${t.textSecondary}`}>
                            Nenhum carregamento marcado como "Pronto" no momento.
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>

            <div className="lg:col-span-4 lg:sticky lg:top-6 w-full space-y-6">
              <div className={`${t.card} rounded-2xl shadow-md overflow-hidden flex flex-col h-[550px] w-full border ${t.border}`}>
                <div className={`p-5 border-b ${t.border} flex justify-between items-center`}>
                  <h2 className={`text-lg font-bold ${t.textPrimary}`}>Mapa de Fluxo de Entregas</h2>
                  <span className={`text-xs ${t.textSecondary}`}>Rota Unificada OSRM</span>
                </div>
                <div className={`h-full w-full relative z-10 ${t.bg}`}>
                  <MapContainer center={COORDENADAS_EMPRESA} zoom={10} className="h-full w-full">
                    <RedimensionarMapa />
                    <TileLayer
                      attribution='&copy; OpenStreetMap &copy; CARTO'
                      url={isDarkMode ? "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png" : "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"}
                    />
                    
                    <Marker position={COORDENADAS_EMPRESA}>
                      <Popup>
                        <div className="text-gray-900 p-1">
                          <strong className="text-[#337418]">Minha Empresa</strong><br />
                          <span className="text-xs text-gray-600">Ponto de Partida</span>
                        </div>
                      </Popup>
                    </Marker>

                    {pedidosProntos.map((pedido) => {
                      const temPosicao = pedido && pedido.latitude && pedido.longitude;
                      const pesoKg = (pedido.peso_total_kg ?? ((pedido.peso_total_ton || 0) * 1000));
                      return temPosicao && (
                        <Marker key={pedido.id} position={[pedido.latitude, pedido.longitude]}>
                          <Popup>
                            <div className="text-gray-900 p-1">
                              <strong className="text-base">{pedido.cliente || 'Sem Nome'}</strong><br />
                              <span className="text-xs text-gray-600">{pedido.cidade_bloco || ''}</span>
                              <hr className="my-1 border-gray-200" />
                              <p className="text-xs m-0"><strong>Ped:</strong> Nº {pedido.id_pedido}</p>
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
                        pathOptions={{ color: '#5DD62C', weight: 5, opacity: 0.95 }} 
                      />
                    )}

                    {rotaVoltaGeometria.length > 0 && (
                      <Polyline
                        key={`volta-${pedidosSelecionados.join('-')}`}
                        positions={rotaVoltaGeometria}
                        pathOptions={{ color: '#337418', weight: 5, opacity: 0.95 }} 
                      />
                    )}
                  </MapContainer>
                </div>
              </div>

              <div className={`${t.card} p-6 rounded-2xl shadow-md w-full border ${t.border}`}>
                <div className={`border-b ${t.border} pb-3 mb-5`}>
                  <h2 className={`text-lg font-bold ${t.textPrimary}`}>Logística LIFO Otimizada</h2>
                  <p className={`text-xs ${t.textSecondary}`}>Sequenciamento físico estruturado</p>
                </div>
                
                <div className="space-y-6 text-sm">
                  <div>
                    <span className={`block text-[11px] font-bold ${t.textSecondary} uppercase tracking-wider mb-4`}>
                      Ordem de Entrega (Menor Rota)
                    </span>
                    <div className="flex flex-col gap-3">
                      {ordemEntregas.length > 0 ? (
                        ordemEntregas.map((id, index) => {
                          const pedido = pedidos.find(p => p && p.id === id);
                          const pesoKg = (pedido?.peso_total_kg ?? ((pedido?.peso_total_ton || 0) * 1000));
                          return (
                            <div key={id} className={`flex items-center justify-between p-3.5 ${t.inner} border ${t.border} rounded-xl ${t.hoverBorderAccent} transition-colors`}>
                              <div className="flex items-center gap-3.5">
                                <span className={`w-7 h-7 rounded-full ${t.bgAccentSoft} ${t.textAccent} font-mono text-xs flex items-center justify-center font-bold border ${t.borderAccentSoft}`}>
                                  {index + 1}
                                </span>
                                <div>
                                  <div className={`font-bold ${t.textPrimary} text-sm`}>{pedido?.cliente || 'Cliente'}</div>
                                  <div className={`text-[11px] ${t.textSecondary} font-mono mt-0.5`}>
                                    Nº {pedido?.id_pedido} {pedido?.pedido_cliente ? `PC ${pedido.pedido_cliente}` : ''}
                                  </div>
                                </div>
                              </div>
                              <span className={`text-xs font-mono ${t.textAccent} font-bold`}>
                                {formatarKg(pesoKg)} kg
                              </span>
                            </div>
                          )
                        })
                      ) : (
                        <div className={`p-5 text-center text-[12px] ${t.textSecondary} ${t.inner} rounded-xl border ${t.border}`}>
                          Selecione um ou mais pedidos na tabela para calcular a rota.
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* ABA: CONTROLE DE PEDIDOS EM ABERTO */}
        {abaAtiva === 'prazos' && (
          <div className="space-y-8 w-full relative z-0">
            
            {/* BLOCOS DE DADOS NUMÉRICOS GERAIS */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
              <div className={`${t.card} p-6 rounded-2xl shadow-md flex flex-col justify-center`}>
                <p className={`text-[13px] font-medium ${t.textSecondary} mb-1.5 tracking-wide`}>Faturamento Acumulado</p>
                <p className={`text-3xl font-bold ${t.textPrimary} tracking-tight`}>
                  R$ {(resumoPedidos.faturamento_acumulado || 0).toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                </p>
              </div>
              
              <div className={`${t.card} p-6 rounded-2xl shadow-md flex flex-col justify-center`}>
                <p className={`text-[13px] font-medium ${t.textSecondary} mb-1.5 tracking-wide`}>Volume de Carga Total</p>
                <p className={`text-3xl font-bold ${t.textPrimary} tracking-tight`}>
                  {formatarKg(resumoPedidos.volume_carga_total_kg)} <span className={`text-base font-medium ${t.textAccent} ml-1`}>kg</span>
                </p>
              </div>

              <div className={`${t.card} p-6 rounded-2xl shadow-md flex flex-col justify-center`}>
                <p className={`text-[13px] font-medium ${t.textSecondary} mb-1.5 tracking-wide`}>Pedidos Ativos</p>
                <p className={`text-3xl font-bold ${t.textPrimary} tracking-tight`}>{resumoPedidos.pedidos_ativos || 0}</p>
              </div>
            </div>

            <div className={`${t.card} rounded-2xl shadow-md p-6 w-full border ${t.border}`}>
              <div className={`flex flex-col md:flex-row justify-between items-start md:items-center mb-6 gap-4 border-b ${t.border} pb-5`}>
                <div>
                  <h2 className={`text-xl font-bold ${t.textPrimary}`}>Pedidos em Aberto</h2>
                  <p className={`text-xs ${t.textSecondary} mt-1`}>Gerencie status, OFs e itens de cada pedido em tempo real</p>
                </div>

                {/* BARRA DE FERRAMENTAS: PESQUISA, ORDENAÇÃO E EXIBIÇÃO EM UMA LINHA */}
                <div className={`flex flex-col xl:flex-row items-center gap-3 w-full xl:w-auto`}>
                  
                  <div className="relative w-full xl:w-64 flex-shrink-0">
                    <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                      <svg className={`w-4 h-4 ${t.textSecondary}`} fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" /></svg>
                    </div>
                    <input
                      type="text"
                      value={termoPesquisa}
                      onChange={(e) => setTermoPesquisa(e.target.value)}
                      placeholder="Pesquisar pedido ou cliente..."
                      className={`w-full pl-9 pr-3 py-2 bg-transparent border ${t.border} rounded-lg text-xs ${t.textPrimary} focus:outline-none focus:border-[#5DD62C] placeholder-${isDarkMode ? 'gray-500' : 'gray-400'}`}
                    />
                  </div>

                  <div className="flex w-full xl:w-auto justify-between xl:justify-start items-center gap-3">
                    <div className="flex items-center gap-2 whitespace-nowrap">
                      <span className={`text-xs ${t.textSecondary} font-bold hidden sm:inline uppercase tracking-wider`}>Ordenar:</span>
                      <select
                        value={ordenarPor}
                        onChange={(e) => setOrdenarPor(e.target.value)}
                        className={`${t.card} text-xs font-bold ${t.textPrimary} border ${t.border} rounded-lg px-3 py-2 focus:outline-none focus:${t.borderAccent} cursor-pointer`}
                      >
                        <option value="prazo">Dias Restantes (Prazo)</option>
                        <option value="id_pedido">Número do Pedido</option>
                        <option value="emissao">Data de Emissão</option>
                        <option value="data_entrega">Data de Entrega</option>
                      </select>

                      <select
                        value={ordem}
                        onChange={(e) => setOrdem(e.target.value)}
                        className={`${t.card} text-xs font-bold ${t.textPrimary} border ${t.border} rounded-lg px-3 py-2 focus:outline-none focus:${t.borderAccent} cursor-pointer`}
                      >
                        <option value="asc">Crescente (A-Z)</option>
                        <option value="desc">Decrescente (Z-A)</option>
                      </select>
                    </div>

                    <div className={`flex items-center ${t.card} p-1 rounded-lg border ${t.border} flex-shrink-0`}>
                      <button
                        onClick={() => setModoExibicao('lista')}
                        title="Exibir em Lista"
                        className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-bold rounded-md transition-colors ${modoExibicao === 'lista' ? 'bg-[#337418] text-[#F8F8F8]' : `${t.textSecondary} hover:${t.textPrimary}`}`}
                      >
                        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 6h16M4 12h16M4 18h16" />
                        </svg>
                        Lista
                      </button>
                      <button
                        onClick={() => setModoExibicao('grade')}
                        title="Exibir em Grade"
                        className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-bold rounded-md transition-colors ${modoExibicao === 'grade' ? 'bg-[#337418] text-[#F8F8F8]' : `${t.textSecondary} hover:${t.textPrimary}`}`}
                      >
                        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2V6zM14 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V6zM4 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2v-2zM14 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z" />
                        </svg>
                        Grade
                      </button>
                    </div>
                  </div>
                </div>
              </div>

              {carregando ? (
                <div className={`p-12 text-center ${t.textSecondary}`}>Carregando dados dos pedidos...</div>
              ) : (
                <div className={modoExibicao === 'lista' ? 'flex flex-col gap-3' : 'grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5'}>
                  {pedidosEmAberto.map((pedido) => {
                    const estaExpandido = pedidosExpandidos.includes(pedido.id)
                    const { concluidas, total } = obterContadorOfs(pedido)
                    const todasConcluidas = total > 0 && concluidas === total
                    const pesoKg = (pedido.peso_total_kg ?? ((pedido.peso_total_ton || 0) * 1000))

                    return modoExibicao === 'lista' ? (
                      <div key={pedido.id} className={`${t.inner} rounded-xl border ${t.border} ${t.hoverBorderAccent} transition-all overflow-hidden`}>
                        <div className="p-4 flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
                          
                          <div className="flex items-start gap-4 flex-1 min-w-[240px]">
                            <button
                              onClick={() => toggleExpandirPedido(pedido.id)}
                              className={`mt-1 p-1.5 ${t.card} ${t.hoverCard} border ${t.border} rounded-lg ${t.textSecondary} hover:${t.textPrimary} transition-colors`}
                              title="Expandir itens do pedido"
                            >
                              <svg className={`w-4 h-4 transition-transform duration-200 ${estaExpandido ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 9l-7 7-7-7" />
                              </svg>
                            </button>

                            <div>
                              <div className="flex items-center gap-2 mb-1.5 flex-wrap">
                                <span className={`text-xs ${t.card} ${t.textSecondary} px-2.5 py-0.5 rounded-md font-mono font-bold border ${t.border}`}>
                                  Nº {pedido.id_pedido} {pedido.pedido_cliente ? `PC ${pedido.pedido_cliente}` : ''}
                                </span>

                                <span className={`text-[11px] px-2 py-0.5 rounded-md font-mono font-bold border ${todasConcluidas ? `${t.bgAccentSoft} ${t.textAccent} ${t.borderAccentSoft}` : `${t.card} ${t.textSecondary} ${t.border}`}`}>
                                  OFs: {concluidas}/{total}
                                </span>
                              </div>
                              <h3 className={`font-bold ${t.textPrimary} text-base leading-tight`}>{pedido.cliente}</h3>
                              <p className={`text-[11px] ${t.textSecondary} mt-1`}>{pedido.cidade_bloco} {pedido.endereco_completo ? `• ${pedido.endereco_completo}` : ''}</p>
                            </div>
                          </div>

                          <div className={`flex items-center gap-8 text-xs text-gray-300 w-full md:w-auto justify-between md:justify-end border-t ${t.border} md:border-t-0 pt-4 md:pt-0`}>
                            <div className="text-left md:text-center">
                              <span className={`block text-[10px] ${t.textSecondary} uppercase tracking-wider mb-0.5`}>Itens</span>
                              <span className={`font-mono font-bold ${t.textPrimary}`}>{pedido.total_itens || 0}</span>
                            </div>

                            <div className="text-left md:text-center">
                              <span className={`block text-[10px] ${t.textSecondary} uppercase tracking-wider mb-0.5`}>Peso</span>
                              <span className={`font-mono font-bold ${t.textAccent}`}>{formatarKg(pesoKg)} kg</span>
                            </div>

                            <div className="text-left md:text-center">
                              <span className={`block text-[10px] ${t.textSecondary} uppercase tracking-wider mb-0.5`}>Emissão</span>
                              <span className={`font-mono ${t.textPrimary}`}>{pedido.data_emissao || '-'}</span>
                            </div>

                            <div>
                              {renderizarTagPrazo(pedido.dias_restantes, pedido.data_entrega)}
                            </div>
                          </div>

                          <div className={`flex items-center gap-3 w-full md:w-auto justify-end border-t ${t.border} md:border-t-0 pt-4 md:pt-0`}>
                            <select
                              value={pedido.status || 'Pendente'}
                              onChange={(e) => alterarStatusPedido(pedido.id, e.target.value)}
                              className={`text-[11px] font-bold rounded-lg px-3 py-2 border transition-all cursor-pointer focus:outline-none ${obterEstiloStatusCompleto(pedido.status)}`}
                            >
                              <option value="Pendente" className={`${t.card} text-amber-500`}>Pendente</option>
                              <option value="Pronto" className={`${t.card} ${t.textAccent}`}>Pronto</option>
                            </select>
                          </div>

                        </div>

                        {estaExpandido && (
                          <div className={`${t.innerAlt} p-5 border-t ${t.border}`}>
                            <h4 className={`text-[11px] font-bold ${t.textSecondary} uppercase tracking-wider mb-4`}>
                              Itens do Pedido / Ordens de Fabricação (OFs)
                            </h4>
                            {pedido.itens && pedido.itens.length > 0 ? (
                              <div className="overflow-x-auto">
                                <table className="w-full text-left border-collapse text-xs">
                                  <thead>
                                    <tr className={`border-b ${t.border} ${t.textSecondary} uppercase font-mono`}>
                                      <th className="py-2.5 px-3">OF (Nº Serial)</th>
                                      <th className="py-2.5 px-3">Referência</th>
                                      <th className="py-2.5 px-3 text-center">Quantidade</th>
                                      <th className="py-2.5 px-3 text-right">Valor Unit.</th>
                                      <th className="py-2.5 px-3 text-right">Peso Item</th>
                                      <th className="py-2.5 px-3 text-center">Fechamento</th>
                                      <th className="py-2.5 px-3 text-center">Status OF</th>
                                    </tr>
                                  </thead>
                                  <tbody className={`divide-y ${t.divider} text-gray-300`}>
                                    {pedido.itens.map((item, idx) => {
                                      const numeroOf = item.id_numof || '-';
                                      const pesoItemKg = item.peso_item || 0;

                                      return (
                                        <tr key={idx} className={`${t.hoverCard} transition-colors`}>
                                          <td className={`py-3 px-3 font-mono font-bold ${t.textAccent}`}>
                                            {numeroOf.toString().startsWith("ITEM") ? numeroOf : `OF ${numeroOf}`}
                                          </td>
                                          <td className={`py-3 px-3 font-medium ${t.textPrimary}`}>
                                            {item.referencia || item.id_produto || '-'}
                                          </td>
                                          <td className={`py-3 px-3 text-center font-mono ${t.textPrimary}`}>
                                            {item.quantidade}
                                          </td>
                                          <td className={`py-3 px-3 text-right font-mono ${t.textPrimary}`}>
                                            R$ {(item.preco_unitario || 0).toLocaleString('pt-BR', { minimumFractionDigits: 2 })}
                                          </td>
                                          <td className={`py-3 px-3 text-right font-mono ${t.textAccent}`}>
                                            {formatarKg(pesoItemKg)} kg
                                          </td>
                                          <td className={`py-3 px-3 text-center font-mono ${t.textSecondary}`}>
                                            {item.fecha || '-'}
                                          </td>
                                          <td className="py-3 px-3 text-center">
                                            <select
                                              value={item.statusOF || 'Pendente'}
                                              onChange={(e) => alternarStatusOf(pedido.id, item.id_numof, e.target.value)}
                                              className={`text-[10px] font-bold rounded-full px-2.5 py-1.5 border cursor-pointer focus:outline-none ${obterEstiloStatusCompleto(item.statusOF)}`}
                                            >
                                              <option value="Pendente" className={`${t.card} text-amber-500`}>O Pendente</option>
                                              <option value="Compras" className={`${t.card} text-sky-500`}>Compras</option>
                                              <option value="Produção" className={`${t.card} text-purple-500`}>Produção</option>
                                              <option value="Pronto" className={`${t.card} ${t.textAccent}`}>✓ Concluído</option>
                                            </select>
                                          </td>
                                        </tr>
                                      )
                                    })}
                                  </tbody>
                                </table>
                              </div>
                            ) : (
                              <div className={`text-xs ${t.textSecondary} italic p-4 text-center`}>
                                Nenhum item detalhado encontrado para este pedido.
                              </div>
                            )}
                          </div>
                        )}                          

                      </div>
                    ) : (
                      <div key={pedido.id} className={`${t.inner} p-5 rounded-2xl border ${t.border} flex flex-col justify-between ${t.hoverBorderAccent} transition-colors`}>
                        <div>
                          <div className="flex justify-between items-start mb-3 gap-2">
                            <div>
                              <div className="flex items-center gap-2 flex-wrap mb-2">
                                <span className={`text-[11px] ${t.card} ${t.textSecondary} px-2.5 py-0.5 rounded-md font-mono font-bold border ${t.border}`}>
                                  Nº {pedido.id_pedido} {pedido.pedido_cliente ? `PC ${pedido.pedido_cliente}` : ''}
                                </span>
                                
                                <span className={`text-[10px] px-2 py-0.5 rounded-md font-mono font-bold border ${todasConcluidas ? `${t.bgAccentSoft} ${t.textAccent} ${t.borderAccentSoft}` : `${t.card} ${t.textSecondary} ${t.border}`}`}>
                                  OFs: {concluidas}/{total}
                                </span>
                              </div>
                              <h3 className={`font-bold ${t.textPrimary} text-base leading-tight`}>{pedido.cliente}</h3>
                              <p className={`text-[11px] ${t.textSecondary} mt-1`}>{pedido.cidade_bloco}</p>
                            </div>
                            <div>{renderizarTagPrazo(pedido.dias_restantes, pedido.data_entrega)}</div>
                          </div>

                          <div className={`my-4 py-3 border-y ${t.border} grid grid-cols-3 gap-2 text-center text-xs`}>
                            <div>
                              <span className={`block text-[10px] ${t.textSecondary} uppercase tracking-wider mb-1`}>Itens</span>
                              <span className={`font-mono font-bold ${t.textPrimary}`}>{pedido.total_itens || 0}</span>
                            </div>
                            <div>
                              <span className={`block text-[10px] ${t.textSecondary} uppercase tracking-wider mb-1`}>Peso</span>
                              <span className={`font-mono font-bold ${t.textAccent}`}>{formatarKg(pesoKg)} kg</span>
                            </div>
                            <div>
                              <span className={`block text-[10px] ${t.textSecondary} uppercase tracking-wider mb-1`}>Emissão</span>
                              <span className={`font-mono ${t.textPrimary}`}>{pedido.data_emissao || '-'}</span>
                            </div>
                          </div>
                        </div>

                        <div className="space-y-4 pt-1">
                          <button
                            onClick={() => toggleExpandirPedido(pedido.id)}
                            className={`w-full py-2 px-3 ${t.card} ${t.hoverCard} border ${t.border} rounded-lg text-xs font-bold ${t.textSecondary} hover:${t.textPrimary} flex items-center justify-center gap-2 transition-colors`}
                          >
                            <span>{estaExpandido ? 'Ocultar OFs' : 'Ver OFs do Pedido'}</span>
                            <svg className={`w-3.5 h-3.5 transition-transform duration-200 ${estaExpandido ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 9l-7 7-7-7" />
                            </svg>
                          </button>

                          {estaExpandido && (
                            <div className={`${t.card} p-3 rounded-xl border ${t.border} text-xs space-y-2 max-h-60 overflow-y-auto`}>
                              {pedido.itens && pedido.itens.length > 0 ? (
                                pedido.itens.map((item, idx) => {
                                  const pesoItemKg = item.peso_item || 0;
                                  const numeroOf = item.id_numof || '-';

                                  return (
                                    <div key={idx} className={`p-3 ${t.inner} border ${t.border} rounded-lg flex flex-col gap-2`}>
                                      <div className="flex justify-between items-center font-mono">
                                        <span className={`font-bold ${t.textAccent}`}>
                                           {numeroOf.toString().startsWith("ITEM") ? numeroOf : `OF ${numeroOf}`}
                                        </span>
                                        <span className={`text-[10px] ${t.textSecondary}`}>Fech: {item.fecha || '-'}</span>
                                      </div>
                                      <div className={`font-bold ${t.textPrimary} truncate`}>{item.referencia || item.id_produto}</div>
                                      <div className={`flex justify-between items-center text-[11px] ${t.textSecondary}`}>
                                        <span>Qtd: <span className={t.textPrimary}>{item.quantidade}</span></span>
                                        <span className={`${t.textAccent} font-mono font-bold`}>{formatarKg(pesoItemKg)} kg</span>
                                      </div>
                                      <select
                                        value={item.statusOF || 'Pendente'}
                                        onChange={(e) => alternarStatusOf(pedido.id, item.id_numof, e.target.value)}
                                        className={`w-full py-1.5 mt-1 rounded-md text-[10px] font-bold border transition-all cursor-pointer focus:outline-none ${obterEstiloStatusCompleto(item.statusOF)}`}
                                      >
                                        <option value="Pendente" className={`${t.card} text-amber-500`}>O Pendente</option>
                                        <option value="Compras" className={`${t.card} text-sky-500`}>Compras</option>
                                        <option value="Produção" className={`${t.card} text-purple-500`}>Produção</option>
                                        <option value="Pronto" className={`${t.card} ${t.textAccent}`}>✓ Concluído</option>
                                      </select>
                                    </div>
                                  )
                                })
                              ) : (
                                <div className={`${t.textSecondary} text-center py-3 italic text-[11px]`}>Nenhum item encontrado.</div>
                              )}
                            </div>
                          )}

                          <div className={`flex items-center justify-between pt-3 border-t ${t.border}`}>
                            <span className={`text-[11px] ${t.textSecondary} font-bold uppercase tracking-wider`}>Status Pedido:</span>
                            <select
                              value={pedido.status || 'Pendente'}
                              onChange={(e) => alterarStatusPedido(pedido.id, e.target.value)}
                              className={`text-[11px] font-bold rounded-lg px-3 py-1.5 border transition-all cursor-pointer focus:outline-none ${obterEstiloStatusCompleto(pedido.status).replace('hover:', '')}`}
                            >
                              <option value="Pendente" className={`${t.card} text-amber-500`}>Pendente</option>
                              <option value="Pronto" className={`${t.card} ${t.textAccent}`}>Pronto</option>
                            </select>
                          </div>
                        </div>
                      </div>
                    )
                  })}

                  {pedidosEmAberto.length === 0 && (
                    <div className={`col-span-full p-8 text-center ${t.textSecondary} ${t.card} rounded-2xl border ${t.border}`}>
                      {termoPesquisa ? 'Nenhum pedido encontrado com esse termo.' : 'Nenhum pedido em aberto encontrado.'}
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