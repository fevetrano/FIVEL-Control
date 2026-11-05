import { useCallback, useEffect, useState } from 'react'
import axios from 'axios'
import { API_URL } from './api.js'

const FORM_VAZIO = { nome: '', login: '', senha: '', perfil: 'vendas' };
const NOME_PERFIL = { admin: 'Admin', vendas: 'Vendas' };

export default function GerenciarUsuarios({ t, usuarioAtual, onFechar }) {
  const [usuarios, setUsuarios] = useState([]);
  const [form, setForm] = useState(FORM_VAZIO);
  const [mensagem, setMensagem] = useState({ texto: '', tipo: '' });
  const [salvando, setSalvando] = useState(false);

  const mostrarErro = (err, padrao) => setMensagem({ texto: err.response?.data?.erro || padrao, tipo: 'erro' });

  const carregar = useCallback(() => {
    axios.get(`${API_URL}/api/usuarios`)
      .then(res => setUsuarios(Array.isArray(res.data) ? res.data : []))
      .catch(err => mostrarErro(err, 'Erro ao carregar usuários.'));
  }, []);

  useEffect(() => { carregar(); }, [carregar]);

  const criar = async (e) => {
    e.preventDefault();
    setSalvando(true);
    try {
      await axios.post(`${API_URL}/api/usuarios`, form);
      setMensagem({ texto: `Usuário "${form.login.trim().toLowerCase()}" criado.`, tipo: 'ok' });
      setForm(FORM_VAZIO);
      carregar();
    } catch (err) {
      mostrarErro(err, 'Erro ao criar usuário.');
    } finally {
      setSalvando(false);
    }
  };

  const trocarSenha = async (login) => {
    const proprio = login === usuarioAtual?.login;
    const senha = window.prompt(`Nova senha para "${login}" (mínimo 8 caracteres)${proprio ? '\nVocê precisará entrar de novo.' : ''}`);
    if (!senha) return;
    try {
      await axios.put(`${API_URL}/api/usuarios/${encodeURIComponent(login)}`, { senha });
      setMensagem({ texto: `Senha de "${login}" alterada.`, tipo: 'ok' });
    } catch (err) {
      mostrarErro(err, 'Erro ao trocar a senha.');
    }
  };

  const alternarAtivo = async (u) => {
    if (!window.confirm(`${u.ativo ? 'Desativar' : 'Reativar'} o acesso de "${u.login}"?`)) return;
    try {
      await axios.put(`${API_URL}/api/usuarios/${encodeURIComponent(u.login)}`, { ativo: !u.ativo });
      carregar();
    } catch (err) {
      mostrarErro(err, 'Erro ao alterar o usuário.');
    }
  };

  const campo = `w-full ${t.inner} ${t.textPrimary} border ${t.border} rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:border-[#5DD62C]`;
  const rotulo = `block text-[10px] font-bold uppercase tracking-wider ${t.textSecondary} mb-1`;

  return (
    <div className="fixed inset-0 bg-black/70 z-50 flex items-center justify-center p-2 sm:p-4" onClick={onFechar}>
      <div className={`${t.card} rounded-2xl border ${t.border} shadow-2xl w-full max-w-2xl max-h-[90vh] overflow-y-auto p-4 sm:p-6 space-y-6`} onClick={(e) => e.stopPropagation()}>
        <div className="flex justify-between items-center">
          <h2 className={`text-xl font-bold ${t.textPrimary}`}>Usuários</h2>
          <button onClick={onFechar} className={`px-3 py-1.5 rounded-lg text-xs font-bold ${t.textSecondary} border ${t.border}`}>Fechar</button>
        </div>

        {mensagem.texto && (
          <p className={`text-xs font-bold rounded-lg px-3 py-2 border ${mensagem.tipo === 'erro' ? 'text-red-400 bg-red-500/10 border-red-500/20' : 'text-[#5DD62C] bg-[#5DD62C]/10 border-[#5DD62C]/20'}`}>{mensagem.texto}</p>
        )}

        <div className={`divide-y ${t.divider} border ${t.border} rounded-xl overflow-hidden`}>
          {usuarios.map(u => (
            <div key={u.login} className={`p-3 flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-4 ${u.ativo ? '' : 'opacity-50'}`}>
              <div className="flex-1 min-w-0">
                <div className={`font-bold text-sm ${t.textPrimary} truncate`}>{u.nome}</div>
                <div className={`text-[11px] font-mono ${t.textSecondary}`}>{u.login} · {NOME_PERFIL[u.perfil] || u.perfil}{u.ativo ? '' : ' · desativado'}</div>
              </div>
              <div className="flex gap-2">
                <button onClick={() => trocarSenha(u.login)} className={`px-3 py-1.5 rounded-lg text-[11px] font-bold ${t.textSecondary} border ${t.border} hover:border-[#5DD62C]`}>Trocar senha</button>
                {u.login !== usuarioAtual?.login && (
                  <button onClick={() => alternarAtivo(u)} className={`px-3 py-1.5 rounded-lg text-[11px] font-bold border ${u.ativo ? 'text-red-400 border-red-500/30' : 'text-[#5DD62C] border-[#5DD62C]/30'}`}>{u.ativo ? 'Desativar' : 'Reativar'}</button>
                )}
              </div>
            </div>
          ))}
          {usuarios.length === 0 && <p className={`p-4 text-center text-xs ${t.textSecondary}`}>Nenhum usuário.</p>}
        </div>

        <form onSubmit={criar} className={`border ${t.border} rounded-xl p-4 space-y-3`}>
          <h3 className={`text-sm font-bold ${t.textPrimary}`}>Novo usuário</h3>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <label><span className={rotulo}>Nome</span><input value={form.nome} onChange={(e) => setForm({ ...form, nome: e.target.value })} className={campo} /></label>
            <label><span className={rotulo}>Login</span><input value={form.login} autoComplete="off" onChange={(e) => setForm({ ...form, login: e.target.value })} className={campo} /></label>
            <label><span className={rotulo}>Senha (mín. 8)</span><input type="password" autoComplete="new-password" value={form.senha} onChange={(e) => setForm({ ...form, senha: e.target.value })} className={campo} /></label>
            <label><span className={rotulo}>Perfil</span>
              <select value={form.perfil} onChange={(e) => setForm({ ...form, perfil: e.target.value })} className={campo}>
                <option value="vendas">Vendas</option>
                <option value="admin">Admin</option>
              </select>
            </label>
          </div>
          <button type="submit" disabled={salvando || !form.nome || !form.login || !form.senha} className="w-full sm:w-auto bg-[#5DD62C] hover:bg-[#337418] text-[#0F0F0F] hover:text-[#F8F8F8] disabled:opacity-50 disabled:cursor-not-allowed px-5 py-2.5 rounded-xl text-sm font-bold transition-all">
            {salvando ? 'Criando...' : 'Criar usuário'}
          </button>
        </form>
      </div>
    </div>
  );
}
