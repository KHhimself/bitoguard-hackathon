# bitoguard_core/tests/test_graph_bipartite.py
from __future__ import annotations
import pandas as pd
import pytest
from features.graph_bipartite import compute_bipartite_features


def _edges_df():
    return pd.DataFrame([
        {"src_type": "user", "src_id": "u1", "relation_type": "login_from_ip",             "dst_type": "ip",     "dst_id": "ip1"},
        {"src_type": "user", "src_id": "u2", "relation_type": "login_from_ip",             "dst_type": "ip",     "dst_id": "ip1"},
        {"src_type": "user", "src_id": "u1", "relation_type": "owns_wallet",               "dst_type": "wallet", "dst_id": "w1"},
        {"src_type": "user", "src_id": "u1", "relation_type": "crypto_transfer_to_wallet", "dst_type": "wallet", "dst_id": "ext1"},
    ])


def test_bipartite_features_columns():
    result = compute_bipartite_features(_edges_df(), ["u1", "u2", "u3"])
    for col in ["ip_n_entities", "ip_total_event_count", "wallet_n_entities",
                "rel_peer_count", "graph_is_isolated"]:
        assert col in result.columns


def test_bipartite_u1_ip():
    result = compute_bipartite_features(_edges_df(), ["u1", "u2"])
    u1 = result[result["user_id"] == "u1"].iloc[0]
    assert u1["ip_n_entities"] == 1     # connected to ip1
    assert u1["wallet_n_entities"] >= 1


def test_bipartite_isolated_user():
    result = compute_bipartite_features(_edges_df(), ["u3"])
    u3 = result[result["user_id"] == "u3"].iloc[0]
    assert u3["graph_is_isolated"] == 1
    assert u3["ip_n_entities"] == 0


from features.graph_propagation import compute_label_propagation


def test_propagation_reaches_neighbor():
    edges = _edges_df()
    # u2 is positive; u1 shares ip1 with u2 → u1 should get IP propagation signal
    labels = pd.Series({"u2": 1, "u1": 0})
    result = compute_label_propagation(edges, labels, user_ids=["u1"])
    u1 = result[result["user_id"] == "u1"].iloc[0]
    assert u1["prop_ip"] > 0.0


def test_propagation_columns():
    labels = pd.Series({"u1": 1, "u2": 0})
    result = compute_label_propagation(_edges_df(), labels, user_ids=["u1", "u2"])
    for col in ["prop_ip", "prop_wallet", "prop_combined",
                "ip_rep_max_rate", "wallet_rep_max_rate",
                "rel_has_pos_neighbor", "rel_direct_pos_count"]:
        assert col in result.columns


def test_propagation_no_leakage():
    """Test user absent from labels still gets correct propagation."""
    edges = _edges_df()
    labels = pd.Series({"u2": 1})   # u1 not in labels (it's the test user)
    result = compute_label_propagation(edges, labels, user_ids=["u1"])
    u1 = result[result["user_id"] == "u1"].iloc[0]
    # u1 receives signal from u2 (training) via shared ip1 — this is correct, not leakage
    assert u1["prop_ip"] > 0.0


def test_temporal_filtering_excludes_future_edges():
    """Edges after snapshot_date must not influence features (no temporal leakage)."""
    edges = pd.DataFrame([
        {
            "src_type": "user", "src_id": "u1",
            "relation_type": "login_from_ip", "dst_type": "ip", "dst_id": "ip_shared",
            "snapshot_time": "2025-10-01T00:00:00+00:00",
        },
        {
            "src_type": "user", "src_id": "u2",
            "relation_type": "login_from_ip", "dst_type": "ip", "dst_id": "ip_shared",
            "snapshot_time": "2026-06-01T00:00:00+00:00",   # after the cutoff
        },
    ])
    cutoff = pd.Timestamp("2025-12-31T23:59:59+00:00")

    result = compute_bipartite_features(edges, ["u1", "u2"], snapshot_date=cutoff)

    # u2's edge is after the cutoff, so ip_shared should have degree 1 (only u1)
    u1 = result[result["user_id"] == "u1"].iloc[0]
    u2 = result[result["user_id"] == "u2"].iloc[0]

    assert u1["ip_n_entities"] == 1, "u1 has one IP edge before the cutoff"
    # ip_shared degree is 1 (only u1's edge survives), so no shared-IP peers for u1
    assert u1["rel_peer_count"] == 0, "u2's edge is filtered out, so u1 has no IP peers"

    assert u2["ip_n_entities"] == 0, "u2's edge is after the cutoff and must be filtered"
    assert u2["graph_is_isolated"] == 1, "u2 has no valid edges before the cutoff"


def test_temporal_filtering_none_uses_all_edges():
    """When snapshot_date=None, all edges are used (backward compatibility)."""
    edges = pd.DataFrame([
        {
            "src_type": "user", "src_id": "u1",
            "relation_type": "owns_wallet", "dst_type": "wallet", "dst_id": "w_shared",
            "snapshot_time": "2025-10-01T00:00:00+00:00",
        },
        {
            "src_type": "user", "src_id": "u2",
            "relation_type": "owns_wallet", "dst_type": "wallet", "dst_id": "w_shared",
            "snapshot_time": "2026-06-01T00:00:00+00:00",
        },
    ])

    result = compute_bipartite_features(edges, ["u1", "u2"], snapshot_date=None)

    u1 = result[result["user_id"] == "u1"].iloc[0]
    u2 = result[result["user_id"] == "u2"].iloc[0]

    # Both edges are present → w_shared degree is 2, each user sees 1 wallet peer
    assert u1["wallet_n_entities"] == 1
    assert u2["wallet_n_entities"] == 1
    assert u1["rel_peer_count"] == 1, "u1 and u2 share w_shared, so they are peers"
    assert u2["rel_peer_count"] == 1


def test_no_redundant_rel_in_degree():
    """rel_in_degree must not appear in output — it was always identical to rel_out_degree."""
    import pandas as pd
    from features.graph_bipartite import compute_bipartite_features

    edges = pd.DataFrame([
        {"src_type": "user", "src_id": "u1", "dst_type": "wallet",
         "dst_id": "w1", "relation_type": "owns_wallet", "edge_id": "e1"},
        {"src_type": "user", "src_id": "u2", "dst_type": "wallet",
         "dst_id": "w1", "relation_type": "owns_wallet", "edge_id": "e2"},
    ])
    result = compute_bipartite_features(edges, ["u1", "u2"])
    assert "rel_in_degree" not in result.columns, (
        "rel_in_degree is always == rel_out_degree and must be removed"
    )
    assert "rel_peer_count" in result.columns
    assert "rel_has_peers" in result.columns
