# Life-Science Research Delivery Skill

Portable Skill package for evidence-grounded life-science research reports and slide-by-slide presentation content packs.

## Package contents

- `SKILL.md` — activation description, domain boundary, tool-use rules, fallback behavior, and deliverable contract.
- `references/workflow-and-quality.md` — the P1–P9 research method and final quality checklist.
- `examples/chronic-implant-neural-interface.md` — a dated, caveated example of a documented validation.
- `JUDGE-GUIDE.md` — import steps, example prompts, required permissions, and expected behavior when a tool is unavailable.

## Use

Import or place the `life-science-research-delivery` directory in the target agent's Skills location. The host agent supplies the model. This package does not call the project's DeepSeek API, include credentials, grant database access, deploy the website, or create a PPTX by itself.

Live research requires tools available to that specific agent session. Built-in web search is used for public scientific and official sources. The Zhihuiya/Patsnap patent MCP is used only for patent records, when exposed and authorized in the session. Availability in another account or project does not imply availability in the target session.

This package has not yet been validated by importing it into an independent judge's environment. See `JUDGE-GUIDE.md` for the manual acceptance run.
