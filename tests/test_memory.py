"""Lightweight tests that don't require a live CockroachDB/AWS connection --
they check the pure helper functions. Full integration tests need a real
CockroachDB cluster (see README "Testing against a real cluster") since
CockroachDB's vector index behavior isn't meaningfully mockable.
"""
from src.embeddings import to_pgvector_literal


def test_to_pgvector_literal_format():
    assert to_pgvector_literal([0.1, -0.2, 0.30000001]) == "[0.10000000,-0.20000000,0.30000001]"


def test_to_pgvector_literal_empty():
    assert to_pgvector_literal([]) == "[]"
