"""
Radar Semanal — busca matérias da semana via Claude API (web search) e gera site/data.json.

Uso:
    ANTHROPIC_API_KEY=sk-ant-... python scripts/buscar_materias.py

Lê config/temas.yaml (pilares -> temas -> keywords + fontes_confiaveis) e, para cada tema,
pede ao Claude para pesquisar na web (restrito às fontes confiáveis do pilar) e reportar a
matéria mais relevante publicada recentemente, via tool use estruturado (sem parsing frágil
de JSON em texto livre).
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import anthropic
import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "temas.yaml"
OUTPUT_PATH = ROOT / "site" / "data.json"

MODEL = "claude-sonnet-5"
ARTICLES_PER_TEMA = 1          # quantas matérias tentar trazer por tema
JANELA_DIAS = 10               # só considerar matérias publicadas nesse período
MAX_WEB_SEARCHES_POR_TEMA = 3  # trava de custo por tema

CORES_PILAR = {
    "Profissional": "var(--pilar-profissional)",
    "Trabalho": "var(--pilar-trabalho)",
    "Lazer": "var(--pilar-lazer)",
}

MESES_PT = [
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
]

REPORTAR_MATERIA_TOOL = {
    "name": "reportar_materia",
    "description": (
        "Reporta a matéria mais relevante e recente encontrada para o tema pesquisado. "
        "Chame esta função exatamente uma vez, depois de pesquisar na web, com o resultado "
        "final — mesmo que seja para informar que nada relevante foi encontrado."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "encontrou": {
                "type": "boolean",
                "description": "true se encontrou uma matéria relevante e recente; false caso contrário.",
            },
            "titulo": {"type": "string", "description": "Título da matéria, em português."},
            "resumo": {
                "type": "string",
                "description": "Resumo executivo em 2-3 frases, em português, direto ao ponto.",
            },
            "fonte": {"type": "string", "description": "Nome do veículo/site que publicou."},
            "data_publicacao": {
                "type": "string",
                "description": "Data de publicação como aparece na fonte (ex: '10 ago 2026').",
            },
            "link": {"type": "string", "description": "URL exata da matéria."},
        },
        "required": ["encontrou"],
    },
}


def montar_system_prompt(pilar_nome, fontes_confiaveis):
    dominios = ", ".join(fontes_confiaveis)
    return f"""Você é um pesquisador que abastece um radar semanal de notícias pessoal.
Pilar: {pilar_nome}.
Fontes confiáveis autorizadas para este pilar: {dominios}.

Regras:
1. Use a ferramenta de busca web para procurar pelo tema informado, restrito às fontes confiáveis listadas.
2. Priorize matérias publicadas nos últimos {JANELA_DIAS} dias. Se não achar nada nesse período nas fontes autorizadas, tente uma janela um pouco maior antes de desistir.
3. Prefira a matéria mais substantiva e relevante — não a primeira que aparecer.
4. Depois de pesquisar, chame a função reportar_materia exatamente uma vez com o resultado.
5. Se, mesmo pesquisando, não achar nada relevante e recente, chame reportar_materia com encontrou=false — não invente matéria."""


def buscar_materia(client, pilar_nome, tema, fontes_confiaveis):
    system = montar_system_prompt(pilar_nome, fontes_confiaveis)
    user_msg = (
        f"Tema: {tema['titulo']}\n"
        f"Palavras-chave: {', '.join(tema['keywords'])}\n\n"
        "Pesquise e reporte a matéria mais relevante."
    )

    tools = [
        {
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": MAX_WEB_SEARCHES_POR_TEMA,
            "allowed_domains": fontes_confiaveis,
        },
        REPORTAR_MATERIA_TOOL,
    ]

    messages = [{"role": "user", "content": user_msg}]

    response = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        system=system,
        messages=messages,
        tools=tools,
    )

    resultado = extrair_reportar_materia(response)
    if resultado is not None:
        return resultado

    # O modelo pesquisou mas não chamou reportar_materia ainda (ex: só respondeu em texto).
    # Fazemos uma segunda chamada forçando a função, com o histórico já construído.
    messages.append({"role": "assistant", "content": response.content})
    messages.append(
        {
            "role": "user",
            "content": "Agora chame a função reportar_materia com o resultado final da sua pesquisa.",
        }
    )
    response2 = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=system,
        messages=messages,
        tools=tools,
        tool_choice={"type": "tool", "name": "reportar_materia"},
    )
    return extrair_reportar_materia(response2)


def extrair_reportar_materia(response):
    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and block.name == "reportar_materia":
            return block.input
    return None


def formatar_data_hoje():
    agora = datetime.now(timezone.utc)
    return f"{agora.day} de {MESES_PT[agora.month - 1]} de {agora.year}"


def main():
    if "ANTHROPIC_API_KEY" not in os.environ:
        print("ERRO: variável de ambiente ANTHROPIC_API_KEY não definida.", file=sys.stderr)
        sys.exit(1)

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    client = anthropic.Anthropic()

    pilares_saida = []
    total_temas = sum(len(p["temas"]) for p in config["pilares"])
    contador = 0

    for pilar in config["pilares"]:
        nome_pilar = pilar["nome"]
        fontes = pilar.get("fontes_confiaveis", [])
        materias_pilar = []

        for tema in pilar["temas"]:
            contador += 1
            print(f"[{contador}/{total_temas}] {nome_pilar} · {tema['titulo']}...", flush=True)

            try:
                resultado = buscar_materia(client, nome_pilar, tema, fontes)
            except Exception as exc:  # nunca deixa um tema derrubar o job inteiro
                print(f"  falhou: {exc}", file=sys.stderr)
                resultado = None

            if resultado and resultado.get("encontrou") and resultado.get("titulo") and resultado.get("link"):
                materias_pilar.append(
                    {
                        "tema": tema["titulo"],
                        "titulo": resultado.get("titulo", ""),
                        "resumo": resultado.get("resumo", ""),
                        "fonte": resultado.get("fonte", ""),
                        "data": resultado.get("data_publicacao", ""),
                        "link": resultado.get("link", ""),
                    }
                )
                print("  ok")
            else:
                print("  nada relevante encontrado, pulando")

            time.sleep(1)  # respiro entre chamadas

        pilares_saida.append(
            {
                "nome": nome_pilar,
                "cor": CORES_PILAR.get(nome_pilar, "var(--pilar-profissional)"),
                "materias": materias_pilar,
            }
        )

    dados = {
        "atualizado_em": formatar_data_hoje(),
        "pilares": pilares_saida,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)

    total_materias = sum(len(p["materias"]) for p in pilares_saida)
    print(f"\nConcluído: {total_materias} matérias gravadas em {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
