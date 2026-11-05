import axios from 'axios'

// VITE_API_URL permite apontar uma cópia de testes para outro backend (ex.: http://localhost:5001).
export const API_URL = import.meta.env.VITE_API_URL || ((window.location.port === '5000')
  ? window.location.origin
  : `http://${window.location.hostname || 'localhost'}:5000`);

const CHAVE_TOKEN = 'fivel_token';
let tokenEmMemoria = null;

// O armazenamento do navegador pode estar bloqueado; nesse caso a sessão vale só até recarregar a página.
export function obterToken() {
  try {
    return localStorage.getItem(CHAVE_TOKEN) || tokenEmMemoria;
  } catch {
    return tokenEmMemoria;
  }
}

export function salvarToken(token) {
  tokenEmMemoria = token;
  try {
    localStorage.setItem(CHAVE_TOKEN, token);
  } catch {
    // segue só com o token em memória
  }
}

export function limparToken() {
  tokenEmMemoria = null;
  try {
    localStorage.removeItem(CHAVE_TOKEN);
  } catch {
    // nada a limpar
  }
}

let aoExpirarSessao = null;

export function definirAoExpirarSessao(funcao) {
  aoExpirarSessao = funcao;
}

axios.interceptors.request.use(config => {
  const token = obterToken();
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// Sessão expirada ou encerrada: volta para a tela de login.
axios.interceptors.response.use(resposta => resposta, erro => {
  if (erro.response?.status === 401 && !String(erro.config?.url || '').includes('/api/auth/login')) {
    limparToken();
    if (aoExpirarSessao) aoExpirarSessao();
  }
  return Promise.reject(erro);
});
