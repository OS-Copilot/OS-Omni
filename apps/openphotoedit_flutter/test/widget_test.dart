import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:openphotoedit_flutter/main.dart';

void main() {
  testWidgets('shows the shared Material editor shell', (tester) async {
    await tester.pumpWidget(const OpenPhotoEditApp());

    expect(find.text('OpenPhotoEdit'), findsOneWidget);
    expect(find.text('Adjust'), findsOneWidget);
    expect(find.byIcon(Icons.tune), findsWidgets);
  });
}
