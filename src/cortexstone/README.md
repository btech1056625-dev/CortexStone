# Product package

This package contains the modular-monolith implementation. Keep business rules in domain/application modules and place external systems behind adapters. Runtime entry points live under `apps/`; this package must not start a process as an import side effect.

Dependencies should point inward toward stable domain contracts. The agent and model layers must not own authorization or execute connector operations.
