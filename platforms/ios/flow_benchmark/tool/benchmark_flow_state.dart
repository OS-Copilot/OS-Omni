import "dart:convert";
import "dart:io";

import "package:flow/data/flow_icon.dart";
import "package:flow/entity/account.dart";
import "package:flow/entity/category.dart";
import "package:flow/entity/transaction.dart";
import "package:flow/objectbox.dart";
import "package:flow/objectbox/actions.dart";
import "package:material_symbols_icons/symbols.dart";

Future<void> main(List<String> args) async {
  final parser = _ArgParser(args);
  final command = parser.command;
  final specPath = parser.getOption("spec");
  final customDirectory = parser.getOption("custom-directory");
  final subdirectory = parser.getOption("subdirectory") ?? "__debug";

  if (command == null || specPath == null || customDirectory == null) {
    _printJsonAndExit(
      {
        "status": "error",
        "message":
            "Usage: flutter pub run tool/benchmark_flow_state.dart <seed|assert-state|summary> --spec <path> --custom-directory <path> [--subdirectory __debug]",
      },
      2,
    );
  }

  try {
    final specFile = File(specPath!);
    final Map<String, dynamic> spec = jsonDecode(
      await specFile.readAsString(),
    ) as Map<String, dynamic>;
    final payload = await runBenchmarkCommand(
      command: command!,
      spec: spec,
      customDirectory: customDirectory!,
      subdirectory: subdirectory,
    );
    final status = (payload["status"] ?? "").toString().toLowerCase();
    _printJsonAndExit(
      payload,
      status == "pass" || status == "ok" ? 0 : 1,
    );
  } catch (error, stackTrace) {
    _printJsonAndExit(
      {
        "status": "error",
        "message": error.toString(),
        "stackTrace": stackTrace.toString(),
      },
      1,
    );
  }
}

Future<Map<String, dynamic>> runBenchmarkCommand({
  required String command,
  required Map<String, dynamic> spec,
  required String customDirectory,
  String subdirectory = "__debug",
}) async {
  await ObjectBox.initialize(
    customDirectory: customDirectory,
    subdirectory: subdirectory,
  );

  switch (command) {
    case "seed":
      final result = await _seed(spec);
      return {"status": "ok", ...result};
    case "assert-state":
      return _assertState(spec);
    case "summary":
      final result = await _summary(spec);
      return {"status": "ok", ...result};
    default:
      return {"status": "error", "message": "Unknown command: $command"};
  }
}

Future<Map<String, dynamic>> _seed(Map<String, dynamic> spec) async {
  await ObjectBox().eraseMainData();

  final categories = <String, Category>{};
  for (final categorySpec in _coerceList(spec["categories"])) {
    final name = _string(categorySpec["name"]);
    if (name.isEmpty) continue;
    final category = Category(
      name: name,
      iconCode: _categoryIconCode(_string(categorySpec["icon"])),
    );
    ObjectBox().box<Category>().put(category);
    categories[name] = category;
  }

  final accounts = <String, Account>{};
  for (final accountSpec in _coerceList(spec["accounts"])) {
    final name = _string(accountSpec["name"]);
    if (name.isEmpty) continue;
    final account = Account(
      name: name,
      currency: _string(accountSpec["currency"]).isEmpty
          ? "USD"
          : _string(accountSpec["currency"]),
      iconCode: _accountIconCode(_string(accountSpec["icon"])),
      type: _string(accountSpec["type"]).isEmpty
          ? AccountType.debit.value
          : _string(accountSpec["type"]),
      excludeFromTotalBalance: categorySpecBool(accountSpec, "exclude_from_total_balance"),
    );
    ObjectBox().box<Account>().put(account);
    accounts[name] = account;
  }

  for (final balanceSpec in _coerceList(spec["opening_balances"])) {
    final account = accounts[_string(balanceSpec["account"])];
    if (account == null) {
      throw Exception("Unknown account in opening_balances: ${balanceSpec["account"]}");
    }
    account.updateBalanceAndSave(
      _double(balanceSpec["amount"]),
      title: _nullableString(balanceSpec["title"]) ?? "${account.name} opening balance",
      transactionDate: _resolveDate(balanceSpec),
    );
  }

  for (final transactionSpec in _coerceList(spec["transactions"])) {
    final kind = _string(transactionSpec["kind"]);
    switch (kind) {
      case "expense":
      case "income":
        final account = accounts[_string(transactionSpec["account"])];
        if (account == null) {
          throw Exception("Unknown account in transactions: ${transactionSpec["account"]}");
        }
        final category = categories[_string(transactionSpec["category"])];
        if (category == null) {
          throw Exception("Unknown category in transactions: ${transactionSpec["category"]}");
        }
        final rawAmount = _double(transactionSpec["amount"]);
        final signedAmount = kind == "expense" ? -rawAmount.abs() : rawAmount.abs();
        account.createAndSaveTransaction(
          amount: signedAmount,
          title: _nullableString(transactionSpec["title"]),
          description: _nullableString(transactionSpec["description"]),
          category: category,
          transactionDate: _resolveDate(transactionSpec),
          isPending: categorySpecBool(transactionSpec, "is_pending"),
        );
        break;
      case "transfer":
        final fromAccount = accounts[_string(transactionSpec["from_account"])];
        final toAccount = accounts[_string(transactionSpec["to_account"])];
        if (fromAccount == null || toAccount == null) {
          throw Exception(
            "Unknown account in transfer: from=${transactionSpec["from_account"]}, to=${transactionSpec["to_account"]}",
          );
        }
        fromAccount.transferTo(
          targetAccount: toAccount,
          amount: _double(transactionSpec["amount"]).abs(),
          title: _nullableString(transactionSpec["title"]),
          description: _nullableString(transactionSpec["description"]),
          transactionDate: _resolveDate(transactionSpec),
          isPending: categorySpecBool(transactionSpec, "is_pending"),
        );
        break;
      default:
        throw Exception("Unsupported transaction kind: $kind");
    }
  }

  return await _summary(spec);
}

Future<Map<String, dynamic>> _assertState(Map<String, dynamic> spec) async {
  final failures = <String>[];
  final summary = await _summary(spec);
  final observedAccounts = {
    for (final account in _coerceList(summary["accounts"])) _string(account["name"]): account,
  };
  final observedTransactions = _coerceList(summary["transactions"]);

  final presentTransactions = _coerceList(spec["present_transactions"]);
  final absentTitles = _coerceStringList(spec["absent_titles"]);

  for (final expectation in presentTransactions) {
    final matched = observedTransactions.any(
      (transaction) => _transactionMatches(transaction, expectation),
    );
    if (!matched) {
      failures.add("missing transaction ${jsonEncode(expectation)}");
    }
  }

  for (final title in absentTitles) {
    final present = observedTransactions.any(
      (transaction) => _string(transaction["title"]) == title,
    );
    if (present) {
      failures.add("unexpected title still present: $title");
    }
  }

  final accountBalances = spec["account_balances"];
  if (accountBalances is Map<String, dynamic>) {
    for (final entry in accountBalances.entries) {
      final observed = observedAccounts[entry.key];
      if (observed == null) {
        failures.add("missing account ${entry.key}");
        continue;
      }
      final expectedBalance = _roundMoney(entry.value);
      final actualBalance = _roundMoney(observed["balance"]);
      if (actualBalance != expectedBalance) {
        failures.add(
          "account ${entry.key} balance expected $expectedBalance but got $actualBalance",
        );
      }
    }
  }

  final transactionCount = spec["transaction_count"];
  if (transactionCount != null) {
    final actualCount = observedTransactions.length;
    if (actualCount != int.parse(transactionCount.toString())) {
      failures.add(
        "transaction count expected $transactionCount but got $actualCount",
      );
    }
  }

  if (failures.isEmpty) {
    return {
      "status": "pass",
      "message": "Flow ObjectBox state matches expectations",
      "summary": summary,
    };
  }

  return {
    "status": "fail",
    "message": "Flow ObjectBox state does not match expectations",
    "failures": failures,
    "summary": summary,
  };
}

Future<Map<String, dynamic>> _summary(Map<String, dynamic> spec) async {
  final accountBox = ObjectBox().box<Account>();
  final transactionBox = ObjectBox().box<Transaction>();
  final categoryBox = ObjectBox().box<Category>();

  final accounts = accountBox.getAll();
  accounts.sort((a, b) => a.name.compareTo(b.name));

  final categories = categoryBox.getAll();
  categories.sort((a, b) => a.name.compareTo(b.name));

  final transactions = transactionBox
      .getAll()
      .where((transaction) => transaction.isDeleted != true)
      .toList()
    ..sort(
      (a, b) =>
          a.transactionDate.compareTo(b.transactionDate) != 0
              ? a.transactionDate.compareTo(b.transactionDate)
              : a.id.compareTo(b.id),
    );

  return {
    "accounts": accounts
        .map(
          (account) => {
            "name": account.name,
            "currency": account.currency,
            "balance": _roundMoney(account.balance.amount),
          },
        )
        .toList(),
    "categories": categories.map((category) => category.name).toList(),
    "transactions": transactions.map(_transactionToJson).toList(),
  };
}

Map<String, dynamic> _transactionToJson(Transaction transaction) {
  return {
    "id": transaction.id,
    "uuid": transaction.uuid,
    "title": transaction.title,
    "description": transaction.description,
    "amount": _roundMoney(transaction.amount),
    "type": transaction.type.name,
    "account": transaction.account.target?.name,
    "category": transaction.category.target?.name,
    "transaction_date": transaction.transactionDate.toIso8601String(),
    "is_pending": transaction.isPending ?? false,
    "is_transfer": transaction.isTransfer,
    "related_transaction_uuid": transaction.extensions.transfer?.relatedTransactionUuid,
    "to_account": transaction.isTransfer
        ? _accountNameFromUuid(transaction.extensions.transfer?.toAccountUuid)
        : null,
    "from_account": transaction.isTransfer
        ? _accountNameFromUuid(transaction.extensions.transfer?.fromAccountUuid)
        : null,
  };
}

String? _accountNameFromUuid(String? uuid) {
  if (uuid == null || uuid.isEmpty) return null;
  return ObjectBox()
      .box<Account>()
      .getAll()
      .firstWhere(
        (account) => account.uuid == uuid,
        orElse: () => Account(
          name: "",
          currency: "USD",
          iconCode: _accountIconCode(""),
        ),
      )
      .name
      .ifEmptyToNull();
}

bool _transactionMatches(
  Map<String, dynamic> observed,
  Map<String, dynamic> expectation,
) {
  bool matchesField(String key, Object? expected) {
    if (expected == null) return true;
    final actual = observed[key];
    if (key == "amount") {
      return _roundMoney(actual) == _roundMoney(expected);
    }
    return _string(actual) == _string(expected);
  }

  final type = _string(expectation["type"]);
  final amount = expectation["amount"];
  final title = expectation["title"];
  final description = expectation["description"];
  final account = expectation["account"];
  final category = expectation["category"];
  final toAccount = expectation["to_account"];
  final fromAccount = expectation["from_account"];
  final isPending = expectation["is_pending"];

  if (!matchesField("type", type)) return false;
  if (amount != null && !matchesField("amount", amount)) return false;
  if (!matchesField("title", title)) return false;
  if (!matchesField("description", description)) return false;
  if (!matchesField("account", account)) return false;
  if (!matchesField("category", category)) return false;
  if (!matchesField("to_account", toAccount)) return false;
  if (!matchesField("from_account", fromAccount)) return false;
  if (isPending != null && observed["is_pending"] != isPending) return false;

  return true;
}

String _accountIconCode(String hint) {
  return switch (hint) {
    "cash" => FlowIconData.icon(Symbols.payments_rounded).toString(),
    "savings" => FlowIconData.icon(Symbols.savings_rounded).toString(),
    _ => FlowIconData.icon(Symbols.credit_card_rounded).toString(),
  };
}

String _categoryIconCode(String hint) {
  return switch (hint) {
    "transport" => const IconFlowIcon(Symbols.train_rounded).toString(),
    "groceries" => const IconFlowIcon(Symbols.grocery_rounded).toString(),
    "income" => const IconFlowIcon(Symbols.wallet_rounded).toString(),
    "shopping" => const IconFlowIcon(Symbols.shopping_cart_rounded).toString(),
    _ => const IconFlowIcon(Symbols.local_cafe_rounded).toString(),
  };
}

double _roundMoney(Object? value) {
  final raw = _double(value);
  return (raw * 100).round() / 100;
}

double _double(Object? value) {
  return double.parse((value ?? 0).toString());
}

String _string(Object? value) => (value ?? "").toString().trim();

String? _nullableString(Object? value) {
  final text = _string(value);
  return text.isEmpty ? null : text;
}

DateTime _resolveDate(Map<String, dynamic> spec) {
  final isoDate = _nullableString(spec["date"]);
  if (isoDate != null) {
    return DateTime.parse(isoDate);
  }
  final dayOffset = int.tryParse((spec["day_offset"] ?? 0).toString()) ?? 0;
  final now = DateTime.now();
  return DateTime(now.year, now.month, now.day).add(Duration(days: dayOffset));
}

List<Map<String, dynamic>> _coerceList(Object? raw) {
  if (raw is! List) return const [];
  return raw.whereType<Map>().map((item) => Map<String, dynamic>.from(item)).toList();
}

List<String> _coerceStringList(Object? raw) {
  if (raw is! List) return const [];
  return raw.map(_string).where((value) => value.isNotEmpty).toList();
}

bool categorySpecBool(Map<String, dynamic> spec, String key) {
  final value = spec[key];
  if (value is bool) return value;
  if (value == null) return false;
  return value.toString().toLowerCase() == "true";
}

void _printJsonAndExit(Map<String, dynamic> payload, int exitCode) {
  stdout.writeln(jsonEncode(payload));
  exit(exitCode);
}

extension on String {
  String? ifEmptyToNull() => isEmpty ? null : this;
}

class _ArgParser {
  final List<String> _args;

  _ArgParser(this._args);

  String? get command {
    if (_args.isEmpty || _args.first.startsWith("--")) return null;
    return _args.first;
  }

  String? getOption(String name) {
    final flag = "--$name";
    final index = _args.indexOf(flag);
    if (index < 0 || index + 1 >= _args.length) return null;
    return _args[index + 1];
  }
}
