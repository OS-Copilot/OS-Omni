# iOS Flow Benchmark Helper

This directory contains the minimal Flow checkout required by the iOS Flow
initializers and evaluators. It is not the app bundle installed in the
simulator. The benchmark harness runs `flutter test
test/benchmark_flow_state_test.dart` here to seed and inspect the Flow
ObjectBox store inside the iOS simulator.

Generated Flutter files such as `.dart_tool/`, `build/`, Pods, and the
symlinked `lib/libobjectbox.dylib` should stay untracked.
