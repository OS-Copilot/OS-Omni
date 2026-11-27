import 'dart:convert';
import 'dart:io';

import 'package:flutter/services.dart';

import '../models/models.dart';

const _nativeDialogs = MethodChannel('opendriver/native_dialogs');

Future<String?> saveRideInvoicePdf(Ride ride) async {
  final path = await _nativeDialogs.invokeMethod<String>('savePdf', {
    'suggestedName': 'opendriver-invoice-${ride.id}.pdf',
  });
  if (path == null || path.trim().isEmpty) return null;

  var normalizedPath = path;
  if (!normalizedPath.toLowerCase().endsWith('.pdf')) {
    normalizedPath = '$normalizedPath.pdf';
  }

  final file = File(normalizedPath);
  await file.writeAsBytes(_buildInvoicePdf(ride), flush: true);
  return file.path;
}

Uint8List _buildInvoicePdf(Ride ride) {
  final lines = _invoiceLines(ride);
  final content = StringBuffer();
  var y = 790;

  void text(String value, {int x = 48, int size = 11, bool bold = false}) {
    final font = bold ? 'F2' : 'F1';
    content
      ..write('BT /$font $size Tf $x $y Td (')
      ..write(_pdfText(value))
      ..writeln(') Tj ET');
    y -= size + 8;
  }

  text('opendriver', size: 24, bold: true);
  text('Ride invoice', size: 13);
  y -= 10;
  for (final line in lines) {
    if (line.section) {
      y -= 8;
      text(line.label, size: 14, bold: true);
      continue;
    }
    if (line.divider) {
      content.writeln('0.65 w 48 $y m 548 $y l S');
      y -= 16;
      continue;
    }
    content
      ..write('BT /F1 10 Tf 48 $y Td (')
      ..write(_pdfText(line.label))
      ..writeln(') Tj ET')
      ..write('BT /${line.bold ? 'F2' : 'F1'} 10 Tf 170 $y Td (')
      ..write(_pdfText(line.value))
      ..writeln(') Tj ET');
    y -= 17;
  }

  final stream = content.toString();
  final objects = <String>[
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] '
        '/Resources << /Font << /F1 4 0 R /F2 5 0 R >> >> '
        '/Contents 6 0 R >>',
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>',
    '<< /Length ${latin1.encode(stream).length} >>\nstream\n$stream\nendstream',
  ];

  final buffer = StringBuffer('%PDF-1.4\n');
  final offsets = <int>[0];
  for (var index = 0; index < objects.length; index += 1) {
    offsets.add(latin1.encode(buffer.toString()).length);
    buffer
      ..writeln('${index + 1} 0 obj')
      ..writeln(objects[index])
      ..writeln('endobj');
  }
  final xrefOffset = latin1.encode(buffer.toString()).length;
  buffer
    ..writeln('xref')
    ..writeln('0 ${objects.length + 1}')
    ..writeln('0000000000 65535 f ');
  for (final offset in offsets.skip(1)) {
    buffer.writeln('${offset.toString().padLeft(10, '0')} 00000 n ');
  }
  buffer
    ..writeln('trailer << /Size ${objects.length + 1} /Root 1 0 R >>')
    ..writeln('startxref')
    ..writeln(xrefOffset)
    ..writeln('%%EOF');

  return Uint8List.fromList(latin1.encode(buffer.toString()));
}

List<_InvoiceLine> _invoiceLines(Ride ride) {
  final fare = ride.fareBreakdown;
  final payment = ride.payment;
  String money(double value) => formatMoney(
    value,
    currencySymbol: fare?.currencySymbol ?? ride.currencySymbol,
    currencyCode: fare?.currencyCode ?? ride.currencyCode,
    currencyDecimals: fare?.currencyDecimals ?? ride.currencyDecimals,
  );

  return [
    const _InvoiceLine.section('Trip'),
    _InvoiceLine('Ride', ride.id),
    if (ride.createdAt.isNotEmpty) _InvoiceLine('Created', ride.createdAt),
    ..._wrappedLine('Pickup', ride.pickupAddress),
    ..._wrappedLine('Destination', ride.destinationAddress),
    _InvoiceLine('Driver', ride.driver?.name ?? 'Unassigned'),
    _InvoiceLine(
      'Vehicle',
      ride.driverProfile == null
          ? 'Not available'
          : '${ride.driverProfile!.vehicleColor} ${ride.driverProfile!.vehicleMake} ${ride.driverProfile!.vehicleModel}',
    ),
    _InvoiceLine(
      'Distance',
      '${(ride.finalDistance ?? ride.estimatedDistance).toStringAsFixed(1)} km',
    ),
    _InvoiceLine(
      'Duration',
      '${ride.finalDuration ?? ride.estimatedDuration} min',
    ),
    const _InvoiceLine.section('Fare'),
    if (fare != null) ...[
      _InvoiceLine('Base', money(fare.baseFare)),
      _InvoiceLine('Distance fare', money(fare.distanceFare)),
      _InvoiceLine('Time fare', money(fare.timeFare)),
      _InvoiceLine('Service fee', money(fare.serviceFee)),
      if (fare.waypointFee != 0) _InvoiceLine('Stops', money(fare.waypointFee)),
      if (fare.pickupTimeAdjustment != 0)
        _InvoiceLine(
          fare.pickupTimeLabel.isEmpty
              ? 'Pickup time'
              : 'Pickup time (${fare.pickupTimeLabel})',
          money(fare.pickupTimeAdjustment),
        ),
      if (fare.discountAmount > 0)
        _InvoiceLine('Promo ${fare.promoCode}', money(-fare.discountAmount)),
    ],
    const _InvoiceLine.divider(),
    _InvoiceLine(
      'Payment',
      payment == null
          ? ride.paymentStatus
          : '${payment.paymentMethod} - ${payment.status}',
    ),
    _InvoiceLine(
      'Total',
      formatMoney(
        ride.finalFare ?? ride.estimatedFare,
        currencySymbol: ride.currencySymbol,
        currencyCode: ride.currencyCode,
        currencyDecimals: ride.currencyDecimals,
      ),
      bold: true,
    ),
  ];
}

List<_InvoiceLine> _wrappedLine(String label, String value) {
  const maxLength = 62;
  final chunks = <_InvoiceLine>[];
  var remaining = value;
  var first = true;
  while (remaining.length > maxLength) {
    var split = remaining.lastIndexOf(' ', maxLength);
    if (split <= 0) split = maxLength;
    chunks.add(_InvoiceLine(first ? label : '', remaining.substring(0, split)));
    remaining = remaining.substring(split).trimLeft();
    first = false;
  }
  chunks.add(_InvoiceLine(first ? label : '', remaining));
  return chunks;
}

String _pdfText(String value) {
  return value
      .replaceAll(RegExp(r'[^\x20-\x7E]'), '?')
      .replaceAll('\\', r'\\')
      .replaceAll('(', r'\(')
      .replaceAll(')', r'\)');
}

class _InvoiceLine {
  const _InvoiceLine(this.label, this.value, {this.bold = false})
    : section = false,
      divider = false;

  const _InvoiceLine.section(this.label)
    : value = '',
      bold = true,
      section = true,
      divider = false;

  const _InvoiceLine.divider()
    : label = '',
      value = '',
      bold = false,
      section = false,
      divider = true;

  final String label;
  final String value;
  final bool bold;
  final bool section;
  final bool divider;
}
