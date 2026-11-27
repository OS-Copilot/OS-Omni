import 'dart:io';

import 'package:flutter/foundation.dart';

import 'token_store_browser_stub.dart'
    if (dart.library.html) 'token_store_browser.dart' as browser_store;

class TokenStore {
  TokenStore({Directory? storageDirectory})
      : _storageDirectoryOverride = storageDirectory;

  static const _fileName = 'auth_token.txt';
  final Directory? _storageDirectoryOverride;

  Future<String?> readToken() async {
    if (kIsWeb) {
      return browser_store.readToken();
    }
    final file = await _tokenFile();
    if (!await file.exists()) {
      return null;
    }
    final token = await file.readAsString();
    return token.trim().isEmpty ? null : token.trim();
  }

  Future<void> writeToken(String token) async {
    if (kIsWeb) {
      browser_store.writeToken(token);
      return;
    }
    final file = await _tokenFile();
    await file.writeAsString(token);
  }

  Future<void> clear() async {
    if (kIsWeb) {
      browser_store.clearToken();
      return;
    }
    final file = await _tokenFile();
    if (await file.exists()) {
      await file.delete();
    }
  }

  Future<File> _tokenFile() async {
    final directory = _storageDirectory();
    if (!await directory.exists()) {
      await directory.create(recursive: true);
    }
    return File('${directory.path}${Platform.pathSeparator}$_fileName');
  }

  Directory _storageDirectory() {
    final overrideDirectory = _storageDirectoryOverride;
    if (overrideDirectory != null) return overrideDirectory;

    final override = Platform.environment['RIDEFLOW_STORAGE_DIR'];
    if (override != null && override.trim().isNotEmpty) {
      return Directory(override.trim());
    }

    if (Platform.isWindows) {
      final appData = Platform.environment['APPDATA'];
      if (appData != null && appData.isNotEmpty) {
        return Directory('$appData${Platform.pathSeparator}opendriver');
      }
    }

    final home =
        Platform.environment['HOME'] ?? Platform.environment['USERPROFILE'];
    if (home != null && home.isNotEmpty) {
      if (Platform.isMacOS) {
        return Directory(
          '$home${Platform.pathSeparator}Library${Platform.pathSeparator}Application Support${Platform.pathSeparator}opendriver',
        );
      }
      return Directory('$home${Platform.pathSeparator}.opendriver');
    }

    return Directory(
      '${Directory.systemTemp.path}${Platform.pathSeparator}opendriver',
    );
  }
}
