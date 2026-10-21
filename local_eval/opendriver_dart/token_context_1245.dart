,import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'app/app_state.dart';
import 'app/ride_flow_app.dart';
import 'core/api/api_client.dart';
import 'core/storage/token_store.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final tokenStore = TokenStore();
  final apiClient = ApiClient(tokenStore: tokenStore);
  runApp(
    ChangeNotifierProvider(
      create: (_) => AppState(apiClient: apiClient)..bootstrap(),
      child: const opendriverApp(),
    ),
  );
}
