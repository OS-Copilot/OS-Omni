import 'dart:io';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:openphotoedit_flutter/sample_export_store.dart';

void main() {
  test('sanitizes path separators and adds a PNG extension', () {
    expect(
      sanitizeExportFilename('../community: cover'),
      '_community_ cover.png',
    );
  });

  test('rejects an empty filename', () {
    expect(() => sanitizeExportFilename('  '), throwsFormatException);
  });

  test('writes the exact bytes under the stable exports directory', () async {
    final temp = await Directory.systemTemp.createTemp('openphotoedit-test-');
    addTearDown(() => temp.delete(recursive: true));
    final store = SampleExportStore(documentsDirectoryProvider: () async => temp);
    final bytes = Uint8List.fromList([1, 2, 3, 255]);

    final saved = await store.saveBytes(
      filename: 'community activity main cover.png',
      bytes: bytes,
    );

    expect(
      saved.path,
      '${temp.path}${Platform.pathSeparator}OpenPhotoEdit'
      '${Platform.pathSeparator}Exports${Platform.pathSeparator}'
      'community activity main cover.png',
    );
    expect(await saved.readAsBytes(), bytes);
  });

}
