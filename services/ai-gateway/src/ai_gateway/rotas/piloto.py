"""Roteador da Aplicação Piloto e Camada Intermediária BFF Segura."""

import hashlib
import hmac
import time
import uuid
from typing import Annotated

from ai_core.aplicacao.casos_de_uso.caso_gerar_resposta import CasoDeUsoGerarResposta
from ai_core.dominio.excecoes import ErroAcessoNaoAutorizadoConversa, ErroDominio
from ai_core.dominio.modelos.geracao import ConfiguracaoGeracao, RequisicaoGeracao
from ai_core.dominio.modelos.mensagem import Mensagem
from ai_core.dominio.portas.porta_memoria import PortaRepositorioMemoria
from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Request,
    Response,
    status,
)
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from ai_gateway.configuracoes import ConfiguracoesGateway
from ai_gateway.dependencias import (
    obter_caso_gerar_resposta,
    obter_configuracoes,
    obter_repositorio_memoria,
)

roteador_piloto = APIRouter(prefix="/piloto", tags=["Aplicação Piloto"])

USUARIOS_PILOTO_PERMITIDOS: frozenset[str] = frozenset({"usuario_alfa", "usuario_beta"})
NOME_COOKIE_SESSAO: str = "piloto_sessao"
NOME_COOKIE_CSRF: str = "piloto_csrf_token"
TTL_SESSAO_SEGUNDOS: int = 86400  # 24 horas


# ------------------------------------------------------------------------------
# Funções Auxiliares Criptográficas de Sessão e Anti-CSRF
# ------------------------------------------------------------------------------


def obter_segredo_piloto(config: ConfiguracoesGateway) -> str:
    """Retorna o segredo para assinatura HMAC da sessão do piloto com fail-closed estrito (SEC-004)."""
    if config.piloto_segredo_sessao:
        return config.piloto_segredo_sessao
    if config.e_producao:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro de configuração de segurança: 'GATEWAY_PILOTO_SEGREDO_SESSAO' não configurado.",
        )
    return "segredo-sessao-piloto-desenvolvimento-local-32chars"


def calcular_hmac_sessao(id_usuario: str, timestamp: int, segredo: str) -> str:
    """Calcula HMAC-SHA256 para integridade e autenticidade da sessão."""
    mensagem = f"{id_usuario}:{timestamp}".encode()
    return hmac.new(segredo.encode("utf-8"), mensagem, hashlib.sha256).hexdigest()


def calcular_token_csrf(id_usuario: str, timestamp: int, segredo: str) -> str:
    """Calcula token anti-CSRF derivado criptograficamente da sessão."""
    mensagem = f"csrf:{id_usuario}:{timestamp}".encode()
    return hmac.new(segredo.encode("utf-8"), mensagem, hashlib.sha256).hexdigest()


def montar_cookie_sessao(id_usuario: str, timestamp: int, segredo: str) -> str:
    """Gera o valor assinado do cookie no formato: id_usuario.timestamp.hmac."""
    assinatura = calcular_hmac_sessao(id_usuario, timestamp, segredo)
    return f"{id_usuario}.{timestamp}.{assinatura}"


def validar_cookie_sessao(
    cookie_val: str | None, segredo: str
) -> tuple[str, int, str] | None:
    """Valida o formato, tempo de expiração e integridade HMAC do cookie.

    Retorna (id_usuario, timestamp, token_csrf) se válido, ou None se inválido/adulterado.
    """
    if not cookie_val or "." not in cookie_val:
        return None
    partes = cookie_val.split(".")
    if len(partes) != 3:
        return None
    id_usuario, ts_str, assinatura_recebida = partes
    if id_usuario not in USUARIOS_PILOTO_PERMITIDOS:
        return None
    try:
        ts = int(ts_str)
    except ValueError:
        return None
    agora = int(time.time())
    if agora - ts > TTL_SESSAO_SEGUNDOS or ts > agora + 300:
        return None
    assinatura_esperada = calcular_hmac_sessao(id_usuario, ts, segredo)
    if not hmac.compare_digest(assinatura_recebida, assinatura_esperada):
        return None
    token_csrf = calcular_token_csrf(id_usuario, ts, segredo)
    return id_usuario, ts, token_csrf


def aplicar_cookies_seguros(
    response: Response,
    request: Request,
    id_usuario: str,
    timestamp: int,
    segredo: str,
    config: ConfiguracoesGateway,
) -> str:
    """Configura cookies seguros (HttpOnly, SameSite, Secure) e retorna o token CSRF."""
    valor_sessao = montar_cookie_sessao(id_usuario, timestamp, segredo)
    token_csrf = calcular_token_csrf(id_usuario, timestamp, segredo)
    e_seguro = config.e_producao or request.url.scheme == "https"

    response.set_cookie(
        key=NOME_COOKIE_SESSAO,
        value=valor_sessao,
        httponly=True,
        samesite="lax",
        secure=e_seguro,
        max_age=TTL_SESSAO_SEGUNDOS,
        path="/piloto",
    )
    response.set_cookie(
        key=NOME_COOKIE_CSRF,
        value=token_csrf,
        httponly=False,
        samesite="lax",
        secure=e_seguro,
        max_age=TTL_SESSAO_SEGUNDOS,
        path="/piloto",
    )
    return token_csrf


# ------------------------------------------------------------------------------
# Dependências FastAPI de Segurança
# ------------------------------------------------------------------------------


def obter_configuracoes_requisicao(request: Request) -> ConfiguracoesGateway:
    """Retorna a configuração associada ao estado da aplicação ou fallback de cache."""
    return getattr(request.app.state, "configuracoes", None) or obter_configuracoes()


def verificar_piloto_habilitado(
    config: Annotated[ConfiguracoesGateway, Depends(obter_configuracoes_requisicao)],
) -> None:
    """Garante fail-closed: se o piloto estiver desabilitado, bloqueia acesso com 404."""
    if not config.piloto_ativo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Aplicação piloto desabilitada neste ambiente.",
        )


async def obter_sessao_piloto(
    request: Request,
    response: Response,
    config: Annotated[ConfiguracoesGateway, Depends(obter_configuracoes_requisicao)],
) -> tuple[str, str]:
    """Obtém ou inicializa a sessão autenticada com HMAC, retornando (id_usuario, csrf_token)."""
    verificar_piloto_habilitado(config)
    segredo = obter_segredo_piloto(config)
    cookie_sessao = request.cookies.get(NOME_COOKIE_SESSAO)

    dados_validados = validar_cookie_sessao(cookie_sessao, segredo)
    if dados_validados is not None:
        id_usuario, _ts, token_csrf = dados_validados
        return id_usuario, token_csrf

    # Se for mutação de estado e a sessão for inexistente ou inválida, rejeita
    if request.method in ("POST", "PUT", "DELETE", "PATCH"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sessão ausente, inválida ou expirada. Recarregue a página da aplicação piloto.",
        )

    # Em requisições de leitura (GET), inicializa uma nova sessão segura com perfil padrão
    ts = int(time.time())
    token_csrf = aplicar_cookies_seguros(
        response=response,
        request=request,
        id_usuario="usuario_alfa",
        timestamp=ts,
        segredo=segredo,
        config=config,
    )
    return "usuario_alfa", token_csrf


async def validar_csrf_piloto(
    sessao: Annotated[tuple[str, str], Depends(obter_sessao_piloto)],
    x_csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> str:
    """Valida o cabeçalho X-CSRF-Token contra o token derivado criptograficamente da sessão."""
    id_usuario, token_csrf_esperado = sessao
    if not x_csrf_token or not hmac.compare_digest(
        x_csrf_token.strip(), token_csrf_esperado
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Falha de validação CSRF: token ausente ou inválido.",
        )
    return id_usuario


# ------------------------------------------------------------------------------
# Esquemas Pydantic do BFF
# ------------------------------------------------------------------------------


class EsquemaRequisicaoPilotoChat(BaseModel):
    """Payload de mensagem enviado pela interface da aplicação piloto."""

    mensagem: str = Field(
        min_length=1, max_length=4096, description="Texto da mensagem do usuário"
    )
    id_conversa: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[a-zA-Z0-9_\-\.:]+$",
        description="Identificador da conversa para persistência no PostgreSQL",
    )
    modelo: str = Field(
        default="modelo-teste", description="Modelo a ser utilizado na inferência"
    )


class EsquemaRespostaPilotoChat(BaseModel):
    """Resposta entregue à interface da aplicação piloto com metadados para diagnóstico."""

    resposta: str
    id_conversa: str
    modelo: str
    request_id: str
    duracao_ms: float
    tokens: dict[str, int]
    id_usuario: str


class EsquemaSessaoPiloto(BaseModel):
    """Dados de sessão de usuário e segurança na aplicação piloto."""

    id_usuario: str = Field(
        pattern=r"^[a-zA-Z0-9_\-]+$",
        description="Identificador do usuário para demonstração multilocatário",
    )
    csrf_token: str | None = Field(
        default=None,
        description="Token de proteção contra Cross-Site Request Forgery",
    )


# ------------------------------------------------------------------------------
# Endpoints da Camada Intermediária BFF (/piloto/api)
# ------------------------------------------------------------------------------


@roteador_piloto.get(
    "/api/status", summary="Status dos serviços para a aplicação piloto"
)
async def obter_status_piloto(
    config: Annotated[ConfiguracoesGateway, Depends(obter_configuracoes_requisicao)],
) -> dict[str, str | bool]:
    """Retorna o estado operacional e configurações locais ativas para a UI."""
    verificar_piloto_habilitado(config)
    return {
        "status": "operacional",
        "ambiente": config.ambiente,
        "memoria_tipo": config.tipo_memoria,
        "modelo_padrao": config.modelo_padrao,
        "metricas_habilitadas": config.metricas_habilitadas,
    }


@roteador_piloto.get(
    "/api/sessao",
    response_model=EsquemaSessaoPiloto,
    summary="Obter usuário e CSRF da sessão",
)
async def obter_sessao(
    sessao: Annotated[tuple[str, str], Depends(obter_sessao_piloto)],
) -> EsquemaSessaoPiloto:
    """Retorna o identificador do usuário e o token CSRF da sessão autenticada com HMAC."""
    id_usuario, token_csrf = sessao
    return EsquemaSessaoPiloto(id_usuario=id_usuario, csrf_token=token_csrf)


@roteador_piloto.post(
    "/api/sessao",
    response_model=EsquemaSessaoPiloto,
    summary="Alternar usuário da sessão demonstrativa",
)
async def definir_sessao(
    dados: EsquemaSessaoPiloto,
    request: Request,
    response: Response,
    _id_usuario_autenticado: Annotated[str, Depends(validar_csrf_piloto)],
    config: Annotated[ConfiguracoesGateway, Depends(obter_configuracoes_requisicao)],
) -> EsquemaSessaoPiloto:
    """Atualiza o perfil da sessão para demonstrar isolamento multilocatário."""
    if config.e_producao:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="A alternância demonstrativa de perfis está estritamente desabilitada em ambiente de produção.",
        )

    if dados.id_usuario not in USUARIOS_PILOTO_PERMITIDOS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Identificador de usuário não permitido para o piloto. "
                f"Valores autorizados: {', '.join(sorted(USUARIOS_PILOTO_PERMITIDOS))}."
            ),
        )

    segredo = obter_segredo_piloto(config)
    ts = int(time.time())
    novo_csrf = aplicar_cookies_seguros(
        response=response,
        request=request,
        id_usuario=dados.id_usuario,
        timestamp=ts,
        segredo=segredo,
        config=config,
    )
    return EsquemaSessaoPiloto(id_usuario=dados.id_usuario, csrf_token=novo_csrf)


@roteador_piloto.post(
    "/api/chat",
    response_model=EsquemaRespostaPilotoChat,
    summary="Enviar mensagem e receber resposta do assistente via BFF",
)
async def enviar_chat_piloto(
    dados: EsquemaRequisicaoPilotoChat,
    request: Request,
    caso_resposta: Annotated[
        CasoDeUsoGerarResposta, Depends(obter_caso_gerar_resposta)
    ],
    id_usuario: Annotated[str, Depends(validar_csrf_piloto)],
    x_request_id: Annotated[str | None, Header(alias="X-Request-ID")] = None,
) -> EsquemaRespostaPilotoChat:
    """Processa a mensagem pelo gateway, persiste histórico e retorna resposta com telemetria."""
    id_requisicao = (
        x_request_id or request.headers.get("X-Request-ID") or str(uuid.uuid4())
    )
    inicio = time.monotonic()

    requisicao_dominio = RequisicaoGeracao(
        modelo=dados.modelo,
        mensagens=(Mensagem(papel="usuario", conteudo=dados.mensagem),),
        configuracao=ConfiguracaoGeracao(temperatura=0.7),
    )

    try:
        resposta_dominio = await caso_resposta.executar(
            requisicao=requisicao_dominio,
            id_conversa=dados.id_conversa,
            id_usuario=id_usuario,
        )
    except ErroDominio as erro:
        codigo_status = (
            status.HTTP_403_FORBIDDEN
            if isinstance(erro, ErroAcessoNaoAutorizadoConversa)
            or "Acesso negado" in str(erro)
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(
            status_code=codigo_status,
            detail=str(erro),
        ) from erro

    duracao_ms = round((time.monotonic() - inicio) * 1000, 2)

    return EsquemaRespostaPilotoChat(
        resposta=resposta_dominio.texto,
        id_conversa=dados.id_conversa,
        modelo=resposta_dominio.modelo,
        request_id=id_requisicao,
        duracao_ms=duracao_ms,
        tokens={
            "tokens_entrada": resposta_dominio.uso.tokens_entrada,
            "tokens_saida": resposta_dominio.uso.tokens_saida,
            "total_tokens": resposta_dominio.uso.total_tokens,
        },
        id_usuario=id_usuario,
    )


@roteador_piloto.get(
    "/api/conversas/{id_conversa}",
    summary="Recuperar histórico do PostgreSQL para a aplicação piloto",
)
async def recuperar_historico_piloto(
    id_conversa: str,
    memoria: Annotated[PortaRepositorioMemoria, Depends(obter_repositorio_memoria)],
    sessao: Annotated[tuple[str, str], Depends(obter_sessao_piloto)],
) -> dict[str, object]:
    """Recupera mensagens do banco garantindo autorização do usuário da sessão."""
    id_usuario = sessao[0]

    try:
        mensagens = await memoria.recuperar_historico(
            id_conversa=id_conversa,
            id_usuario=id_usuario,
        )
    except ErroDominio as erro:
        codigo_status = (
            status.HTTP_403_FORBIDDEN
            if isinstance(erro, ErroAcessoNaoAutorizadoConversa)
            or "Acesso negado" in str(erro)
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(
            status_code=codigo_status,
            detail=str(erro),
        ) from erro

    return {
        "id_conversa": id_conversa,
        "id_usuario": id_usuario,
        "mensagens": [
            {
                "papel": m.papel,
                "conteudo": m.conteudo,
                "nome": m.nome,
            }
            for m in mensagens
        ],
        "total_mensagens": len(mensagens),
    }


# ------------------------------------------------------------------------------
# Interface Gráfica Responsiva (Single Page Application)
# ------------------------------------------------------------------------------

JAVASCRIPT_SPA_PILOTO: str = """
    let usuarioAtual = 'usuario_alfa';
    let idConversaAtual = 'conv-piloto-01';
    let csrfTokenAtual = '';

    // Inicialização e vinculação de eventos sem inline handlers (SEC-009)
    document.addEventListener('DOMContentLoaded', async () => {
      document.getElementById('btn-enviar')?.addEventListener('click', enviarMensagem);
      document.getElementById('campo-mensagem')?.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') enviarMensagem();
      });
      document.getElementById('seletor-usuario')?.addEventListener('change', alternarUsuario);
      document.getElementById('btn-nova-conversa')?.addEventListener('click', gerarNovaConversa);
      document.getElementById('btn-recarregar-historico')?.addEventListener('click', carregarHistoricoDoBanco);
      document.querySelectorAll('.chip-sugestao').forEach((btn) => {
        btn.addEventListener('click', () => {
          const s = btn.getAttribute('data-sugestao');
          if (s) usarSugestao(s);
        });
      });

      await sincronizarSessao();
      await carregarStatus();
      await carregarHistoricoDoBanco();
    });

    async function sincronizarSessao() {
      try {
        const resp = await fetch('/piloto/api/sessao');
        if (resp.ok) {
          const dados = await resp.json();
          usuarioAtual = dados.id_usuario;
          csrfTokenAtual = dados.csrf_token || '';
          document.getElementById('seletor-usuario').value = usuarioAtual;
          atualizarLabelsUsuario();
        }
      } catch (err) {
        console.warn('Falha ao sincronizar sessão inicial:', err);
      }
    }

    async function alternarUsuario() {
      const novoUsuario = document.getElementById('seletor-usuario').value;
      try {
        const resp = await fetch('/piloto/api/sessao', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRF-Token': csrfTokenAtual
          },
          body: JSON.stringify({ id_usuario: novoUsuario, csrf_token: csrfTokenAtual })
        });
        if (resp.ok) {
          const dados = await resp.json();
          usuarioAtual = dados.id_usuario;
          csrfTokenAtual = dados.csrf_token || csrfTokenAtual;
          atualizarLabelsUsuario();
          await carregarHistoricoDoBanco();
        } else {
          const err = await resp.json();
          mostrarErro(`Falha ao alternar usuário (${resp.status}): ${err.detail || 'Operação negada'}`);
        }
      } catch (err) {
        mostrarErro('Falha ao alternar usuário: ' + err.message);
      }
    }

    function atualizarLabelsUsuario() {
      document.getElementById('subtitulo-conversa-header').textContent = `Sessão ativa como: ${usuarioAtual}`;
      document.getElementById('telemetria-usuario').textContent = usuarioAtual;
    }

    async function carregarStatus() {
      try {
        const resp = await fetch('/piloto/api/status');
        if (resp.ok) {
          const s = await resp.json();
          document.getElementById('txt-banco').textContent = s.memoria_tipo.toUpperCase() + ' 17';
        }
      } catch (e) {
        console.error('Falha ao obter status do piloto', e);
      }
    }

    function gerarNovaConversa() {
      const timestamp = new Date().toISOString().replace(/[-:T.]/g, '').slice(0, 14);
      idConversaAtual = `conv-${timestamp}`;
      document.getElementById('input-id-conversa').value = idConversaAtual;
      document.getElementById('titulo-conversa-header').textContent = `Conversa: ${idConversaAtual}`;
      
      // Limpa a tela mantendo apenas a mensagem de boas-vindas
      const painel = document.getElementById('painel-mensagens');
      painel.innerHTML = `
        <div class="mensagem assistente">
          <div class="mensagem-autor">🤖 Assistente Simulado • Nova Conversa</div>
          <div class="mensagem-bolha">Nova sessão iniciada: <b>${escapeHtml(idConversaAtual)}</b>.<br>Envie sua mensagem para persistir neste novo tópico do PostgreSQL.</div>
        </div>
      `;
      ocultarErro();
    }

    async function carregarHistoricoDoBanco() {
      idConversaAtual = document.getElementById('input-id-conversa').value.trim() || 'conv-piloto-01';
      document.getElementById('titulo-conversa-header').textContent = `Conversa: ${idConversaAtual}`;
      ocultarErro();

      try {
        const resp = await fetch(`/piloto/api/conversas/${encodeURIComponent(idConversaAtual)}`);
        if (!resp.ok) {
          if (resp.status === 403) {
            mostrarErro(`🔒 Acesso Negado (403 Forbidden): A conversa '${idConversaAtual}' pertence a outro usuário. O isolamento multilocatário e a proteção contra IDOR do PostgreSQL impedem o acesso por '${usuarioAtual}'.`);
          } else {
            const errJson = await resp.json();
            mostrarErro(`Erro ao carregar histórico: ${errJson.detail || resp.statusText}`);
          }
          return;
        }

        const dados = await resp.json();
        const painel = document.getElementById('painel-mensagens');
        painel.innerHTML = '';

        if (dados.mensagens.length === 0) {
          painel.innerHTML = `
            <div class="mensagem assistente">
              <div class="mensagem-autor">🤖 Sistema • Histórico Vazio</div>
              <div class="mensagem-bolha">Nenhuma mensagem gravada ainda para a conversa <b>${escapeHtml(idConversaAtual)}</b> sob o usuário <b>${escapeHtml(usuarioAtual)}</b>. Envie a primeira mensagem abaixo!</div>
            </div>
          `;
          return;
        }

        dados.mensagens.forEach(m => {
          adicionarMensagemNaTela(m.papel, m.conteudo, false);
        });

      } catch (err) {
        mostrarErro('Falha de conexão ao recuperar histórico: ' + err.message);
      }
    }

    function tratarEnter(e) {
      if (e.key === 'Enter') {
        enviarMensagem();
      }
    }

    function usarSugestao(texto) {
      const campo = document.getElementById('campo-mensagem');
      campo.value = texto;
      campo.focus();
    }

    async function enviarMensagem() {
      const campo = document.getElementById('campo-mensagem');
      const texto = campo.value.trim();
      idConversaAtual = document.getElementById('input-id-conversa').value.trim() || 'conv-piloto-01';

      if (!texto) return;

      campo.value = '';
      ocultarErro();
      adicionarMensagemNaTela('usuario', texto);

      const indicador = document.getElementById('indicador-carregamento');
      const btnEnviar = document.getElementById('btn-enviar');
      indicador.style.display = 'flex';
      btnEnviar.disabled = true;

      try {
        const resp = await fetch('/piloto/api/chat', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRF-Token': csrfTokenAtual
          },
          body: JSON.stringify({
            mensagem: texto,
            id_conversa: idConversaAtual,
            modelo: 'modelo-teste'
          })
        });

        if (!resp.ok) {
          const err = await resp.json();
          mostrarErro(`Falha na requisição (${resp.status}): ${err.detail || 'Erro desconhecido'}`);
          return;
        }

        const dados = await resp.json();
        adicionarMensagemNaTela('assistente', dados.resposta);

        // Atualiza painel de telemetria
        document.getElementById('telemetria-request-id').textContent = dados.request_id || '-';
        document.getElementById('telemetria-tempo').textContent = `${dados.duracao_ms} ms`;
        if (dados.tokens) {
          document.getElementById('telemetria-tokens').textContent = 
            `${dados.tokens.tokens_entrada} / ${dados.tokens.tokens_saida} / ${dados.tokens.total_tokens}`;
        }
      } catch (err) {
        mostrarErro('Erro de comunicação com o AI Gateway: ' + err.message);
      } finally {
        indicador.style.display = 'none';
        btnEnviar.disabled = false;
        campo.focus();
      }
    }

    function adicionarMensagemNaTela(papel, conteudo, animar = true) {
      const painel = document.getElementById('painel-mensagens');
      const div = document.createElement('div');
      div.className = `mensagem ${papel}`;
      if (!animar) div.style.animation = 'none';

      const autor = papel === 'usuario' ? `👤 ${usuarioAtual}` : '🤖 Assistente Simulado';
      div.innerHTML = `
        <div class="mensagem-autor">${escapeHtml(autor)}</div>
        <div class="mensagem-bolha">${escapeHtml(conteudo)}</div>
      `;

      painel.appendChild(div);
      painel.scrollTop = painel.scrollHeight;
    }

    function mostrarErro(msg) {
      const banner = document.getElementById('banner-alerta');
      banner.textContent = msg;
      banner.style.display = 'block';
    }

    function ocultarErro() {
      const banner = document.getElementById('banner-alerta');
      banner.style.display = 'none';
      banner.textContent = '';
    }

    function escapeHtml(texto) {
      if (texto === null || texto === undefined) return '';
      const div = document.createElement('div');
      div.textContent = String(texto);
      return div.innerHTML;
    }
"""

HTML_PAGINA_PILOTO = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Reusable AI Backend Architecture — Aplicação Piloto</title>
  <style>
    :root {
      --bg-principal: #0b0f19;
      --bg-painel: #111827;
      --bg-cartao: #1f2937;
      --bg-input: #111827;
      --borda: #374151;
      --borda-foco: #6366f1;
      --texto-primario: #f9fafb;
      --texto-secundario: #9ca3af;
      --destaque: #6366f1;
      --destaque-hover: #4f46e5;
      --verde: #10b981;
      --azul: #38bdf8;
      --vermelho: #ef4444;
      --amarelo: #f59e0b;
      --fonte: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    }

    * { box-sizing: border-box; margin: 0; padding: 0; }

    body {
      font-family: var(--fonte);
      background-color: var(--bg-principal);
      color: var(--texto-primario);
      display: flex;
      height: 100vh;
      overflow: hidden;
    }

    /* Barra Lateral */
    aside {
      width: 320px;
      background-color: var(--bg-painel);
      border-right: 1px solid var(--borda);
      display: flex;
      flex-direction: column;
      padding: 1.25rem;
      gap: 1.25rem;
      overflow-y: auto;
    }

    .logo-container {
      display: flex;
      align-items: center;
      gap: 0.75rem;
      padding-bottom: 1rem;
      border-bottom: 1px solid var(--borda);
    }

    .logo-icone {
      width: 36px;
      height: 36px;
      background: linear-gradient(135deg, var(--destaque), var(--azul));
      border-radius: 8px;
      display: flex;
      align-items: center;
      justify-content: center;
      font-weight: bold;
      color: white;
      font-size: 1.1rem;
    }

    .logo-texto h1 { font-size: 1rem; font-weight: 700; color: var(--texto-primario); }
    .logo-texto span { font-size: 0.75rem; color: var(--texto-secundario); }

    .secao-titulo {
      font-size: 0.75rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--texto-secundario);
      margin-bottom: 0.5rem;
      font-weight: 600;
    }

    .cartao-lateral {
      background-color: var(--bg-cartao);
      border: 1px solid var(--borda);
      border-radius: 8px;
      padding: 0.85rem;
      display: flex;
      flex-direction: column;
      gap: 0.6rem;
    }

    .badge-status {
      display: inline-flex;
      align-items: center;
      gap: 0.4rem;
      font-size: 0.75rem;
      font-weight: 500;
      padding: 0.2rem 0.5rem;
      border-radius: 9999px;
      background-color: rgba(16, 185, 129, 0.15);
      color: var(--verde);
      width: fit-content;
    }

    .badge-ponto {
      width: 6px;
      height: 6px;
      background-color: currentColor;
      border-radius: 50%;
    }

    .btn {
      background-color: var(--destaque);
      color: white;
      border: none;
      border-radius: 6px;
      padding: 0.6rem 0.9rem;
      font-size: 0.85rem;
      font-weight: 600;
      cursor: pointer;
      transition: background-color 0.15s ease;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 0.5rem;
    }

    .btn:hover { background-color: var(--destaque-hover); }

    .btn-secundario {
      background-color: var(--bg-cartao);
      color: var(--texto-primario);
      border: 1px solid var(--borda);
    }
    .btn-secundario:hover { background-color: var(--borda); }

    select, input {
      width: 100%;
      background-color: var(--bg-input);
      color: var(--texto-primario);
      border: 1px solid var(--borda);
      border-radius: 6px;
      padding: 0.5rem 0.75rem;
      font-size: 0.85rem;
      outline: none;
    }

    select:focus, input:focus { border-color: var(--borda-foco); }

    /* Área Principal do Chat */
    main {
      flex: 1;
      display: flex;
      flex-direction: column;
      background-color: var(--bg-principal);
      position: relative;
    }

    header {
      padding: 1rem 1.5rem;
      background-color: var(--bg-painel);
      border-bottom: 1px solid var(--borda);
      display: flex;
      justify-content: space-between;
      align-items: center;
    }

    .chat-header-info h2 { font-size: 1.05rem; font-weight: 600; }
    .chat-header-info p { font-size: 0.8rem; color: var(--texto-secundario); }

    .header-links {
      display: flex;
      gap: 0.75rem;
      align-items: center;
    }

    .link-metrica {
      font-size: 0.8rem;
      color: var(--azul);
      text-decoration: none;
      display: flex;
      align-items: center;
      gap: 0.3rem;
      border: 1px solid rgba(56, 189, 248, 0.3);
      padding: 0.35rem 0.65rem;
      border-radius: 6px;
      transition: background 0.15s;
    }
    .link-metrica:hover { background-color: rgba(56, 189, 248, 0.1); }

    /* Mensagens */
    .mensagens-container {
      flex: 1;
      overflow-y: auto;
      padding: 1.5rem;
      display: flex;
      flex-direction: column;
      gap: 1.25rem;
    }

    .mensagem {
      max-width: 75%;
      display: flex;
      flex-direction: column;
      gap: 0.35rem;
      animation: fadeIn 0.2s ease-in-out;
    }

    @keyframes fadeIn {
      from { opacity: 0; transform: translateY(6px); }
      to { opacity: 1; transform: translateY(0); }
    }

    .mensagem.usuario {
      align-self: flex-end;
    }

    .mensagem.assistente {
      align-self: flex-start;
    }

    .mensagem-autor {
      font-size: 0.75rem;
      color: var(--texto-secundario);
      display: flex;
      align-items: center;
      gap: 0.4rem;
    }

    .mensagem-bolha {
      padding: 0.85rem 1.1rem;
      border-radius: 12px;
      font-size: 0.92rem;
      line-height: 1.5;
      word-break: break-word;
      white-space: pre-wrap;
    }

    .mensagem.usuario .mensagem-bolha {
      background-color: var(--destaque);
      color: white;
      border-bottom-right-radius: 2px;
    }

    .mensagem.assistente .mensagem-bolha {
      background-color: var(--bg-cartao);
      color: var(--texto-primario);
      border: 1px solid var(--borda);
      border-bottom-left-radius: 2px;
    }

    .banner-alerta {
      background-color: rgba(239, 68, 68, 0.15);
      border: 1px solid var(--vermelho);
      color: #fca5a5;
      padding: 0.75rem 1rem;
      border-radius: 8px;
      font-size: 0.85rem;
      display: none;
      margin: 0 1.5rem 1rem;
    }

    /* Diagnóstico e Telemetria */
    .telemetria-painel {
      background-color: rgba(17, 24, 39, 0.8);
      border-top: 1px solid var(--borda);
      padding: 0.6rem 1.5rem;
      display: flex;
      align-items: center;
      justify-content: space-between;
      font-size: 0.75rem;
      color: var(--texto-secundario);
      flex-wrap: wrap;
      gap: 0.75rem;
    }

    .telemetria-item {
      display: flex;
      align-items: center;
      gap: 0.4rem;
    }

    .telemetria-valor {
      color: var(--texto-primario);
      font-family: monospace;
      background: var(--bg-cartao);
      padding: 0.15rem 0.4rem;
      border-radius: 4px;
      border: 1px solid var(--borda);
    }

    /* Sugestões e Input */
    .sugestoes {
      display: flex;
      gap: 0.5rem;
      padding: 0 1.5rem 0.5rem;
      overflow-x: auto;
    }

    .chip-sugestao {
      background-color: var(--bg-cartao);
      color: var(--texto-secundario);
      border: 1px solid var(--borda);
      border-radius: 9999px;
      padding: 0.35rem 0.75rem;
      font-size: 0.75rem;
      cursor: pointer;
      white-space: nowrap;
      transition: all 0.15s;
    }
    .chip-sugestao:hover {
      background-color: var(--borda);
      color: var(--texto-primario);
    }

    .input-container {
      padding: 0.75rem 1.5rem 1.25rem;
      background-color: var(--bg-painel);
      border-top: 1px solid var(--borda);
      display: flex;
      gap: 0.75rem;
    }

    .input-container input {
      flex: 1;
      padding: 0.75rem 1rem;
      font-size: 0.92rem;
      border-radius: 8px;
    }

    /* Carregamento */
    .digitando-indicador {
      display: none;
      align-items: center;
      gap: 0.4rem;
      padding: 0.5rem 1.5rem;
      font-size: 0.8rem;
      color: var(--azul);
    }

    .pontos-animados span {
      display: inline-block;
      width: 4px;
      height: 4px;
      background-color: currentColor;
      border-radius: 50%;
      animation: piscar 1.4s infinite both;
    }
    .pontos-animados span:nth-child(2) { animation-delay: 0.2s; }
    .pontos-animados span:nth-child(3) { animation-delay: 0.4s; }

    @keyframes piscar {
      0%, 80%, 100% { opacity: 0; }
      40% { opacity: 1; }
    }

    @media (max-width: 768px) {
      body { flex-direction: column; }
      aside { width: 100%; height: auto; max-height: 220px; }
      .mensagem { max-width: 90%; }
    }
  </style>
</head>
<body>

  <!-- Barra Lateral -->
  <aside>
    <div class="logo-container">
      <div class="logo-icone">AI</div>
      <div class="logo-texto">
        <h1>Aplicação Piloto</h1>
        <span>Reusable AI Backend</span>
      </div>
    </div>

    <!-- Seletor de Multilocatário -->
    <div>
      <div class="secao-titulo">Sessão e Identidade (Multilocatário)</div>
      <div class="cartao-lateral">
        <label for="seletor-usuario" style="font-size:0.75rem; color:var(--texto-secundario);">Usuário Ativo (X-User-ID):</label>
        <select id="seletor-usuario">
          <option value="usuario_alfa">usuario_alfa (Locatário A)</option>
          <option value="usuario_beta">usuario_beta (Locatário B)</option>
        </select>
        <span style="font-size:0.7rem; color:var(--texto-secundario);">
          Alterne para verificar o isolamento multilocatário e a prevenção de IDOR no PostgreSQL.
        </span>
      </div>
    </div>

    <!-- Gerenciamento da Conversa -->
    <div>
      <div class="secao-titulo">Conversa e Persistência</div>
      <div class="cartao-lateral">
        <label for="input-id-conversa" style="font-size:0.75rem; color:var(--texto-secundario);">ID da Conversa (PostgreSQL):</label>
        <input type="text" id="input-id-conversa" value="conv-piloto-01" spellcheck="false" />
        <div style="display:flex; gap:0.5rem; margin-top:0.25rem;">
          <button class="btn btn-secundario" style="flex:1;" id="btn-nova-conversa">Nova</button>
          <button class="btn btn-secundario" style="flex:1;" id="btn-recarregar-historico">Recarregar</button>
        </div>
      </div>
    </div>

    <!-- Status da Infraestrutura -->
    <div>
      <div class="secao-titulo">Infraestrutura Local</div>
      <div class="cartao-lateral" id="card-status">
        <div class="badge-status">
          <span class="badge-ponto"></span>
          <span id="txt-status-gateway">AI Gateway: Conectado</span>
        </div>
        <div style="font-size:0.75rem; color:var(--texto-secundario);">
          <div>• Persistência: <b style="color:var(--texto-primario);" id="txt-banco">PostgreSQL 17</b></div>
          <div>• Modelo: <b style="color:var(--texto-primario);">modelo-teste (Simulado)</b></div>
          <div>• Custo financeiro: <b style="color:var(--verde);">R$ 0,00 (Gratuito)</b></div>
        </div>
      </div>
    </div>
  </aside>

  <!-- Área Central -->
  <main>
    <header>
      <div class="chat-header-info">
        <h2 id="titulo-conversa-header">Conversa: conv-piloto-01</h2>
        <p id="subtitulo-conversa-header">Sessão ativa como: usuario_alfa</p>
      </div>
      <div class="header-links">
        <a class="link-metrica" href="/metrics" target="_blank" title="Inspecionar métricas expostas ao Prometheus">
          📊 Métricas Prometheus
        </a>
      </div>
    </header>

    <div class="mensagens-container" id="painel-mensagens">
      <div class="mensagem assistente">
        <div class="mensagem-autor">🤖 Assistente Simulado • Boas-vindas</div>
        <div class="mensagem-bolha">Olá! Esta é a aplicação piloto oficial da <b>Reusable AI Backend Architecture</b>.
O ambiente está integrado de ponta a ponta com o <b>AI Gateway</b>, <b>AI Core</b>, <b>PostgreSQL 17</b> e <b>Observabilidade</b>.
Envie uma mensagem abaixo para experimentar o envio, a resposta do adaptador simulado e a retenção de contexto no banco relacional.</div>
      </div>
    </div>

    <div class="banner-alerta" id="banner-alerta"></div>

    <div class="digitando-indicador" id="indicador-carregamento">
      <span class="pontos-animados">Processando no Gateway e persistindo no PostgreSQL <span></span><span></span><span></span></span>
    </div>

    <!-- Sugestões Rápidas -->
    <div class="sugestoes">
      <button class="chip-sugestao" data-sugestao="Mensagem 1: Olá! Por favor, confirme a saúde e o status do sistema.">
        1ª Requisição: Status do Sistema
      </button>
      <button class="chip-sugestao" data-sugestao="Mensagem 2: Verifique que o histórico desta conversa foi recuperado do PostgreSQL.">
        2ª Requisição: Memória no PostgreSQL
      </button>
      <button class="chip-sugestao" data-sugestao="Qual o modelo ativo e o ambiente de execução?">
        Modelo e Ambiente
      </button>
    </div>

    <!-- Barra de Input -->
    <div class="input-container">
      <input type="text" id="campo-mensagem" placeholder="Digite sua mensagem para o AI Gateway..." />
      <button class="btn" id="btn-enviar">
        <span>Enviar</span> ➤
      </button>
    </div>

    <!-- Rodapé de Telemetria e Diagnóstico -->
    <div class="telemetria-painel">
      <div class="telemetria-item">
        <span>X-Request-ID:</span>
        <span class="telemetria-valor" id="telemetria-request-id">-</span>
      </div>
      <div class="telemetria-item">
        <span>Tempo de Resposta:</span>
        <span class="telemetria-valor" id="telemetria-tempo">-</span>
      </div>
      <div class="telemetria-item">
        <span>Tokens (In/Out/Total):</span>
        <span class="telemetria-valor" id="telemetria-tokens">-</span>
      </div>
      <div class="telemetria-item">
        <span>Usuário Autenticado:</span>
        <span class="telemetria-valor" id="telemetria-usuario">usuario_alfa</span>
      </div>
    </div>
  </main>

  <script src="/piloto/app.js"></script>
</body>
</html>
"""


@roteador_piloto.get(
    "", response_class=HTMLResponse, summary="Interface da Aplicação Piloto"
)
@roteador_piloto.get("/", response_class=HTMLResponse, include_in_schema=False)
async def carregar_pagina_piloto(
    request: Request,
    config: Annotated[ConfiguracoesGateway, Depends(obter_configuracoes_requisicao)],
) -> HTMLResponse:
    """Entrega a aplicação piloto responsiva (SPA em HTML/CSS/JS puro) com cookies de sessão e CSRF."""
    verificar_piloto_habilitado(config)
    resposta = HTMLResponse(content=HTML_PAGINA_PILOTO, status_code=status.HTTP_200_OK)
    segredo = obter_segredo_piloto(config)
    cookie_sessao = request.cookies.get(NOME_COOKIE_SESSAO)
    dados_validados = validar_cookie_sessao(cookie_sessao, segredo)
    if dados_validados is None:
        ts = int(time.time())
        aplicar_cookies_seguros(
            response=resposta,
            request=request,
            id_usuario="usuario_alfa",
            timestamp=ts,
            segredo=segredo,
            config=config,
        )
    return resposta


@roteador_piloto.get("/app.js", response_class=Response, include_in_schema=False)
async def carregar_script_piloto(
    config: Annotated[ConfiguracoesGateway, Depends(obter_configuracoes_requisicao)],
) -> Response:
    """Entrega o script client-side da SPA do piloto externamente para conformidade com CSP (SEC-009)."""
    verificar_piloto_habilitado(config)
    return Response(
        content=JAVASCRIPT_SPA_PILOTO,
        media_type="application/javascript; charset=utf-8",
        headers={"Cache-Control": "public, max-age=3600"},
    )
