import "dart:convert";
import "dart:io";

import "package:flutter_test/flutter_test.dart";
import "../tool/benchmark_flow_state.dart" as bench;

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test("flow benchmark runner", () async {
    final command = const String.fromEnvironment("FLOW_BENCHMARK_COMMAND");
    final specPath = const String.fromEnvironment("FLOW_BENCHMARK_SPEC");
    final customDirectory = const String.fromEnvironment("FLOW_BENCHMARK_CUSTOM_DIRECTORY");
    final subdirectory = const String.fromEnvironment(
      "FLOW_BENCHMARK_SUBDIRECTORY",
      defaultValue: "__debug",
    );

    if (command.isEmpty || specPath.isEmpty || customDirectory.isEmpty) {
      fail("Missing FLOW_BENCHMARK_COMMAND, FLOW_BENCHMARK_SPEC, or FLOW_BENCHMARK_CUSTOM_DIRECTORY");
    }

    final spec = jsonDecode(
      await File(specPath).readAsString(),
    ) as Map<String, dynamic>;

    final payload = await bench.runBenchmarkCommand(
      command: command,
      spec: spec,
      customDirectory: customDirectory,
      subdirectory: subdirectory,
    );

    // Keep one machine-readable line for the benchmark harness.
    print("__FLOW_BENCHMARK_JSON__${jsonEncode(payload)}");
  }, timeout: const Timeout(Duration(minutes: 5)));
}
