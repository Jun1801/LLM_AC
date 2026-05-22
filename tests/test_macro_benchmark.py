from __future__ import annotations

from collections import Counter

from scripts.macro_benchmark import build_trace_catalog, generate_zipfian_workload


def test_trace_catalog_default_size_and_uniqueness():
    catalog = build_trace_catalog()
    assert 100 <= len(catalog) <= 500
    assert len({trace.prompt_id for trace in catalog}) == len(catalog)
    assert len({trace.cluster_id for trace in catalog}) == 40


def test_zipfian_workload_has_locality_and_first_seen_flags():
    catalog = build_trace_catalog()
    workload = generate_zipfian_workload(catalog=catalog, workload_size=500, zipf_exponent=1.2, seed=7)

    cluster_counts = Counter(event.cluster_id for event in workload)
    assert len(cluster_counts) > 10
    assert cluster_counts.most_common(1)[0][1] > cluster_counts.most_common()[-1][1]

    first_seen = [event for event in workload if event.first_seen_cluster]
    repeats = [event for event in workload if not event.first_seen_cluster]
    assert first_seen
    assert repeats
    assert all(event.cluster_occurrence == 1 for event in first_seen)
    assert all(event.cluster_occurrence > 1 for event in repeats)
