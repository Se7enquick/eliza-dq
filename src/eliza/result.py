"""Result classes for Eliza DQ checks."""

import json
from dataclasses import dataclass, field


@dataclass
class CheckResult:
    name: str
    status: str
    fail_count: int
    total_rows: int
    column: str | None = None
    error: str | None = None

    @property
    def fail_rate(self):
        return self.fail_count / self.total_rows if self.total_rows else 0.0


@dataclass
class ElizaResult:
    checks: list = field(default_factory=list)
    total_rows: int = 0
    elapsed_ms: float = 0.0
    samples: dict = field(default_factory=dict)

    def passed(self):
        return all(c.status in ("pass", "warn") for c in self.checks)

    @property
    def exit_code(self):
        if any(c.status == "error" for c in self.checks):
            return 2
        if any(c.status == "fail" for c in self.checks):
            return 1
        return 0

    def summary(self):
        p = sum(1 for c in self.checks if c.status == "pass")
        w = sum(1 for c in self.checks if c.status == "warn")
        f = sum(1 for c in self.checks if c.status == "fail")
        e = sum(1 for c in self.checks if c.status == "error")
        parts = f"{p} passed, {w} warnings, {f} failed"
        if e:
            parts += f", {e} errors"
        return f"{parts} ({self.total_rows:,} rows, {self.elapsed_ms:.0f}ms)"

    def raise_on_fail(self):
        if not self.passed():
            failures = [c for c in self.checks if c.status in ("fail", "error")]
            msg = "; ".join(
                f"{c.name}: {c.error}" if c.error else f"{c.name}({c.fail_count:,}, {c.fail_rate:.1%})"
                for c in failures
            )
            raise RuntimeError(f"Eliza check failed: {msg}")

    def to_dict(self):
        return {
            "passed": self.passed(),
            "exit_code": self.exit_code,
            "total_rows": self.total_rows,
            "elapsed_ms": round(self.elapsed_ms, 1),
            "checks": [
                {
                    "name": c.name,
                    "column": c.column,
                    "status": c.status,
                    "fail_count": c.fail_count,
                    "fail_rate": round(c.fail_rate, 4),
                    "total_rows": c.total_rows,
                    **({"error": c.error} if c.error else {}),
                }
                for c in self.checks
            ],
        }

    def to_json(self):
        return json.dumps(self.to_dict(), indent=2)

    def __repr__(self):
        return self.summary()
