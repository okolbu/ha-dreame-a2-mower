"""Domain layer (layer 4) — orchestration services between transport/state and
the entity/presentation layers.

Extracted incrementally by refactor-v2 P3 (target architecture §2). Modules here
own one domain concern each and take the coordinator (``coord``) as an explicit
first argument rather than being coordinator mixins, so the logic lives at the
domain layer while the coordinator keeps its public method surface via thin
delegators.

Layer rule (tests/audit/test_layer_imports.py): domain=4 may import
state=3 / transport=2 / protocol=1 / foundation=0; it must NOT import
entities (5) or presentation (6).
"""
