import { useState } from 'react'
import axios from 'axios'
import { API_URL, salvarToken } from './api.js'

export default function TelaLogin({ onEntrar }) {
  const [login, setLogin] = useState('');
  const [senha, setSenha] = useState('');
  const [erro, setErro] = useState('');
  const [enviando, setEnviando] = useState(false);

  const entrar = async (e) => {
    e.preventDefault();
    setErro('');
    setEnviando(true);
    try {
      const res = await axios.post(`${API_URL}/api/auth/login`, { login, senha });
      salvarToken(res.data.token);
      onEntrar(res.data.usuario);
    } catch (err) {
      setErro(err.response?.data?.erro || 'Não foi possível conectar ao servidor.');
      setSenha('');
    } finally {
      setEnviando(false);
    }
  };

  const campo = "w-full bg-[#151515] border border-[#333333] rounded-lg px-3 py-3 sm:py-2.5 text-sm text-[#F8F8F8] focus:outline-none focus:border-[#5DD62C]";

  return (
    <div className="min-h-screen bg-[#0F0F0F] flex items-center justify-center p-4 font-sans">
      <form onSubmit={entrar} className="w-full max-w-sm bg-[#202020] border border-[#333333] rounded-2xl shadow-xl p-6 sm:p-8 space-y-5">
        <div className="flex items-center gap-3.5">
          <img src="/logo.svg" alt="" className="w-10 h-10 object-contain" />
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-[#F8F8F8]">FIVEL Control</h1>
            <p className="text-[#A0A0A0] text-sm">Entre com seu usuário</p>
          </div>
        </div>

        <label className="block">
          <span className="block text-[11px] font-bold uppercase tracking-wider text-[#A0A0A0] mb-1.5">Usuário</span>
          <input autoFocus autoComplete="username" autoCapitalize="characters" value={login} onChange={(e) => setLogin(e.target.value.toUpperCase())} className={`${campo} uppercase`} />
        </label>

        <label className="block">
          <span className="block text-[11px] font-bold uppercase tracking-wider text-[#A0A0A0] mb-1.5">Senha</span>
          <input type="password" autoComplete="current-password" value={senha} onChange={(e) => setSenha(e.target.value)} className={campo} />
        </label>

        {erro && (
          <p className="text-xs font-bold text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2">{erro}</p>
        )}

        <button
          type="submit"
          disabled={enviando || !login || !senha}
          className="w-full bg-[#5DD62C] hover:bg-[#337418] text-[#0F0F0F] hover:text-[#F8F8F8] disabled:opacity-50 disabled:cursor-not-allowed py-3 sm:py-2.5 rounded-xl text-sm font-bold shadow-sm transition-all"
        >
          {enviando ? 'Entrando...' : 'Entrar'}
        </button>
      </form>
    </div>
  );
}
