#!/usr/bin/env python3
"""
TEAM BRAIN — Cérebro de equipe para agentes de IA.

Faz os agentes conversarem ENTRE SI em vez de só responderem o usuário:
- Rodada 1: cada agente pensa sozinho (pensamento individual)
- Rodada 2: cada agente VÊ as falas dos colegas e responde a UM deles
  (construindo sobre a ideia do colega, não repetindo)
- Rodada 3: cada agente se posiciona — que parte da tarefa ele assume
- Síntese: o líder organiza tudo num plano único com divisão de papéis

Regras anti-manada (do IAdrive):
- Proibido repetir o que o colega já disse
- Proibido "perfeito não existe" / clichês
- Sempre SOMAR sobre a fala de alguém, chamando pelo nome
- Se discordar, dar alternativa concreta
"""
import json
import time
import threading
from datetime import datetime

MANIFEST = """
Você é {nome}, um membro da EQUIPE {time}. Você não fala sozinho — você conversa com seus colegas agentes e todos pensam juntos.

REGRAS DE EQUIPE:
1. Você VÊ o que os colegas disseram antes de falar. Sua fala deve SEMPRE referenciar a de um colega: "Concordo com [nome do colega] e somo que...", "Discordo do [nome do colega]: aqui está a alternativa..."
2. NUNCA repita o que já foi dito. Se a ideia já existe, SOMAR um detalhe novo ou partir para outra parte.
3. Proibido clichês: "perfeito não existe", "depende", "MVP primeiro", "boa pergunta". Seja específico.
4. Se discordar, apresente alternativa concreta — nunca descarte sem solução.
5. Na rodada de papéis: escolha UMA parte da tarefa que você executa melhor e diga "EU FAÇO: ...".
6. Fale como o especialista que você é, direto ao ponto, em português do Brasil.

MEMBROS DA EQUIPE:
{membros}

"""


class TeamBrain:
    def __init__(self, nome_time, membros, ask, max_rodadas=3, verbose=True):
        """
        membros: lista de dicts {"nome": str, "personalidade": str}
        ask: callable (nome_agente, mensagens) -> str  (mensagens = lista OpenAI-style)
        """
        self.nome_time = nome_time
        self.membros = membros
        self.ask = ask
        self.max_rodadas = max_rodadas
        self.verbose = verbose
        self.falas = {}  # nome -> lista de {rodada, texto, dirigida_a}

    def _system_prompt(self, membro):
        descs = "\n".join(
            "- %s: %s" % (m["nome"], m["personalidade"]) for m in self.membros
        )
        return MANIFEST.format(nome=membro["nome"], time=self.nome_time, membros=descs)

    def _contexto_colegas(self, rodada):
        """Constrói o contexto das falas anteriores dos colegas."""
        partes = []
        for nome, falas in self.falas.items():
            for f in falas:
                if f["rodada"] < rodada:
                    alvo = f.get("dirigida_a")
                    sufixo = " → %s" % alvo if alvo else ""
                    partes.append("[%s, rodada %d%s] %s" % (nome, f["rodada"], sufixo, f["texto"]))
        if not partes:
            return "(você é o primeiro a falar nesta rodada)"
        return "\n".join(partes)

    def _falar(self, nome, rodada, pergunta):
        """Um membro fala, vendo o que os colegas disseram."""
        membro = next(m for m in self.membros if m["nome"] == nome)
        system = self._system_prompt(membro)
        colegas_anteriores = [m["nome"] for m in self.membros[: self.membros.index(membro)]]
        instrucao = ""
        if rodada == 1:
            instrucao = ("PENSAMENTO INDIVIDUAL: responda à pergunta com sua visão técnica "
                         "inicial. Seja concreto.")
        elif rodada == 2:
            alvo = self.membros[(self.membros.index(membro) - 1) % len(self.membros)]["nome"]
            instrucao = ("RÉPLICA DIRECIONADA: responda ESPECIFICAMENTE ao que %s disse "
                         "na rodada anterior. Construa sobre a parte dele ou dispute com alternativa concreta." % alvo)
        elif rodada == 3:
            instrucao = ("DIVISÃO DE PAPÉIS: diga 'EU FAÇO: <sua parte>' escolhendo a tarefa "
                         "que você executa melhor, e diga o que espera dos colegas.")
        else:
            instrucao = ("RODADA LIVRE: progrida no plano, referencie os colegas, "
                         "resolva pendências levantadas.")

        user = ("PERGUNTA DO USUÁRIO: %s\n\n"
                "O QUE SEUS COLEGAS JÁ DISSERAM:\n%s\n\n"
                "SUA TAREFA AGORA: %s\n\n"
                "Escreva sua fala (máx. 250 palavras):" % (pergunta, self._contexto_colegas(rodada), instrucao))

        msg = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        resp = self.ask(nome, msg)
        resp = (resp or "").strip()
        self.falas.setdefault(nome, []).append({
            "rodada": rodada,
            "texto": resp,
            "dirigida_a": self._dirigida(instrucao),
            "ts": datetime.now().isoformat(),
        })
        return resp

    def _dirigida(self, instrucao):
        m = __import__("re").search(r"ao que (\w+) disse", instrucao)
        return m.group(1) if m else None

    def debater(self, pergunta, executar=None):
        """Roda o debate completo. executar: callable(nome, texto) se quiser que
        cada agente execute algo (ex: rodar código) antes da próxima rodada."""
        print("🧠 %s — equipe pensando sobre: %s" % (self.nome_time, pergunta[:80]))
        for rodada in range(1, self.max_rodadas + 1):
            print("   ── rodada %d ──" % rodada)
            for membro in self.membros:
                nome = membro["nome"]
                t0 = time.time()
                resp = self._falar(nome, rodada, pergunta)
                dt = time.time() - t0
                alvo = self.falas[nome][-1].get("dirigida_a")
                seta = " → %s" % alvo if alvo else ""
                print("   %s%s (%.1fs)" % (nome, seta, dt))
                print("   %s" % resp[:200].replace("\n", " "))
                if executar:
                    try:
                        executar(nome, resp)
                    except Exception as e:
                        print("   [execução de %s falhou: %s]" % (nome, e))
        return self.sintese(pergunta)

    def sintese(self, pergunta):
        """O líder organiza a decisão final da equipe."""
        lider = self.membros[0]["nome"]
        system = self._system_prompt(self.membros[0])
        falas = []
        for nome, fl in self.falas.items():
            for f in fl:
                falas.append("[%s r%d] %s" % (nome, f["rodada"], f["texto"]))
        user = (
            "Você é o LÍDER da equipe. Os colegas debateram a pergunta:\n%s\n\n"
            "FALAS DA EQUIPE:\n%s\n\n"
            "Sua tarefa: produza a DECISÃO FINAL ORGANIZADA — (1) resumo do que a equipe "
            "concluiu, (2) plano de ação passo a passo com o responsável de cada passo "
            "(nome do agente), (3) qualquer pendência levantada. Seja executável, sem enrolação."
            % (pergunta, "\n".join(falas))
        )
        resp = self.ask(lider, [{"role": "system", "content": system}, {"role": "user", "content": user}])
        return (resp or "").strip()


def roda_debate(nome_time, membros, ask, pergunta, max_rodadas=3, executar=None, verbose=True):
    """Atalho de uso único: cria, debate e devolve a síntese."""
    brain = TeamBrain(nome_time, membros, ask, max_rodadas=max_rodadas, verbose=verbose)
    return brain.debater(pergunta, executar=executar)
