"""FX-5: CORS ERP идёт с cookie (`Access-Control-Allow-Credentials: true`), поэтому в списках ERP только Cabinet и сам ERP.

Origin сайта и github.io допустимы только у CRM (форма «Запрос», без cookie). Проверка читает `infra/` как текст,
без зависимостей и Docker; пропусков нет — нет файла, тест падает. Запуск: python3 -m unittest discover -s scripts/tests"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROD = ROOT / "infra/compose/prod.yml"
BASE = ROOT / "infra/compose/base.yml"
EXAMPLE = ROOT / "infra/.env.prod.example"


# ключ как `KEY:`, `"KEY":` или запись списком `- KEY=...`
OVERRIDE = re.compile(
    r"""^\s*(?:-\s*)?["']?(CABINET_ORIGIN|ERP_CABINET_ORIGIN|CORS_ALLOWED_ORIGINS)["']?\s*[:=]""", re.M
)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")  # нет файла — FileNotFoundError, то есть падение


def block(text: str, header: str, indent: int) -> str:
    """Строки от `header` до следующей строки с отступом не больше `indent` (комментарии на этом уровне не конец)."""
    lines = text.splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith(header))
    out = [lines[start]]
    for ln in lines[start + 1 :]:
        stripped = ln.strip()
        if stripped and not stripped.startswith("#") and len(ln) - len(ln.lstrip()) <= indent:
            break
        out.append(ln)
    return "\n".join(out)


def value_of(text: str, key: str) -> str:
    match = re.search(rf"^\s*{key}:\s*(.+?)\s*$", text, re.M)
    assert match, f"нет {key}"
    return match.group(1)


def origins_in(value: str) -> list[str]:
    """Origin'ы значения вместе с умолчанием `${VAR:-a,b}` (вложенные `${…}` внутри origin остаются как есть)."""
    inner = re.sub(r"^\$\{ERP_CABINET_ORIGIN:-(.*)\}$", r"\1", value)
    parts = re.split(r",(?=https?://)", inner)
    return [p.strip() for p in parts if p.strip()]


class ErpCorsOrigins(unittest.TestCase):
    def setUp(self):
        self.prod = read(PROD)
        self.erp_env = block(self.prod, "x-erp-prod-env:", 0)

    def test_erp_env_does_not_take_shared_cabinet_origin(self):
        self.assertIsNone(re.search(r"^\s*CABINET_ORIGIN:", self.erp_env, re.M))

    def test_erp_cabinet_origin_default_is_cabinet_only(self):
        self.assertEqual(origins_in(value_of(self.erp_env, "ERP_CABINET_ORIGIN")), ["https://${CABINET_DOMAIN}"])

    def test_erp_cors_allowed_origins_are_erp_and_cabinet_only(self):
        found = origins_in(value_of(self.erp_env, "CORS_ALLOWED_ORIGINS"))
        self.assertEqual(found, ["https://${ERP_DOMAIN}", "https://${CABINET_DOMAIN}"])

    def test_erp_services_do_not_override_cors_inline(self):
        services = re.findall(r"^  (erp-[a-z-]+):", self.prod, re.M)
        self.assertIn("erp-backend", services)
        for name in services:
            service = block(self.prod, f"  {name}:", 2)
            self.assertNotRegex(service, OVERRIDE, msg=name)

    def test_base_compose_erp_backend_is_cabinet_only(self):
        service = block(read(BASE), "  erp-backend:", 2)
        self.assertIsNone(re.search(r"^\s*CABINET_ORIGIN:", service, re.M))
        for origin in origins_in(value_of(service, "ERP_CABINET_ORIGIN")):
            self.assertNotIn("WEBSITE_DOMAIN", origin)
            self.assertNotIn("4321", origin)  # dev-сервер Astro сайта
            self.assertRegex(origin, r"cabinet|CABINET_DOMAIN")

    def test_prod_example_erp_origin_is_cabinet_only(self):
        example = read(EXAMPLE)
        cabinet = re.search(r"^CABINET_DOMAIN=(\S+)", example, re.M)
        self.assertTrue(cabinet, "нет CABINET_DOMAIN")
        lines = [ln for ln in example.splitlines() if re.match(r"^#?\s*ERP_CABINET_ORIGIN=", ln)]
        self.assertTrue(lines, "в примере нет ERP_CABINET_ORIGIN")
        for line in lines:
            value = line.split("=", 1)[1].strip()
            self.assertEqual([o for o in value.split(",") if o], [f"https://{cabinet.group(1)}"], line)

    def test_prod_example_does_not_set_erp_via_shared_name(self):
        example = read(EXAMPLE)
        self.assertIn("ERP_CABINET_ORIGIN=", example)
        self.assertRegex(example.split("CABINET_ORIGIN=")[0].splitlines()[-2], "CRM")


if __name__ == "__main__":
    unittest.main()
