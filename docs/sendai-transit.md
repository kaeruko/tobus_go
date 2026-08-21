# 仙台市営バス GTFS-JP / GTFS-Realtime

Phase 7 (#137) では、名古屋で導入した共通 `TransitDataset -> TransitRouteEngine` を仙台市営バスへ再利用し、GTFS-Realtimeを共通 `RealtimeProvider` 境界へ追加する。

## 公式データ

仙台市交通局は2026-03-02に、市営バスのGTFS-JPとGTFS-Realtimeを公共交通オープンデータセンターで公開した。

静的GTFS-JP取得元:

```text
https://api.odpt.org/api/v4/files/odpt/SendaiMunicipal/bus_realtime_information.zip?date=current
```

静的データ取得にはODPTの `acl:consumerKey` を使用する。取得スクリプトは `ODPT_API_TOKEN` がなければ停止する。

GTFS-Realtimeは公共交通オープンデータセンターで公開されている以下のpublic endpointだけを使用する。

```text
VehiclePosition:
https://api-public.odpt.org/api/v4/gtfs/realtime/odpt_SendaiMunicipal_bus_realtime_information_vehicle

TripUpdates:
https://api-public.odpt.org/api/v4/gtfs/realtime/odpt_SendaiMunicipal_bus_realtime_information_trip_update

Alert:
https://api-public.odpt.org/api/v4/gtfs/realtime/odpt_SendaiMunicipal_bus_realtime_information_alert
```

public endpointが失敗した場合、consumer-key endpoint、HTML、別データ源へ自動fallbackしない。

ライセンスは公共交通オープンデータセンター記載の CC BY 4.0 に従う。

## 静的GTFSの鮮度guard

`date=current` を無条件に「正しい現行ダイヤ」とみなさない。取得時に公開ZIPを共通 `GtfsTransitAdapter` で完全パースし、明示した `--expected-service-date` に少なくとも1つactive serviceが存在することを確認する。

```bash
ODPT_API_TOKEN=... \
python scripts/fetch_sendai_gtfs.py \
  --output data/sendai/2026-08-21 \
  --expected-service-date 2026-08-21
```

生成する `sendai_gtfs_manifest.json` には以下を保存する。

- source URL
- validated service date
- fetched_at
- source ZIP SHA-256
- calendar coverage start/end

runtimeでも `SENDAI_GTFS_EXPECTED_SERVICE_DATE` とmanifestのvalidated service dateを完全一致で検証し、不一致なら起動停止する。古いディレクトリへfallbackしない。

## backend起動

```bash
APP_CITY=sendai \
SENDAI_GTFS_DIR=data/sendai/2026-08-21 \
SENDAI_GTFS_EXPECTED_SERVICE_DATE=2026-08-21 \
python -m ...
```

Sendai runtimeはTokyoのgraph/timetable runtimeを初期化せず、`GtfsTransitAdapter -> TransitDataset -> GtfsRouteBackend` を使用する。Realtimeは `GtfsRealtimeHttpProvider` を使用する。

## API

- `POST /route`: 静的GTFS-JPによる乗換検索
- `GET /bus/location`: VehiclePositionをroute/trip完全一致で取得
- `GET /realtime/trip-updates`: TripUpdates
- `GET /realtime/alerts`: Alert
- `POST /realtime/update`: 3feedを同一要求内で確認。どれかが失敗した場合は503

`/bus/location` は近いroute/tripを推測しない。0件は404、複数件は409で、vehicle IDを明示しない限り任意の車両を選ばない。

## 既知のデータ注意事項

公共交通オープンデータセンターの仙台市交通局データセットには、運用上GTFS-JP内に一部類似データがあり、Realtime連携に一部不具合が生じる場合がある旨が記載されている。そのため、static tripとRealtime tripが対応しない場合も別tripへ自動補正しない。対応不成立をそのまま検出可能にする。
