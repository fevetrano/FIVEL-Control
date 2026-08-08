import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react'
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
const API_URL = 'http://192.168.1.34:5000'

function RedimensionarMapa() {
  const map = useMap();
  useEffect(() => { 
    setTimeout(() => map.invalidateSize(), 100); 
  }, [map]);
  return null;
}

function App() {
  const [isDarkMode, setIsDarkMode] = useState(true); 
  const [pedidos, setPedidos] = useState([])
  const [orcamentos, setOrcamentos] = useState([])
  const [compras, setCompras] = useState([])
  const [carregando, setCarregando] = useState(true)
  const [abaAtiva, setAbaAtiva] = useState('prazos') 
  const [pedidosSelecionados, setPedidosSelecionados] = useState([]) 
  const [rotaIdaGeometria, setRotaIdaGeometria] = useState([]) 
  const [rotaVoltaGeometria, setRotaVoltaGeometria] = useState([]) 
  const [ordemEntregas, setOrdemEntregas] = useState([]) 
  const [limiteExibicao, setLimiteExibicao] = useState(20)
  
  const [modoPesoAberto, setModoPesoAberto] = useState('total');
  const [filtroStatusPedido, setFiltroStatusPedido] = useState('aberto'); // Aberto vs Faturado
  
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
    distribuicao_kanban: { Pendente: 0, Compras: 0, Produção: 0, Pronto: 0, Parcial: 0, Faturada: 0 },
    mes_referencia: ''
  })

  const [ordenarPor, setOrdenarPor] = useState('prazo') 
  const [ordem, setOrdem] = useState('asc') 
  const [modoExibicao, setModoExibicao] = useState('lista') 
  const [termoPesquisa, setTermoPesquisa] = useState("");
  const [termoPesquisaOrcamento, setTermoPesquisaOrcamento] = useState("");
  
  const [modalBipadorAberto, setModalBipadorAberto] = useState(false);
  const [statusBipador, setStatusBipador] = useState('Produção');
  const [ofBipador, setOfBipador] = useState("");
  const [msgBipador, setMsgBipador] = useState({ texto: "", tipo: "" });
  
  const inputBipadorRef = useRef(null);
  const [pedidosExpandidos, setPedidosExpandidos] = useState([])
  const [comprasExpandidas, setComprasExpandidas] = useState([])
  const [orcamentosExpandidos, setOrcamentosExpandidos] = useState([])
  const [editandoNotaOrcamento, setEditandoNotaOrcamento] = useState(null)
  const [textoNotaTemp, setTextoNotaTemp] = useState("")

  const abortControllerOSRM = useRef(null)
  const isUpdatingRef = useRef(false);
  const fallbackTimerRef = useRef(null);

  const iniciarAtualizacao = () => {
    isUpdatingRef.current = true;
    if (fallbackTimerRef.current) clearTimeout(fallbackTimerRef.current);
    fallbackTimerRef.current = setTimeout(() => { isUpdatingRef.current = false; }, 8000); 
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
    hoverBorderAccent: isDarkMode ? 'hover:border-[#5DD62C]/50' : 'hover:border-[#337418]/50', 
    divider: isDarkMode ? 'divide-[#333333]' : 'divide-gray-200',
    ring: isDarkMode ? 'hover:ring-[#333333]' : 'hover:ring-gray-300'
  };

  const formatarKg = (valor) => {
    if (!valor || isNaN(valor)) return '0'
    return Math.round(valor).toLocaleString('pt-BR')
  }

  const carregarPedidos = useCallback((silencioso = false) => {
    if (silencioso && isUpdatingRef.current) return;
    if (!silencioso) setCarregando(true)
    
    axios.get(`${API_URL}/api/pedidos?ordenar_por=${ordenarPor}&ordem=${ordem}`)
      .then(response => {
        if (isUpdatingRef.current) return; 
        setPedidos(Array.isArray(response.data) ? response.data : [])
        if (!silencioso) setCarregando(false)
      })
      .catch(error => { 
        console.error("Erro API Pedidos:", error); 
        if (!silencioso) setCarregando(false) 
      })
  }, [ordenarPor, ordem])

  const carregarCompras = useCallback((silencioso = false) => {
    if (silencioso && isUpdatingRef.current) return;
    axios.get(`${API_URL}/api/compras`).then(res => { 
      if (!isUpdatingRef.current) setCompras(Array.isArray(res.data) ? res.data : []) 
    })
  }, [])

  const carregarOrcamentos = useCallback((silencioso = false) => {
    if (silencioso && isUpdatingRef.current) return;
    axios.get(`${API_URL}/api/orcamentos`).then(res => { 
      if (!isUpdatingRef.current) setOrcamentos(Array.isArray(res.data) ? res.data : []) 
    })
  }, [])

  const salvarNotaOrcamento = (idOrcamento) => {
    iniciarAtualizacao();
    axios.put(`${API_URL}/api/orcamentos/${idOrcamento}/nota`, { anotacao: textoNotaTemp })
      .then(res => {
         finalizarAtualizacao();
         setOrcamentos(prev => prev.map(o => o.id_orcamento === idOrcamento ? { ...o, anotacao: textoNotaTemp, data_anotacao: res.data.data_atualizacao } : o));
         setEditandoNotaOrcamento(null);
      })
      .catch(err => {
         finalizarAtualizacao();
         console.error("Erro ao salvar nota", err);
      });
  }

  const carregarResumos = useCallback(() => {
    Promise.all([ 
      axios.get(`${API_URL}/api/resumo/mapa`), 
      axios.get(`${API_URL}/api/resumo/dashboard`) 
    ]).then(([resMapa, resDash]) => {
        setResumoMapa(prev => ({ 
          ...prev, 
          peso_entregue_mes_kg: resMapa.data?.peso_entregue_mes_kg || 0 
        }))
        
        if (resDash.data) {
          setDadosDashboard(prev => ({
            ...prev, 
            faturamento_mes: resDash.data.faturamento_mes, 
            peso_mes_kg: resDash.data.peso_mes_kg,
            total_nfs_mes: resDash.data.total_nfs_mes, 
            mes_referencia: resDash.data.mes_referencia
          }))
        }
      }).catch(err => console.error("Erro API Resumos:", err))
  }, [])

  useEffect(() => {
    const pedidosAtivosGerais = pedidos.filter(p => p.status !== 'Faturada');
    const fatAcumulado = pedidosAtivosGerais.reduce((acc, p) => acc + (p.faturamento_total || 0), 0);
    const pesoTotal = pedidosAtivosGerais.reduce((acc, p) => acc + (p.peso_total_kg || 0), 0);
    
    let fatPronto = 0, pesoPronto = 0;
    const distrib = { Pendente: 0, Compras: 0, Produção: 0, Parcial: 0, Pronto: 0, Faturada: 0 };
    
    pedidos.forEach(p => {
      if (p.status === 'Pronto') { 
        fatPronto += (p.faturamento_total || 0); 
        pesoPronto += (p.peso_total_kg || 0); 
      }
      p.itens.forEach(item => { 
        if (distrib[item.statusOF] !== undefined) distrib[item.statusOF]++; 
      });
    });

    setResumoMapa(prev => ({ 
      ...prev, 
      faturamento_pronto: fatPronto, 
      peso_pronto_kg: pesoPronto 
    }));
    
    setDadosDashboard(prev => ({ 
      ...prev, 
      faturamento_carteira: fatAcumulado, 
      peso_carteira_kg: pesoTotal, 
      total_pedidos_carteira: pedidosAtivosGerais.length, 
      distribuicao_kanban: distrib 
    }));
  }, [pedidos]);

  useEffect(() => {
    carregarPedidos(); 
    carregarCompras(); 
    carregarOrcamentos();
    carregarResumos();
    
    const intervalId = setInterval(() => { 
      carregarPedidos(true); 
      carregarCompras(true); 
      carregarOrcamentos(true);
      carregarResumos(); 
    }, 5000)
    
    return () => clearInterval(intervalId)
  }, [carregarPedidos, carregarCompras, carregarOrcamentos, carregarResumos])

  useEffect(() => { 
    setLimiteExibicao(20); 
  }, [termoPesquisa, termoPesquisaOrcamento, abaAtiva, filtroStatusPedido, modoPesoAberto]);

  useEffect(() => { 
    if (modalBipadorAberto && inputBipadorRef.current) inputBipadorRef.current.focus(); 
  }, [modalBipadorAberto]);

  const calcularDistancia = (coord1, coord2) => {
    if (!coord1 || !coord2) return 0;
    const R = 6371; 
    const dLat = (coord2[0] - coord1[0]) * Math.PI / 180;
    const dLon = (coord2[1] - coord1[1]) * Math.PI / 180;
    const a = Math.sin(dLat/2) * Math.sin(dLat/2) + Math.cos(coord1[0] * Math.PI / 180) * Math.cos(coord2[0] * Math.PI / 180) * Math.sin(dLon/2) * Math.sin(dLon/2);
    return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
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

    if (abortControllerOSRM.current) abortControllerOSRM.current.abort();
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
        const waypointsOrdenados = [...res.data.waypoints].sort((a, b) => a.waypoint_index - b.waypoint_index).filter(wp => wp.waypoint_index !== 0);
        
        const ordemCalculada = waypointsOrdenados.map(wp => {
            const idxOriginal = wp.trips_index !== undefined ? wp.trips_index : wp.waypoint_index;
            return pedidosParaRota[idxOriginal - 1] ? pedidosParaRota[idxOriginal - 1].id : null;
        }).filter(id => id !== null); 

        setOrdemEntregas(ordemCalculada);
        const ultimoPedidoId = ordemCalculada[ordemCalculada.length - 1];
        const ultimoPedido = pedidosParaRota.find(p => p.id === ultimoPedidoId);

        if (ultimoPedido) {
          const coordUltimoCliente = [ultimoPedido.latitude, ultimoPedido.longitude];
          let indiceCorte = 0, menorDistancia = Infinity;
          
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
      if (!axios.isCancel(err)) console.error("Erro OSRM:", err); 
    }
  }, [pedidos]);

  useEffect(() => { 
    calcularRotaOtimizada(pedidosSelecionados, pedidos); 
  }, [pedidosSelecionados, pedidos, calcularRotaOtimizada]);

  const darBaixaCompra = (idCompra) => {
    iniciarAtualizacao();
    setCompras(prev => prev.map(c => c.idCompra === idCompra ? { ...c, status: 'RECEBIDA', dataRecebida: new Date().toLocaleDateString('pt-BR') } : c));
    
    axios.put(`${API_URL}/api/compras/${idCompra}/baixa`)
      .then(() => { 
        finalizarAtualizacao(); 
        carregarCompras(true); 
        carregarPedidos(true); 
        carregarResumos(); 
      })
      .catch(() => { 
        finalizarAtualizacao(); 
        carregarCompras(true); 
      });
  }

  const toggleSelecaoPedido = (pedido) => {
    if (!pedido) return;
    setPedidosSelecionados(prev => prev.includes(pedido.id) ? prev.filter(id => id !== pedido.id) : [...prev, pedido.id]);
  }
  
  const toggleExpandirPedido = (idPedido) => { 
    setPedidosExpandidos(prev => prev.includes(idPedido) ? prev.filter(id => id !== idPedido) : [...prev, idPedido]) 
  }
  
  const toggleExpandirCompra = (idCompra) => { 
    setComprasExpandidas(prev => prev.includes(idCompra) ? prev.filter(id => id !== idCompra) : [...prev, idCompra]) 
  }

  const toggleExpandirOrcamento = (idOrcamento) => { 
    setOrcamentosExpandidos(prev => prev.includes(idOrcamento) ? prev.filter(id => id !== idOrcamento) : [...prev, idOrcamento]) 
  }

  const alternarStatusOf = (idPedido, idOf, novoStatus) => {
    iniciarAtualizacao();
    
    setPedidos(prevPedidos => {
      return prevPedidos.map(p => {
        if (p.id === idPedido) {
          const novosItens = p.itens.map(item => item.id_numof === idOf ? { ...item, statusOF: novoStatus, concluido: (novoStatus === "Pronto" || novoStatus === "Faturada") } : item);
          const abertos = novosItens.filter(i => i.statusOF !== "Faturada");
          const todasConcluidas = abertos.length > 0 && abertos.every(i => i.statusOF === "Pronto");
          return { ...p, itens: novosItens, status: todasConcluidas ? 'Pronto' : 'Pendente' }
        }
        return p
      })
    })
    
    axios.put(`${API_URL}/api/pedidos/${idPedido}/itens/${idOf}/status`, { status: novoStatus })
      .then(() => { 
        finalizarAtualizacao(); 
        carregarResumos() 
      })
      .catch(() => { 
        finalizarAtualizacao(); 
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
            return { ...item, statusOF: statusBipador, concluido: (statusBipador === "Pronto" || statusBipador === "Faturada") } 
          }
          return item;
        });
        
        if (encontrouOF) {
          const abertos = novosItens.filter(i => i.statusOF !== "Faturada");
          const todasConcluidas = abertos.length > 0 && abertos.every(i => i.statusOF === "Pronto");
          return { ...p, itens: novosItens, status: todasConcluidas ? 'Pronto' : 'Pendente' }
        }
        return p;
      })
    });

    try {
      await axios.put(`${API_URL}/api/ofs/status-rapido`, { id_of: numeroOF, status: statusBipador });
      finalizarAtualizacao(); 
      setMsgBipador({ texto: `OF ${numeroOF} salva!`, tipo: 'success' }); 
      carregarResumos();
    } catch (error) {
      finalizarAtualizacao(); 
      setMsgBipador({ texto: `Erro na OF ${numeroOF}`, tipo: 'error' }); 
      carregarPedidos(true); 
    }
    setTimeout(() => setMsgBipador({texto: "", tipo: ""}), 3000); 
  }

  const alterarStatusPedido = (id, novoStatus) => {
    iniciarAtualizacao();
    setPedidos(prevPedidos => prevPedidos.map(p => p.id === id ? { ...p, status: novoStatus } : p));
    
    axios.put(`${API_URL}/api/pedidos/${id}/status`, { status: novoStatus })
      .then(() => { 
        finalizarAtualizacao(); 
        carregarResumos() 
      })
      .catch(() => { 
        finalizarAtualizacao(); 
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
    const validas = pedido.itens.filter(i => i.statusOF !== "Faturada")
    return { 
      concluidas: validas.filter(i => i.statusOF === "Pronto").length, 
      total: validas.length 
    }
  }

  const calcularTempoProducao = (dataProdStr) => {
    if (!dataProdStr) return { texto: 'INÍCIO NÃO REGISTRADO', dias: 0 };
    const d = new Date(dataProdStr.replace(" ", "T"));
    if (isNaN(d)) return { texto: 'INÍCIO NÃO REGISTRADO', dias: 0 };
    
    const diffTime = Math.abs(new Date() - d);
    const diffDays = Math.floor(diffTime / (1000 * 60 * 60 * 24));
    const dataFormatada = d.toLocaleDateString('pt-BR');
    
    if (diffDays === 0) return { texto: `HOJE (${dataFormatada})`, dias: 0 };
    if (diffDays === 1) return { texto: `1 DIA (${dataFormatada})`, dias: 1 };
    return { texto: `${diffDays} DIAS (${dataFormatada})`, dias: diffDays };
  }

  const calcularTempoOrcamento = (dataStr) => {
    if (!dataStr) return { texto: 'N/A', dias: 0 };
    const d = new Date(dataStr.replace(" ", "T"));
    if (isNaN(d)) return { texto: 'N/A', dias: 0 };
    
    const diffTime = Math.abs(new Date() - d);
    const diffDays = Math.floor(diffTime / (1000 * 60 * 60 * 24));
    
    if (diffDays === 0) return { texto: `Emitido Hoje`, dias: 0 };
    if (diffDays === 1) return { texto: `Ontem`, dias: 1 };
    return { texto: `Há ${diffDays} Dias`, dias: diffDays };
  }

  const pedidosFiltrados = useMemo(() => {
    return pedidos.filter(p => {
      if (!p) return false;
      const termo = termoPesquisa.toLowerCase();
      if (!termo) return true;
      return String(p.id_pedido || '').toLowerCase().includes(termo) || 
             String(p.cliente || '').toLowerCase().includes(termo) || 
             String(p.pedido_cliente || '').toLowerCase().includes(termo);
    });
  }, [pedidos, termoPesquisa]);

  // FILTRO INTELIGENTE GERAL PARA A TELA DE CONTROLE DE PEDIDOS
  const pedidosAbaControle = useMemo(() => {
     let filtrados = pedidosFiltrados;
     
     if (filtroStatusPedido === 'aberto') {
         filtrados = filtrados.filter(p => p.status !== 'Faturada');
     } else {
         filtrados = filtrados.filter(p => p.status === 'Faturada');
     }

     if (filtroStatusPedido === 'aberto' && modoPesoAberto === 'mes') {
         const endOfMonth = new Date();
         endOfMonth.setFullYear(endOfMonth.getFullYear(), endOfMonth.getMonth() + 1, 0);
         const endOfMonthStr = endOfMonth.toISOString().split('T')[0];
         filtrados = filtrados.filter(p => p.raw_entrega && p.raw_entrega <= endOfMonthStr);
     }

     return filtrados;
  }, [pedidosFiltrados, filtroStatusPedido, modoPesoAberto]);

  const pedidosAbaControlePaginados = useMemo(() => pedidosAbaControle.slice(0, limiteExibicao), [pedidosAbaControle, limiteExibicao]);
  
  // Mapa só usa pedidos prontos "Em Aberto" com itens ativos
  const pedidosProntosParaMapa = useMemo(() => pedidos.filter(p => p.status === 'Pronto' && p.total_itens_abertos > 0), [pedidos]);

  // Orcamentos Filtrados
  const orcamentosFiltrados = useMemo(() => {
    return orcamentos.filter(o => {
       if (!o) return false;
       const termo = termoPesquisaOrcamento.toLowerCase();
       if (!termo) return true;
       return String(o.id_orcamento || '').toLowerCase().includes(termo) || 
              String(o.cliente || '').toLowerCase().includes(termo) || 
              String(o.comprador || '').toLowerCase().includes(termo);
    }).slice(0, limiteExibicao);
  }, [orcamentos, termoPesquisaOrcamento, limiteExibicao]);

  const renderizarTagPrazo = (dias, dataEntrega) => {
    if (dias === null || dias === undefined || isNaN(dias)) return <span className={t.textSecondary}>-</span>;
    let tag = null;
    
    if (dias < 0) {
      tag = <span className={`inline-flex items-center gap-1.5 px-3 py-1 text-[11px] font-semibold rounded-full ${isDarkMode ? 'bg-red-500/10 text-red-400 border-red-500/20' : 'bg-red-100 text-red-700 border-red-300'} whitespace-nowrap`}><span className="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse"></span>Atrasado ({Math.abs(dias)}d)</span>
    } else if (dias === 0 || dias === 1) {
      tag = <span className={`inline-flex items-center gap-1.5 px-3 py-1 text-[11px] font-semibold rounded-full ${isDarkMode ? 'bg-amber-500/10 text-amber-400 border-amber-500/20' : 'bg-amber-100 text-amber-700 border-amber-300'} whitespace-nowrap`}><span className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse"></span>Prazo: {dias}d</span>
    } else {
      tag = <span className={`inline-flex items-center gap-1.5 px-3 py-1 text-[11px] font-semibold rounded-full ${t.bgAccentSoft} ${t.textAccent} border ${t.borderAccentSoft} whitespace-nowrap`}><span className="w-1.5 h-1.5 rounded-full bg-[#5DD62C]"></span>Prazo: {dias}d</span>
    }
    
    return (
      <div className="flex flex-col md:items-end items-start sm:items-center gap-1">
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
      'Parcial': isDarkMode ? 'bg-teal-500/10 text-teal-400 border-teal-500/20' : 'bg-teal-100 text-teal-700 border-teal-300',
      'Pronto': isDarkMode ? 'bg-[#5DD62C]/10 text-[#5DD62C] border-[#5DD62C]/20' : 'bg-[#5DD62C]/20 text-[#337418] border-[#337418]/30',
      'Faturada': isDarkMode ? 'bg-gray-500/10 text-gray-400 border-gray-500/20 opacity-75' : 'bg-gray-200 text-gray-600 border-gray-300 opacity-75'
    }
    return estilos[status] || (isDarkMode ? 'bg-[#202020] text-[#A0A0A0] border-[#333333]' : 'bg-gray-100 text-gray-500 border-gray-200')
  }

  const renderCartaoCompra = (compra) => {
    const isExpanded = comprasExpandidas.includes(compra.idCompra);
    let todosClientes = [];
    
    if(compra.itens) {
      compra.itens.forEach(item => { 
        if(item.ofs) item.ofs.forEach(of => { 
          if(of.cliente) todosClientes.push(of.cliente); 
        }); 
      });
    }
    const clientesUnicos = [...new Set(todosClientes)].join(", ");
    const isRecebida = compra.dataRecebida || compra.status === 'RECEBIDA';

    return (
      <div key={compra.idCompra} className={`${t.card} rounded-xl overflow-hidden shadow-lg transition-all ${t.ring}`}>
        <div className={`p-4 md:p-5 flex flex-col md:flex-row justify-between items-start md:items-center gap-4 cursor-pointer ${t.hoverCard} transition-colors`} onClick={() => toggleExpandirCompra(compra.idCompra)}>
          <div className="flex-1 min-w-[250px] w-full">
            <div className="flex items-center gap-2 mb-1.5 flex-wrap">
               <span className={`text-xs font-mono font-bold ${t.bgAccentSoft} ${t.textAccent} px-2 py-0.5 rounded border ${t.borderAccentSoft}`}>OC: {compra.idCompra}</span>
               <span className={`text-[10px] px-2 py-0.5 rounded font-bold uppercase border ${!isRecebida ? (isDarkMode ? 'bg-amber-500/10 text-amber-400 border-amber-500/20' : 'bg-amber-100 text-amber-700 border-amber-300') : `${t.bgAccentSoft} ${t.textAccent} ${t.borderAccentSoft}`}`}>{!isRecebida ? 'Em Compras' : 'Recebida'}</span>
            </div>
            <h3 className={`font-bold ${t.textPrimary} text-base leading-tight mt-1`}>{compra.fornecedor || 'Fornecedor Não Informado'}</h3>
          </div>
          
          <div className={`flex flex-wrap items-center gap-4 md:gap-6 text-xs ${t.textSecondary} w-full md:w-auto justify-between md:justify-end border-t ${t.border} md:border-t-0 pt-3 md:pt-0`}>
            <div className="text-left md:text-center w-[45%] md:w-auto">
              <span className="block text-[10px] uppercase mb-0.5">Emissão</span>
              <span className={`font-mono ${t.textPrimary}`}>{compra.dataEmissao || '-'}</span>
            </div>
            <div className="text-left md:text-center w-[45%] md:w-auto">
              <span className="block text-[10px] uppercase mb-0.5">Previsão</span>
              <span className={`font-mono ${t.textPrimary}`}>{compra.dataPrevisao || '-'}</span>
            </div>
            <div className="text-left md:text-center w-[45%] md:w-auto">
              <span className="block text-[10px] uppercase mb-0.5">Peso Total</span>
              <span className={`font-mono font-semibold ${t.textPrimary}`}>{formatarKg(compra.pesoTotalKg)} <span className={t.textAccent}>kg</span></span>
            </div>
            <div className="text-left md:text-center w-[45%] md:w-auto">
              <span className="block text-[10px] uppercase mb-0.5">Valor Total</span>
              <span className={`font-mono font-semibold ${t.textPrimary}`}>R$ {(compra.valorTotal || 0).toLocaleString('pt-BR', {minimumFractionDigits: 2})}</span>
            </div>
            
            <div className={`pt-3 md:pt-0 md:pl-4 border-t md:border-t-0 md:border-l ${t.border} flex items-center justify-end w-full md:w-auto md:min-w-[140px]`}>
               {!isRecebida ? (
                 <button onClick={(e) => { e.stopPropagation(); darBaixaCompra(compra.idCompra); }} className="bg-[#5DD62C] hover:bg-[#337418] text-[#0F0F0F] hover:text-[#F8F8F8] text-xs font-bold px-4 py-3 md:py-2.5 rounded-lg shadow-lg hover:scale-105 w-full text-center transition-all">
                   Dar Baixa
                 </button>
               ) : (
                 <div className={`text-[11px] ${t.textSecondary} font-semibold flex flex-row md:flex-col items-center md:items-end justify-between w-full`}>
                   <span className={`${t.textAccent} flex items-center gap-1`}><svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M5 13l4 4L19 7" /></svg>Baixa Realizada</span>
                   <span className={t.textPrimary}>{compra.dataRecebida}</span>
                 </div>
               )}
            </div>
          </div>
        </div>
        
        <div className={`px-4 md:px-5 py-2.5 ${t.innerAlt} border-t ${t.border} text-xs flex justify-between items-center ${t.textSecondary}`}>
           <span className="truncate pr-4"><strong>Cliente(s):</strong> <span className={t.textPrimary}>{clientesUnicos || '-'}</span></span>
        </div>
        
        {isExpanded && (
          <div className={`${t.inner} p-4 md:p-5 border-t ${t.border}`}>
            <h4 className={`text-xs font-bold ${t.textSecondary} uppercase tracking-wider mb-4`}>Itens da Compra e OFs Vinculadas</h4>
            {compra.itens && compra.itens.length > 0 ? (
              <div className="overflow-x-auto w-full scrollbar-hide">
                <table className="w-full text-left border-collapse text-xs min-w-[600px]">
                  <thead>
                    <tr className={`border-b ${t.border} ${t.textSecondary} uppercase font-mono ${isDarkMode ? 'bg-slate-950/50' : 'bg-gray-200/50'}`}>
                      <th className="py-3 px-3">OF (OF)</th>
                      <th className="py-3 px-3">Cliente</th>
                      <th className="py-3 px-3">Referência</th>
                      <th className="py-3 px-3 text-center">Qtd OF</th>
                      <th className="py-3 px-3 text-center">Qtd Chapas</th>
                      <th className="py-3 px-3 text-right">Valor Item</th>
                      <th className="py-3 px-3 text-right">Peso Item</th>
                      <th className="py-3 px-3 text-center">Status OF</th>
                    </tr>
                  </thead>
                  <tbody className={`divide-y ${t.divider} ${t.textPrimary}`}>
                    {compra.itens.map((itemGroup, idxGroup) => {
                      if (!itemGroup.ofs || itemGroup.ofs.length === 0) {
                        return (
                          <tr key={`item-${idxGroup}`} className={`${t.hoverCard}`}>
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
                        <tr key={`of-${idxGroup}-${idxOf}`} className={`${t.hoverCard}`}>
                          <td className={`py-3 px-3 font-mono font-bold ${t.textAccent}`}>OF {of.idOF}</td>
                          <td className="py-3 px-3 font-medium">{of.cliente || '-'}</td>
                          <td className="py-3 px-3 font-medium">{of.referencia || itemGroup.item}</td>
                          <td className="py-3 px-3 text-center font-mono">{of.quantOF}</td>
                          <td className={`py-3 px-3 text-center font-mono ${t.textSecondary}`}>{idxOf === 0 ? itemGroup.quantidadeChapa : '—'}</td>
                          <td className="py-3 px-3 text-right font-mono">{idxOf === 0 ? `R$ ${itemGroup.vltot.toLocaleString('pt-BR', { minimumFractionDigits: 2 })}` : '—'}</td>
                          <td className={`py-3 px-3 text-right font-mono ${t.textAccent}`}>{idxOf === 0 ? `${formatarKg(itemGroup.pesoChapa)} kg` : '—'}</td>
                          <td className="py-3 px-3 text-center">
                            <span className={`px-2.5 py-1 rounded-full text-[11px] font-semibold border whitespace-nowrap ${obterEstiloStatusCompleto(of.statusOF).replace('hover:', '')}`}>
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
              <div className={`text-xs ${t.textSecondary} italic p-4 text-center`}>Nenhum item detalhado encontrado.</div>
            )}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className={`min-h-screen ${t.bg} p-2 md:p-4 lg:p-8 font-sans w-full transition-colors duration-300`}>
      
      {/* HEADER */}
      <header className={`w-full mx-auto mb-6 flex flex-col sm:flex-row justify-between items-start sm:items-center border-b ${t.border} pb-5 gap-4 relative z-10`}>
        <div className="flex items-center gap-3.5">
          <img src="/logo.svg" alt="FIVEL Control Logo" className="w-10 h-10 object-contain" />
          <div>
            <h1 className={`text-2xl font-bold tracking-tight ${t.textPrimary}`}>FIVEL Control</h1>
            <p className={`${t.textSecondary} text-sm`}>Painel de Controle de Carga e Produção</p>
          </div>
        </div>
        
        <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-3 w-full sm:w-auto">
          
          <button onClick={() => setModalBipadorAberto(true)} className={`flex items-center justify-center gap-2 bg-[#5DD62C] hover:bg-[#337418] text-[#0F0F0F] hover:text-[#F8F8F8] px-4 py-3 sm:py-2 rounded-xl border border-transparent shadow-sm hover:scale-105 transition-all text-xs font-bold w-full sm:w-auto`}>
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 4v16m8-8H4" /></svg>
            Lançador de OFs
          </button>
          
          <button onClick={() => setIsDarkMode(!isDarkMode)} className={`flex items-center justify-center gap-2 ${t.card} px-4 py-3 sm:py-2 rounded-xl border ${t.border} shadow-sm hover:scale-105 transition-all text-xs font-bold ${t.textSecondary} hover:${t.textPrimary} w-full sm:w-auto`}>
            {isDarkMode ? 'Modo Claro' : 'Modo Escuro'}
          </button>
          
          <div className={`flex items-center gap-2 ${t.card} px-4 py-3 sm:py-2 rounded-xl border ${t.border} justify-center shadow-md w-full sm:w-auto`}>
            <span className="w-2.5 h-2.5 rounded-full bg-[#5DD62C] animate-pulse"></span>
            <span className={`text-xs font-medium ${t.textPrimary}`}>Monitor Ativo</span>
          </div>
        </div>
      </header>

      {/* MODAL BIPADOR */}
      {modalBipadorAberto && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
          <div className={`${t.card} border ${t.border} rounded-2xl shadow-2xl p-6 w-full max-w-lg transform scale-100 transition-all`}>
            <div className="flex justify-between items-center mb-5">
              <h2 className={`text-lg font-bold ${t.textPrimary}`}>Lançamento Rápido de OF</h2>
              <button onClick={() => setModalBipadorAberto(false)} className={`text-[#A0A0A0] hover:text-red-500 transition-colors p-2`}>
                <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" /></svg>
              </button>
            </div>
            
            <div className="space-y-5">
              <div>
                <label className={`block text-xs font-bold ${t.textSecondary} uppercase tracking-wider mb-2`}>1. Escolha o Status</label>
                <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
                  <button onClick={() => { setStatusBipador('Pendente'); inputBipadorRef.current.focus(); }} className={`py-3 sm:py-2 rounded-lg text-[11px] font-bold border transition-all ${statusBipador === 'Pendente' ? 'bg-amber-500/20 text-amber-500 border-amber-500/50' : `${t.inner} ${t.textSecondary} ${t.border}`}`}>PENDENTE</button>
                  <button onClick={() => { setStatusBipador('Produção'); inputBipadorRef.current.focus(); }} className={`py-3 sm:py-2 rounded-lg text-[11px] font-bold border transition-all ${statusBipador === 'Produção' ? 'bg-purple-500/20 text-purple-500 border-purple-500/50' : `${t.inner} ${t.textSecondary} ${t.border}`}`}>PRODUÇÃO</button>
                  <button onClick={() => { setStatusBipador('Parcial'); inputBipadorRef.current.focus(); }} className={`py-3 sm:py-2 rounded-lg text-[11px] font-bold border transition-all ${statusBipador === 'Parcial' ? 'bg-teal-500/20 text-teal-500 border-teal-500/50' : `${t.inner} ${t.textSecondary} ${t.border}`}`}>PARCIAL</button>
                  <button onClick={() => { setStatusBipador('Pronto'); inputBipadorRef.current.focus(); }} className={`py-3 sm:py-2 rounded-lg text-[11px] font-bold border transition-all ${statusBipador === 'Pronto' ? 'bg-[#5DD62C]/20 text-[#5DD62C] border-[#5DD62C]/50' : `${t.inner} ${t.textSecondary} ${t.border}`}`}>PRONTO</button>
                  <button onClick={() => { setStatusBipador('Faturada'); inputBipadorRef.current.focus(); }} className={`py-3 sm:py-2 rounded-lg text-[11px] font-bold border transition-all ${statusBipador === 'Faturada' ? 'bg-gray-500/20 text-gray-400 border-gray-500/50' : `${t.inner} ${t.textSecondary} ${t.border}`}`}>FATURADA</button>
                </div>
              </div>
              
              <div>
                <label className={`block text-xs font-bold ${t.textSecondary} uppercase tracking-wider mb-2`}>2. Digite ou Bipe a OF e tecle Enter</label>
                <input ref={inputBipadorRef} type="text" value={ofBipador} onChange={(e) => setOfBipador(e.target.value)} onKeyDown={handleBiparOF} placeholder="Nº da OF..." className={`w-full ${t.inner} ${t.textPrimary} border ${t.border} rounded-xl px-4 py-4 sm:py-3 text-lg font-mono font-bold focus:outline-none focus:border-[#5DD62C] transition-all`} />
                <p className={`text-[10px] mt-1.5 ${t.textSecondary}`}>O status será salvo instantaneamente em toda a rede.</p>
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
      <div className={`w-full mx-auto mb-6 sm:mb-8 flex gap-2 border-b ${t.border} pb-px overflow-x-auto relative z-0 scrollbar-hide`}>
        <button onClick={() => alterarAba('mapa')} className={`pb-3 px-4 font-medium text-sm transition-colors relative whitespace-nowrap ${abaAtiva === 'mapa' ? `${t.textAccent} border-b-2 ${t.borderAccent}` : `${t.textSecondary} hover:${t.textPrimary}`}`}>Expedição e Mapa</button>
        <button onClick={() => alterarAba('producao')} className={`pb-3 px-4 font-medium text-sm transition-colors relative whitespace-nowrap ${abaAtiva === 'producao' ? `${t.textAccent} border-b-2 ${t.borderAccent}` : `${t.textSecondary} hover:${t.textPrimary}`}`}>Produção</button>
        <button onClick={() => alterarAba('prazos')} className={`pb-3 px-4 font-medium text-sm transition-colors relative whitespace-nowrap ${abaAtiva === 'prazos' ? `${t.textAccent} border-b-2 ${t.borderAccent}` : `${t.textSecondary} hover:${t.textPrimary}`}`}>Pedidos</button>
        <button onClick={() => alterarAba('orcamentos')} className={`pb-3 px-4 font-medium text-sm transition-colors relative whitespace-nowrap ${abaAtiva === 'orcamentos' ? `${t.textAccent} border-b-2 ${t.borderAccent}` : `${t.textSecondary} hover:${t.textPrimary}`}`}>Orçamentos</button>
        <button onClick={() => alterarAba('compras')} className={`pb-3 px-4 font-medium text-sm transition-colors relative whitespace-nowrap ${abaAtiva === 'compras' ? `${t.textAccent} border-b-2 ${t.borderAccent}` : `${t.textSecondary} hover:${t.textPrimary}`}`}>Compras</button>
        <button onClick={() => alterarAba('dashboard')} className={`pb-3 px-4 font-medium text-sm transition-colors relative whitespace-nowrap ${abaAtiva === 'dashboard' ? `${t.textAccent} border-b-2 ${t.borderAccent}` : `${t.textSecondary} hover:${t.textPrimary}`}`}>Dashboard</button>
      </div>

      <main className="w-full mx-auto relative z-0">
        
        {/* ABA MAPA E GERAL */}
        {abaAtiva === 'mapa' && (
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start w-full">
            <div className="lg:col-span-8 space-y-6 w-full">
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4 md:gap-5">
                <div className={`${t.card} p-5 md:p-6 rounded-2xl shadow-md flex flex-col justify-center`}>
                  <p className={`text-[13px] font-medium ${t.textSecondary} mb-1.5`}>Faturamento Pronto</p>
                  <p className={`text-2xl md:text-3xl font-bold ${t.textPrimary}`}>R$ {(resumoMapa.faturamento_pronto || 0).toLocaleString('pt-BR', { minimumFractionDigits: 2 })}</p>
                </div>
                <div className={`${t.card} p-5 md:p-6 rounded-2xl shadow-md flex flex-col justify-center`}>
                  <p className={`text-[13px] font-medium ${t.textSecondary} mb-1.5`}>Peso Pronto</p>
                  <p className={`text-2xl md:text-3xl font-bold ${t.textPrimary}`}>{formatarKg(resumoMapa.peso_pronto_kg)} <span className={`text-sm md:text-base font-medium ${t.textAccent} ml-1`}>kg</span></p>
                </div>
                <div className={`${t.card} p-5 md:p-6 rounded-2xl shadow-md flex flex-col justify-center`}>
                  <p className={`text-[13px] font-medium ${t.textSecondary} mb-1.5`}>Peso Entregue Mês (ERP)</p>
                  <p className={`text-2xl md:text-3xl font-bold ${t.textPrimary}`}>{formatarKg(resumoMapa.peso_entregue_mes_kg)} <span className={`text-sm md:text-base font-medium ${t.textAccent} ml-1`}>kg</span></p>
                </div>
              </div>

              <div className={`${t.card} rounded-2xl shadow-md overflow-hidden w-full border ${t.border}`}>
                <div className={`p-4 md:p-5 border-b ${t.border} flex flex-col md:flex-row justify-between items-start md:items-center gap-3 ${t.card}`}>
                  <h2 className={`text-lg font-bold ${t.textPrimary}`}>Pedidos Prontos para Expedição</h2>
                  <span className={`${t.bgAccentSoft} ${t.textAccent} text-xs px-3 py-1.5 rounded-full font-bold border ${t.borderAccentSoft}`}>
                    {pedidosProntosParaMapa.length} Prontos
                  </span>
                </div>
                
                <div className="overflow-x-auto w-full scrollbar-hide">
                  <table className="w-full text-left border-collapse min-w-[600px]">
                    <thead>
                      <tr className={`${t.inner} ${t.textSecondary} text-[11px] font-bold uppercase tracking-wider border-b ${t.border}`}>
                        <th className="p-4 w-16 text-center">Rota</th>
                        <th className="p-4">Pedido / Cliente</th>
                        <th className="p-4 text-center">Itens Prontos</th>
                        <th className="p-4 text-center">Peso</th>
                        <th className="p-4 text-center">Valor (R$)</th>
                        <th className="p-4 text-center">Status</th>
                      </tr>
                    </thead>
                    <tbody className={`divide-y ${t.divider} text-sm ${t.textPrimary}`}>
                      {pedidosProntosParaMapa.map((pedido) => {
                        const { concluidas } = obterContadorOfs(pedido)
                        return (
                          <tr key={pedido.id} className={`${t.hoverCard} transition-colors ${pedidosSelecionados.includes(pedido.id) ? (isDarkMode ? 'bg-[#5DD62C]/5' : 'bg-[#5DD62C]/10') : ''}`}>
                            <td className="p-4 text-center">
                              <label className="relative flex items-center justify-center cursor-pointer select-none group">
                                <input type="checkbox" checked={pedidosSelecionados.includes(pedido.id)} onChange={() => toggleSelecaoPedido(pedido)} className="sr-only peer" />
                                <div className={`w-5 h-5 ${isDarkMode ? 'bg-[#0F0F0F]' : 'bg-white'} border ${t.border} rounded-md flex items-center justify-center text-transparent transition-all duration-200 peer-checked:bg-[#5DD62C] peer-checked:border-[#5DD62C] peer-checked:text-[#0F0F0F] focus-within:ring-2`}>
                                  <svg className="w-3.5 h-3.5 stroke-[3] scale-75 peer-checked:scale-100" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" /></svg>
                                </div>
                              </label>
                            </td>
                            <td className="p-4 font-medium">
                              <div className="flex items-center gap-2">
                                <span className={`text-xs ${t.inner} px-2 py-0.5 rounded ${t.textSecondary} font-mono border ${t.border}`}>PEDIDO {pedido.id_pedido}</span>
                              </div>
                              <div className="mt-1 font-bold">{pedido.cliente || 'Sem Nome'}</div>
                              <span className={`block text-[11px] ${t.textSecondary}`}>{pedido.cidade_bloco || ''}</span>
                            </td>
                            <td className="p-4 text-center font-mono">{concluidas}</td>
                            <td className={`p-4 text-center font-mono ${t.textAccent}`}>{formatarKg(pedido.peso_total_kg)} kg</td>
                            <td className="p-4 text-center font-mono font-medium">R$ {(pedido.faturamento_total || 0).toLocaleString('pt-BR', { minimumFractionDigits: 2 })}</td>
                            <td className="p-4 text-center">
                              <div className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-full border ${t.bgAccentSoft} ${t.textAccent} ${t.borderAccentSoft} text-[11px] font-bold`}>Pronto</div>
                            </td>
                          </tr>
                        )
                      })}
                      {pedidosProntosParaMapa.length === 0 && (
                        <tr><td colSpan="6" className={`p-8 text-center ${t.textSecondary}`}>Nenhum carregamento marcado como "Pronto" no momento.</td></tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>

            <div className="lg:col-span-4 lg:sticky lg:top-6 w-full space-y-6">
              <div className={`${t.card} rounded-2xl shadow-md overflow-hidden flex flex-col h-[400px] lg:h-[550px] w-full border ${t.border}`}>
                <div className={`p-4 md:p-5 border-b ${t.border} flex justify-between items-center`}>
                  <h2 className={`text-lg font-bold ${t.textPrimary}`}>Mapa de Entregas</h2>
                </div>
                <div className={`h-full w-full relative z-10 ${t.bg}`}>
                  <MapContainer center={COORDENADAS_EMPRESA} zoom={10} className="h-full w-full" scrollWheelZoom={false}>
                    <RedimensionarMapa />
                    <TileLayer url={isDarkMode ? "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png" : "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"} />
                    <Marker position={COORDENADAS_EMPRESA}>
                      <Popup><div className="text-gray-900 p-1"><strong className="text-[#337418]">Minha Empresa</strong><br/><span className="text-xs text-gray-600">Partida</span></div></Popup>
                    </Marker>
                    {pedidosProntosParaMapa.map((pedido) => {
                      return pedido.latitude && (
                        <Marker key={pedido.id} position={[pedido.latitude, pedido.longitude]}>
                          <Popup><div className="text-gray-900 p-1"><strong className="text-base">{pedido.cliente}</strong><hr className="my-1 border-gray-200" /><p className="text-xs m-0">Ped: {pedido.id_pedido}</p><p className="text-xs m-0">Carga: {formatarKg(pedido.peso_total_kg)} kg</p></div></Popup>
                        </Marker>
                      )
                    })}
                    {rotaIdaGeometria.length > 0 && <Polyline key={`ida`} positions={rotaIdaGeometria} pathOptions={{ color: '#5DD62C', weight: 5, opacity: 0.95 }} />}
                    {rotaVoltaGeometria.length > 0 && <Polyline key={`volta`} positions={rotaVoltaGeometria} pathOptions={{ color: '#337418', weight: 5, opacity: 0.95 }} />}
                  </MapContainer>
                </div>
              </div>

              <div className={`${t.card} p-5 md:p-6 rounded-2xl shadow-md w-full border ${t.border}`}>
                <div className={`border-b ${t.border} pb-3 mb-5`}><h2 className={`text-lg font-bold ${t.textPrimary}`}>Sequenciamento LIFO</h2></div>
                <div className="space-y-6 text-sm">
                  <div className="flex flex-col gap-3">
                    {ordemEntregas.length > 0 ? (
                      ordemEntregas.map((id, index) => {
                        const pedido = pedidos.find(p => p && p.id === id);
                        return (
                          <div key={id} className={`flex items-center justify-between p-3.5 ${t.inner} border ${t.border} rounded-xl ${t.hoverBorderAccent} transition-colors`}>
                            <div className="flex items-center gap-3.5">
                              <span className={`w-7 h-7 rounded-full ${t.bgAccentSoft} ${t.textAccent} font-mono text-xs flex items-center justify-center font-bold border ${t.borderAccentSoft}`}>{index + 1}</span>
                              <div>
                                <div className={`font-bold ${t.textPrimary} text-sm line-clamp-1`}>{pedido?.cliente || 'Cliente'}</div>
                                <div className={`text-[11px] ${t.textSecondary} font-mono mt-0.5`}>PEDIDO {pedido?.id_pedido}</div>
                              </div>
                            </div>
                            <span className={`text-xs font-mono ${t.textAccent} font-bold whitespace-nowrap`}>{formatarKg(pedido?.peso_total_kg)} kg</span>
                          </div>
                        )
                      })
                    ) : (<div className={`p-5 text-center text-[12px] ${t.textSecondary} ${t.inner} rounded-xl border ${t.border}`}>Selecione pedidos no mapa para roteirizar.</div>)}
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* ABA PRODUÇÃO (3x3) */}
        {abaAtiva === 'producao' && (() => {
          const ofsEmProducao = pedidos.flatMap(p => 
            p.itens.filter(i => i.statusOF === 'Produção').map(i => ({ ...i, pedido: p }))
          ).sort((a, b) => new Date(b.data_producao || 0) - new Date(a.data_producao || 0));

          return (
            <div className="space-y-6 w-full relative z-0">
               <div className={`flex flex-col md:flex-row justify-between items-start md:items-center mb-6 gap-4 border-b ${t.border} pb-5`}>
                  <div>
                    <h2 className={`text-2xl font-bold ${t.textPrimary}`}>Painel de Controle de Produção</h2>
                  </div>
                  <div className={`${t.bgAccentSoft} ${t.textAccent} font-mono px-5 py-2.5 rounded-xl text-lg font-bold border ${t.borderAccentSoft}`}>
                    {ofsEmProducao.length} OFs em Produção
                  </div>
               </div>
               
               <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
                  {ofsEmProducao.map((of, idx) => {
                     const { texto: textoDias, dias } = calcularTempoProducao(of.data_producao);
                     const corTag = dias >= 5 ? 'text-red-400 bg-red-500/10 border-red-500/20' : 
                                    dias >= 3 ? 'text-amber-400 bg-amber-500/10 border-amber-500/20' : 
                                    'text-sky-400 bg-sky-500/10 border-sky-500/20';

                     return (
                        <div key={`${of.id_numof}-${idx}`} className={`${t.card} rounded-2xl border ${t.border} p-5 flex flex-col justify-between shadow-lg transition-all hover:border-purple-500/40 hover:shadow-purple-500/5`}>
                           <div className="flex justify-between items-start gap-4 mb-4">
                              <div className="flex-1 min-w-0">
                                 <div className="flex items-center gap-2 mb-2 flex-wrap">
                                    <span className={`text-xs font-mono font-bold bg-purple-500/10 text-purple-400 px-2.5 py-0.5 rounded border border-purple-500/20`}>
                                       OF {of.id_numof}
                                    </span>
                                    <span className={`text-[10px] font-mono font-bold ${t.inner} ${t.textSecondary} px-2 py-0.5 rounded border ${t.border}`}>
                                       PED {of.pedido.id_pedido}
                                    </span>
                                 </div>
                                 <h3 className={`font-bold ${t.textPrimary} text-lg leading-tight truncate`} title={of.pedido.cliente}>{of.pedido.cliente}</h3>
                                 <p className={`text-[12px] ${t.textPrimary} mt-1.5 font-medium truncate`} title={of.referencia}>{of.referencia}</p>
                              </div>
                           </div>

                           <div className="mb-4">
                              <span className={`text-[10px] font-bold uppercase tracking-wider px-2.5 py-1 rounded border ${corTag} inline-block w-full text-center`}>
                                 {textoDias}
                              </span>
                           </div>

                           <div className={`grid grid-cols-2 gap-y-4 gap-x-2 py-4 border-y ${t.border} mb-4`}>
                              <div>
                                 <span className={`block text-[10px] ${t.textSecondary} uppercase tracking-wider mb-1`}>Qtd Faltante / Peso</span>
                                 <span className={`font-mono font-bold ${t.textPrimary} text-sm`}>{Math.round(of.qtd_restante)} <span className="text-[10px] font-sans font-normal">cx</span></span>
                                 <div className={`font-mono font-bold ${t.textAccent} text-xs`}>{formatarKg(of.peso_restante)} kg</div>
                              </div>
                              <div>
                                 <span className={`block text-[10px] ${t.textSecondary} uppercase tracking-wider mb-1`}>Qualidade</span>
                                 <span className={`font-mono font-bold ${t.textPrimary} block truncate text-sm`} title={`${of.onda || '-'} / ${of.qualidade || '-'}`}>{of.onda || '-'} / {of.qualidade || '-'}</span>
                                 <div className={`text-xs ${t.textSecondary} font-mono`}>{of.gramatura ? `${of.gramatura}g` : '-'}</div>
                              </div>
                              <div>
                                 <span className={`block text-[10px] ${t.textSecondary} uppercase tracking-wider mb-1`}>Fechamento</span>
                                 <span className={`font-mono font-bold ${t.textPrimary} block truncate text-sm`}>{of.fecha || 'N/A'}</span>
                                 <div className={`text-xs ${t.textSecondary} font-mono`}>{of.comp || 0}x{of.larg || 0}x{of.alt || 0}</div>
                              </div>
                              <div>
                                 <span className={`block text-[10px] ${t.textSecondary} uppercase tracking-wider mb-1`}>Impressão</span>
                                 {(!of.cor1 && !of.cor2) ? (
                                    <span className={`font-mono font-bold ${t.textSecondary} block text-sm`}>Sem Impr.</span>
                                 ) : (
                                    <>
                                       <span className={`font-mono font-bold ${t.textPrimary} block truncate text-xs`} title={of.cor1}>{of.cor1 || '-'}</span>
                                       {of.cor2 && <span className={`font-mono font-bold ${t.textPrimary} block truncate text-xs`} title={of.cor2}>{of.cor2}</span>}
                                    </>
                                 )}
                              </div>
                           </div>

                           <div className="flex gap-2 justify-end mt-auto">
                              <button 
                                 onClick={() => alternarStatusOf(of.pedido.id, of.id_numof, 'Pendente')} 
                                 className={`px-3 py-2.5 rounded-lg text-[10px] font-bold border transition-all bg-amber-500/10 text-amber-500 border-amber-500/20 hover:bg-amber-500/20`}
                                 title="Voltar para Pendente"
                              >
                                 <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M10 19l-7-7m0 0l7-7m-7 7h18" /></svg>
                              </button>
                              <button 
                                 onClick={() => alternarStatusOf(of.pedido.id, of.id_numof, 'Pronto')} 
                                 className={`flex-1 px-4 py-2.5 rounded-lg text-xs font-bold border transition-all bg-[#5DD62C] text-[#0F0F0F] border-[#5DD62C] hover:bg-[#337418] hover:border-[#337418] hover:text-[#F8F8F8] flex justify-center gap-2 items-center`}
                              >
                                 <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M5 13l4 4L19 7" /></svg> Marcar Pronto
                              </button>
                           </div>
                        </div>
                     )
                  })}
                  
                  {ofsEmProducao.length === 0 && !carregando && (
                    <div className={`col-span-full p-16 text-center ${t.textSecondary} ${t.inner} rounded-2xl border ${t.border}`}>
                       <svg className="w-12 h-12 mx-auto mb-4 opacity-50" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
                       <p className="text-lg">Nenhuma Ordem de Fabricação em produção no momento.</p>
                    </div>
                  )}
               </div>
            </div>
          );
        })()}

        {/* ABA ORÇAMENTOS */}
        {abaAtiva === 'orcamentos' && (
          <div className="space-y-6 w-full relative z-0">
             <div className={`flex flex-col md:flex-row justify-between items-start md:items-center mb-6 gap-4 border-b ${t.border} pb-5`}>
                <div>
                  <h2 className={`text-xl font-bold ${t.textPrimary}`}>Gestão de Orçamentos</h2>
                </div>
                
                <div className={`flex flex-col xl:flex-row items-center gap-3 w-full xl:w-auto`}>
                  <div className="relative w-full xl:w-64 flex-shrink-0">
                    <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none"><svg className={`w-4 h-4 ${t.textSecondary}`} fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" /></svg></div>
                    <input type="text" value={termoPesquisaOrcamento} onChange={(e) => setTermoPesquisaOrcamento(e.target.value)} placeholder="Buscar Nº, cliente ou contato..." className={`w-full pl-9 pr-3 py-3 md:py-2 bg-transparent border ${t.border} rounded-lg text-xs md:text-sm ${t.textPrimary} focus:outline-none focus:border-sky-500`} />
                  </div>
                  <button onClick={() => carregarOrcamentos(false)} className={`w-full xl:w-auto ${t.card} border ${t.border} ${t.textPrimary} hover:border-sky-500 hover:text-sky-500 px-4 py-3 md:py-2 rounded-lg text-xs font-semibold shadow-sm transition-all`}>
                    Atualizar Tabela
                  </button>
                </div>
             </div>

             <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-5">
                {orcamentosFiltrados.map((orc) => {
                   const estaExpandido = orcamentosExpandidos.includes(orc.id_orcamento);
                   const isEditando = editandoNotaOrcamento === orc.id_orcamento;
                   const { texto: textoDias, dias } = calcularTempoOrcamento(orc.raw_emissao);
                   
                   const corDias = dias > 15 ? 'text-red-400 bg-red-500/10 border-red-500/20' : 
                                   dias > 7 ? 'text-amber-400 bg-amber-500/10 border-amber-500/20' : 
                                   'text-[#5DD62C] bg-[#5DD62C]/10 border-[#5DD62C]/20';

                   return (
                      <div key={orc.id_orcamento} className={`${t.inner} rounded-2xl border ${t.border} overflow-hidden shadow-sm hover:border-sky-500/50 transition-all flex flex-col`}>
                         <div className={`p-4 md:p-5 flex flex-col gap-4 border-b ${t.border}`}>
                            <div className="flex justify-between items-start gap-2">
                               <div>
                                  <div className="flex items-center gap-2 mb-1.5 flex-wrap">
                                     <span className={`text-xs font-mono font-bold bg-sky-500/10 text-sky-500 px-2 py-0.5 rounded border border-sky-500/20`}>ORC: {orc.id_orcamento}</span>
                                     <span className={`text-[10px] font-mono font-bold ${corDias} px-2 py-0.5 rounded border`}>{textoDias}</span>
                                  </div>
                                  <h3 className={`font-bold ${t.textPrimary} text-base leading-tight mt-1 line-clamp-1`} title={orc.cliente}>{orc.cliente}</h3>
                               </div>
                            </div>
                            
                            <div className={`grid grid-cols-2 gap-3 text-xs ${t.textSecondary}`}>
                               <div>
                                  <span className="block text-[10px] uppercase mb-0.5">Contato Comercial</span>
                                  <span className={`font-medium ${t.textPrimary} truncate block`} title={orc.comprador}>{orc.comprador || 'Não Informado'}</span>
                                  <span className="font-mono mt-0.5 block">{orc.telefone || 'Sem telefone'}</span>
                               </div>
                               <div>
                                  <span className="block text-[10px] uppercase mb-0.5">Valor Total</span>
                                  <span className={`font-mono font-bold ${t.textPrimary} text-sm`}>R$ {(orc.total_geral || 0).toLocaleString('pt-BR', {minimumFractionDigits: 2})}</span>
                                  <span className="font-mono mt-0.5 block">{formatarKg(orc.total_peso)} kg</span>
                               </div>
                            </div>
                            
                            <div className={`flex gap-3 text-[10px] uppercase font-bold tracking-wider pt-3 border-t ${t.border} ${t.textSecondary}`}>
                               <div className="flex-1 truncate"><span className="opacity-70">Pagto:</span> <span className={t.textPrimary}>{orc.cond_pagto || 'N/A'}</span></div>
                               <div className="flex-1 text-right truncate"><span className="opacity-70">Prazo:</span> <span className={t.textPrimary}>{orc.prazo_entrega || 'N/A'}</span></div>
                            </div>
                         </div>

                         {/* BLOCO DE FOLLOW UP (SQLITE) */}
                         <div className={`p-4 ${t.card}`}>
                            <div className="flex justify-between items-center mb-2">
                               <h4 className={`text-[11px] font-bold ${t.textSecondary} uppercase tracking-wider flex items-center gap-1.5`}>
                                  <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" /></svg> Histórico / Notas
                               </h4>
                               {orc.data_anotacao && !isEditando && (
                                  <span className={`text-[9px] font-mono ${t.textSecondary}`}>Atualizado em: {orc.data_anotacao}</span>
                               )}
                            </div>
                            
                            {isEditando ? (
                               <div className="space-y-2">
                                  <textarea 
                                     autoFocus
                                     value={textoNotaTemp} 
                                     onChange={(e) => setTextoNotaTemp(e.target.value)}
                                     placeholder="Digite as anotações da negociação aqui..."
                                     className={`w-full ${t.inner} ${t.textPrimary} border ${t.border} rounded-lg px-3 py-2 text-xs focus:outline-none focus:border-sky-500 resize-none h-20 transition-all`}
                                  />
                                  <div className="flex gap-2 justify-end">
                                     <button onClick={() => setEditandoNotaOrcamento(null)} className={`px-3 py-1.5 rounded-md text-[10px] font-bold ${t.textSecondary} hover:${t.textPrimary} border ${t.border} transition-colors`}>Cancelar</button>
                                     <button onClick={() => salvarNotaOrcamento(orc.id_orcamento)} className="px-4 py-1.5 rounded-md text-[10px] font-bold bg-sky-500 hover:bg-sky-600 text-white shadow-sm transition-colors">Salvar Nota</button>
                                  </div>
                               </div>
                            ) : (
                               <div 
                                  onClick={() => { setTextoNotaTemp(orc.anotacao || ""); setEditandoNotaOrcamento(orc.id_orcamento); }}
                                  className={`w-full ${t.inner} border ${t.border} border-dashed rounded-lg p-3 text-xs ${orc.anotacao ? t.textPrimary : `${t.textSecondary} italic`} cursor-pointer hover:border-sky-500/50 transition-colors min-h-[60px] whitespace-pre-wrap`}
                               >
                                  {orc.anotacao || "Clique para adicionar uma anotação sobre esta negociação..."}
                               </div>
                            )}
                         </div>

                         <div className="mt-auto">
                            <button onClick={() => toggleExpandirOrcamento(orc.id_orcamento)} className={`w-full py-2.5 px-3 border-t ${t.border} text-[11px] font-bold ${t.textSecondary} hover:${t.textPrimary} flex items-center justify-center gap-1.5 transition-colors ${t.hoverCard}`}>
                               <span>{estaExpandido ? 'Ocultar Itens' : `Ver Itens (${orc.itens.length})`}</span>
                               <svg className={`w-3.5 h-3.5 transition-transform duration-200 ${estaExpandido ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 9l-7 7-7-7" /></svg>
                            </button>

                            {estaExpandido && (
                               <div className={`${t.innerAlt} border-t ${t.border} text-[11px] max-h-48 overflow-y-auto divide-y ${t.divider}`}>
                                  {orc.itens.map((item, idx) => (
                                     <div key={idx} className="p-3">
                                        <div className="flex justify-between items-start mb-1">
                                           <strong className={`${t.textPrimary} flex-1 pr-2`}>{item.referencia || item.modelo}</strong>
                                           <span className={`font-mono font-bold ${item.aprovado === 'S' ? 'text-[#5DD62C]' : t.textSecondary}`}>
                                              {item.aprovado === 'S' ? 'APROVADO' : ''}
                                           </span>
                                        </div>
                                        <div className={`flex justify-between text-[10px] ${t.textSecondary} font-mono mt-1.5`}>
                                           <span>Qtd: {item.quantidade} cx</span>
                                           <span>R$ {item.vl_unit.toLocaleString('pt-BR', {minimumFractionDigits:4})} /un</span>
                                        </div>
                                        <div className={`flex justify-between text-[10px] ${t.textSecondary} font-mono mt-0.5`}>
                                           <span>{item.onda} / {item.qualidade}</span>
                                           <span>{item.comp}x{item.larg}x{item.alt}</span>
                                        </div>
                                     </div>
                                  ))}
                               </div>
                            )}
                         </div>
                      </div>
                   )
                })}

                {orcamentosFiltrados.length === 0 && !carregando && (
                  <div className={`col-span-full p-12 text-center ${t.textSecondary} ${t.inner} rounded-2xl border ${t.border}`}>Nenhum orçamento encontrado.</div>
                )}
             </div>
             
             {orcamentos.length > limiteExibicao && (
                <div className="flex justify-center mt-6">
                   <button onClick={() => setLimiteExibicao(prev => prev + 20)} className={`px-6 py-3 rounded-xl text-sm font-bold shadow-md transition-all bg-sky-500 hover:bg-sky-600 text-white w-full md:w-auto hover:scale-105`}>
                      Carregar Mais Orçamentos
                   </button>
                </div>
             )}
          </div>
        )}

        {/* ABA CONTROLE DE PEDIDOS */}
        {abaAtiva === 'prazos' && (() => {
          const faturamentoAtual = pedidosAbaControle.reduce((acc, p) => acc + (p.faturamento_total || 0), 0);
          const pesoAtual = pedidosAbaControle.reduce((acc, p) => acc + (p.peso_total_kg || 0), 0);
          const ativosAtual = pedidosAbaControle.length;

          return (
          <div className="space-y-6 sm:space-y-8 w-full relative z-0">
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 md:gap-5">
              <div className={`${t.card} p-5 md:p-6 rounded-2xl shadow-md flex flex-col justify-center transition-all duration-300`}>
                <p className={`text-[12px] sm:text-[13px] font-medium ${t.textSecondary} mb-1.5`}>Faturamento em Aberto</p>
                <p className={`text-2xl md:text-3xl font-bold ${t.textPrimary}`}>R$ {(faturamentoAtual || 0).toLocaleString('pt-BR', { minimumFractionDigits: 2 })}</p>
              </div>
              
              <div className={`${t.card} p-5 md:p-6 rounded-2xl shadow-md flex flex-col justify-center relative transition-all duration-300`}>
                <div className="flex justify-between items-center mb-1.5">
                  <p className={`text-[12px] sm:text-[13px] font-medium ${t.textSecondary}`}>Peso em Aberto</p>
                  
                  <div className={`flex bg-[#151515] rounded-md border ${t.border} p-0.5 ml-2`}>
                    <button 
                      onClick={() => setModoPesoAberto('mes')} 
                      disabled={filtroStatusPedido === 'faturado'}
                      className={`px-2 py-0.5 text-[10px] font-bold rounded-sm transition-all ${filtroStatusPedido === 'faturado' ? 'opacity-30 cursor-not-allowed' : (modoPesoAberto === 'mes' ? 'bg-[#337418] text-white shadow-sm' : 'text-gray-500 hover:text-gray-300')}`}
                    >Mês</button>
                    <button 
                      onClick={() => setModoPesoAberto('total')} 
                      disabled={filtroStatusPedido === 'faturado'}
                      className={`px-2 py-0.5 text-[10px] font-bold rounded-sm transition-all ${filtroStatusPedido === 'faturado' ? 'opacity-30 cursor-not-allowed' : (modoPesoAberto === 'total' ? 'bg-[#337418] text-white shadow-sm' : 'text-gray-500 hover:text-gray-300')}`}
                    >Total</button>
                  </div>
                </div>
                <p className={`text-2xl md:text-3xl font-bold ${t.textPrimary}`}>
                  {formatarKg(pesoAtual)} <span className={`text-sm md:text-base font-medium ${t.textAccent} ml-1`}>kg</span>
                </p>
              </div>

              <div className={`${t.card} p-5 md:p-6 rounded-2xl shadow-md flex flex-col justify-center transition-all duration-300`}>
                <p className={`text-[12px] sm:text-[13px] font-medium ${t.textSecondary} mb-1.5`}>Pedidos Ativos</p>
                <p className={`text-2xl md:text-3xl font-bold ${t.textPrimary}`}>{ativosAtual || 0}</p>
              </div>
            </div>

            <div className={`${t.card} rounded-2xl shadow-md p-4 md:p-6 w-full border ${t.border}`}>
              <div className={`flex flex-col lg:flex-row justify-between items-start lg:items-center mb-6 gap-4 border-b ${t.border} pb-5`}>
                <div>
                  <h2 className={`text-xl font-bold ${t.textPrimary}`}>Controle de Pedidos</h2>
                </div>
                
                <div className={`flex ${t.innerAlt} rounded-xl border ${t.border} p-1 w-full lg:w-auto`}>
                  <button 
                    onClick={() => setFiltroStatusPedido('aberto')} 
                    className={`flex-1 lg:flex-none px-6 py-2 text-xs font-bold rounded-lg transition-all ${filtroStatusPedido === 'aberto' ? 'bg-[#337418] text-white shadow-md' : `text-gray-500 hover:${t.textPrimary}`}`}
                  >Em Aberto</button>
                  <button 
                    onClick={() => setFiltroStatusPedido('faturado')} 
                    className={`flex-1 lg:flex-none px-6 py-2 text-xs font-bold rounded-lg transition-all ${filtroStatusPedido === 'faturado' ? 'bg-[#337418] text-white shadow-md' : `text-gray-500 hover:${t.textPrimary}`}`}
                  >Faturados</button>
                </div>
              </div>
              
              <div className={`flex flex-col xl:flex-row items-center gap-3 w-full mb-6`}>
                 <div className="relative w-full xl:w-64 flex-shrink-0">
                   <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none"><svg className={`w-4 h-4 ${t.textSecondary}`} fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" /></svg></div>
                   <input type="text" value={termoPesquisa} onChange={(e) => setTermoPesquisa(e.target.value)} placeholder="Buscar pedido" className={`w-full pl-9 pr-3 py-3 md:py-2 bg-transparent border ${t.border} rounded-lg text-xs md:text-sm ${t.textPrimary} focus:outline-none focus:border-[#5DD62C]`} />
                 </div>
                 
                 <div className="flex flex-col sm:flex-row w-full xl:w-auto justify-between items-stretch sm:items-center gap-3 ml-auto">
                   <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-2 w-full sm:w-auto">
                     <select value={ordenarPor} onChange={(e) => setOrdenarPor(e.target.value)} className={`w-full sm:w-auto ${t.card} text-xs font-bold ${t.textPrimary} border ${t.border} rounded-lg px-3 py-3 md:py-2 focus:outline-none focus:${t.borderAccent} cursor-pointer`}>
                       <option value="prazo">Dias Restantes</option><option value="id_pedido">Pedido</option><option value="emissao">Data Emissão</option>
                     </select>
                     <select value={ordem} onChange={(e) => setOrdem(e.target.value)} className={`w-full sm:w-auto ${t.card} text-xs font-bold ${t.textPrimary} border ${t.border} rounded-lg px-3 py-3 md:py-2 focus:outline-none focus:${t.borderAccent} cursor-pointer`}>
                       <option value="asc">Crescente (A-Z)</option><option value="desc">Decrescente (Z-A)</option>
                     </select>
                   </div>
                   <div className={`flex items-center justify-center ${t.card} p-1 rounded-lg border ${t.border} w-full sm:w-auto`}>
                     <button onClick={() => setModoExibicao('lista')} className={`flex-1 sm:flex-none flex items-center justify-center gap-1.5 px-3 py-2 md:py-1.5 text-xs font-bold rounded-md transition-colors ${modoExibicao === 'lista' ? 'bg-[#337418] text-[#F8F8F8]' : `${t.textSecondary} hover:${t.textPrimary}`}`}><svg className="w-4 h-4 md:w-3.5 md:h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 6h16M4 12h16M4 18h16" /></svg>Lista</button>
                     <button onClick={() => setModoExibicao('grade')} className={`flex-1 sm:flex-none flex items-center justify-center gap-1.5 px-3 py-2 md:py-1.5 text-xs font-bold rounded-md transition-colors ${modoExibicao === 'grade' ? 'bg-[#337418] text-[#F8F8F8]' : `${t.textSecondary} hover:${t.textPrimary}`}`}><svg className="w-4 h-4 md:w-3.5 md:h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2V6zM14 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V6zM4 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2zM14 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z" /></svg>Grade</button>
                   </div>
                 </div>
              </div>

              {carregando ? (<div className={`p-12 text-center ${t.textSecondary}`}>Carregando dados dos pedidos...</div>) : (
                <>
                  <div className={modoExibicao === 'lista' ? 'flex flex-col gap-3' : 'grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-5'}>
                    {pedidosAbaControlePaginados.map((pedido) => {
                      const estaExpandido = pedidosExpandidos.includes(pedido.id)
                      const { concluidas, total } = obterContadorOfs(pedido)
                      const todasConcluidas = total > 0 && concluidas === total
                      const isFaturadoGeral = pedido.status === 'Faturada'

                      return modoExibicao === 'lista' ? (
                        <div key={pedido.id} className={`${t.inner} rounded-xl border ${t.border} ${t.hoverBorderAccent} transition-all overflow-hidden ${isFaturadoGeral ? 'opacity-70 grayscale hover:grayscale-0' : ''}`}>
                          <div className="p-4 flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
                            
                            <div className="flex items-start gap-4 flex-1 min-w-[240px]">
                              <button onClick={() => toggleExpandirPedido(pedido.id)} className={`mt-1 p-2 md:p-1.5 ${t.card} ${t.hoverCard} border ${t.border} rounded-lg ${t.textSecondary} hover:${t.textPrimary} transition-colors`}>
                                <svg className={`w-5 h-5 md:w-4 md:h-4 transition-transform duration-200 ${estaExpandido ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 9l-7 7-7-7" /></svg>
                              </button>
                              <div>
                                <div className="flex items-center gap-2 mb-1.5 flex-wrap">
                                  <span className={`text-xs ${t.card} ${t.textSecondary} px-2.5 py-0.5 rounded-md font-mono font-bold border ${t.border}`}>PEDIDO {pedido.id_pedido}</span>
                                  {!isFaturadoGeral && <span className={`text-[11px] px-2 py-0.5 rounded-md font-mono font-bold border ${todasConcluidas ? `${t.bgAccentSoft} ${t.textAccent} ${t.borderAccentSoft}` : `${t.card} ${t.textSecondary} ${t.border}`}`}>OFs Prontas: {concluidas}/{total}</span>}
                                  {isFaturadoGeral && <span className={`text-[11px] px-2 py-0.5 rounded-md font-bold uppercase border bg-gray-500/10 text-gray-400 border-gray-500/20`}>Faturado</span>}
                                </div>
                                <h3 className={`font-bold ${t.textPrimary} text-base leading-tight`}>{pedido.cliente}</h3>
                                {pedido.pedido_cliente && <p className={`text-xs ${t.textAccent} font-mono font-bold mt-1`}>Pedido Cliente: {pedido.pedido_cliente}</p>}
                                <p className={`text-[11px] ${t.textSecondary} mt-1`}>{pedido.cidade_bloco} {pedido.endereco_completo ? `• ${pedido.endereco_completo}` : ''}</p>
                              </div>
                            </div>

                            <div className={`flex flex-wrap items-center gap-4 md:gap-8 text-xs text-gray-300 w-full md:w-auto justify-between md:justify-end border-t ${t.border} md:border-t-0 pt-4 md:pt-0`}>
                              {!isFaturadoGeral && (
                                 <div className="text-left md:text-center w-[45%] md:w-auto">
                                   <span className={`block text-[10px] ${t.textSecondary} uppercase tracking-wider mb-0.5`}>Itens</span>
                                   <span className={`font-mono font-bold ${t.textPrimary}`}>{pedido.total_itens_abertos || 0}</span>
                                 </div>
                              )}
                              <div className="text-left md:text-center w-[45%] md:w-auto">
                                <span className={`block text-[10px] ${t.textSecondary} uppercase tracking-wider mb-0.5`}>{isFaturadoGeral ? 'Peso Faturado' : 'Peso'}</span>
                                <span className={`font-mono font-bold ${isFaturadoGeral ? t.textSecondary : t.textAccent}`}>{formatarKg(pedido.peso_total_kg)} kg</span>
                              </div>
                              <div className="text-left md:text-center w-[45%] md:w-auto">
                                <span className={`block text-[10px] ${t.textSecondary} uppercase tracking-wider mb-0.5`}>Emissão</span>
                                <span className={`font-mono ${t.textPrimary}`}>{pedido.data_emissao || '-'}</span>
                              </div>
                              <div className="w-[45%] md:w-auto">
                                {isFaturadoGeral ? <span className={`text-[11px] font-bold ${t.textSecondary}`}>ENTREGUE</span> : renderizarTagPrazo(pedido.dias_restantes, pedido.data_entrega)}
                              </div>
                            </div>
                          </div>

                          {estaExpandido && (
                            <div className={`${t.innerAlt} p-4 md:p-5 border-t ${t.border}`}>
                              <h4 className={`text-[11px] font-bold ${t.textSecondary} uppercase tracking-wider mb-4`}>Itens do Pedido</h4>
                              {pedido.itens && pedido.itens.length > 0 ? (
                                <div className="overflow-x-auto w-full scrollbar-hide">
                                  <table className="w-full text-left border-collapse text-xs min-w-[600px]">
                                    <thead>
                                      <tr className={`border-b ${t.border} ${t.textSecondary} uppercase font-mono`}>
                                        <th className="py-2.5 px-3">OF</th>
                                        <th className="py-2.5 px-3">Referência</th>
                                        <th className="py-2.5 px-3 text-center">Qtde (Restante)</th>
                                        <th className="py-2.5 px-3 text-right">Peso (Restante)</th>
                                        <th className="py-2.5 px-3 text-center">Status OF</th>
                                      </tr>
                                    </thead>
                                    <tbody className={`divide-y ${t.divider} ${t.textPrimary}`}>
                                      {pedido.itens.map((item, idx) => {
                                        const numeroOf = item.id_numof || '-';
                                        const isFaturada = item.statusOF === 'Faturada';
                                        
                                        return (
                                          <tr key={idx} className={`${t.hoverCard} transition-colors ${isFaturada ? 'opacity-40 grayscale' : ''}`}>
                                            <td className={`py-3 px-3 font-mono font-bold ${t.textAccent}`}>{numeroOf.toString().startsWith("ITEM") ? numeroOf : `OF ${numeroOf}`}</td>
                                            <td className={`py-3 px-3 font-medium ${t.textPrimary}`}>{item.referencia || item.id_produto || '-'}</td>
                                            <td className={`py-3 px-3 text-center font-mono ${t.textPrimary}`}>{Math.round(item.qtd_restante)}</td>
                                            <td className={`py-3 px-3 text-right font-mono ${t.textAccent}`}>{formatarKg(item.peso_restante)} kg</td>
                                            <td className="py-3 px-3 text-center">
                                              <select value={item.statusOF || 'Pendente'} onChange={(e) => alternarStatusOf(pedido.id, item.id_numof, e.target.value)} className={`text-[10px] font-bold rounded-full px-2.5 py-1.5 border cursor-pointer focus:outline-none ${obterEstiloStatusCompleto(item.statusOF)}`}>
                                                <option value="Pendente" className={`${t.card} text-amber-500`}>O Pendente</option>
                                                <option value="Compras" className={`${t.card} text-sky-500`}>Compras</option>
                                                <option value="Produção" className={`${t.card} text-purple-500`}>Produção</option>
                                                <option value="Parcial" className={`${t.card} text-teal-500`}>Parcial</option>
                                                <option value="Pronto" className={`${t.card} ${t.textAccent}`}>✓ Concluído</option>
                                                <option value="Faturada" className={`${t.card} text-gray-500`}>Faturada (Entregue)</option>
                                              </select>
                                            </td>
                                          </tr>
                                        )
                                      })}
                                    </tbody>
                                  </table>
                                </div>
                              ) : (<div className={`text-xs ${t.textSecondary} italic p-4 text-center`}>Nenhum item detalhado encontrado.</div>)}
                            </div>
                          )}                          
                        </div>
                      ) : (
                        <div key={pedido.id} className={`${t.inner} p-4 md:p-5 rounded-2xl border ${t.border} flex flex-col justify-between ${t.hoverBorderAccent} transition-colors ${isFaturadoGeral ? 'opacity-70 grayscale hover:grayscale-0' : ''}`}>
                          <div>
                            <div className="flex justify-between items-start mb-3 gap-2">
                              <div>
                                <div className="flex items-center gap-2 flex-wrap mb-2">
                                  <span className={`text-[11px] ${t.card} ${t.textSecondary} px-2.5 py-0.5 rounded-md font-mono font-bold border ${t.border}`}>PEDIDO {pedido.id_pedido}</span>
                                  {!isFaturadoGeral && <span className={`text-[10px] px-2 py-0.5 rounded-md font-mono font-bold border ${todasConcluidas ? `${t.bgAccentSoft} ${t.textAccent} ${t.borderAccentSoft}` : `${t.card} ${t.textSecondary} ${t.border}`}`}>OFs Ativas: {concluidas}/{total}</span>}
                                  {isFaturadoGeral && <span className={`text-[10px] px-2 py-0.5 rounded-md font-bold uppercase border bg-gray-500/10 text-gray-400 border-gray-500/20`}>Faturado</span>}
                                </div>
                                <h3 className={`font-bold ${t.textPrimary} text-base leading-tight`}>{pedido.cliente}</h3>
                                {pedido.pedido_cliente && <p className={`text-xs ${t.textAccent} font-mono font-bold mt-1`}>Pedido Cliente {pedido.pedido_cliente}</p>}
                              </div>
                              <div className="flex-shrink-0">{isFaturadoGeral ? <span className={`text-[11px] font-bold ${t.textSecondary}`}>ENTREGUE</span> : renderizarTagPrazo(pedido.dias_restantes, pedido.data_entrega)}</div>
                            </div>
                            <div className={`my-4 py-3 border-y ${t.border} grid ${isFaturadoGeral ? 'grid-cols-2' : 'grid-cols-3'} gap-2 text-center text-xs`}>
                              {!isFaturadoGeral && <div><span className={`block text-[10px] ${t.textSecondary} uppercase tracking-wider mb-1`}>Itens Ativos</span><span className={`font-mono font-bold ${t.textPrimary}`}>{pedido.total_itens_abertos || 0}</span></div>}
                              <div><span className={`block text-[10px] ${t.textSecondary} uppercase tracking-wider mb-1`}>{isFaturadoGeral ? 'Peso Faturado' : 'Peso Faltante'}</span><span className={`font-mono font-bold ${isFaturadoGeral ? t.textSecondary : t.textAccent}`}>{formatarKg(pedido.peso_total_kg)} kg</span></div>
                              <div><span className={`block text-[10px] ${t.textSecondary} uppercase tracking-wider mb-1`}>Emissão</span><span className={`font-mono ${t.textPrimary}`}>{pedido.data_emissao || '-'}</span></div>
                            </div>
                          </div>

                          <div className="space-y-4 pt-1">
                            <button onClick={() => toggleExpandirPedido(pedido.id)} className={`w-full py-2.5 md:py-2 px-3 ${t.card} ${t.hoverCard} border ${t.border} rounded-lg text-xs font-bold ${t.textSecondary} hover:${t.textPrimary} flex items-center justify-center gap-2 transition-colors`}>
                              <span>{estaExpandido ? 'Ocultar OFs' : 'Ver OFs do Pedido'}</span>
                              <svg className={`w-4 h-4 md:w-3.5 md:h-3.5 transition-transform duration-200 ${estaExpandido ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 9l-7 7-7-7" /></svg>
                            </button>

                            {estaExpandido && (
                              <div className={`${t.card} p-3 rounded-xl border ${t.border} text-xs space-y-2 max-h-60 overflow-y-auto`}>
                                {pedido.itens && pedido.itens.length > 0 ? (
                                  pedido.itens.map((item, idx) => {
                                    const numeroOf = item.id_numof || '-';
                                    return (
                                      <div key={idx} className={`p-3 ${t.inner} border ${t.border} rounded-lg flex flex-col gap-2 ${item.statusOF === 'Faturada' ? 'opacity-40 grayscale' : ''}`}>
                                        <div className="flex justify-between items-center font-mono">
                                          <span className={`font-bold ${t.textAccent}`}>{numeroOf.toString().startsWith("ITEM") ? numeroOf : `OF ${numeroOf}`}</span>
                                        </div>
                                        <div className={`font-bold ${t.textPrimary} truncate`}>{item.referencia || item.id_produto}</div>
                                        <div className={`flex justify-between items-center text-[11px] ${t.textSecondary}`}>
                                          <span>Qtd Restante: <span className={t.textPrimary}>{Math.round(item.qtd_restante)}</span></span>
                                          <span className={`${t.textAccent} font-mono font-bold`}>{formatarKg(item.peso_restante)} kg</span>
                                        </div>
                                        <select value={item.statusOF || 'Pendente'} onChange={(e) => alternarStatusOf(pedido.id, item.id_numof, e.target.value)} className={`w-full py-2 md:py-1.5 mt-1 rounded-md text-[11px] md:text-[10px] font-bold border transition-all cursor-pointer focus:outline-none ${obterEstiloStatusCompleto(item.statusOF)}`}>
                                          <option value="Pendente" className={`${t.card} text-amber-500`}>Pendente</option>
                                          <option value="Compras" className={`${t.card} text-sky-500`}>Compras</option>
                                          <option value="Produção" className={`${t.card} text-purple-500`}>Produção</option>
                                          <option value="Parcial" className={`${t.card} text-teal-500`}>Parcial</option>
                                          <option value="Pronto" className={`${t.card} ${t.textAccent}`}>Concluído</option>
                                          <option value="Faturada" className={`${t.card} text-gray-500`}>Faturada</option>
                                        </select>
                                      </div>
                                    )
                                  })
                                ) : (<div className={`${t.textSecondary} text-center py-3 italic text-[11px]`}>Nenhum item encontrado.</div>)}
                              </div>
                            )}
                          </div>
                        </div>
                      )
                    })}

                    {pedidosAbaControle.length === 0 && (<div className={`col-span-full p-8 text-center ${t.textSecondary} ${t.card} rounded-2xl border ${t.border}`}>{termoPesquisa ? 'Nenhum pedido encontrado.' : 'Nenhum pedido com os filtros atuais.'}</div>)}
                  </div>
                  
                  {pedidosAbaControle.length > limiteExibicao && (
                    <div className="flex justify-center mt-6">
                      <button onClick={() => setLimiteExibicao(prev => prev + 20)} className={`px-6 py-3 rounded-xl text-sm font-bold shadow-md transition-all bg-[#5DD62C] hover:bg-[#337418] text-[#0F0F0F] hover:text-[#F8F8F8] w-full md:w-auto hover:scale-105`}>
                        Carregar Mais ({pedidosAbaControle.length - limiteExibicao} restantes)
                      </button>
                    </div>
                  )}
                </>
              )}
            </div>
          </div>
          );
        })()}

        {/* ABA GESTÃO DE COMPRAS */}
        {abaAtiva === 'compras' && (() => {
          const comprasEmAberto = compras.filter(c => !(c.dataRecebida || c.status === 'RECEBIDA'));
          const comprasRecebidas = compras.filter(c => c.dataRecebida || c.status === 'RECEBIDA');
          const valorTotalComprasAberto = comprasEmAberto.reduce((acc, c) => acc + (c.valorTotal || 0), 0);
          const pesoTotalComprasAberto = comprasEmAberto.reduce((acc, c) => acc + (c.pesoTotalKg || 0), 0);

          return (
            <div className="space-y-8 w-full">
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4 md:gap-5">
                <div className={`${t.card} p-5 md:p-6 rounded-2xl shadow-md flex flex-col justify-center`}>
                  <p className={`text-[13px] font-medium ${t.textSecondary} mb-1.5`}>Valor Total</p>
                  <p className={`text-2xl md:text-3xl font-bold ${t.textPrimary}`}>R$ {valorTotalComprasAberto.toLocaleString('pt-BR', { minimumFractionDigits: 2 })}</p>
                </div>
                <div className={`${t.card} p-5 md:p-6 rounded-2xl shadow-md flex flex-col justify-center`}>
                  <p className={`text-[13px] font-medium ${t.textSecondary} mb-1.5`}>Peso Total em Compras</p>
                  <p className={`text-2xl md:text-3xl font-bold ${t.textPrimary}`}>{formatarKg(pesoTotalComprasAberto)} <span className={`text-sm md:text-base font-medium ${t.textAccent} ml-1`}>kg</span></p>
                </div>
                <div className={`${t.card} p-5 md:p-6 rounded-2xl shadow-md flex flex-col justify-center`}>
                  <p className={`text-[13px] font-medium ${t.textSecondary} mb-1.5`}>Compras em Aberto</p>
                  <p className={`text-2xl md:text-3xl font-bold ${t.textPrimary}`}>{comprasEmAberto.length}</p>
                </div>
              </div>

              <div className={`flex flex-col md:flex-row justify-between items-start md:items-center border-b ${t.border} pb-4 md:pb-3 gap-4`}>
                <div>
                  <h2 className={`text-xl font-bold ${t.textPrimary}`}>Gestão de Compras (Chapas)</h2>
                </div>
                <button onClick={() => carregarCompras(false)} className={`w-full md:w-auto ${t.card} border ${t.border} ${t.textPrimary} hover:${t.borderAccent} hover:${t.textAccent} px-4 py-3 md:py-2 rounded-lg text-xs font-semibold shadow-sm`}>
                  Atualizar Compras
                </button>
              </div>
              
              <div className="space-y-4">
                <h3 className={`text-lg font-bold ${isDarkMode ? 'text-amber-400' : 'text-amber-600'} flex items-center gap-2`}>
                  Compras em Aberto ({comprasEmAberto.length})
                </h3>
                <div className="grid grid-cols-1 gap-4">
                  {comprasEmAberto.map(compra => renderCartaoCompra(compra))}
                  {comprasEmAberto.length === 0 && !carregando && (
                    <div className={`p-8 text-center ${t.textSecondary} ${t.card} rounded-2xl border ${t.border}`}>Nenhuma ordem de compra em aberto.</div>
                  )}
                </div>
              </div>

              <div className={`space-y-4 pt-6 border-t ${t.border}`}>
                <h3 className={`text-lg font-bold ${t.textAccent} flex items-center gap-2`}>
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
                  Compras Recebidas ({comprasRecebidas.length})
                </h3>
                <div className="grid grid-cols-1 gap-4 opacity-80 hover:opacity-100 transition-opacity">
                  {comprasRecebidas.map(compra => renderCartaoCompra(compra))}
                  {comprasRecebidas.length === 0 && !carregando && (
                    <div className={`p-8 text-center ${t.textSecondary} ${t.card} rounded-2xl border ${t.border}`}>Nenhuma ordem de compra concluída.</div>
                  )}
                </div>
              </div>
            </div>
          );
        })()}

        {/* ABA DASHBOARD */}
        {abaAtiva === 'dashboard' && (
          <div className="space-y-8 w-full">
            <div className={`flex flex-col sm:flex-row justify-between items-start sm:items-center border-b ${t.border} pb-4 sm:pb-3 gap-3`}>
              <h2 className={`text-xl font-bold ${t.textPrimary}`}>Indicadores Operacionais e Faturamento</h2>
              <span className={`text-xs ${t.textAccent} ${t.bgAccentSoft} border ${t.borderAccentSoft} px-3 py-1.5 rounded-full font-mono w-full sm:w-auto text-center`}>
                Mês de Referência: {dadosDashboard.mes_referencia}
              </span>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 md:gap-5">
              <div className={`${t.card} p-5 md:p-6 rounded-2xl shadow-md flex flex-col justify-center relative overflow-hidden`}>
                <div className={`absolute top-0 right-0 w-2 h-full bg-[#5DD62C]`}></div>
                <p className={`text-[13px] font-medium ${t.textSecondary} mb-1.5`}>Faturamento (Mês ERP)</p>
                <p className={`text-2xl md:text-3xl font-bold ${t.textPrimary}`}>R$ {(dadosDashboard.faturamento_mes || 0).toLocaleString('pt-BR', { minimumFractionDigits: 2 })}</p>
              </div>
              
              <div className={`${t.card} p-5 md:p-6 rounded-2xl shadow-md flex flex-col justify-center relative overflow-hidden`}>
                <div className={`absolute top-0 right-0 w-2 h-full bg-sky-500`}></div>
                <p className={`text-[13px] font-medium ${t.textSecondary} mb-1.5`}>Peso Expedido (Mês ERP)</p>
                <p className={`text-2xl md:text-3xl font-bold ${t.textPrimary}`}>{formatarKg(dadosDashboard.peso_mes_kg)} <span className={`text-sm md:text-base font-medium ${t.textAccent} ml-1`}>kg</span></p>
              </div>
              
              <div className={`${t.card} p-5 md:p-6 rounded-2xl shadow-md flex flex-col justify-center relative overflow-hidden`}>
                <div className={`absolute top-0 right-0 w-2 h-full bg-indigo-500`}></div>
                <p className={`text-[13px] font-medium ${t.textSecondary} mb-1.5`}>NFs Emitidas</p>
                <p className={`text-2xl md:text-3xl font-bold ${t.textPrimary}`}>{dadosDashboard.total_nfs_mes || 0}</p>
              </div>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <div className={`${t.card} p-5 md:p-6 rounded-2xl shadow-md flex flex-col justify-between`}>
                <div>
                  <h3 className={`text-lg font-bold ${t.textPrimary} mb-5 border-b ${t.border} pb-2`}>Resumo da Carteira em Aberto</h3>
                  <div className="space-y-4">
                    <div className={`flex justify-between items-center ${t.inner} p-4 rounded-xl border ${t.border}`}>
                      <span className={`text-sm ${t.textSecondary}`}>Faturamento Ativo</span>
                      <span className={`text-base md:text-lg font-bold ${t.textPrimary} font-mono`}>R$ {(dadosDashboard.faturamento_carteira || 0).toLocaleString('pt-BR', { minimumFractionDigits: 2 })}</span>
                    </div>
                    <div className={`flex justify-between items-center ${t.inner} p-4 rounded-xl border ${t.border}`}>
                      <span className={`text-sm ${t.textSecondary}`}>Volume em Carga</span>
                      <span className={`text-base md:text-lg font-bold ${t.textAccent} font-mono`}>{formatarKg(dadosDashboard.peso_carteira_kg)} kg</span>
                    </div>
                    <div className={`flex justify-between items-center ${t.inner} p-4 rounded-xl border ${t.border}`}>
                      <span className={`text-sm ${t.textSecondary}`}>Pedidos Ativos</span>
                      <span className={`text-base md:text-lg font-bold ${t.textPrimary} font-mono`}>{dadosDashboard.total_pedidos_carteira || 0} ped.</span>
                    </div>
                  </div>
                </div>
              </div>

              <div className={`${t.card} p-5 md:p-6 rounded-2xl shadow-md`}>
                <h3 className={`text-lg font-bold ${t.textPrimary} mb-5 border-b ${t.border} pb-2`}>Distribuição de OFs Por Estágio (Kanban)</h3>
                <div className="space-y-4">
                  {['Pendente', 'Compras', 'Produção', 'Parcial', 'Pronto', 'Faturada'].map(stage => {
                    const totalOFS = Object.values(dadosDashboard.distribuicao_kanban).reduce((a,b)=>a+b,0);
                    const count = dadosDashboard.distribuicao_kanban[stage] || 0;
                    const color = stage === 'Pronto' ? 'bg-[#5DD62C]' : stage === 'Produção' ? 'bg-purple-500' : stage === 'Compras' ? 'bg-sky-500' : stage === 'Parcial' ? 'bg-teal-500' : stage === 'Faturada' ? 'bg-gray-500' : 'bg-amber-500';
                    return (
                      <div key={stage}>
                        <div className="flex justify-between text-xs font-semibold mb-1.5">
                          <span className={t.textPrimary}>{stage} ({count})</span>
                          <span className={t.textSecondary}>{totalOFS ? Math.round((count/totalOFS)*100) : 0}%</span>
                        </div>
                        <div className={`w-full ${t.inner} h-3 rounded-full overflow-hidden border ${t.border}`}>
                          <div className={`${color} h-full transition-all duration-500`} style={{ width: `${totalOFS ? (count/totalOFS)*100 : 0}%` }}></div>
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            </div>
          </div>
        )}

      </main>
    </div>
  )
}

export default App;