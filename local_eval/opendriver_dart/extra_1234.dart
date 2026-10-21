class AppConfig {
  static const apiBaseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'http://127.0.0.1:4320',
  );

  static const appEnv = String.fromEnvironment(
    'APP_ENV',
    defaultValue: 'development',
  );

  static const mapTileUrlTemplate = String.fromEnvironment(
    'MAP_TILE_URL_TEMPLATE',
    defaultValue: '',
  );

  static const mapReferenceTileUrlTemplate = String.fromEnvironment(
    'MAP_REFERENCE_TILE_URL_TEMPLATE',
    defaultValue: '',
  );

  static const vectorMapsEnabled = bool.fromEnvironment(
    'VECTOR_MAPS_ENABLED',
    defaultValue: false,
  );

  static const localPmTilesFileName = String.fromEnvironment(
    'LOCAL_PMTILES_FILE_NAME',
    defaultValue: 'opendriver_us_markets.pmtiles',
  );

  static const sandboxMapsEnabled = bool.fromEnvironment(
    'SANDBOX_MAPS_ENABLED',
    defaultValue: true,
  );

  static const sandboxPaymentsEnabled = bool.fromEnvironment(
    'SANDBOX_PAYMENTS_ENABLED',
    defaultValue: true,
  );

  static const pollingIntervalSeconds = int.fromEnvironment(
    'POLLING_INTERVAL_SECONDS',
    defaultValue: 3,
  );
}
0