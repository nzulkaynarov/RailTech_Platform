# packages/ui-tokens — общие токены дизайна (M0-INF-05). Источник — tokens.json; остальное генерируется.
SHELL := /bin/bash
.DEFAULT_GOAL := build

.PHONY: build
build: ## tokens.json → dist/{tokens.css,shadcn.css,cabinet.css,antd.ts}, apps/cabinet/src/styles/tokens.generated.css
	node build.mjs

.PHONY: test
test: build ## Контраст WCAG 2.1 AA ≥ 4.5:1 для пар «текст / фон» (node --test, без зависимостей)
	node --test contrast.test.mjs

.PHONY: check
check: build test ## Контраст токенов и сгенерированное совпадает с закоммиченным (CI)
	git diff --exit-code -- dist ../../apps/cabinet/src/styles/tokens.generated.css \
	  || { echo "ui-tokens: dist/ или копии tokens.generated.* устарели — выполните make tokens и закоммитьте"; exit 1; }
