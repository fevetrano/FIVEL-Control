import { useEffect, useState } from 'react'
import axios from 'axios'
import App from './App.jsx'
import TelaLogin from './TelaLogin.jsx'
import { API_URL, obterToken, limparToken, definirAoExpirarSessao } from './api.js'

export default function Root() {
  // undefined = conferindo a sessão salva; null = precisa entrar.
  const [usuario, setUsuario] = useState(() => (obterToken() ? undefined : null));

  useEffect(() => {
    definirAoExpirarSessao(() => setUsuario(null));
    if (!obterToken()) return;
    axios.get(`${API_URL}/api/auth/eu`)
      .then(res => setUsuario(res.data.usuario))
      .catch(() => setUsuario(null));
  }, []);

  const sair = () => {
    axios.post(`${API_URL}/api/auth/logout`)
      .catch(() => {})
      .finally(() => {
        limparToken();
        setUsuario(null);
      });
  };

  if (usuario === undefined) return <div className="min-h-screen bg-[#0F0F0F]" />;
  if (!usuario) return <TelaLogin onEntrar={setUsuario} />;
  return <App key={usuario.login} usuario={usuario} onSair={sair} />;
}
