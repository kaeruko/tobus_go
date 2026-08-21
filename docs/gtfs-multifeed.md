# GTFS multi-feed repository contract

`GtfsRepository` is feed-scoped. One instance owns one static GTFS source.

- Create repositories with an explicit `feed_id` for non-legacy use.
- Raw GTFS IDs stay raw inside one repository.
- Use `qualified_id(source_id)` when an ID crosses the feed boundary.
- Use `GtfsFeedRegistry` when multiple feeds must coexist in one process.
- Loading a second source directory into an already-loaded repository is an error.
- Required GTFS files are validated before parsing.
- Parsing is atomic: a failed load never commits partially parsed data.
- A failed `GtfsFeedRegistry.load()` does not register the failed feed.

The deployed Tokyo code keeps the compatibility handle `gtfs_repo`, now backed by a normal `GtfsRepository("toei_bus")` instance.
