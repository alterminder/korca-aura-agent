from neo4j import AsyncSession

TEAMWORK_ROUTING_MODES = frozenset({"manual", "auto_comment", "auto_assign"})
TEAMWORK_AUTO_SYNC_INTERVALS = frozenset({60, 120, 300, 600})


async def get_teamwork_routing_mode(session: AsyncSession) -> str:
    """Return the persisted Teamwork routing mode, defaulting to manual."""
    result = await session.run(
        """
        MATCH (s:TeamworkSetting {key: "routing_mode"})
        RETURN s.value AS mode
        """
    )
    row = await result.single()
    mode = row.get("mode") if row else None
    return mode if mode in TEAMWORK_ROUTING_MODES else "manual"


async def set_teamwork_routing_mode(session: AsyncSession, mode: str) -> dict[str, str]:
    """Persist the Teamwork routing mode."""
    if mode not in TEAMWORK_ROUTING_MODES:
        raise ValueError(f"Invalid routing mode: {mode}")
    result = await session.run(
        """
        MERGE (s:TeamworkSetting {key: "routing_mode"})
        SET s.value = $mode,
            s.updated_at = toString(datetime())
        RETURN s.value AS mode
        """,
        mode=mode,
    )
    row = await result.single()
    return {"mode": row["mode"] if row else mode}


async def get_teamwork_update_sync_state(session: AsyncSession) -> dict | None:
    """Return the Teamwork updatedAt sync cursor state, if initialized."""
    result = await session.run(
        """
        MATCH (s:SyncState {source: "teamwork", name: "ticket_updates"})
        RETURN s {.*} AS state
        """
    )
    row = await result.single()
    return row.get("state") if row and row.get("state") else None


async def bootstrap_teamwork_update_sync_state(
    session: AsyncSession,
    cursor: str | None = None,
) -> dict:
    """Initialize Teamwork update sync to now so old Teamwork data is not replayed."""
    result = await session.run(
        """
        MERGE (s:SyncState {source: "teamwork", name: "ticket_updates"})
        SET s.cursor = coalesce($cursor, toString(datetime())),
            s.initialized_at = coalesce(s.initialized_at, toString(datetime())),
            s.status = "ok",
            s.error = null
        RETURN s {.*} AS state
        """,
        cursor=cursor,
    )
    row = await result.single()
    return row["state"] if row else {}


async def complete_teamwork_update_sync_state(
    session: AsyncSession,
    cursor: str,
    status: str,
    counts: dict[str, int],
    error: str | None = None,
    failed_ticket_ids: list[str] | None = None,
    failed_ticket_errors: list[str] | None = None,
) -> dict:
    """Record the result of a Teamwork update-sync run."""
    result = await session.run(
        """
        MERGE (s:SyncState {source: "teamwork", name: "ticket_updates"})
        SET s.cursor = $cursor,
            s.status = $status,
            s.error = $error,
            s.last_run_at = toString(datetime()),
            s.processed = $processed,
            s.imported = $imported,
            s.updated = $updated,
            s.protected_skipped = $protected_skipped,
            s.failed = $failed,
            s.failed_ticket_ids = $failed_ticket_ids,
            s.last_failed_ticket_errors = $failed_ticket_errors
        RETURN s {.*} AS state
        """,
        cursor=cursor,
        status=status,
        error=error,
        processed=counts.get("processed", 0),
        imported=counts.get("imported", 0),
        updated=counts.get("updated", 0),
        protected_skipped=counts.get("protected_skipped", 0),
        failed=counts.get("failed", 0),
        failed_ticket_ids=failed_ticket_ids or [],
        failed_ticket_errors=failed_ticket_errors or [],
    )
    row = await result.single()
    return row["state"] if row else {}


async def get_teamwork_auto_sync_settings(session: AsyncSession) -> dict[str, int | bool]:
    """Return auto-sync settings, defaulting to disabled and 60 seconds."""
    result = await session.run(
        """
        OPTIONAL MATCH (enabled:TeamworkSetting {key: "auto_sync_enabled"})
        OPTIONAL MATCH (interval:TeamworkSetting {key: "auto_sync_interval_seconds"})
        RETURN enabled.value AS enabled,
               interval.value AS interval_seconds
        """
    )
    row = await result.single()
    enabled = bool(row and row.get("enabled") is True)
    try:
        interval_seconds = (
            int(row.get("interval_seconds")) if row and row.get("interval_seconds") else 60
        )
    except (TypeError, ValueError):
        interval_seconds = 60
    if interval_seconds not in TEAMWORK_AUTO_SYNC_INTERVALS:
        interval_seconds = 60
    return {"enabled": enabled, "interval_seconds": interval_seconds}


async def set_teamwork_auto_sync_settings(
    session: AsyncSession,
    enabled: bool,
    interval_seconds: int,
) -> dict[str, int | bool]:
    """Persist auto-sync enablement and interval."""
    if interval_seconds not in TEAMWORK_AUTO_SYNC_INTERVALS:
        raise ValueError(f"Invalid auto-sync interval: {interval_seconds}")
    result = await session.run(
        """
        MERGE (enabled:TeamworkSetting {key: "auto_sync_enabled"})
        SET enabled.value = $enabled,
            enabled.updated_at = toString(datetime())
        MERGE (interval:TeamworkSetting {key: "auto_sync_interval_seconds"})
        SET interval.value = $interval_seconds,
            interval.updated_at = toString(datetime())
        RETURN enabled.value AS enabled,
               interval.value AS interval_seconds
        """,
        enabled=enabled,
        interval_seconds=interval_seconds,
    )
    row = await result.single()
    return {
        "enabled": bool(row["enabled"]) if row else enabled,
        "interval_seconds": int(row["interval_seconds"]) if row else interval_seconds,
    }
