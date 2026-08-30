"""Carga y validacion de la configuracion YAML."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from .matching import Term

DEFAULTS: dict[str, Any] = {
    "keywords_file": "config/keywords.yml",
    "paths": {
        "digests_dir": "digests",
        "database": "data/state.sqlite3",
        "cache_dir": ".cache",
    },
    "http": {
        "user_agent": "dofwatch/0.1 (+https://github.com/y7k4bnch6r-droid/DOF)",
        "timeout": 45,
        "max_retries": 4,
        "backoff_seconds": 2.0,
        "delay_seconds": 0.6,
        "cache_enabled": True,
        "cache_ttl_days": 45,
    },
    "matching": {"snippet_chars": 140, "max_snippets": 3, "min_score": 1},
    "dof": {
        "enabled": True,
        "api_enabled": False,
        "api_base": "https://sidofqa.segob.gob.mx/dof/sidof",
        "web_base": "https://dof.gob.mx",
        "full_text": True,
        "skip_weekends": True,
        "editions": ["MAT", "VES", "EXT"],
    },
    "gaceta": {
        "enabled": True,
        "base": "https://gaceta.diputados.gob.mx",
        "full_text": True,
        "pdf_full_text": False,
        "pdf_max_per_day": 40,
        "legislaturas": [
            {"numero": 64, "inicio": "2018-09-01", "fin": "2021-08-31"},
            {"numero": 65, "inicio": "2021-09-01", "fin": "2024-08-31"},
            {"numero": 66, "inicio": "2024-09-01", "fin": "2027-08-31"},
            {"numero": 67, "inicio": "2027-09-01", "fin": "2030-08-31"},
        ],
    },
    "digest": {
        "title": "Monitor de vejez y envejecimiento",
        "formats": ["md", "json", "html"],
        "group_by": "source",
        "include_snippets": True,
    },
    "notify": {
        "email_enabled": False,
        "email_to": [],
        "email_from": None,
        "webhook_enabled": False,
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


@dataclass
class Config:
    data: dict
    root: Path
    terms: list[Term]

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def path(self, key: str) -> Path:
        """Ruta absoluta de una entrada de ``paths``, relativa a la raiz."""
        return (self.root / self.data["paths"][key]).resolve()

    @property
    def enabled_terms(self) -> list[Term]:
        return [t for t in self.terms if t.enabled]

    @property
    def terms_by_id(self) -> dict[str, Term]:
        return {t.id: t for t in self.terms}


def load_terms(path: Path) -> list[Term]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    terms: list[Term] = []
    for item in raw.get("terms", []):
        patterns = tuple(item.get("patterns") or [])
        if not patterns:
            raise ValueError(f"El término '{item.get('id')}' no tiene patrones")
        terms.append(
            Term(
                id=item["id"],
                label=item.get("label", item["id"]),
                patterns=patterns,
                enabled=bool(item.get("enabled", True)),
                weight=int(item.get("weight", 1)),
            )
        )
    if not terms:
        raise ValueError(f"No se encontraron términos en {path}")
    return terms


def load_config(config_path: str | Path | None = None, root: str | Path | None = None) -> Config:
    root_path = Path(root).resolve() if root else Path.cwd().resolve()
    data = copy.deepcopy(DEFAULTS)

    if config_path:
        cfg_file = Path(config_path)
        if not cfg_file.is_absolute():
            cfg_file = root_path / cfg_file
        if not cfg_file.exists():
            raise FileNotFoundError(f"No existe el archivo de configuración {cfg_file}")
        user_data = yaml.safe_load(cfg_file.read_text(encoding="utf-8")) or {}
        data = _deep_merge(data, user_data)

    kw_path = Path(data["keywords_file"])
    if not kw_path.is_absolute():
        kw_path = root_path / kw_path
    terms = load_terms(kw_path)

    return Config(data=data, root=root_path, terms=terms)


def legislatura_for(cfg: Config, day: date) -> int | None:
    """Numero de legislatura vigente en una fecha, segun la configuracion."""
    for leg in cfg["gaceta"]["legislaturas"]:
        inicio = date.fromisoformat(str(leg["inicio"]))
        fin = date.fromisoformat(str(leg["fin"]))
        if inicio <= day <= fin:
            return int(leg["numero"])
    return None
