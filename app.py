"""Interface Streamlit do TriageAI.

Tres abas:
  1. Triagem em tempo real: chama a IA (consome cota da API) e mostra o veredito do supervisor.
  2. Avaliacao em lote: le as respostas SALVAS e recalcula as metricas (nao usa a API).
  3. Auditoria do supervisor: para um chamado do conjunto de teste, mostra quais regras disparam.

Uso:  streamlit run app.py
"""
from pathlib import Path

import streamlit as st

import avaliar as pontuacao
import regras
from modelos import ResultadoTriagem
from regras import avaliar as supervisor
from triagem import triar

CAMINHO_CHAMADOS = Path("dados/chamados_exemplo.json")

st.set_page_config(page_title="TriageAI: triagem de chamados de TI", layout="wide")
st.title("TriageAI: triagem de chamados de TI")
st.caption(
    "A IA sugere (categoria, equipe, prioridade); um supervisor determinístico decide "
    "se o chamado segue ou se precisa de revisão humana. Projeto de portfólio, dados fictícios."
)


def listar_respostas() -> list[Path]:
    return sorted(Path("dados").glob("respostas*.json"))


def escolher_arquivo(chave: str) -> Path | None:
    arquivos = listar_respostas()
    if not arquivos:
        return None
    padrao = next((i for i, a in enumerate(arquivos) if a.name == "respostas_v2.json"), len(arquivos) - 1)
    return st.selectbox("Arquivo de respostas", arquivos, index=padrao,
                        format_func=lambda p: p.name, key=chave)


exemplos: dict[str, str] = {}
if CAMINHO_CHAMADOS.exists():
    for c in pontuacao.carregar_json(CAMINHO_CHAMADOS):
        exemplos[f"{c['id']} ({c['tipo']})"] = c["relato"]


def carregar_exemplo() -> None:
    escolha = st.session_state.get("exemplo")
    if escolha in exemplos:
        st.session_state["relato"] = exemplos[escolha]


aba1, aba2, aba3 = st.tabs(["Triagem em tempo real", "Avaliação em lote", "Auditoria do supervisor"])

# ---------------------------------------------------------------- ABA 1
with aba1:
    st.markdown("### Triagem de um relato")
    st.caption("Cada execução chama a API do Gemini e consome cota. Use apenas dados fictícios.")

    st.selectbox("Carregar um exemplo do conjunto de teste (opcional)",
                 ["(digitar)"] + list(exemplos), key="exemplo", on_change=carregar_exemplo)
    relato_input = st.text_area(
        "Relato do usuário:", key="relato", height=120,
        placeholder="Ex.: O e-SAJ está muito lento e não consigo assinar os processos desde as 9h.",
    )

    if st.button("Executar triagem", type="primary"):
        if not relato_input.strip():
            st.warning("Informe o relato do chamado antes de triar.")
        else:
            with st.spinner("Consultando o modelo e aplicando as regras..."):
                resp = triar(relato_input)

            if not resp.ok:
                st.error(f"Não foi possível triar automaticamente: {resp.mensagem}")
            else:
                resultado_ia = resp.resultado
                avaliacao = supervisor(resultado_ia, relato_input)

                st.markdown("---")
                if avaliacao.requer_revisao:
                    st.error("REVISÃO HUMANA EXIGIDA: o encaminhamento automático foi bloqueado.")
                elif avaliacao.motivos:
                    st.warning("Encaminhamento automático, COM AVISOS para o atendente.")
                else:
                    st.success("Encaminhamento automático aprovado.")
                st.caption(f"Modelo que respondeu: `{resp.modelo}`")

                col_esq, col_dir = st.columns(2)
                with col_esq:
                    st.subheader("Problemas identificados")
                    for idx, prob in enumerate(resultado_ia.problemas, 1):
                        with st.expander(f"Problema {idx}: {prob.categoria.value}", expanded=True):
                            st.write(f"**Equipe de destino:** {prob.equipe_destino.value}")
                            st.write(f"**Prioridade sugerida:** {prob.prioridade_sugerida.value}")
                            st.write(f"**Justificativa:** {prob.justificativa}")
                            st.caption(f"Trecho citado: \"{prob.trecho_do_relato}\"")

                with col_dir:
                    st.subheader("Diagnóstico do supervisor")
                    st.write(f"**Confiança autodeclarada (não calibrada):** "
                             f"`{resultado_ia.confianca_autodeclarada:.2f}`")
                    st.write(f"**Fora do escopo:** `{'Sim' if resultado_ia.fora_do_escopo else 'Não'}`")
                    if resultado_ia.informacoes_essenciais_faltantes:
                        st.markdown("**Informações essenciais faltando:**")
                        for item in resultado_ia.informacoes_essenciais_faltantes:
                            st.write(f"- {item}")
                    if resultado_ia.informacoes_complementares:
                        st.markdown("**Informações complementares:**")
                        for item in resultado_ia.informacoes_complementares:
                            st.write(f"- {item}")
                    if avaliacao.motivos:
                        st.markdown("**Alertas do supervisor:**")
                        for m in avaliacao.motivos:
                            nivel = "REVISÃO" if m.severidade.value == "revisao" else "AVISO"
                            st.write(f"- `{nivel}` **{m.codigo}**: {m.mensagem}")

# ---------------------------------------------------------------- ABA 2
with aba2:
    st.markdown("### Avaliação em lote (offline)")
    st.caption("Lê as respostas salvas e recalcula as métricas com as regras atuais. Não usa a API.")

    arquivo = escolher_arquivo("arquivo_lote")
    if not CAMINHO_CHAMADOS.exists() or arquivo is None:
        st.info("Rode `python coletar_respostas.py` para gerar as respostas e volte aqui.")
    else:
        linhas = pontuacao.carregar_linhas(CAMINHO_CHAMADOS, arquivo)
        grupos: dict[str, list] = {}
        for l in linhas:
            grupos.setdefault(l.conjunto, []).append(l)

        for nome in sorted(grupos):
            r = pontuacao.resumir(grupos[nome])
            st.markdown(f"#### Conjunto: {nome} ({r['total']} chamados)")
            if nome == "reservado":
                st.caption("Consultado durante o desenvolvimento: funciona como verificação adicional, "
                           "não como teste cego.")
            if r["nao_avaliados"]:
                st.warning(f"Chamados não avaliados: {r['nao_avaliados']}")
            if r["modelos"]:
                st.caption("Modelos que responderam: " + ", ".join(f"{m}: {n}" for m, n in sorted(r["modelos"].items())))

            c, v, p = r["classificacao"], r["revisao"], r["prioridade"]
            col = st.columns(5)
            col[0].metric("Categoria correta", f"{c['categoria']}/{c['n']}" if c["n"] else "-")
            col[1].metric("Equipe correta", f"{c['equipe']}/{c['n']}" if c["n"] else "-")
            col[2].metric("Prioridade inflada", f"{len(p['infladas'])} de {p['n']}" if p["n"] else "-")
            col[3].metric("Falsos alarmes", f"{len(v['falsos_alarmes'])} de {v['nao_precisavam']}",
                          help="O supervisor pediu revisão, mas o gabarito dizia que não era preciso.")
            col[4].metric("Alertas perdidos", f"{len(v['perdidos'])} de {v['precisavam']}",
                          help="O supervisor não pediu revisão, mas o gabarito dizia que era preciso.")
            if v["falsos_alarmes"]:
                col[3].caption(", ".join(v["falsos_alarmes"]))
            if v["perdidos"]:
                col[4].caption(", ".join(v["perdidos"]))

        st.markdown("#### Detalhe por chamado")
        st.dataframe([
            {
                "id": l.id, "tipo": l.tipo, "conjunto": l.conjunto, "status": l.status,
                "revisão esperada": l.revisao_esperada, "revisão obtida": l.revisao_obtida,
                "motivos do supervisor": ", ".join(l.motivos),
                "divergências": " | ".join(l.divergencias),
            }
            for l in linhas
        ])
        st.caption("Com 15 chamados, cada um vale cerca de 7 pontos percentuais: leia as contagens, "
                   "não porcentagens.")

# ---------------------------------------------------------------- ABA 3
with aba3:
    st.markdown("### Auditoria do supervisor")
    limite_conf = getattr(regras, "LIMITE_CONFIANCA", 0.70)
    min_palavras = getattr(regras, "MIN_PALAVRAS_RELATO", 6)
    st.markdown(
        f"O supervisor é código comum (`regras.py`), sem IA: confere a resposta contra o relato "
        f"original e contra tabelas de negócio. Exemplos do que ele verifica: confiança abaixo de "
        f"`{limite_conf:.2f}`, relato com menos de `{min_palavras}` palavras, trecho citado que não "
        f"existe no relato, equipe incompatível com a categoria e prioridade crítica.\n\n"
        "**Limite conhecido:** parte dos sinais vem do próprio modelo (confiança, ambiguidades, "
        "informações faltando). Quando ele não sinaliza nada, o supervisor pode deixar passar um "
        "caso. Veja o resultado do conjunto reservado na aba de avaliação."
    )

    arquivo_aud = escolher_arquivo("arquivo_auditoria")
    if not CAMINHO_CHAMADOS.exists() or arquivo_aud is None:
        st.info("Rode `python coletar_respostas.py` para gerar as respostas e volte aqui.")
    else:
        chamados = pontuacao.carregar_json(CAMINHO_CHAMADOS)
        respostas = pontuacao.carregar_json(arquivo_aud)
        por_id = {c["id"]: c for c in chamados}
        cid = st.selectbox("Chamado", list(por_id), key="chamado_auditoria",
                           format_func=lambda i: f"{i} ({por_id[i]['tipo']})")
        chamado, resposta = por_id[cid], respostas.get(cid)

        st.markdown(f"**Relato:** {chamado['relato']}")
        st.write(f"**Gabarito:** revisão humana esperada = "
                 f"`{chamado['gabarito_esperado']['revisao_humana']}`")

        if not resposta or not resposta.get("ok"):
            st.warning("Não há resposta válida salva para este chamado.")
        else:
            try:
                resultado = ResultadoTriagem.model_validate(resposta["resultado"])
                avaliacao = supervisor(resultado, chamado["relato"])
            except Exception:
                st.error("A resposta salva não cabe no schema atual. Recolha as respostas.")
            else:
                st.write(f"**Supervisor (regras atuais):** revisão humana = `{avaliacao.requer_revisao}`")
                if avaliacao.motivos:
                    for m in avaliacao.motivos:
                        nivel = "REVISÃO" if m.severidade.value == "revisao" else "AVISO"
                        st.write(f"- `{nivel}` **{m.codigo}**: {m.mensagem}")
                else:
                    st.write("Nenhuma regra disparou.")
                with st.expander("Resposta da IA (JSON salvo)"):
                    st.json(resposta["resultado"])