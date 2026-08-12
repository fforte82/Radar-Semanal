# Radar Semanal

Dashboard pessoal com atualizações semanais de matérias, organizadas em 3 pilares: Profissional, Trabalho e Lazer.

## Estrutura
- `site/` — frontend estático (HTML/CSS/JS), publicado via GitHub Pages
- `config/temas.yaml` — temas, palavras-chave e fontes confiáveis por pilar (editável, sem precisar mexer em código)
- `scripts/` — job que roda semanalmente, busca matérias via Claude API (web search) e gera `site/data.json`
- `.github/workflows/` — automação (cron semanal) que roda o script e publica no GitHub Pages

## Status
- [x] Temas, palavras-chave e fontes definidos
- [x] Wireframe do site (dados de exemplo)
- [ ] Script de busca com Claude API
- [ ] GitHub Actions (cron semanal) + secret ANTHROPIC_API_KEY
- [ ] Deploy no GitHub Pages
