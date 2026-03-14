"""Rebuild canonical.entity_edges from normalized source tables.

Data-quality guards (see docs/DATA_QUALITY_GUARDS.md):
  Guard 1 — null/placeholder device IDs are rejected before becoming graph nodes.
  Guard 2 — super-node detection: nodes connecting > SUPERNODE_USER_FRACTION_THRESHOLD
             of the population are flagged and excluded.
  Guard 3 — duplicate (src_id, dst_id, relation_type) edges are deduplicated.
  Guard 4 — all guard violations are written to ops.data_quality_issues.
"""
from __future__ import annotations

import hashlib
import logging
import warnings

import pandas as pd

from config import (
    PLACEHOLDER_DEVICE_IDS,
    SUPERNODE_USER_FRACTION_THRESHOLD,
    load_settings,
)
from db.store import DuckDBStore, make_id, utc_now

logger = logging.getLogger(__name__)


def _is_placeholder_device(device_id: object) -> bool:
    """Return True if device_id is null, empty, or a known placeholder sentinel."""
    if device_id is None or (isinstance(device_id, float) and device_id != device_id):
        return True
    s = str(device_id).strip()
    if not s or s.lower() in ("null", "none", "unknown", "n/a", "0", "na"):
        return True
    # Prefixed form used by this project: "dev_<hex32>"
    bare = s.removeprefix("dev_")
    # Check known placeholder hashes
    if s in PLACEHOLDER_DEVICE_IDS:
        return True
    # Dynamically detect MD5 of common sentinel strings
    sentinel_hashes = {
        hashlib.md5(v.encode()).hexdigest()
        for v in ("0", "", "null", "unknown", "none", "na", "n/a")
    }
    if bare in sentinel_hashes:
        return True
    return False


def _log_quality_issue(
    store: DuckDBStore,
    table_name: str,
    issue_type: str,
    detail: str,
    row_count: int,
) -> None:
    try:
        store.execute(
            """
            INSERT INTO ops.data_quality_issues
                (issue_id, recorded_at, table_name, issue_type, issue_detail, row_count)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (make_id("dqi"), utc_now(), table_name, issue_type, detail, row_count),
        )
    except Exception:
        logger.warning("Could not write data_quality_issue: %s — %s", issue_type, detail)


def _detect_and_remove_supernodes(
    edge_df: pd.DataFrame,
    total_users: int,
    store: DuckDBStore,
) -> pd.DataFrame:
    """Remove any graph nodes that connect an implausibly large fraction of users.

    A node connecting >= SUPERNODE_USER_FRACTION_THRESHOLD of the user population
    is almost certainly a placeholder/sentinel and would create an artificial giant
    component.  See docs/GRAPH_TRUST_BOUNDARY.md.
    """
    if edge_df.empty:
        return edge_df

    threshold = max(10, int(total_users * SUPERNODE_USER_FRACTION_THRESHOLD))
    # Count distinct src_id (users) per dst node
    dst_user_counts = (
        edge_df[edge_df["src_type"] == "user"]
        .groupby(["dst_type", "dst_id"])["src_id"]
        .nunique()
        .reset_index(name="n_users")
    )
    supernodes = dst_user_counts[dst_user_counts["n_users"] >= threshold]

    if supernodes.empty:
        return edge_df

    for _, sn in supernodes.iterrows():
        msg = (
            f"Super-node detected: {sn['dst_type']}:{sn['dst_id']} "
            f"connects {sn['n_users']} users "
            f"(>= {threshold} = {SUPERNODE_USER_FRACTION_THRESHOLD:.0%} of {total_users} total). "
            "Removing from graph to prevent artificial giant component."
        )
        warnings.warn(msg, UserWarning, stacklevel=2)
        logger.warning(msg)
        _log_quality_issue(
            store,
            "canonical.entity_edges",
            "supernode_removed",
            msg,
            int(sn["n_users"]),
        )

    supernode_set = set(
        zip(supernodes["dst_type"].tolist(), supernodes["dst_id"].tolist())
    )
    mask = edge_df.apply(
        lambda r: (r["dst_type"], r["dst_id"]) not in supernode_set, axis=1
    )
    return edge_df[mask].copy()


def rebuild_edges() -> pd.DataFrame:
    """Rebuild entity_edges with data-quality guards.

    Returns the final edge DataFrame (also persisted to canonical.entity_edges).
    """
    settings = load_settings()
    store = DuckDBStore(settings.db_path)

    user_device_links = store.read_table("canonical.user_device_links")
    user_bank_links = store.read_table("canonical.user_bank_links")
    crypto_wallets = store.read_table("canonical.crypto_wallets")
    crypto_transactions = store.read_table("canonical.crypto_transactions")
    login_events = store.read_table("canonical.login_events")
    users = store.read_table("canonical.users")
    total_users = max(1, len(users))

    edges: list[dict] = []
    counter = 1
    skipped_placeholder = 0

    # ── Guard 1: device links — reject placeholders ───────────────────────────
    for _, row in user_device_links.iterrows():
        did = row.get("device_id")
        if _is_placeholder_device(did):
            skipped_placeholder += 1
            continue
        edges.append({
            "edge_id": f"edge_{counter:06d}",
            "snapshot_time": row["first_seen_at"],
            "src_type": "user",
            "src_id": row["user_id"],
            "relation_type": "uses_device",
            "dst_type": "device",
            "dst_id": str(did),
        })
        counter += 1

    if skipped_placeholder > 0:
        msg = (
            f"Rejected {skipped_placeholder} user_device_links with null/placeholder device_id. "
            "These would have created an artificial super-node. See docs/DATA_QUALITY_GUARDS.md."
        )
        warnings.warn(msg, UserWarning, stacklevel=2)
        logger.warning(msg)
        _log_quality_issue(
            store, "canonical.user_device_links",
            "placeholder_device_rejected", msg, skipped_placeholder,
        )

    # ── Bank links ────────────────────────────────────────────────────────────
    for _, row in user_bank_links.iterrows():
        bid = row.get("bank_account_id")
        if bid is None or (isinstance(bid, float) and bid != bid) or str(bid).strip() == "":
            continue
        edges.append({
            "edge_id": f"edge_{counter:06d}",
            "snapshot_time": row["linked_at"],
            "src_type": "user",
            "src_id": row["user_id"],
            "relation_type": "uses_bank_account",
            "dst_type": "bank_account",
            "dst_id": str(bid),
        })
        counter += 1

    # ── Wallet ownership ──────────────────────────────────────────────────────
    for _, row in crypto_wallets[crypto_wallets["user_id"].notna()].iterrows():
        wid = row.get("wallet_id")
        if wid is None or (isinstance(wid, float) and wid != wid) or str(wid).strip() == "":
            continue
        edges.append({
            "edge_id": f"edge_{counter:06d}",
            "snapshot_time": row["created_at"],
            "src_type": "user",
            "src_id": row["user_id"],
            "relation_type": "owns_wallet",
            "dst_type": "wallet",
            "dst_id": str(wid),
        })
        counter += 1

    # ── Crypto transfer targets ───────────────────────────────────────────────
    for _, row in crypto_transactions.iterrows():
        cpw = row.get("counterparty_wallet_id")
        if cpw is None or (isinstance(cpw, float) and cpw != cpw) or str(cpw).strip() == "":
            continue
        edges.append({
            "edge_id": f"edge_{counter:06d}",
            "snapshot_time": row["occurred_at"],
            "src_type": "user",
            "src_id": row["user_id"],
            "relation_type": "crypto_transfer_to_wallet",
            "dst_type": "wallet",
            "dst_id": str(cpw),
        })
        counter += 1

    # ── Login IP links ────────────────────────────────────────────────────────
    for _, row in login_events.iterrows():
        ip = row.get("ip_address")
        if ip is None or (isinstance(ip, float) and ip != ip) or str(ip).strip() == "":
            continue
        edges.append({
            "edge_id": f"edge_{counter:06d}",
            "snapshot_time": row["occurred_at"],
            "src_type": "user",
            "src_id": row["user_id"],
            "relation_type": "login_from_ip",
            "dst_type": "ip",
            "dst_id": str(ip),
        })
        counter += 1

    edge_df = pd.DataFrame(edges)
    if edge_df.empty:
        edge_df = pd.DataFrame(columns=[
            "edge_id", "snapshot_time", "src_type", "src_id",
            "relation_type", "dst_type", "dst_id",
        ])
    else:
        # ── Guard 3: deduplicate edges ────────────────────────────────────────
        before_dedup = len(edge_df)
        edge_df = edge_df.drop_duplicates(
            subset=["src_type", "src_id", "relation_type", "dst_type", "dst_id"],
            keep="first",
        ).reset_index(drop=True)
        n_dupes = before_dedup - len(edge_df)
        if n_dupes > 0:
            msg = f"Removed {n_dupes} duplicate edges during rebuild."
            logger.info(msg)
            _log_quality_issue(
                store, "canonical.entity_edges",
                "duplicate_edges_removed", msg, n_dupes,
            )

        # Re-assign edge IDs after dedup
        edge_df["edge_id"] = [f"edge_{i + 1:06d}" for i in range(len(edge_df))]

        # ── Guard 2: super-node detection and removal ─────────────────────────
        edge_df = _detect_and_remove_supernodes(edge_df, total_users, store)

    store.replace_table("canonical.entity_edges", edge_df)
    logger.info("rebuild_edges: %d edges written to canonical.entity_edges", len(edge_df))
    return edge_df


if __name__ == "__main__":
    rebuild_edges()
