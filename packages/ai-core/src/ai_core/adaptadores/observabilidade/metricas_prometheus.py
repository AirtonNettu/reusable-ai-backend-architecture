"""Adaptador de observabilidade e métricas compatível com o ecossistema Prometheus."""

import threading

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

from ai_core.dominio.portas.porta_observabilidade import PortaObservabilidade


class MetricasPrometheus(PortaObservabilidade):
    """Implementação da porta de observabilidade com métricas Prometheus estruturadas e baixa cardinalidade."""

    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        self._registry = registry or CollectorRegistry(auto_describe=True)
        self._trava = threading.Lock()

        # Métricas HTTP de borda
        self.http_requisicoes_total = Counter(
            "http_requisicoes_total",
            "Total acumulado de requisições HTTP recebidas pelo gateway.",
            ["metodo", "rota", "status_codigo"],
            registry=self._registry,
        )
        self.http_requisicao_duracao_segundos = Histogram(
            "http_requisicao_duracao_segundos",
            "Latência de atendimento das requisições HTTP em segundos.",
            ["metodo", "rota"],
            buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
            registry=self._registry,
        )

        # Métricas de execução de Modelos LLM
        self.llm_requisicoes_total = Counter(
            "llm_requisicoes_total",
            "Total de requisições de inferência processadas por modelo.",
            ["modelo"],
            registry=self._registry,
        )
        self.llm_execucao_duracao_segundos = Histogram(
            "llm_execucao_duracao_segundos",
            "Duração da inferência do modelo LLM em segundos.",
            ["modelo", "provedor"],
            buckets=(0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 30.0, 60.0),
            registry=self._registry,
        )
        self.llm_tokens_total = Counter(
            "llm_tokens_total",
            "Total de tokens faturados/processados por modelo.",
            ["modelo", "tipo"],
            registry=self._registry,
        )
        self.llm_falhas_total = Counter(
            "llm_falhas_total",
            "Total de falhas e erros de inferência reportados por modelo.",
            ["modelo", "tipo_erro"],
            registry=self._registry,
        )
        self.llm_fallbacks_total = Counter(
            "llm_fallbacks_total",
            "Total de acionamentos de contingência/fallback entre modelos.",
            ["modelo_origem", "modelo_destino"],
            registry=self._registry,
        )

        # Métricas de execução de Agentes Autônomos (ReAct)
        self.agente_erros_total = Counter(
            "agente_erros_total",
            "Total de erros de execução do orquestrador de agentes.",
            ["modelo"],
            registry=self._registry,
        )
        self.agente_passos_total = Counter(
            "agente_passos_total",
            "Total de passos cognitivos executados pelos agentes.",
            ["modelo"],
            registry=self._registry,
        )

        # Estado dos Circuit Breakers (0 = Fechado/Normal, 1 = Meio-Aberto, 2 = Aberto)
        self.disjuntor_estado = Gauge(
            "disjuntor_estado",
            "Estado atual do disjuntor (0: Fechado, 1: Meio-Aberto, 2: Aberto).",
            ["disjuntor"],
            registry=self._registry,
        )

        # Métricas de persistência de conversas
        self.persistencia_operacoes_total = Counter(
            "persistencia_operacoes_total",
            "Total de operações de banco de dados executadas pelos repositórios de memória.",
            ["tipo_memoria", "operacao", "sucesso"],
            registry=self._registry,
        )
        self.persistencia_duracao_segundos = Histogram(
            "persistencia_duracao_segundos",
            "Tempo de execução de operações de persistência em segundos.",
            ["tipo_memoria", "operacao"],
            buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0),
            registry=self._registry,
        )

    # Implementação dos métodos da PortaObservabilidade
    def registrar_contagem(
        self, nome: str, valor: int = 1, tags: dict[str, str] | None = None
    ) -> None:
        """Mapeia contagens genéricas da porta para contadores Prometheus correspondentes."""
        tags = tags or {}
        if nome in ("requisicoes_geracao_total", "llm_requisicoes_total"):
            modelo = tags.get("modelo", "desconhecido")
            self.llm_requisicoes_total.labels(modelo=modelo).inc(valor)
        elif nome in ("tokens_total", "llm_tokens_total"):
            modelo = tags.get("modelo", "desconhecido")
            tipo = tags.get("tipo", "total")
            self.llm_tokens_total.labels(modelo=modelo, tipo=tipo).inc(valor)
        elif nome == "llm_falha":
            modelo = tags.get("modelo", "desconhecido")
            tipo_erro = tags.get("tipo_erro", "erro_geral")
            self.llm_falhas_total.labels(modelo=modelo, tipo_erro=tipo_erro).inc(valor)
        elif nome == "llm_fallback":
            origem = tags.get("modelo_origem", "desconhecido")
            destino = tags.get("modelo_destino", "desconhecido")
            self.llm_fallbacks_total.labels(
                modelo_origem=origem, modelo_destino=destino
            ).inc(valor)
        elif nome == "agente_erro":
            modelo = tags.get("modelo", "desconhecido")
            self.agente_erros_total.labels(modelo=modelo).inc(valor)
        elif nome == "agente_passo":
            modelo = tags.get("modelo", "desconhecido")
            self.agente_passos_total.labels(modelo=modelo).inc(valor)
        elif nome == "persistencia_operacao":
            tipo = tags.get("tipo_memoria", "memoria")
            op = tags.get("operacao", "desconhecida")
            sucesso = tags.get("sucesso", "true")
            self.persistencia_operacoes_total.labels(
                tipo_memoria=tipo, operacao=op, sucesso=sucesso
            ).inc(valor)

    def registrar_latencia(
        self, nome: str, segundos: float, tags: dict[str, str] | None = None
    ) -> None:
        """Mapeia medições de latência da porta para histogramas Prometheus."""
        tags = tags or {}
        if nome in ("latencia_geracao_segundos", "llm_execucao_duracao"):
            modelo = tags.get("modelo", "desconhecido")
            provedor = tags.get("provedor", "desconhecido")
            self.llm_execucao_duracao_segundos.labels(
                modelo=modelo, provedor=provedor
            ).observe(segundos)
        elif nome == "persistencia_duracao":
            tipo = tags.get("tipo_memoria", "memoria")
            op = tags.get("operacao", "desconhecida")
            self.persistencia_duracao_segundos.labels(
                tipo_memoria=tipo, operacao=op
            ).observe(segundos)

    def registrar_evento(
        self, evento: str, dados: dict[str, object] | None = None
    ) -> None:
        """Registra transições de estado como o disjuntor ou fallbacks."""
        dados = dados or {}
        if evento == "transicao_disjuntor":
            nome_disjuntor = str(dados.get("disjuntor", "padrao"))
            estado_str = str(dados.get("novo_estado", "fechado")).lower()
            mapa_estados = {"fechado": 0, "meio_aberto": 1, "aberto": 2}
            valor_estado = mapa_estados.get(estado_str, 0)
            self.disjuntor_estado.labels(disjuntor=nome_disjuntor).set(valor_estado)

    # Métodos fortemente tipados para instrumentação direta de alta performance
    def registrar_requisicao_http(
        self, metodo: str, rota: str, status_codigo: int, duracao_segundos: float
    ) -> None:
        """Registra a conclusão de uma requisição HTTP nas métricas de tráfego e latência."""
        rota_limpa = rota or "/"
        self.http_requisicoes_total.labels(
            metodo=metodo.upper(), rota=rota_limpa, status_codigo=str(status_codigo)
        ).inc()
        self.http_requisicao_duracao_segundos.labels(
            metodo=metodo.upper(), rota=rota_limpa
        ).observe(duracao_segundos)

    def registrar_execucao_llm(
        self, modelo: str, provedor: str, duracao_segundos: float
    ) -> None:
        """Registra o tempo de resposta da inferência do modelo."""
        self.llm_execucao_duracao_segundos.labels(
            modelo=modelo, provedor=provedor
        ).observe(duracao_segundos)

    def registrar_tokens(
        self, modelo: str, tokens_entrada: int, tokens_saida: int
    ) -> None:
        """Registra os tokens consumidos na inferência segregados por direção e total real."""
        if tokens_entrada > 0:
            self.llm_tokens_total.labels(modelo=modelo, tipo="entrada").inc(
                tokens_entrada
            )
        if tokens_saida > 0:
            self.llm_tokens_total.labels(modelo=modelo, tipo="saida").inc(tokens_saida)
        total_tokens = tokens_entrada + tokens_saida
        if total_tokens > 0:
            self.llm_tokens_total.labels(modelo=modelo, tipo="total").inc(total_tokens)

    def registrar_falha_llm(self, modelo: str, tipo_erro: str) -> None:
        """Registra uma falha de geração do modelo por tipo de erro."""
        self.llm_falhas_total.labels(modelo=modelo, tipo_erro=tipo_erro).inc()

    def registrar_fallback_llm(self, modelo_origem: str, modelo_destino: str) -> None:
        """Registra a ocorrência de comutação para modelo de contingência."""
        self.llm_fallbacks_total.labels(
            modelo_origem=modelo_origem, modelo_destino=modelo_destino
        ).inc()

    def registrar_operacao_persistencia(
        self,
        tipo_memoria: str,
        operacao: str,
        duracao_segundos: float,
        sucesso: bool = True,
    ) -> None:
        """Registra métricas operacionais dos adaptadores de persistência."""
        status_str = "true" if sucesso else "false"
        self.persistencia_operacoes_total.labels(
            tipo_memoria=tipo_memoria, operacao=operacao, sucesso=status_str
        ).inc()
        self.persistencia_duracao_segundos.labels(
            tipo_memoria=tipo_memoria, operacao=operacao
        ).observe(duracao_segundos)

    def definir_estado_disjuntor(
        self, nome_disjuntor: str, estado_numerico: int
    ) -> None:
        """Atualiza diretamente o gauge de estado do disjuntor."""
        self.disjuntor_estado.labels(disjuntor=nome_disjuntor).set(estado_numerico)

    def gerar_exposicao_prometheus(self) -> bytes:
        """Gera o payload de métricas no formato padrão de exportação de texto do Prometheus."""
        return generate_latest(self._registry)
