from __future__ import annotations

from typing import Any, Callable

from . import v139_native_context

VERSION = "13.9-engine-adapter-v1"
_PROBABILITY_FIELDS = (
    "p_baseball_raw",
    "p_baseball_calibrated",
    "p_posterior",
    "p_predictive_final",
    "p_effective",
    "p_model",
    "p_win",
    "p_push",
)


def _option_key(option: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(option.get("market") or ""),
        str(option.get("name") or ""),
        str(option.get("point")),
    )


def _probability_snapshot(result: dict[str, Any]) -> dict[tuple[str, str, str], dict[str, Any]]:
    return {
        _option_key(option): {field: option.get(field) for field in _PROBABILITY_FIELDS}
        for option in result.get("options") or []
    }


def _assert_research_attachment_is_probability_neutral(
    before: dict[tuple[str, str, str], dict[str, Any]],
    result: dict[str, Any],
) -> None:
    after = _probability_snapshot(result)
    if before != after:
        raise RuntimeError(
            "V13.9 native research context attempted to mutate champion probability fields"
        )


class V13Engine:
    """Explicit V13 runner-facing engine boundary.

    V13 historically evolved through runtime shims layered on ``engine_v12``.
    This adapter gives the runner one explicit V13 engine object while retaining
    the already-tested legacy numerical core underneath. New V13 research/native
    metadata is attached at this boundary and is verified probability-neutral.
    """

    def __init__(self, legacy_engine: Any):
        self._legacy_engine = legacy_engine
        self._legacy_analyze: Callable[..., dict[str, Any]] = legacy_engine.analyze
        self.version = VERSION
        self.architecture = "explicit-v13-adapter-over-validated-legacy-core"

    @property
    def legacy_engine(self) -> Any:
        return self._legacy_engine

    def analyze(self, game: dict[str, Any], event: dict[str, Any], as_of: Any = None) -> dict[str, Any]:
        result = self._legacy_analyze(game, event, as_of=as_of)
        before = _probability_snapshot(result)
        v139_native_context.attach(result, as_of=as_of)
        _assert_research_attachment_is_probability_neutral(before, result)
        result["v13_engine"] = {
            "version": VERSION,
            "architecture": self.architecture,
            "legacy_core": getattr(self._legacy_engine, "__name__", type(self._legacy_engine).__name__),
            "native_research_attached": True,
            "native_research_affects_champion": False,
        }
        return result

    def __getattr__(self, name: str) -> Any:
        # Numerical helpers (joint_score_matrix, prob_home_win, etc.) remain
        # available to runner/tests without duplicating the validated core.
        return getattr(self._legacy_engine, name)

    def status(self) -> dict[str, Any]:
        return {
            "installed": True,
            "version": VERSION,
            "architecture": self.architecture,
            "legacy_core": getattr(self._legacy_engine, "__name__", type(self._legacy_engine).__name__),
            "native_context": v139_native_context.VERSION,
            "probability_neutral_research_boundary": True,
        }


def install_runner_engine(runner_module: Any) -> V13Engine:
    current = runner_module.engine
    if isinstance(current, V13Engine):
        return current
    engine = V13Engine(current)
    runner_module.engine = engine
    return engine


def is_installed(runner_module: Any) -> bool:
    return isinstance(getattr(runner_module, "engine", None), V13Engine)
